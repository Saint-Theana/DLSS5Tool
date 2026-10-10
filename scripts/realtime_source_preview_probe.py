"""Bounded synthetic-only capture/layout acceptance; no native enhancement starts."""
import argparse
from copy import deepcopy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import sys
import time
import tkinter as tk
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dlss5tool import ui_theme, i18n
    from dlss5tool.realtime import PresetStore, DEFAULT_CONFIG, nr_preset
    from dlss5tool.realtime_snapshot import SnapshotJob, SnapshotError, capture_window
    from dlss5tool.realtime_ui import RealtimeWorkspace
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/realtime-source-preview-20261008')
    parser.add_argument('--language', choices=('zh_CN', 'en_US'), default='zh_CN')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    i18n.set_language(args.language)
    user = ctypes.WinDLL('user32')
    user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    root = tk.Tk(); root.title('DLSS5Tool synthetic preview acceptance')
    root.geometry('1280x960+40+40')
    ui_theme.apply_ttk(root, ui_theme.tokens('dark'))
    source = tk.Toplevel(root); source.title('Synthetic capture fixture')
    source.geometry('800x450+110+120')
    canvas = tk.Canvas(source, bg='#243447', highlightthickness=0); canvas.pack(fill='both', expand=True)
    canvas.create_rectangle(24, 24, 185, 88, fill='#617585', outline='')
    canvas.create_text(40, 40, text='HUD  ·  100 / 100', fill='#ffffff', anchor='nw', font=('Segoe UI', 16))
    canvas.create_rectangle(250, 180, 600, 290, fill='#487a70', outline='')
    canvas.create_text(425, 230, text='SYNTHETIC SOURCE', fill='#ffffff', font=('Segoe UI', 18))
    canvas.create_text(400, 408, text='Subtitle / protection region', fill='#ffffff', font=('Segoe UI', 18))
    root.update()
    target = dict(hwnd=int(user.GetAncestor(source.winfo_id(), 2)), pid=os.getpid(), title='Synthetic source', application='synthetic.exe')
    client = mock.Mock(); client.events = queue.Queue(); client.generation = 1; client.settings = {}
    store = PresetStore(args.output/'probe-presets.json')
    config = deepcopy(DEFAULT_CONFIG)
    config['quality'].update(protection=True, regions=[[.025, .035, .24, .21], [.19, .84, .81, .97]])
    store.data['presets'] = {'Game setup': config}
    store.data['nr_presets'] = {'Natural detail': nr_preset(config)}
    store.data['session'] = config
    with mock.patch('dlss5tool.realtime_ui.RealtimeClient', return_value=client), \
         mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=store), \
         mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[target]):
        ui = RealtimeWorkspace(root, on_copy_local=lambda: None)
    ui.window.pack(fill='both', expand=True)
    ui.target.set(''); ui._notify_session()
    root.update(); root.lift()
    report = {}; failures = []

    def wait_job(job, completed, deadline=None):
        deadline = deadline or time.monotonic()+8
        try:
            result = job.poll()
            if result is not None: completed(result); return
            if time.monotonic() > deadline: raise TimeoutError('probe timeout')
            root.after(40, lambda: wait_job(job, completed, deadline))
        except Exception as error:
            failures.append(str(error)); finish()

    def save_ui(name, after):
        root.update_idletasks()
        # Only this probe's own window; no desktop or foreign app reads.
        window = dict(hwnd=int(user.GetAncestor(root.winfo_id(), 2)), pid=os.getpid())
        def saved(result):
            result.image.save(args.output/(args.language+'-'+name+'.png'))
            report[name] = {'size': result.source_size, 'preset_height': ui.presets_section.winfo_height(),
                            'action_row': ui.preset_actions.grid_info()['row']}
            root.after(150, after)
        wait_job(SnapshotJob(window), saved)

    def finish():
        for expected, fixture in [('missing', dict(target, pid=target['pid']+1)), ('minimized', target)]:
            if expected == 'minimized': source.iconify(); root.update()
            try:
                capture_window(fixture)
                failures.append('expected '+expected)
            except SnapshotError as error:
                report[expected] = str(error) == expected
                if str(error) != expected: failures.append('wrong failure '+str(error))
        timeout_job = SnapshotJob(target, timeout=0)
        try:
            timeout_job.poll(); failures.append('timeout not enforced')
        except SnapshotError as error:
            report['timeout_reaped'] = str(error) == 'timeout' and not timeout_job.process.is_alive()
            if not report['timeout_reaped']: failures.append('worker not reaped')
        report['failures'] = failures
        report['native_started'] = client.start.called
        print(json.dumps(report, ensure_ascii=False), flush=True)
        ui.close(); source.destroy(); root.destroy()

    def light_presets():
        ui._focus_page('startup', ui.presets_section)
        root.after(200, lambda: save_ui('light-presets', frozen))

    def frozen():
        # Simulate presentation state only; never start native enhancement.
        ui._active = ui._render_confirmed = True
        ui._session_target = target
        ui._notify_session()
        ui.stage_canvas.yview_moveto(0)
        root.after(200, lambda: save_ui('frozen', finish))

    def light():
        ui.apply_theme(ui_theme.tokens('light')); ui_theme.apply_ttk(root, ui_theme.tokens('light'))
        root.geometry('960x780'); root.after(250, lambda: save_ui('light-narrow', light_presets))

    def editor():
        ui.source_preview.edit_regions(); root.update()
        edit = ui.source_preview.editor
        target_edit = dict(hwnd=int(user.GetAncestor(edit.window.winfo_id(), 2)), pid=os.getpid())
        def saved(result):
            result.image.save(args.output/(args.language+'-regions-editor.png')); edit.close(); light()
        wait_job(SnapshotJob(target_edit), saved)

    def dark_presets():
        ui._focus_page('startup', ui.presets_section)
        root.after(200, lambda: save_ui('dark-presets', editor))

    def await_source(deadline):
        if ui.source_preview.snapshot:
            snapshot = ui.source_preview.snapshot
            report['source_size'] = snapshot.source_size
            report['source_image_size'] = snapshot.image.size
            report['source_nonblack'] = snapshot.image.getbbox() is not None
            if snapshot.source_size != (800, 450): failures.append('source crop differs from synthetic client')
            save_ui('dark-wide', dark_presets)
        elif time.monotonic() > deadline or ui.source_preview.job is None:
            failures.append(ui.source_preview.message.get()); finish()
        else:
            root.after(100, lambda: await_source(deadline))
    def begin_source():
        ui.apply_theme(ui_theme.tokens('dark')); ui_theme.apply_ttk(root, ui_theme.tokens('dark'))
        root.geometry('1280x960')
        ui.target.current(0)
        ui.presets_section.toggle(); ui.preset_choice.set('Game setup'); ui._preset_scope_changed()
        ui._target_changed()
        root.after(100, lambda: await_source(time.monotonic()+8))

    def idle_light():
        ui.apply_theme(ui_theme.tokens('light')); ui_theme.apply_ttk(root, ui_theme.tokens('light'))
        root.geometry('960x780')
        root.after(250, lambda: save_ui('idle-light', begin_source))

    root.after(250, lambda: save_ui('idle-dark', idle_light))
    root.mainloop()
    return 1 if failures else 0


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
