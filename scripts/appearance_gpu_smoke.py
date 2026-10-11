"""Small synthetic local NR/NVOFA/cache/export acceptance test; no user media.

Run with the existing source environment. This is not a throughput benchmark.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hdr', action='store_true', help='HDR10/PQ full-precision NR/cache/export probe')
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
    from dlss5tool.video_export import compose_output_frame, compose_hdr_frame, find_ffmpeg, probe_video_stream, classify_color_info
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
    rng = np.random.default_rng(17)
    if args.hdr:
        settings['hdr_mode'] = True
        settings['nr_residual'].update(shadowStructureMultiplier=.7, reflectionGlowMultiplier=1.2, residualLightness=.8)
        source = root/'source.mp4'
        pixels = rng.integers(12000, 50000, (192, 320, 3), dtype=np.uint16)
        command = [str(find_ffmpeg()), '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
            '-pixel_format', 'rgb48le', '-video_size', '320x192', '-framerate', '24', '-i', 'pipe:0',
            '-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params',
            'log-level=error:lossless=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc',
            '-pix_fmt', 'yuv420p10le', '-color_trc', 'smpte2084',
            '-color_primaries', 'bt2020', '-colorspace', 'bt2020nc', str(source)]
        subprocess.run(command, input=b''.join(np.roll(pixels, i*2, axis=1).tobytes() for i in range(4)),
                       check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert probe_video_stream(find_ffmpeg(), source)['is_hdr'], 'Fixture lost HDR transfer metadata'
    else:
        source = root/'source.avi'
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 24, (320, 192))
        if not writer.isOpened():
            raise RuntimeError('Synthetic writer failed')
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
            if args.hdr:
                expected = compose_hdr_frame(raw.mix_source, raw[0], mix=.8, profile='hdr10_pq', settings=settings)
                np.testing.assert_array_equal(rendered[0], expected)
                assert rendered[0].dtype == np.float16 and np.isfinite(rendered[0]).all()
                assert session.metadata['hdr_metadata']['is_hdr']
            else:
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
        exported = classify_color_info(probe_video_stream(find_ffmpeg(), root/'export.mp4'))
        assert exported['is_hdr'] == args.hdr
        report = {'status': 'passed', 'guidance': info, 'frames': decoded,
                  'hdr': args.hdr, 'output_color': exported,
                  'raw_nr_reused': True, 'composition_array_exact': True,
                  'export_cache_hits': result['cache_hits'], 'export_new_frames': result['new_frames'],
                  'scope': '320x192 synthetic ' + ('HDR10/PQ' if args.hdr else 'SDR') + ', source Python, not frozen/game/performance acceptance'}
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        timer.cancel()
        manager.close()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
