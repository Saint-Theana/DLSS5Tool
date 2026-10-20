"""Bounded, isolated memory comparison of existing unmodified reference binaries.

The supervisor measures exact process identities externally. Only the optional
standalone Python harness loads the task-local thread notification counter.
This tool does not certify a long-term plateau or alter system configuration.
"""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save, Memory
from scripts.ngx_updater_lifecycle_probe import Processes
from scripts.compare_adapter_isolation import curve


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def request_close(pid):
    """Normal close for only top-level windows owned by the exact live child."""
    user = C.WinDLL('user32', use_last_error=True)
    callback_type = C.WINFUNCTYPE(C.c_int, C.c_void_p, C.c_ssize_t)
    user.EnumWindows.argtypes = [callback_type, C.c_ssize_t]
    user.GetWindowThreadProcessId.argtypes = [C.c_void_p, C.POINTER(C.c_uint32)]
    user.GetClassNameW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
    user.PostMessageW.argtypes = [C.c_void_p, C.c_uint32, C.c_size_t, C.c_ssize_t]
    sent = []
    @callback_type
    def callback(window, unused):
        owner = C.c_uint32()
        user.GetWindowThreadProcessId(window, C.byref(owner))
        name = C.create_unicode_buffer(256)
        user.GetClassNameW(window, name, len(name))
        if owner.value == pid and name.value == 'VeyraApp':
            sent.append(dict(window=window, posted=bool(user.PostMessageW(window, 0x10, 0, 0))))
        return 1
    if not user.EnumWindows(callback, 0):
        raise C.WinError(C.get_last_error())
    return sent


def modules(processes, identity):
    """A failed inventory is explicitly recorded, never treated as absence."""
    handle = processes.k.OpenProcess(0x410, False, identity['pid'])
    if not handle:
        return dict(error=C.get_last_error())
    try:
        psapi = C.WinDLL('psapi', use_last_error=True)
        psapi.EnumProcessModulesEx.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32,
                                              C.POINTER(C.c_uint32), C.c_uint32]
        psapi.GetModuleFileNameExW.argtypes = [C.c_void_p, C.c_void_p, C.c_wchar_p, C.c_uint32]
        values, needed = (C.c_void_p * 2048)(), C.c_uint32()
        if not psapi.EnumProcessModulesEx(handle, values, C.sizeof(values), C.byref(needed), 3):
            return dict(error=C.get_last_error())
        if needed.value > C.sizeof(values):
            return dict(error='module inventory capacity exceeded')
        found = []
        for value in values[:needed.value // C.sizeof(C.c_void_p)]:
            name = C.create_unicode_buffer(32768)
            if not psapi.GetModuleFileNameExW(handle, value, name, len(name)):
                return dict(error=C.get_last_error(), partial=found)
            found.append(dict(path=name.value, base=value))
        return dict(modules=found)
    finally:
        processes.k.CloseHandle(handle)


def standalone(args, work):
    """Call the original Python API, without monkeypatching its implementation."""
    import numpy as np
    from scripts.profile_thread_activity import load_counter, read_counter
    source = checked_path(ROOT / 'tmp/dlss5standaloneV2/dlss_engine.py')
    spec = importlib.util.spec_from_file_location('original_dlss_engine', source)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    # Keep its source/runtime paths intact, redirect only its output log.
    original.LOG_PATH = str(work / 'original-host.log')
    counter = load_counter()
    pixels = np.zeros((360, 640, 4), np.uint8)
    pixels[..., 0] = np.arange(640, dtype=np.uint16)[None, :] % 256
    pixels[..., 1] = np.arange(360, dtype=np.uint16)[:, None] % 256
    pixels[..., 3] = 255
    motion = np.zeros((360, 640, 2), np.float32)
    depth = np.ones((360, 640), np.float32)
    live = None
    records = []
    try:
        live = original.Live(640, 360, dict(guidance_mode=0))
        output = live.process(pixels, motion, depth, reset=True)
        if output is None or output.shape != pixels.shape:
            raise RuntimeError('Original reference did not return a valid first frame')
        save(work / 'first-output.json', dict(wall=time.time(), pid=os.getpid(), sha256=digest(source),
             output_sha256=hashlib.sha256(output.tobytes()).hexdigest()))
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            records.append(dict(wall=time.time(), thread_activity=read_counter(counter)))
            save(work / 'thread-activity.json', records)
            time.sleep(1)
        save(work/'idle-end.json', dict(wall=time.time(), pid=os.getpid()))
    finally:
        if live:
            save(work/'closing.json', dict(wall=time.time(), pid=os.getpid()))
            live.close()
            save(work/'closed.json', dict(wall=time.time(), pid=os.getpid()))


def supervise(args, task, work):
    from dlss5tool.memory_budget import system_memory
    from dlss5tool.process_job import KillOnCloseJob
    proc = Processes()
    memory = Memory(proc)
    baseline = {row['pid'] for row in proc.snapshot()}
    env = dict(os.environ, TEMP=str(work), TMP=str(work),
               VEYRA_LOG_FILE=str(work / 'reference.log'))
    for key in list(env):
        if key.startswith('DLSS5TOOL_P0_') or key.startswith('VEYRA_TEST_'):
            env.pop(key)
    if args.reference == 'standalone':
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--task', str(task),
                   '--label', args.label, '--reference', args.reference,
                   '--seconds', str(args.seconds), '--worker']
        if args.thread_counter:
            env['DLSS5TOOL_P0_THREAD_ACTIVITY'] = '1'
        manifests = [ROOT / 'tmp/dlss5standaloneV2' / name for name in
                     ('dlss_engine.py', 'dlssnr_host.dll', 'nvngx_dlssnr.dll')]
    else:
        binary = checked_path(task / 'veyra/Veyra.exe')
        command = [str(binary), '--smoke-seconds', str(args.seconds), '--native', '--no-fg']
        command += (['--nr', '--nr-community', '--no-sr'] if args.effect == 'nr' else
                    ['--no-nr', '--video-sr', '2'] if args.effect == 'vsr' else ['--no-nr', '--no-sr'])
        command.append(str(checked_path(task / 'source.png')))
        manifests = [path for path in (task / 'veyra').rglob('*') if path.is_file()
                     and path.suffix.lower() in ('.exe', '.dll', '.hlsl', '.hlsli')]
    before = [dict(path=str(path), bytes=path.stat().st_size, sha256=digest(path)) for path in manifests]
    save(work / 'manifest-before.json', before)
    known, held, samples, inventories, recovery = {}, {}, [], [], []
    failure = None
    started = time.monotonic()
    next_print, next_modules, exit_at = 0, 1, None
    normal_close = None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    child = job = None
    try:
        with (work / 'console.log').open('wb') as log:
            child = subprocess.Popen(command, cwd=work, env=env, stdout=log,
                stderr=subprocess.STDOUT, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW)
            job = KillOnCloseJob(child)
            save(work/'starting.json', dict(pid=child.pid, wall=time.time(), command=command))
            while True:
                now = time.monotonic()
                rows = proc.snapshot()
                family = {child.pid} | set(known)
                for _ in range(8):
                    added = {r['pid'] for r in rows if r['parent'] in family and r['pid'] not in baseline}
                    if added <= family:
                        break
                    family |= added
                active = []
                for row in rows:
                    if row['pid'] not in family:
                        continue
                    identity = proc.identity(row)
                    if 'created' not in identity:
                        continue
                    old = known.get(row['pid'])
                    if old and old['created'] != identity['created']:
                        continue
                    if row['pid'] not in held:
                        handle = proc.k.OpenProcess(0x1000 | 0x100000, False, row['pid'])
                        if not handle:
                            continue
                        held[row['pid']] = handle
                    known[row['pid']] = identity
                    if proc.k.WaitForSingleObject(held[row['pid']], 0) != 0:
                        active.append(memory.read(identity))
                status = system_memory()
                samples.append(dict(wall=time.time(), seconds=now-started, processes=active, system=status))
                if now-started >= next_modules:
                    for identity in active:
                        if 'nvngx_update' not in identity['name'].lower():
                            inventories.append(dict(wall=time.time(), identity=identity,
                                                    inventory=modules(proc, identity)))
                    next_modules += 15
                    save(work / 'modules.json', inventories)
                if now-started >= next_print:
                    save(work / 'memory-samples.json', samples)
                    print(json.dumps(dict(label=args.label, seconds=round(now-started),
                        private_mib=round(sum(v.get('private_bytes', 0) for v in active)/1024**2, 2),
                        process_count=len(active))), flush=True)
                    next_print += 20
                if (args.reference == 'veyra' and args.external_close and normal_close is None
                        and now-started >= args.seconds and child.poll() is None):
                    normal_close = dict(wall=time.time(), posted=request_close(child.pid))
                    save(work/'normal-close.json', normal_close)
                if (work/'cancel.flag').exists():
                    raise RuntimeError('Explicit task-local controller stop')
                if (sum(v.get('private_bytes', 0) for v in active) > 4*1024**3 or
                    min(status['free_physical_bytes'], status['free_commit_bytes']) < 8*1024**3):
                    raise RuntimeError('Memory safety reserve reached')
                if now-started > args.seconds+45:
                    raise TimeoutError('Reference did not finish within the bounded window')
                if child.poll() is not None:
                    exit_at = exit_at or now
                    if not active or now-exit_at > 5:
                        break
                time.sleep(.5)
    except BaseException:
        failure = traceback.format_exc()
    finally:
        remaining = [identity for pid, identity in known.items()
                     if proc.k.WaitForSingleObject(held[pid], 0) != 0]
        for identity in remaining:
            recovery.append(proc.terminate_owned(identity))
        if child is not None and child.poll() is None:
            # Popen retains the exact process object even if enumeration failed.
            child.terminate()
            child.wait(timeout=10)
        if job:
            job.close()
        final_remaining = [identity for pid, identity in known.items()
                           if proc.k.WaitForSingleObject(held[pid], 0) != 0]
        for handle in held.values():
            proc.k.CloseHandle(handle)
        save(work / 'memory-samples.json', samples)
        save(work / 'modules.json', inventories)
        after = [dict(path=str(path), bytes=path.stat().st_size, sha256=digest(path)) for path in manifests]
        save(work / 'manifest-after.json', after)
        first_output = json.loads((work/'first-output.json').read_text()) if (work/'first-output.json').is_file() else None
        idle_end = json.loads((work/'idle-end.json').read_text()) if (work/'idle-end.json').is_file() else None
        measured_pid = first_output['pid'] if first_output else child.pid if child else None
        begin_wall = (first_output['wall']+10 if first_output else samples[0]['wall']+20) if samples else 0
        end_wall = idle_end['wall'] if idle_end else normal_close['wall'] if normal_close else samples[-1]['wall'] if samples else 0
        root_points = [(s['wall'], r['private_bytes']) for s in samples if begin_wall <= s['wall'] <= end_wall
                       for r in s['processes'] if r['pid'] == measured_pid and 'private_bytes' in r]
        result = dict(arguments=vars(args), command=command, started_pid=child.pid if child else None,
            exit_code=child.poll() if child else None, elapsed_seconds=time.monotonic()-started,
            failure=failure, source_and_binary_unchanged=before == after,
            remaining_before_recovery=remaining, recovery=recovery, remaining=final_remaining,
            root_private_commit_excluding_first_20_seconds=curve(root_points),
            private_commit=curve(root_points),
            plateau_verified=False, identities=list(known.values()),
            normal_close=normal_close,
            measured_pid=measured_pid, measured_window=dict(begin_wall=begin_wall, end_wall=end_wall),
            instrumentation='external memory/module sampling; standalone optional local thread counter only')
        save(work / 'result.json', result)
        print(json.dumps({key: result[key] for key in ('exit_code', 'failure',
            'root_private_commit_excluding_first_20_seconds', 'remaining')}, default=str), flush=True)
    return 1 if failure or result['exit_code'] != 0 or final_remaining else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--reference', choices=('veyra', 'standalone'), required=True)
    parser.add_argument('--effect', choices=('off', 'nr', 'vsr'), default='nr')
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--thread-counter', action='store_true')
    parser.add_argument('--external-close', action='store_true',
                        help='Normally close the hidden reference window at the declared deadline')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    task = checked_path(args.task)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file():
        parser.error('Use a registered task under repository tmp/')
    if shutil.disk_usage(task).free < 15*1024**3+512*1024**2:
        parser.error('Insufficient disk headroom')
    if not 5 <= args.seconds <= 240 or not args.label.replace('-', '').replace('_', '').isalnum():
        parser.error('Use a simple label and 5..240 seconds')
    work = checked_path(task / args.label)
    if args.worker:
        standalone(args, work)
        return 0
    work.mkdir(exist_ok=False)
    return supervise(args, task, work)


if __name__ == '__main__':
    raise SystemExit(main())
