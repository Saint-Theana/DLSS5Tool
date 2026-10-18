"""Small sequential SDR/PQ/HLG SR+FG equivalence check using production APIs."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool import frame_generation as fg, dlss_host_process as host
from dlss5tool.video_export import FFmpegVideoWriter, find_ffmpeg, probe_video_stream
from scripts.diagnose_composer_lifetime import memory_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--label', default='verified')
    args = parser.parse_args()
    task = args.task.resolve(strict=True)
    if not (task/'TASK.md').is_file():
        raise ValueError('Register task first')
    prefix = 'zero-' + args.label
    destination = task/f'{prefix}-pipeline.json'
    if destination.exists():
        raise ValueError('Refusing report overwrite')
    if min(memory_snapshot()[k] for k in ('free_physical_bytes', 'free_commit_bytes')) < 2*1024**3:
        raise MemoryError('Insufficient headroom')
    ffmpeg = find_ffmpeg()
    reports = []
    for profile in ('srgb', 'hdr10_pq', 'hdr10_hlg'):
        source = task/f'{prefix}-source-{profile}.mp4'
        hdr = profile != 'srgb'
        codec = (['-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params',
                  'pools=2:frame-threads=1:log-level=error:colorprim=9:colormatrix=9:transfer=' +
                  ('16' if profile == 'hdr10_pq' else '18'), '-pix_fmt', 'yuv420p10le',
                  '-color_primaries', 'bt2020', '-colorspace', 'bt2020nc', '-color_trc',
                  'smpte2084' if profile == 'hdr10_pq' else 'arib-std-b67'] if hdr else
                 ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p'])
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-f', 'lavfi',
            '-i', 'testsrc2=size=256x256:rate=30', '-frames:v', '8', *codec, str(source)],
            check=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        source_meta = probe_video_stream(ffmpeg, source)
        if source_meta['profile'] != profile:
            raise RuntimeError('Fixture colour profile mismatch: ' + str(source_meta))
        reference = None
        for mode in ('plain', 'quality-zero', 'basic-zero'):
            output = task/f'{prefix}-{profile}-{mode}.mp4'
            hashes, formats, host_pids = [], [], []
            original_write, original_host_init = FFmpegVideoWriter.write, host._HostSession.__init__
            def write(self, frame):
                hashes.append(hashlib.sha256(memoryview(frame).cast('B')).hexdigest())
                if not formats:
                    formats.append(dict(dtype=str(frame.dtype), shape=list(frame.shape),
                        unique_first_channel=int(np.unique(frame[..., 0]).size)))
                return original_write(self, frame)
            def host_init(self, *a, **k):
                original_host_init(self, *a, **k)
                host_pids.append(self._process.pid)
            settings = dict(host_backend='v2', host_auto_fallback=False, host_in_flight=1,
                hdr_mode=True, guidance_mode=0, output_mix=1., output_view=0,
                nvenc_preset='p5', quality_profile='high', rate_control='quality')
            if mode == 'quality-zero':
                settings['nr_quality'] = {'total': 0}
            if mode == 'basic-zero':
                settings.update(intensity=0., local_tone=0., local_struct=0., skin_struct=0., use_auto_mask=False)
            started = time.perf_counter()
            row = dict(profile=profile, mode=mode, source=str(source), source_metadata=source_meta,
                       output=str(output), settings=settings)
            try:
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(FFmpegVideoWriter, 'write', write))
                    stack.enter_context(mock.patch.object(host._HostSession, '__init__', host_init))
                    row['result'] = fg.export_video(source, output, scale=2, multiplier=2,
                        enhance=mode != 'plain', settings=settings,
                        log_dir=task/f'{prefix}-{profile}-{mode}-logs')
                if reference is None:
                    reference = hashes.copy()
                row.update(status='complete', raw_hashes=hashes, formats=formats, nr_host_pids=host_pids,
                    equivalent_to_plain=(hashes == reference), output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
                output_meta = probe_video_stream(ffmpeg, output)
                row['output_metadata'] = output_meta
                if output_meta['profile'] != profile or (hdr and formats[0]['dtype'] != 'float16'):
                    raise RuntimeError('Output colour/precision contract mismatch')
                if hdr and output_meta['pixel_format'] != 'yuv420p10le':
                    raise RuntimeError('HDR was not encoded as Main10')
                if host_pids or len(hashes) != 16 or hashes != reference:
                    raise RuntimeError('Zero path differs or unexpectedly starts NR')
            except Exception as error:
                row.update(status='failed', error=str(error))
            row['elapsed_seconds'] = time.perf_counter()-started
            reports.append(row)
            print(json.dumps({k:row.get(k) for k in ('profile','mode','status','error','equivalent_to_plain','elapsed_seconds')}, ensure_ascii=False), flush=True)
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(dict(pid=os.getpid(), cases=reports, memory_after=memory_snapshot()), stream, ensure_ascii=False, indent=2)
    return int(any(row['status'] != 'complete' for row in reports))


if __name__ == '__main__':
    raise SystemExit(main())
