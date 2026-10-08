"""Bounded diagnostic using only an owned animated source and isolated host state."""
from __future__ import annotations

import argparse
from copy import deepcopy
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'tmp/realtime-parameter-freeze-20261007'
sys.path.insert(0, str(ROOT))


def watchdog(pid: int) -> None:
    """An independent process, never reliant on UI callbacks or the command pipe."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100001, False, pid)  # SYNCHRONIZE | TERMINATE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    print('armed', flush=True)
    try:
        if kernel.WaitForSingleObject(handle, 25000) == 0x102:
            kernel.TerminateProcess(handle, 124)
            print('host_deadline_terminated', flush=True)
    finally:
        kernel.CloseHandle(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--effect', choices=['Bilinear', 'NR'], default='Bilinear')
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--no-panel', action='store_true', help='Control run without opening the overlay')
    parser.add_argument('--host', type=Path, default=ROOT / 'runtime/realtime/dlss5_realtime_host.exe')
    parser.add_argument('--output', type=Path, default=FOLDER)
    parser.add_argument('--case', default='')
    parser.add_argument('--screenshot', action='store_true', help='Save this owned synthetic output only')
    parser.add_argument('--watch', type=int)
    args = parser.parse_args()
    if args.watch is not None:
        watchdog(args.watch)
        return
    import tkinter as tk
    from dlss5tool import mod_paths
    from dlss5tool.realtime import DEFAULT_CONFIG, NR

    label = args.effect + ('-fullscreen' if args.fullscreen else '-windowed')
    if args.no_panel:
        label += '-control'
    if args.case:
        if not all(c.isalnum() or c in '-_' for c in args.case):
            raise ValueError('Unsafe case name')
        label += '-' + args.case
    folder = args.output.resolve() / label
    folder.mkdir(parents=True, exist_ok=True)
    host = args.host.resolve()
    environment = os.environ.copy()
    nr_path = Path(mod_paths.runtime_path({})).resolve()
    environment.update(DLSS5_REALTIME_STATE_ROOT=str(folder),
                       DLSS5_REALTIME_EFFECTS_ROOT=str(ROOT / 'runtime/realtime/effects'),
                       DLSS5_REALTIME_RUNTIME_ROOT=str(nr_path.parent),
                       DLSS5_REALTIME_NR_PATH=str(nr_path))
    root = tk.Tk()
    root.title('DLSS5Tool owned parameter-freeze diagnostic')
    root.geometry('800x450+80+80')
    canvas = tk.Canvas(root, bg='#122033', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    root.update()
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    hwnd = int(user.GetAncestor(root.winfo_id(), 2))
    process = subprocess.Popen([str(host)], cwd=folder, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                               errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
    guard = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                              '--watch', str(process.pid)], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        if guard.stdout.readline().strip() != 'armed':
            raise RuntimeError('Independent host deadline could not be armed')
        incoming, outgoing = queue.Queue(), queue.Queue()
        events, commands = [], []
        started = time.monotonic()
        state = {'ready': False, 'started': False, 'opened_at': None,
                 'closed_at': None, 'stop_at': None, 'source_ticks': 0, 'screenshot': False}

        def read() -> None:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    event = {'event': 'log', 'message': line[:2000]}
                incoming.put(event)

        def write() -> None:
            while process.poll() is None:
                item = outgoing.get()
                try:
                    process.stdin.write(json.dumps(item) + '\n')
                    process.stdin.flush()
                except (OSError, ValueError):
                    break

        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=write, daemon=True).start()

        def send(command: str, **fields) -> None:
            item = dict(fields, command=command, id=len(commands) + 1)
            commands.append({'time': time.monotonic() - started, **item})
            outgoing.put(item)

        def request_stop() -> None:
            if state['stop_at'] is None:
                state['stop_at'] = time.monotonic() - started
                send('stop')
                send('quit')

        root.protocol('WM_DELETE_WINDOW', request_stop)
        last_status = -1

        def tick() -> None:
            nonlocal last_status
            age = time.monotonic() - started
            state['source_ticks'] += 1
            canvas.delete('all')
            canvas.create_text(20, 20, anchor='nw', fill='white', font=('Arial', 20),
                               text=f'Owned synthetic source: {age:.2f}s\nParameter-panel diagnostic')
            x = (age * 130) % 630
            canvas.create_rectangle(x, 120, x + 130, 280, fill='#e8ad3b')
            while not incoming.empty():
                event = incoming.get_nowait()
                event['probe_time'] = age
                events.append(event)
                if event.get('event') == 'ready':
                    state['ready'] = True
                    if args.fullscreen and not event.get('stop_hotkey_registered'):
                        request_stop()
                if event.get('event') == 'status':
                    metrics = event.get('metrics', {})
                    print(json.dumps({'t': round(age, 2), 'state': event.get('state'),
                                      'captured': metrics.get('captured'),
                                      'submitted': metrics.get('submitted')}), flush=True)
                    if not args.no_panel and metrics.get('submitted', 0) > 30 and state['opened_at'] is None and age >= 3:
                        state['opened_at'] = age
                        send('parameters')
            if state['ready'] and not state['started'] and state['stop_at'] is None:
                config = deepcopy(DEFAULT_CONFIG)
                config.update(windowed=not args.fullscreen, game_mode=False)
                config['effects'] = [{'name': NR if args.effect == 'NR' else 'Bilinear',
                                      'parameters': {}, 'scale': [1, 1], 'scaling_type': 0}]
                state['config'] = config
                user.AllowSetForegroundWindow(process.pid)
                send('start', hwnd=hwnd, pid=os.getpid(), config=config, activate=True)
                state['started'] = True
            if state['opened_at'] is not None and age - state['opened_at'] >= 5 and state['closed_at'] is None:
                state['closed_at'] = age
                send('parameters')
            if args.screenshot and state['opened_at'] is not None and age - state['opened_at'] >= 2 and not state['screenshot']:
                state['screenshot'] = True
                send('screenshot')
            if age >= 15:
                request_stop()
            if age - last_status >= .5 and state['stop_at'] is None:
                last_status = age
                send('status')
            if process.poll() is not None or age >= 28:
                root.quit()
                return
            root.after(16, tick)

        tick()
        root.mainloop()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=3)
        guard.wait(timeout=3)
        report = {'label': label, 'host_pid': process.pid,
                  'host_sha256': hashlib.sha256(host.read_bytes()).hexdigest(),
                  'exit_code': process.returncode, 'state': state,
                  'watchdog': guard.stdout.read(), 'events': events, 'commands': commands}
        path = folder / 'report.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(path), 'exit_code': process.returncode,
                          'opened_at': state['opened_at'], 'source_ticks': state['source_ticks']}), flush=True)
    finally:
        # Every process handle here was created by this invocation only.
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
        root.destroy()
        guard.wait(timeout=4)


if __name__ == '__main__':
    main()
