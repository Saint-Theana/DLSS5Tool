"""Bounded P0/P1 diagnostics without models, native GPU calls or media output.

Records current behavior rather than treating an existing gap as a passing test.
Fault injection uses one 256-byte shared segment; HDR timings cover CPU input
preparation only, never whole export throughput. The probe does not change production code.
"""
import argparse
import gc
import inspect
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from unittest import mock
import weakref

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dlss5tool import memory_budget, residual_composition, super_resolution
from dlss5tool.app_version import __version__
from dlss5tool.render_cache import RenderSession


def allocation_failure():
    real_memory = super_resolution.shared_memory.SharedMemory
    allocated = []
    owner = super_resolution.ProcessSuperResolution.__new__(
        super_resolution.ProcessSuperResolution)

    def allocate(**kwargs):
        if allocated:
            raise MemoryError('audit: second shared allocation failed')
        segment = real_memory(**kwargs)
        segment.close = mock.Mock(wraps=segment.close)
        segment.unlink = mock.Mock(wraps=segment.unlink)
        allocated.append(segment)
        return segment

    try:
        with mock.patch.object(super_resolution, 'memory_headroom_bytes',
                               return_value=4 * 1024**3), mock.patch.object(
                super_resolution.shared_memory, 'SharedMemory', side_effect=allocate):
            try:
                owner.__init__(8, 8, 2)
            except MemoryError as error:
                failure = str(error)
            else:
                raise AssertionError('Injected second allocation did not fail')
        segment = allocated[0]
        result = dict(error=failure, allocated_bytes=segment.size,
                      close_calls_after_failure=segment.close.call_count,
                      unlink_calls_after_failure=segment.unlink.call_count,
                      mapping_open_after_failure=segment._mmap is not None)
        try:
            owner.close()
            result['partial_owner_close_error'] = None
        except Exception as error:
            result['partial_owner_close_error'] = f'{type(error).__name__}: {error}'
        return result
    finally:
        # Explicitly retire the tiny probe-owned resource even on the old code.
        for segment in allocated:
            segment.close()
            segment.unlink()


def retained_exception():
    references = []

    def failing_renderer(*args, **kwargs):
        pixels = np.ones((64, 64, 4), dtype=np.float32)
        references.append(weakref.ref(pixels))
        raise RuntimeError('audit: renderer failed after frame allocation')

    session = RenderSession('audit-synthetic-source', {}, 1024**2,
                            renderer=failing_renderer)
    session._produce()
    reported_error = session.error
    error_text = str(reported_error)
    gc.collect()
    before = references[0]() is not None
    session.close()
    gc.collect()
    after = references[0]() is not None
    reported_error.__traceback__ = None
    gc.collect()
    stripped = references[0]() is not None
    return dict(error=error_text, synthetic_frame_bytes=64*64*4*4,
                retained_before_close=before, retained_after_close=after,
                retained_after_clearing_traceback=stripped,
                cache_reported_bytes=session.bytes)


def zero_headroom_slots():
    from dlss5tool.dlss_host_process import _HostSession
    no_headroom = dict(total_physical_bytes=32*1024**3,
                       free_physical_bytes=0, free_commit_bytes=0)
    with mock.patch.object(super_resolution, 'bounded_frame_count', return_value=0):
        slots = super_resolution.select_in_flight(1920, 1080, 1, 16, is_hdr=True)
    # Stop at the first shared allocation; no real frame or GPU is allocated.
    with mock.patch.object(memory_budget, 'system_memory', return_value=no_headroom), \
            mock.patch('dlss5tool.dlss_host_process._open_shared_memory',
                       side_effect=MemoryError('audit: stop before real allocation')) as allocate:
        try:
            _HostSession(1920, 1080, dict(frame_format='rgba16f',
                host_backend='v2', host_in_flight=slots), live_factory=mock.Mock())
        except MemoryError:
            pass
    return dict(bounded_frame_count=0, selected_in_flight=slots,
                host_attempted_shared_allocation=allocate.called,
                attempted_shared_bytes=allocate.call_args.kwargs['size'] if allocate.called else 0,
                case='1920x1080 HDR, scale=1; no VSR constructor admission')


def multiple_gpu_query():
    output = b'GPU A, 24576, 20000\nGPU B, 8192, 500\n'
    with mock.patch.object(super_resolution, '_GPU_QUERY_CACHE', None), mock.patch.object(
            super_resolution.subprocess, 'run', return_value=mock.Mock(stdout=output)):
        snapshot = super_resolution.query_gpu_memory(cache_seconds=0)
    estimate = dict(output_width=3840, output_height=2160,
                    recommended_gpu_bytes=3*1024**3)
    return dict(simulated_driver_rows=output.decode().splitlines(),
                snapshot=snapshot,
                risk_from_first_gpu=super_resolution.classify_resource_risk(estimate, snapshot),
                risk_if_using_gpu_b=super_resolution.classify_resource_risk(
                    estimate, dict(free_bytes=500*1024**2)),
                query_parameters=list(inspect.signature(super_resolution.query_gpu_memory).parameters))


def hdr_preparation():
    headroom = memory_budget.memory_headroom_bytes()
    if headroom is not None and headroom < 512*1024**2:
        return dict(skipped='Less than the 512 MiB diagnostic headroom budget')
    height, width = 1080, 1920
    original = np.empty((height, width, 4), dtype=np.float16)
    original[..., :3] = np.linspace(.01, .99, width, dtype=np.float16)[None, :, None]
    original[..., 3] = 1
    processed = original.copy()
    processed[..., :3] *= .95
    measurements = {}
    for profile in ('hdr10_pq', 'hdr10_hlg'):
        prepared = residual_composition._native_inputs(
            original, processed, order='rgb', profile=profile)
        del prepared
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            prepared = residual_composition._native_inputs(
                original, processed, order='rgb', profile=profile)
            samples.append((time.perf_counter()-start)*1000)
            del prepared
        gc.collect()
        tracemalloc.start()
        try:
            prepared = residual_composition._native_inputs(
                original, processed, order='rgb', profile=profile)
            _, peak = tracemalloc.get_traced_memory()
            retained = prepared[0].nbytes + prepared[1].nbytes
            del prepared
        finally:
            tracemalloc.stop()
        from dlss5tool import video_export
        function_name = '_pq_eotf' if profile == 'hdr10_pq' else '_hlg_eotf'
        real_decode = getattr(video_export, function_name)
        decode_times = []

        def timed_decode(values):
            start = time.perf_counter()
            result = real_decode(values)
            decode_times.append((time.perf_counter()-start)*1000)
            return result

        with mock.patch.object(video_export, function_name, side_effect=timed_decode):
            start = time.perf_counter()
            prepared = residual_composition._native_inputs(
                original, processed, order='rgb', profile=profile)
            breakdown_total = (time.perf_counter()-start)*1000
            del prepared
        measurements[profile] = dict(samples_ms=samples,
            median_ms=statistics.median(samples),
            prepared_pair_bytes=retained, python_numpy_traced_peak_bytes=peak,
            separate_breakdown=dict(total_ms=breakdown_total, eotf_calls_ms=decode_times,
                                    other_preparation_ms=breakdown_total-sum(decode_times)))
    return dict(width=width, height=height, dtype='float16',
                input_pair_bytes=original.nbytes+processed.nbytes,
                method='one warmup, five sequential CPU preparation calls per profile; '
                       'allocation peak measured separately; no DLL, GPU or encoder',
                profiles=measurements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hdr-1080', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Diagnostics must be written under the repository tmp task directory')
    if output.exists():
        raise FileExistsError(output)
    for ancestor in (args.output.absolute(), *args.output.absolute().parents):
        if ancestor.exists() and ancestor.is_junction():
            raise ValueError(f'Junction output path: {ancestor}')
        if ancestor.is_symlink():
            raise ValueError(f'Linked output path: {ancestor}')
    report = dict(schema=1, source_version=__version__,
                  python=sys.version.split()[0], numpy=np.__version__,
                  p0_shared_allocation_failure=allocation_failure(),
                  p0_retained_error=retained_exception(),
                  p0_zero_headroom_slots=zero_headroom_slots(),
                  p1_multiple_gpu_query=multiple_gpu_query())
    if args.hdr_1080:
        report['p1_hdr_cpu_preparation'] = hdr_preparation()
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
