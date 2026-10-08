"""Bounded native guidance/input acceptance using only a synthetic owned source."""
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
from dlss5tool import ui_theme


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--game', action='store_true')
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--nr', action='store_true')
    parser.add_argument('--fault', action='store_true')
    args = parser.parse_args()
    ui_theme.enable_dpi_awareness()
    folder = args.output.resolve()
    if not folder.is_relative_to(ROOT / 'tmp') or folder == ROOT / 'tmp':
        parser.error('Output must be a task subdirectory of tmp')
    folder.mkdir(parents=True, exist_ok=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.GetClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
    user.ClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    class CursorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD), ('cursor', wintypes.HANDLE), ('point', wintypes.POINT)]
    user.GetCursorInfo.argtypes = [ctypes.POINTER(CursorInfo)]
    def cursor():
        value, clip = CursorInfo(), wintypes.RECT()
        value.cbSize = ctypes.sizeof(value)
        user.GetCursorInfo(ctypes.byref(value)); user.GetClipCursor(ctypes.byref(clip))
        return dict(visible=bool(value.flags & 1), clip=[clip.left, clip.top, clip.right, clip.bottom])
    before, position = cursor(), wintypes.POINT()
    user.GetCursorPos(ctypes.byref(position))
    root = tk.Tk(); root.title('Owned guidance/input test')
    root.geometry('900x550+100+100')
    canvas = tk.Canvas(root, bg='#10243a', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    clicks = []
    canvas.bind('<ButtonPress-1>', lambda _: clicks.append(time.monotonic()))
    canvas.create_text(450, 260, text='Synthetic source · no private content', fill='white', font=('Arial', 24))
    root.update()
    source = user.GetAncestor(root.winfo_id(), 2)
    def activate_source():
        user.SetForegroundWindow(source)
        root.lift(); root.focus_force(); root.update_idletasks()
        if user.GetForegroundWindow() == source: return
        # USER32 may deny programmatic foreground activation. Click only this
        # owned source's verified title bar to emulate a real user's activation.
        rect = wintypes.RECT(); user.GetWindowRect(source, ctypes.byref(rect))
        point = wintypes.POINT(rect.left + 80, rect.top + 12)
        user.SetCursorPos(point.x, point.y)
        if user.GetAncestor(user.WindowFromPoint(point), 2) != source:
            raise RuntimeError('Owned source is occluded; cannot safely activate test')
        user.mouse_event(2, 0, 0, 0, 0); user.mouse_event(4, 0, 0, 0, 0)
        root.update()
    activate_source()
    user.SetCursorPos(500, 400)
    if args.game:
        root.configure(cursor='none'); canvas.configure(cursor='none')
    client = RealtimeClient(host=args.host)
    real_popen = subprocess.Popen
    def launch(*arguments, **kwargs):
        kwargs['env']['DLSS5_REALTIME_EFFECTS_ROOT'] = str(ROOT / 'runtime/realtime/effects')
        return real_popen(*arguments, **kwargs)
    with mock.patch('dlss5tool.realtime.paths.state_path', return_value=folder), \
         mock.patch('dlss5tool.realtime.subprocess.Popen', side_effect=launch):
        client.launch()
    process = client.process
    guard = subprocess.Popen([sys.executable, '-B', str(ROOT / 'scripts/realtime_parameter_freeze_probe.py'), '--watch', str(process.pid)],
                             stdout=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if guard.stdout.readline().strip() != 'armed': raise RuntimeError('watchdog failed')
    events, states, feedback, pictures = [], [], [], []
    started = time.monotonic()
    phase = dict(first=None, opened=False, closed=False, stop=None, idle=None)
    def owned(hwnd):
        pid = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == process.pid
    def snapshot(hwnd, name):
        if not hwnd or not owned(hwnd): return
        foreground = user.GetForegroundWindow()
        if foreground != source and not owned(foreground): return
        from PIL import ImageGrab
        user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            rect = wintypes.RECT(); user.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right <= rect.left or rect.bottom <= rect.top: return
            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(folder / (name + '.png'))
        finally:
            user.SetThreadDpiAwarenessContext(previous)
        pictures.append(name)
    def tick():
        now = time.monotonic() - started
        if not args.static:
            canvas.delete('tick')
            canvas.create_rectangle(20 + now * 30 % 700, 400, 80 + now * 30 % 700, 450, fill='#f5b44c', tags='tick')
        while not client.events.empty():
            event = client.events.get_nowait(); event['time'] = now; events.append(event)
            if event.get('event') == 'ready':
                if not event.get('independent_stop'): raise RuntimeError('No supervised stop')
                config = deepcopy(DEFAULT_CONFIG)
                config.update(windowed=not args.fullscreen, game_mode=args.game)
                config['effects'] = [dict(name=NR if args.nr else 'Bilinear', parameters={}, scale=[1, 1])]
                user.SetForegroundWindow(source)
                client.start(source, config, os.getpid())
            if event.get('event') == 'ack' and not event.get('ok'):
                raise RuntimeError(event.get('message', 'Command failed'))
            if event.get('event') == 'status':
                g = event.get('guidance', {})
                if g:
                    states.append(dict(time=now, **g, cursor=cursor(), foreground=int(user.GetForegroundWindow() or 0), submitted=event['metrics']['submitted']))
                popup = g.get('feedback_hwnd')
                if popup and owned(popup) and user.IsWindowVisible(popup):
                    label = ctypes.create_unicode_buffer(256); user.GetWindowTextW(popup, label, 256)
                    if label.value and label.value not in feedback: feedback.append(label.value)
                if event['metrics']['submitted'] > 0 and phase['first'] is None:
                    phase['first'] = now
                if phase['first'] is not None:
                    age = now - phase['first']
                    if age > .5 and 'intro' not in pictures: snapshot(g.get('output_hwnd'), 'intro')
                    if age > 6 and not phase['opened']:
                        # Restore only our explicitly owned test source, simulating
                        # invoking controls while the game is in the foreground.
                        activate_source()
                        user.SetCursorPos(500, 400)
                        phase['activation_foreground'] = int(user.GetForegroundWindow() or 0)
                        phase['before_control'] = cursor()
                        phase['opened'] = True; client.send('parameters')
                    if age > 7.2 and g.get('control_mode') == 1 and 'control' not in pictures:
                        snapshot(g.get('output_hwnd'), 'control')
                        hwnd = g.get('control_hwnd')
                        # Owned input-host button edges in a blank game area:
                        # first click must be consumed while leaving Edit.
                        if hwnd and owned(hwnd):
                            user.PostMessageW(hwnd, 0x201, 1, 20 | (400 << 16))
                            user.PostMessageW(hwnd, 0x202, 0, 20 | (400 << 16))
                    if age > 8 and not phase['closed']:
                        phase['closed'] = True; client.send('parameters')
                    if age > 9 and phase['stop'] is None:
                        if args.fault:
                            ntdll = ctypes.WinDLL('ntdll'); ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
                            if ntdll.NtSuspendProcess(int(process._handle)) != 0: raise RuntimeError('Suspend failed')
                        phase['stop'] = now
                        user.PostThreadMessageW(client._safety._thread.native_id, 0x312, 1, 0)
            if event.get('event') == 'state' and event.get('state') == 0 and phase['stop'] is not None:
                phase['idle'] = now
        if process.poll() is not None or now > 20 or (phase['idle'] is not None and now - phase['idle'] > 1.2):
            root.quit(); return
        if int(now * 10) != phase.get('poll') and (not args.fault or phase['stop'] is None):
            phase['poll'] = int(now * 10); client.send('status')
        root.after(25, tick)
    root.report_callback_exception = lambda *err: (phase.update(error=str(err[1])), root.quit())
    try:
        tick(); root.mainloop()
    finally:
        client.close(); guard.wait(timeout=5)
        while not client.events.empty(): events.append(client.events.get_nowait())
        root.configure(cursor=''); canvas.configure(cursor='')
        root.update_idletasks()
        after = cursor(); root.destroy()
        user.ClipCursor(None); user.SetCursorPos(position.x, position.y)
    report = dict(phase=phase, source_hwnd=int(source),
                  states=states, events=events, feedback=feedback, source_clicks=len(clicks),
                  cursor_before=before, cursor_after=after, exit=process.returncode, watchdog=guard.stdout.read())
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    brief = dict(phase=phase, feedback=feedback, source_clicks=len(clicks), exit=process.returncode,
                 control_seen=any(s.get('control_mode') == 1 for s in states),
                 hidden_seen=any(s.get('stop_alpha') == 0 and s.get('phase') == 2 for s in states),
                 report=str(folder / 'report.json'))
    print(json.dumps(brief, ensure_ascii=False), flush=True)
    first = phase['first']
    introductory = [s for s in states if first is not None and first + .4 < s['time'] < first + 4.5]
    controls = [s for s in states if s.get('control_mode') == 1]
    assert introductory and all(s['toolbar_alpha'] == 1 and s['stop_alpha'] == 1 for s in introductory)
    assert all(s['toolbar_alpha'] == s['stop_alpha'] for s in states)
    assert controls and all(s['foreground'] == s['control_hwnd'] for s in controls)
    if args.fullscreen and args.game:
        assert controls[0]['cursor']['clip'] != phase['before_control']['clip']
        returned = [s for s in states if s['time'] > controls[-1]['time'] and s['control_mode'] == 0 and s['time'] < phase['stop']]
        assert returned and returned[-1]['cursor']['clip'] == phase['before_control']['clip']
    if args.fault:
        forced = next(e for e in events if e.get('event') == 'safety_stop')
        assert 1.8 < forced['time'] - phase['stop'] < 3.5
        assert any(e.get('event') == 'cursor_restore' and e.get('ok') for e in events)
        assert phase['idle'] is None and '已退出增强' not in feedback
    else:
        assert phase['idle'] is not None and phase['idle'] - phase['stop'] < 2
        assert process.returncode == 0
    if phase.get('error') or report['watchdog'] or not brief['control_seen'] or not brief['hidden_seen']:
        raise SystemExit(1)


if __name__ == '__main__': main()
