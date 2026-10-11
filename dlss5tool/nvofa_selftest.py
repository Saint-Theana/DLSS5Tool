"""Bounded opt-in frozen-lite smoke test. No user settings/media or downloads."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import threading
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hdr', action='store_true')
    args = parser.parse_args(argv)
    root = args.output.resolve()
    if root.exists():
        raise ValueError('Use a new output directory')
    if shutil.disk_usage(root.parent).free < 15*1024**3 + 64*1024**2:
        raise ValueError('Need 15 GiB margin + 64 MiB')
    root.mkdir()
    os.environ['DLSS5TOOL_FG_LOG_ROOT'] = str(root/'logs')
    report = {'status': 'failed', 'frozen': bool(getattr(sys, 'frozen', False)), 'hdr': args.hdr}
    started = time.perf_counter()
    manager = None
    cancel = threading.Event()
    timer = threading.Timer(120, cancel.set)
    timer.start()
    try:
        import cv2
        import numpy as np
        from dlss5tool.guidance_client import preflight
        from dlss5tool.render_cache import RenderCache, encode_cached
        from dlss5tool.video_export import find_ffmpeg, find_ffprobe, probe_video_stream
        settings = {'host_backend': 'v2', 'dlss_runtime': '__bundled__', 'intensity': .5,
                    'guidance_mode': 1, 'guidance_flow_backend': 'nvofa', 'guidance_device': 'cuda',
                    'guidance_flow_fallback': False, 'guidance_flow_edge': 128,
                    'mods_directory': str(root/'absent-addon'), 'output_mix': 1,
                    'frame_generation_multiplier': 1, 'super_resolution_scale': 1}
        info = preflight(settings)
        assert info['flow_backend'] == 'nvofa' and info['model_runtime'] == 'driver-only'
        assert info['torch_imported'] is False
        if args.hdr:
            settings['hdr_mode'] = True
            source = root/'synthetic.mp4'
            pixels = np.random.default_rng(17).integers(12000, 50000, (192, 320, 3), dtype=np.uint16)
            command = [find_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
                '-pixel_format', 'rgb48le', '-video_size', '320x192', '-framerate', '24', '-i', 'pipe:0',
                '-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params',
                'log-level=error:lossless=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc',
                '-pix_fmt', 'yuv420p10le', '-color_trc', 'smpte2084',
                '-color_primaries', 'bt2020', '-colorspace', 'bt2020nc', str(source)]
            subprocess.run(command, input=b''.join(np.roll(pixels, i*2, axis=1).tobytes() for i in range(4)),
                           check=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert probe_video_stream(find_ffmpeg(), source)['is_hdr']
        else:
            source = root/'synthetic.avi'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 24, (320, 192))
            assert writer.isOpened()
            pixels = np.random.default_rng(17).integers(25, 220, (192, 320, 3), dtype=np.uint8)
            try:
                for index in range(4):
                    writer.write(np.roll(pixels, index*2, axis=1))
            finally:
                writer.release()
        manager = RenderCache(128*1024**2)
        session = manager.session(source, settings)
        for index in range(4):
            frame = session.wait(index, cancel)[0]
            assert frame.shape == (192, 320, 4) and np.isfinite(frame).all()
        result = encode_cached(session, root/'export.mp4', settings, cancel, lambda *_: None)
        assert result['cache_hits'] == 4 and result['new_frames'] == 0
        capture = cv2.VideoCapture(str(root/'export.mp4'))
        decoded = 0
        try:
            while capture.read()[0]:
                decoded += 1
        finally:
            capture.release()
        assert decoded == 4
        assert not any(name == 'torch' or name.startswith('torch.') for name in sys.modules)
        ffmpeg = find_ffmpeg()
        stream = probe_video_stream(ffmpeg, root/'export.mp4')
        assert stream['is_hdr'] == args.hdr
        if args.hdr:
            assert stream['pix_fmt'] == 'yuv420p10le'
        report.update(status='passed', worker=info, preview_frames=4, decoded_frames=decoded,
                      export=result, ffmpeg=ffmpeg, ffprobe=find_ffprobe(ffmpeg),
                      stream=stream,
                      addon_present=(root/'absent-addon').exists(), torch_imported=False,
                      scope='synthetic NVOFA + NR preview cache/export; not GUI/game/throughput acceptance')
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        timer.cancel()
        if manager is not None:
            manager.close()
        report['elapsed_s'] = time.perf_counter() - started
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
