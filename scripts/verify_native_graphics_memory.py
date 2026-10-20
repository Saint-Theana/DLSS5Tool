"""Run bounded standalone D3D/CUDA controls without project processing DLLs."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def run(task, executable, *, concurrent_workload):
    if shutil.disk_usage(task).free < 15 * 1024**3:
        raise RuntimeError('Less than 15 GiB free on the task volume')
    output = checked_path(task/'standalone-controls')
    output.mkdir(exist_ok=False)
    source = ROOT/'scripts/native_graphics_memory_probe.cpp'
    provenance = dict(source_sha256=digest(source), binary_sha256=digest(executable),
        concurrent_workload=concurrent_workload,
        limitation='Sequential controls; any concurrent workload is declared. No throughput comparison.',
        results=[])
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetProcessTimes.argtypes = [C.c_void_p] + [C.c_void_p]*4
    kernel.GetProcessTimes.restype = C.c_int
    for label, arguments in (
        ('d3d-one', [0, 1, 1, 60]),
        ('cuda-d3d-one', [1, 1, 1, 60]),
        ('d3d-two', [0, 2, 1, 60]),
        ('d3d-churn-ten', [0, 1, 10, 60]),
    ):
        log = output/(label+'.jsonl')
        started = time.time()
        with log.open('wb') as stream:
            process = subprocess.Popen([str(executable), *map(str, arguments)],
                stdout=stream, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            created, exited, kernel_time, user_time = [C.c_uint64() for _ in range(4)]
            try:
                if not kernel.GetProcessTimes(int(process._handle), C.byref(created),
                        C.byref(exited), C.byref(kernel_time), C.byref(user_time)):
                    raise C.WinError(C.get_last_error())
                code = process.wait(timeout=90)
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                raise
        rows = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        identity = next(row for row in rows if row['event'] == 'starting')
        if identity['pid'] != process.pid:
            raise RuntimeError('Standalone PID does not match the owned child')
        entry = dict(label=label, arguments=arguments, pid=process.pid, created=created.value,
            exit_code=code, elapsed_seconds=time.time()-started, stdout_sha256=digest(log),
            closed=bool(rows and rows[-1]['event']=='closed'),
            released_device_refs=[row['retained_refs'] for row in rows if row['event']=='device-release'])
        provenance['results'].append(entry)
        save(output/'provenance.json', provenance)
        print(json.dumps(entry), flush=True)
        if code or not entry['closed'] or any(entry['released_device_refs']):
            raise RuntimeError('Standalone control did not close cleanly')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--concurrent-workload', default='none')
    args = parser.parse_args()
    task, executable = checked_path(args.task), checked_path(args.executable)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file() or not executable.is_relative_to(task):
        parser.error('Use a registered tmp task and executable inside it')
    run(task, executable, concurrent_workload=args.concurrent_workload)


if __name__ == '__main__':
    main()
