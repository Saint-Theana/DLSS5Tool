"""Small synthetic local NR/NVOFA/cache/export acceptance test; no user media.

Run with the existing source environment. This is not a throughput benchmark.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise ValueError('Use a new task output directory; no overwrites')
    if shutil.disk_usage(root.parent).free < 15*1024**3 + 64*1024**2:
        raise ValueError('Need 15 GiB safety margin + 64 MiB')
    root.mkdir()
    os.environ['DLSS5TOOL_FG_LOG_ROOT'] = str(root/'logs')
    import cv2
    import numpy as np
    from dlss5tool.render_cache import RenderCache, encode_cached
    from dlss5tool.video_export import compose_output_frame
    from dlss5tool.guidance_client import preflight
    settings = {'host_backend': 'v2', 'dlss_runtime': '__bundled__', 'intensity': .5,
                'guidance_mode': 1, 'guidance_flow_backend': 'nvofa', 'guidance_device': 'cuda',
                'guidance_flow_fallback': False, 'guidance_flow_edge': 128,
                'mods_directory': str(root/'absent-addon'), 'output_mix': .8,
                'frame_generation_multiplier': 1, 'super_resolution_scale': 1,
                'nr_residual': {'residualMultiplier': 1.3, 'residualSaturation': .7},
                'nr_quality': {'total': .6, 'protection': True, 'feather': 6,
                               'regions': [[.1, .1, .4, .8]]}}
    info = preflight(settings)
    source = root/'source.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 24, (320, 192))
    if not writer.isOpened():
        raise RuntimeError('Synthetic writer failed')
    rng = np.random.default_rng(17)
    pixels = rng.integers(25, 220, (192, 320, 3), dtype=np.uint8)
    try:
        for i in range(4):
            writer.write(np.roll(pixels, i*2, axis=1))
    finally:
        writer.release()
    manager = RenderCache(128*1024**2)
    cancel = threading.Event()
    timer = threading.Timer(120, cancel.set)
    timer.start()
    try:
        session = manager.session(source, settings)
        for i in range(4):
            rendered = session.wait(i, cancel)
            raw = manager.base.wait(i, cancel)
            expected = compose_output_frame(cv2.cvtColor(raw.mix_source, cv2.COLOR_RGBA2BGR),
                cv2.cvtColor(raw[0], cv2.COLOR_RGBA2BGR), mix=.8, settings=settings)
            np.testing.assert_array_equal(cv2.cvtColor(rendered[0], cv2.COLOR_RGBA2BGR), expected)
        base = manager.base
        changed = dict(settings, nr_quality={'total': .25})
        next_session = manager.session(source, changed)
        next_session.wait(0, cancel)
        if manager.base is not base:
            raise AssertionError('Appearance change recreated raw NR inference')
        for i in range(4):
            next_session.wait(i, cancel)
        result = encode_cached(next_session, root/'export.mp4', changed, cancel, lambda *_: None)
        capture = cv2.VideoCapture(str(root/'export.mp4'))
        decoded = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                assert frame.shape == (192, 320, 3)
                decoded += 1
        finally:
            capture.release()
        assert decoded == 4
        assert result['cache_hits'] == 4 and result['new_frames'] == 0
        report = {'status': 'passed', 'guidance': info, 'frames': decoded,
                  'raw_nr_reused': True, 'composition_array_exact': True,
                  'export_cache_hits': result['cache_hits'], 'export_new_frames': result['new_frames'],
                  'scope': '320x192 SDR synthetic, source Python, not frozen/game/HDR/performance acceptance'}
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        timer.cancel()
        manager.close()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
