"""Bounded real-host zero-control checks, deliberately bypassing Python routing."""
import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool.dlss_host_process import _HostSession
from scripts.diagnose_composer_lifetime import memory_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--label', default='styles')
    parser.add_argument('--backend', choices=('v2', 'legacy'), default='v2')
    args = parser.parse_args()
    task = args.task.resolve(strict=True)
    if not (task / 'TASK.md').is_file():
        raise ValueError('Register task before GPU checks')
    destination = task / ('zero-native-contract-' + args.label + '.json')
    if destination.exists():
        raise ValueError('Refusing report overwrite')
    before = memory_snapshot()
    if min(before['free_physical_bytes'], before['free_commit_bytes']) < 2 * 1024**3:
        raise MemoryError('Insufficient memory headroom')
    rng = np.random.default_rng(19)
    records = []
    for profile in (('srgb',) if args.backend == 'legacy' else ('srgb', 'hdr10_pq', 'hdr10_hlg', 'scrgb')):
        hdr = profile != 'srgb'
        frame = (rng.random((256, 256, 4)) * (1 if hdr else 255)).astype(np.float16 if hdr else np.uint8)
        frame[..., 3] = 1 if hdr else 255
        if profile == 'scrgb':
            frame[..., :3] = frame[..., :3] * 6 - .5
        settings = dict(host_backend=args.backend, host_auto_fallback=False,
            frame_format='rgba16f' if hdr else 'rgba8', color_profile=profile,
            color_primaries='bt709' if profile in ('srgb', 'scrgb') else 'bt2020',
            intensity=0., local_tone=0., local_struct=0., skin_struct=0.,
            use_auto_mask=False, guidance_mode=0, host_in_flight=1)
        session = None
        row = {'profile': profile, 'settings': settings, 'frames': []}
        try:
            session = _HostSession(256, 256, settings)
            row['pid'] = session._process.pid
            row['adapter'] = session.adapter_info
            for index in range(9):
                style = index // 3
                session.request('update', settings={**settings, 'style': style})
                source = np.ascontiguousarray(np.roll(frame, index, axis=1))
                session.copy_input(source)
                response = session.request('process', reset=index == 0)
                if not response['has_output']:
                    raise RuntimeError('NR returned no output')
                output = session.copy_output()
                error = np.abs(output.astype(np.float32) - source.astype(np.float32))
                expected = source.copy()
                if hdr:
                    np.clip(expected[..., :3], 0, 1, out=expected[..., :3])
                row['frames'].append(dict(style=style,
                    matches_native_zero_fast_path=bool(np.array_equal(output, expected)),
                    different_rgb_values=int(np.count_nonzero(output[..., :3] != source[..., :3])),
                    max_rgb_error=float(error[..., :3].max()), alpha_exact=bool(np.array_equal(output[..., 3], source[..., 3])),
                    finite=bool(np.isfinite(output).all()), min_rgb=float(output[..., :3].min()), max_rgb=float(output[..., :3].max())))
            if not all(sample['matches_native_zero_fast_path'] for sample in row['frames']):
                raise RuntimeError('Native zero output differs from the fast-path contract')
            row['status'] = 'complete'
        except Exception as error:
            row.update(status='failed', error=str(error))
        finally:
            if session is not None:
                session.close()
        records.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report = dict(pid=os.getpid(), memory_before=before, memory_after=memory_snapshot(), profiles=records)
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return int(any(row['status'] != 'complete' for row in records))


if __name__ == '__main__':
    raise SystemExit(main())
