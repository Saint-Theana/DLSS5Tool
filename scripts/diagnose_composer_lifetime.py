"""Bounded diagnostic for native composer ownership; no application fixes.

Default: count fake native allocations through production _native_bridge and
LatestPreviewJob. --native also runs 1000x1000 SDR composition with the existing
DLL. Every handle created by this isolated probe is explicitly cleaned up after
the observations, including handles that production thread exit did not free.
Prints JSON only; does not alter settings or write media.
"""
import argparse
import ctypes as C
import gc
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlss5tool import appearance, residual_composition as composition
from dlss5tool.preview_jobs import LatestPreviewJob


def memory_snapshot():
    if os.name != 'nt':
        return {}

    class Counters(C.Structure):
        _fields_ = [('cb', C.c_uint32), ('faults', C.c_uint32)] + [
            (name, C.c_size_t) for name in (
                'peak_working_set', 'working_set', 'peak_paged', 'paged',
                'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]

    class Status(C.Structure):
        _fields_ = [('length', C.c_uint32), ('load', C.c_uint32)] + [
            (name, C.c_uint64) for name in (
                'total_physical', 'free_physical', 'total_pagefile',
                'free_pagefile', 'total_virtual', 'free_virtual', 'extended')]

    kernel = C.WinDLL('kernel32', use_last_error=True)
    psapi = C.WinDLL('psapi', use_last_error=True)
    kernel.GetCurrentProcess.restype = C.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32]
    psapi.GetProcessMemoryInfo.restype = C.c_int
    counters = Counters()
    counters.cb = C.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), C.byref(counters), counters.cb):
        raise C.WinError(C.get_last_error())
    kernel.GlobalMemoryStatusEx.argtypes = [C.c_void_p]
    kernel.GlobalMemoryStatusEx.restype = C.c_int
    status = Status()
    status.length = C.sizeof(status)
    if not kernel.GlobalMemoryStatusEx(C.byref(status)):
        raise C.WinError(C.get_last_error())
    return {'private_bytes': counters.private, 'working_set_bytes': counters.working_set,
            'free_physical_bytes': status.free_physical,
            'free_commit_bytes': status.free_pagefile}


class CountedCall:
    """Forward ctypes signatures while observing successful create/destroy."""
    def __init__(self, function, observer):
        self.function, self.observer = function, observer

    @property
    def argtypes(self):
        return getattr(self.function, 'argtypes', None)

    @argtypes.setter
    def argtypes(self, value):
        self.function.argtypes = value

    @property
    def restype(self):
        return getattr(self.function, 'restype', None)

    @restype.setter
    def restype(self, value):
        self.function.restype = value

    def __call__(self, *args):
        result = self.function(*args)
        self.observer(args, result)
        return result


def run(args):
    native_path = composition._native_library_path() if args.native else 'mock-composer.dll'
    if not native_path:
        raise RuntimeError('Existing native composer DLL unavailable or disabled')
    created, destroyed, live, dispatches = [], [], set(), []
    pixel_errors, alpha_matches = [], []

    def allocated(_args, handle):
        if handle:
            created.append(int(handle))
            live.add(int(handle))

    def released(call_args, _result):
        handle = int(call_args[0])
        destroyed.append(handle)
        live.discard(handle)

    if args.native:
        import numpy as np
        backend = C.CDLL(native_path)
        original = np.full((1000, 1000, 3), 100, dtype=np.uint8)
        processed = np.full_like(original, 110)
        settings = {'nr_quality': {'total': .75}}
        appearance.preflight(settings)
        reference = None
        if args.verify_pixels:
            rng = np.random.default_rng(20261019)
            original = rng.integers(0, 256, (1000, 1000, 4), dtype=np.uint8)
            processed = rng.integers(0, 256, original.shape, dtype=np.uint8)
            with mock.patch.object(composition, '_native_compose', return_value=None):
                reference = composition.compose(original, processed, settings)
    else:
        backend = SimpleNamespace(
            dlss5_quality_create=lambda: len(created) + 1,
            dlss5_quality_destroy=lambda handle: None,
            dlss5_quality_compose=lambda *call_args: 1)

    library = SimpleNamespace(
        dlss5_quality_create=CountedCall(backend.dlss5_quality_create, allocated),
        dlss5_quality_destroy=CountedCall(backend.dlss5_quality_destroy, released),
        dlss5_quality_compose=CountedCall(
            backend.dlss5_quality_compose,
            lambda call_args, result: dispatches.append(bool(result))))

    started, workers = threading.Event(), []
    def compute():
        if not args.persistent_thread:
            workers.append(threading.current_thread())
            started.set()
        if args.native:
            result = composition.compose(original, processed, settings)
            if result is processed or result.shape != processed.shape:
                raise RuntimeError('Native composition did not produce the expected frame')
            if reference is not None:
                error = int(np.abs(result[..., :3].astype(np.int16) -
                                   reference[..., :3].astype(np.int16)).max())
                alpha_ok = bool(np.array_equal(result[..., 3], original[..., 3]))
                pixel_errors.append(error)
                alpha_matches.append(alpha_ok)
                if error > 1 or not alpha_ok:
                    raise RuntimeError('Native output exceeded CPU quantization/alpha contract')
            return int(result[0, 0, 0])
        if composition._native_bridge() is None:
            raise RuntimeError('Mock bridge creation failed')
        return True

    report = {'mode': 'native' if args.native else 'mock',
              'lifetime': 'persistent-thread' if args.persistent_thread else 'preview-threads',
              'dll': str(native_path), 'requested_cycles': args.cycles, 'samples': [],
              'verify_pixels': args.verify_pixels, 'release_each_cycle': args.release_each_cycle}
    baseline = memory_snapshot()
    report['baseline'] = baseline
    if args.native and min(baseline.get('free_physical_bytes', 2**63),
                           baseline.get('free_commit_bytes', 2**63)) < 2 * 1024**3:
        raise RuntimeError('System memory headroom below 2 GiB; native probe not started')
    job = LatestPreviewJob('p0-composer-probe')
    try:
        with mock.patch.object(composition, '_native_state', threading.local()), \
                mock.patch.object(composition, '_native_library_path', return_value=native_path), \
                mock.patch.object(composition.ctypes, 'CDLL', return_value=library):
            for cycle in range(args.cycles):
                if args.persistent_thread:
                    compute()
                else:
                    started.clear()
                    job.request(cycle, compute)
                    if not started.wait(3):
                        raise RuntimeError('Probe worker did not start')
                    # _thread may already be None while TLS finalizers still run.
                    worker = workers[-1]
                    worker.join(timeout=20)
                    if worker.is_alive():
                        raise RuntimeError('Probe worker exceeded 20 seconds')
                    # Re-request the same key to surface the production job error.
                    job.request(cycle, compute)
                    if not job.ready():
                        raise RuntimeError('Preview job did not publish a result')
                    job.invalidate()
                if args.release_each_cycle:
                    composition.release_native_composer()
                gc.collect()
                sample = {'cycle': cycle + 1, 'created': len(created),
                          'destroyed': len(destroyed), 'live': len(live),
                          **memory_snapshot()}
                report['samples'].append(sample)
                if args.native and sample.get('private_bytes', 0) - baseline.get('private_bytes', 0) >= 512 * 1024**2:
                    report['stopped'] = 'Private commit growth reached 512 MiB'
                    break
                if args.native and min(sample.get('free_physical_bytes', 2**63),
                                       sample.get('free_commit_bytes', 2**63)) < 2 * 1024**3:
                    report['stopped'] = 'System memory headroom below 2 GiB'
                    break
            report['before_probe_cleanup'] = {
                'created': len(created), 'destroyed': len(destroyed), 'live': len(live),
                'native_dispatches': len(dispatches),
                'failed_dispatches': dispatches.count(False)}
            if args.verify_pixels:
                report['pixels'] = {'comparisons': len(pixel_errors),
                                    'max_rgb_code_error': max(pixel_errors, default=0),
                                    'alpha_exact': all(alpha_matches)}
    finally:
        # This is probe-owned cleanup, deliberately after production lifecycle
        # observations. It is not evidence that the application freed anything.
        active_worker = workers[-1] if workers else None
        if active_worker is not None and active_worker.is_alive():
            report['cleanup_skipped'] = 'Worker still active; isolated process exit will reclaim resources'
        else:
            for handle in sorted(live):
                library.dlss5_quality_destroy(handle)
        gc.collect()
        report['after_probe_cleanup'] = {
            'created': len(created), 'destroyed': len(destroyed), 'live': len(live),
            **memory_snapshot()}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--cycles', type=int, default=6)
    parser.add_argument('--persistent-thread', action='store_true')
    parser.add_argument('--verify-pixels', action='store_true',
                        help='Compare deterministic RGBA output against the CPU reference')
    parser.add_argument('--release-each-cycle', action='store_true',
                        help='Exercise explicit cleanup followed by re-creation')
    args = parser.parse_args()
    if args.verify_pixels and not args.native:
        parser.error('--verify-pixels requires --native')
    if not 1 <= args.cycles <= (6 if args.native else 64):
        parser.error('cycles must be 1..6 for native, or 1..64 for mock')
    print(json.dumps(run(args), indent=2))


if __name__ == '__main__':
    main()
