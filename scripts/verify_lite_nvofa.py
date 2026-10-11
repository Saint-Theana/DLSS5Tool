"""Verify the actual portable EXE in an isolated working directory, without addon.

Local validation only, not an edition/update packaging or release workflow.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hdr', action='store_true')
    args = parser.parse_args()
    exe, output = args.exe.resolve(), args.output.resolve()
    if not exe.is_file() or output.exists():
        raise ValueError('An existing executable and a new report directory are required')
    forbidden = [path for path in exe.parent.rglob('*') if path.name.lower() in
                 ('torch', 'torchvision', 'depth_anything_v2', 'imageio_ffmpeg', 'guidance_worker.exe')]
    if forbidden or (exe.parent/'mods/enhancement').exists():
        raise AssertionError(f'Not a clean lite candidate: {forbidden}')
    output.mkdir(parents=True)
    env = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'DLSS5TOOL_GUIDANCE_PYTHON', 'FFMPEG_EXE', 'FFPROBE_EXE', 'IMAGEIO_FFMPEG_EXE'):
        env.pop(name, None)
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),
               PYINSTALLER_RESET_ENVIRONMENT='1', DLSS5TOOL_DISABLE_UPDATE_CHECK='1',
               DLSS5TOOL_SETTINGS_PATH=str(output/'settings.json'), DLSS5TOOL_QUEUE_PATH=str(output/'queue.json'))
    started = time.perf_counter()
    command = [str(exe), '--nvofa-selftest', '--output', str(output/'smoke')]
    if args.hdr:
        command.append('--hdr')
    result = subprocess.run(command, cwd=output, env=env, capture_output=True, timeout=180,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    report_path = output/'smoke/report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    evidence = {'exe_sha256': digest, 'returncode': result.returncode, 'elapsed_s': time.perf_counter()-started,
                'isolated_cwd': str(output), 'search_path': env['PATH'], 'forbidden_dependencies': [],
                'stdout': result.stdout.decode('utf-8', errors='replace'),
                'stderr': result.stderr.decode('utf-8', errors='replace'), 'smoke': report}
    (output/'verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    assert result.returncode == 0 and report.get('status') == 'passed' and report.get('frozen') is True, evidence
    for key in ('ffmpeg', 'ffprobe'):
        assert Path(report[key]).is_relative_to(exe.parent), f'{key} escaped candidate'
    print(json.dumps({'status': 'passed', 'report': str(output/'verification.json'), 'hdr': args.hdr}))


if __name__ == '__main__':
    main()
