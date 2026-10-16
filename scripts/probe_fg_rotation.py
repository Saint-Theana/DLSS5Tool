"""Synthetic rotation regression probe; no production edits or driver changes.

Runs tagged frame_generation modules with the current shared dependencies.
This is a source-path comparison, NOT a frozen-release or cross-GPU certification.
Native mode uses the existing GPU/runtime and may take up to the normal worker timeout.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from dlss5tool.video_export import find_ffmpeg, find_ffprobe


def run(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=60,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def load_tag(tag):
    source = run(['git', 'show', f'{tag}:dlss5tool/frame_generation.py']).stdout.decode('utf-8')
    module = types.ModuleType('rotation_probe_' + tag.replace('.', '_'))
    exec(compile(source, f'{tag}:dlss5tool/frame_generation.py', 'exec'), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if not work.is_relative_to(ROOT / 'tmp') or not (work / 'TASK.md').is_file():
        parser.error('Use a registered task directory under repository tmp/')
    ffmpeg = find_ffmpeg()
    base = work / 'landscape.mp4'
    if not base.exists():
        run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
             'testsrc2=size=320x180:rate=30', '-frames:v', '6', '-c:v', 'libx264',
             '-pix_fmt', 'yuv420p', '-n', str(base)])
    cases = [('landscape', base)]
    for degrees in (90, 180, 270):
        target = work / f'rotate{degrees}.mp4'
        if not target.exists():
            run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(base), '-c', 'copy',
                 '-metadata:s:v:0', f'rotate={degrees}', '-n', str(target)])
        cases.append((f'rotate{degrees}', target))
    portrait = work / 'portrait_pixels.mp4'
    if not portrait.exists():
        run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(base), '-vf', 'transpose=1',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', str(portrait)])
    cases.append(('portrait_pixels', portrait))
    report = {'scope': 'tagged FG modules, current shared dependencies; synthetic SDR',
              'opencv': cv2.__version__, 'ffmpeg': ffmpeg, 'native': args.native,
              'cases': []}
    for tag in ('v2.3.3', 'v3.0.0'):
        module = load_tag(tag)
        for name, media in cases:
            meta, rate, width, height, total = module.inspect_source(media, threading.Event())
            cap = module.open_capture(media)
            ok, frame = cap.read()
            cap.release()
            raw = json.loads(run([find_ffprobe(ffmpeg), '-v', 'error', '-select_streams', 'v:0',
                                 '-show_streams', '-of', 'json', str(media)]).stdout)
            row = {'tag': tag, 'case': name, 'inspected_size': [width, height],
                   'decoded_size': [frame.shape[1], frame.shape[0]] if ok else None,
                   'side_data': raw['streams'][0].get('side_data_list', []),
                   'source_frames': total}
            emitted = []
            logdir = work / f'{tag}-{name}-{"native" if args.native else "cpu"}'
            if logdir.exists():
                shutil.rmtree(logdir)
            try:
                # CPU mode exercises the same dimension guard without initializing GPU.
                with patch('dlss5tool.super_resolution.query_gpu_memory', return_value=None):
                    module.export_video(media, None, multiplier=2 if args.native else 1,
                                        enhance=False, cancel=threading.Event(),
                                        progress=lambda *a: None, log_dir=logdir,
                                        frame_sink=lambda index, rgba, reference: emitted.append(index))
                row['outcome'] = 'complete'
            except Exception as error:
                row['outcome'] = 'failed'
                row['error'] = str(error).split('\n')[0]
            row['emitted_frames'] = len(emitted)
            log = logdir / 'native.log'
            if log.exists():
                lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
                row['native_markers'] = [line for line in lines if
                    any(key in line for key in ('init=', 'capabilities=', 'create=', 'evaluate=',
                                                 'release=', 'parameters=', 'FG_ERROR'))]
            report['cases'].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        # Reproduce the user's metadata/decoded-frame disagreement: ffprobe says
        # landscape, while the decoder returns a portrait frame. This stays CPU-only.
        media = work / 'portrait_pixels.mp4'
        meta, _, decoded_w, decoded_h, total = module.inspect_source(media, threading.Event())
        mismatch_log = work / f'{tag}-mismatched-orientation'
        if mismatch_log.exists():
            shutil.rmtree(mismatch_log)
        try:
            with patch('dlss5tool.super_resolution.query_gpu_memory', return_value=None):
                module.export_video(
                    media, None, multiplier=1, cancel=threading.Event(),
                    progress=lambda *a: None, log_dir=mismatch_log,
                    source_inspector=lambda *a, **k: (meta, 30, decoded_h, decoded_w, total),
                    frame_sink=lambda *a, **k: None,
                )
            outcome, error = 'complete', ''
        except Exception as exc:
            outcome, error = 'failed', str(exc).split('\n')[0]
        row = {'tag': tag, 'case': 'metadata_landscape_decoded_portrait',
               'inspected_size': [decoded_h, decoded_w], 'decoded_size': [decoded_w, decoded_h],
               'outcome': outcome, 'error': error}
        report['cases'].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    destination = work / ('native-summary.json' if args.native else 'cpu-summary.json')
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
