"""Exercise real UI controller rollback using only a synthetic owned source."""
from copy import deepcopy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool.realtime import DEFAULT_CONFIG, PresetStore
from dlss5tool.realtime_ui import RealtimeWindow


def main():
    root = tk.Tk(); root.title('Realtime rollback owned test source'); root.geometry('640x360+20+20')
    canvas = tk.Canvas(root, bg='#153348'); canvas.pack(fill='both', expand=True)
    root.update()
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]; user.GetAncestor.restype = wintypes.HWND
    hwnd = int(user.GetAncestor(root.winfo_id(), 2))
    source = {'hwnd': hwnd, 'pid': os.getpid(), 'title': 'Owned rollback target', 'application': 'owned-probe'}
    folder = ROOT / 'tmp/realtime-integration-20261003'
    store = PresetStore(folder / 'rollback-probe-presets.json')
    with mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=store), mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[source]):
        ui = RealtimeWindow(root)
    config = deepcopy(DEFAULT_CONFIG)
    config.update(windowed=True, effects=[{'name': 'Bilinear', 'parameters': {}, 'scale': [1,1], 'scaling_type': 0}])
    ui.apply_config(config)
    ui.target.current(0)  # Explicit owned target; refresh no longer auto-selects.
    started = time.monotonic()
    phase = 0
    changed_at = None
    def tick():
        nonlocal phase, changed_at
        age = time.monotonic() - started
        canvas.delete('all'); canvas.create_text(20, 20, anchor='nw', text=f'Rollback acceptance {age:.1f}s', fill='white')
        canvas.create_rectangle(20+(age*50)%450, 80, 100+(age*50)%450, 200, fill='#edc267')
        if phase == 0 and age > 1:
            phase = 1; ui.start()
        elif phase == 1 and ui._known_good and not ui._pending_start:
            # Syntactically valid effect, unavailable native backend: rejected
            # by the actual host; UI must rebuild and restore known-good config.
            broken = deepcopy(config)
            broken['effects'][0]['name'] = 'XeSS\\XeSS'
            ui.apply_config(broken)
            ui.start(); phase = 2; changed_at = age
        elif phase == 2 and ui._rollback_used and not ui._pending_start and not ui._recovering and ui._active:
            finish(True); return
        if age > 40:
            finish(False); return
        root.after(30, tick)
    def finish(success):
        result = {'success': success, 'phase': phase, 'failure_injected_at': changed_at,
                  'active_config': ui._running_config, 'saved_session': store.data.get('session'),
                  'status': ui.status.get(), 'events': list(ui.diagnostics)}
        (folder / 'probe-ui-rollback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'success': success, 'status': ui.status.get(), 'saved_known_good': store.data.get('session') == config}, ensure_ascii=False), flush=True)
        ui.close(); root.destroy()
    root.after(100, tick)
    root.mainloop()


if __name__ == '__main__': main()
