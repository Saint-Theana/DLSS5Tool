"""UI-only output-mode acceptance; no native capture or user settings touched."""
import argparse
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import sys
import tkinter as tk
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--language', choices=('zh_CN', 'en_US'), default='zh_CN')
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark')
    parser.add_argument('--windowed', action='store_true')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if work == ROOT / 'tmp' or not work.is_relative_to(ROOT / 'tmp'):
        parser.error('--work-dir must be a task subdirectory of tmp')
    work.mkdir(parents=True, exist_ok=True)
    os.environ.update(DLSS5TOOL_SETTINGS_PATH=str(work / 'settings.json'),
                      DLSS5TOOL_QUEUE_PATH=str(work / 'queue.json'),
                      DLSS5TOOL_DISABLE_UPDATE_CHECK='1', DLSS5TOOL_LANG=args.language)
    from dlss5tool import gui, ui_theme
    from dlss5tool.realtime import PresetStore
    from PIL import ImageGrab

    ui_theme.enable_dpi_awareness()
    client = mock.Mock(events=queue.Queue(), generation=1, settings={})
    client.send.return_value = 1
    errors = []
    with ExitStack() as stack:
        for name, value in [('RealtimeClient', client),
                            ('PresetStore', PresetStore(work / 'realtime.json')), ('list_windows', [])]:
            stack.enter_context(mock.patch('dlss5tool.realtime_ui.' + name, return_value=value))
        stack.enter_context(mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=False))
        root = tk.Tk()
        root.report_callback_exception = lambda *error: errors.append(str(error[1]))
        app = gui.App(root)
        root.title('DLSS5Tool output-mode UI acceptance')
        root.geometry('1000x680')
        app._select_workbench_mode('realtime')
        app._apply_ui_theme(args.theme, persist=False)
        ui = app._realtime_workspace
        ui._gpu_sampling = True
        ui.windows = [dict(hwnd=123, pid=123, title='Example source (not captured)', application='example.exe')]
        ui.target.configure(values=['Example source (not captured)'])
        ui.target.current(0)
        if args.windowed:
            ui.controls['capture_method'][0].current(1)
            ui.controls['game_mode'][0].set(True)
            ui.output_selector._nudge(1)
        ui._focus_page('display')
        ui.stop_hint.set('Ctrl+Alt+F10 · UI-only test')

        def finish():
            try:
                root.update_idletasks()
                user = ctypes.WinDLL('user32', use_last_error=True)
                user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user.GetAncestor.restype = wintypes.HWND
                hwnd = user.GetAncestor(root.winfo_id(), 2)
                # Pillow's window= uses PrintWindow: only this owned HWND,
                # including when obscured, never a screenshot of the desktop.
                shot = work / f'{args.language}-{args.theme}-{args.windowed}.png'
                ImageGrab.grab(window=hwnd).save(shot)
                config = ui.collect()
                result = {'image': str(shot), 'callback_errors': errors,
                          'windowed': config['windowed'], 'capture_method': config['capture_method'],
                          'game_mode': config['game_mode'], 'geometry': root.geometry(),
                          'theme': app._ui_theme_name,
                          'selector_visible': bool(ui.output_selector.winfo_ismapped()),
                          'start_visible': bool(ui.start_button.winfo_ismapped()),
                          'stop_visible': bool(ui.stop_button.winfo_ismapped())}
                print(json.dumps(result, ensure_ascii=False), flush=True)
            finally:
                app._on_close()

        root.after(1500, finish)
        root.mainloop()
        if errors:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
