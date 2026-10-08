"""Test the real client and owned native host, including bounded fault injection."""
import argparse
from copy import deepcopy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool.realtime import RealtimeClient, DEFAULT_CONFIG, NR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, default=ROOT / 'runtime/realtime/dlss5_realtime_host.exe')
    parser.add_argument('--effect', choices=['Bilinear', 'NR'], default='Bilinear')
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--fault', choices=['none', 'suspend', 'crash'], default='none')
    parser.add_argument('--hide-cursor', action='store_true', help='Inject hidden cursor immediately before fault')
    args = parser.parse_args()
    folder = ROOT / 'tmp/realtime-parameter-fix-20261007' / (
        f'safety-{args.effect}-{args.fault}-' + ('fullscreen' if args.fullscreen else 'windowed') +
        ('-hidden-cursor' if args.hide_cursor else ''))
    folder.mkdir(parents=True, exist_ok=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    class CursorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                    ('hCursor', wintypes.HANDLE), ('pos', wintypes.POINT)]
    user.GetCursorInfo.argtypes = [ctypes.POINTER(CursorInfo)]
    user.GetClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
    def cursor():
        info, rect = CursorInfo(), wintypes.RECT()
        info.cbSize = ctypes.sizeof(info)
        user.GetCursorInfo(ctypes.byref(info))
        user.GetClipCursor(ctypes.byref(rect))
        return {'visible': bool(info.flags & 1), 'clip': [rect.left, rect.top, rect.right, rect.bottom]}

    before = cursor()
    root = tk.Tk()
    root.title('DLSS5Tool owned safety acceptance')
    root.geometry('800x450+80+80')
    canvas = tk.Canvas(root, bg='#122033', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    root.update()
    source = int(user.GetAncestor(root.winfo_id(), 2))
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    saved_cursor, source_rect = wintypes.POINT(), wintypes.RECT()
    user.GetCursorPos(ctypes.byref(saved_cursor))
    user.GetWindowRect(source, ctypes.byref(source_rect))
    root.lift()
    root.focus_force()
    user.SetForegroundWindow(source)
    user.SetCursorPos((source_rect.left + source_rect.right) // 2,
                      (source_rect.top + source_rect.bottom) // 2)
    client = RealtimeClient(host=args.host)
    with mock.patch('dlss5tool.realtime.paths.state_path', side_effect=lambda name: folder / name):
        client.launch()
    process = client.process
    # Last-resort independent process in case the feature being tested fails.
    guard = subprocess.Popen([sys.executable, '-B', str(ROOT / 'scripts/realtime_parameter_freeze_probe.py'),
                              '--watch', str(process.pid)], stdout=subprocess.PIPE, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    events, actions = [], []
    state = {'start': False, 'open': None, 'edit': False, 'closed': False, 'fault': None,
             'hotkey': None, 'idle': None, 'snapshot': False, 'source_ticks': 0}
    started = time.monotonic()

    def send(command, **fields):
        actions.append({'time': time.monotonic() - started, 'command': command, **fields})
        return client.send(command, **fields)

    def snapshot():
        # Select only a visible window owned by our exact host process. No
        # desktop screenshots and no enumeration of unrelated window titles.
        windows = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            pid, rect = wintypes.DWORD(), wintypes.RECT()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process.pid and user.IsWindowVisible(hwnd):
                user.GetWindowRect(hwnd, ctypes.byref(rect))
                area = (rect.right - rect.left) * (rect.bottom - rect.top)
                if area > 10000:
                    windows.append((area, hwnd))
            return True
        callback = callback_type(visit)
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.EnumWindows(callback, 0)
        if windows:
            from PIL import ImageGrab
            # DComp output is black through PrintWindow. Capture only the owned
            # renderer client rectangle, and only while our session owns focus.
            user.GetForegroundWindow.restype = wintypes.HWND
            foreground_pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(foreground_pid))
            if foreground_pid.value not in (process.pid, os.getpid()):
                state['snapshot_skipped'] = 'unrelated foreground'
                return
            user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
            user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
            previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            try:
                rect, point = wintypes.RECT(), wintypes.POINT()
                user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
                owned = max(windows)[1]
                user.GetClientRect(owned, ctypes.byref(rect))
                user.ClientToScreen(owned, ctypes.byref(point))
                ImageGrab.grab(bbox=(point.x, point.y, point.x + rect.right, point.y + rect.bottom),
                               all_screens=True).save(folder / 'owned-overlay.png')
            finally:
                user.SetThreadDpiAwarenessContext(previous)

    def tick():
        age = time.monotonic() - started
        state['source_ticks'] += 1
        canvas.delete('all')
        canvas.create_text(20, 20, anchor='nw', text=f'Owned safety test {age:.2f}s', fill='white', font=('Arial', 22))
        x = age * 110 % 630
        canvas.create_rectangle(x, 130, x + 130, 300, fill='#e8ad3b')
        while not client.events.empty():
            event = client.events.get_nowait()
            event['probe_time'] = age
            events.append(event)
            if event.get('event') == 'ready':
                if not event.get('independent_stop'):
                    raise RuntimeError('Supervised stop hotkey unavailable; refusing this acceptance test')
                config = deepcopy(DEFAULT_CONFIG)
                config.update(windowed=not args.fullscreen)
                config['effects'] = [{'name': NR if args.effect == 'NR' else 'Bilinear', 'parameters': {}, 'scale': [1, 1]}]
                state['start'] = True
                user.SetForegroundWindow(source)
                client.start(source, config, os.getpid())
            if event.get('event') == 'status' and event.get('metrics', {}).get('submitted', 0) > 30 and state['open'] is None:
                state['open'] = age
                send('parameters')
            if event.get('event') == 'state' and event.get('state') == 0 and state['hotkey'] is not None:
                state['idle'] = age
        if state['open'] is not None:
            elapsed = age - state['open']
            if elapsed > 1 and not state['snapshot']:
                state['snapshot'] = True
                snapshot()
                state['cursor_running'] = cursor()
            if elapsed > 1.5 and not state['edit']:
                state['edit'] = True
                if args.effect == 'NR':
                    send('set_parameter', effect=0, name='intensity', value=.65)
            if elapsed > 3 and not state['closed']:
                state['closed'] = True
                send('parameters')
            if elapsed > 4 and state['hotkey'] is None:
                if args.hide_cursor:
                    show = user.ShowSystemCursor
                    show.argtypes = [wintypes.BOOL]
                    show(False)
                    state['cursor_fault'] = cursor()
                if args.fault == 'suspend':
                    ntdll = ctypes.WinDLL('ntdll')
                    ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
                    ntdll.NtSuspendProcess.restype = wintypes.LONG
                    if ntdll.NtSuspendProcess(int(process._handle)) != 0:
                        raise RuntimeError('Could not suspend probe-owned host')
                elif args.fault == 'crash':
                    process.terminate()
                state['fault'] = age
                state['hotkey'] = age
                if args.fault != 'crash':
                    # Inject the same WM_HOTKEY received from the successfully
                    # registered shortcut; no keys are sent to another app.
                    if not user.PostThreadMessageW(client._safety._thread.native_id, 0x312, 1, 0):
                        raise ctypes.WinError(ctypes.get_last_error())
        if process.poll() is not None or state['idle'] is not None or age > 18:
            root.quit()
            return
        if state['hotkey'] is None and int(age * 2) != state.get('last_status'):
            state['last_status'] = int(age * 2)
            send('status')
        root.after(25, tick)

    try:
        if guard.stdout.readline().strip() != 'armed':
            raise RuntimeError('Probe watchdog failed to arm')
        root.report_callback_exception = lambda *error: (state.update(error=str(error[1])), root.quit())
        root.protocol('WM_DELETE_WINDOW', root.quit)
        tick()
        root.mainloop()
    finally:
        client.close()
        guard.wait(timeout=4)
        while not client.events.empty():
            events.append(client.events.get_nowait())
        state['cursor_after'] = cursor()
        if args.hide_cursor and not state['cursor_after']['visible']:
            user.ShowSystemCursor(True)  # Probe fallback, never counted as product success.
            state['cursor_fallback_required'] = True
        state['source_survived'] = bool(root.winfo_exists())
        root.destroy()
        user.SetCursorPos(saved_cursor.x, saved_cursor.y)
    statuses = [e for e in events if e.get('event') == 'status']
    report = {'state': state, 'events': events, 'actions': actions, 'cursor_before': before,
              'host_pid': process.pid, 'exit_code': process.returncode, 'watchdog': guard.stdout.read(),
              'last_submitted': statuses[-1]['metrics']['submitted'] if statuses else 0,
              'parameter_confirmed': any(abs(e.get('effects', [{}])[0].get('parameters', {}).get('intensity', -1) - .65) < 1e-5 for e in statuses if e.get('effects'))}
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(folder / 'report.json'), 'exit_code': process.returncode,
                      'last_submitted': report['last_submitted'], 'parameter_confirmed': report['parameter_confirmed'],
                      'state': state}, ensure_ascii=False), flush=True)
    if ('error' in state or not state['closed'] or not state['source_survived'] or report['watchdog']
            or state.get('cursor_fallback_required')):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
