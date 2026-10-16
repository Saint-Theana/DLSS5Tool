"""Bounded, mocked realtime-panel preview; capture only this probe's own HWND."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
import ctypes
import faulthandler
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
    parser.add_argument('--mode', choices=('local', 'realtime'), default='realtime')
    parser.add_argument('--scenario', choices=('idle', 'running', 'restart', 'syncing', 'stopped', 'details'), default='idle')
    parser.add_argument('--geometry', default='1000x680')
    parser.add_argument('--inspector-width', type=int, help='Set a user-selected width in logical pixels')
    parser.add_argument('--expand-presets', action='store_true')
    parser.add_argument('--page', choices=('effects', 'workflow', 'protection', 'display', 'runtime'), default='effects')
    parser.add_argument('--hold-seconds', type=int, default=0, help='Keep the mocked window open for manual/UI-tool inspection')
    parser.add_argument('--no-screenshot', action='store_true', help='Do not capture; inspection is handled externally')
    parser.add_argument('--full-catalog', action='store_true', help='Use installed shader names as mocked catalog entries')
    parser.add_argument('--show-shortcuts', action='store_true', help='Show the isolated shortcut editor')
    parser.add_argument('--startup-timeout', type=int, default=60, help='Dump Python stacks and exit if startup cannot finish')
    args = parser.parse_args()
    faulthandler.dump_traceback_later(max(10, args.startup_timeout), exit=True)
    work = args.work_dir.resolve()
    if work == ROOT / 'tmp' or not work.is_relative_to(ROOT / 'tmp'):
        parser.error('--work-dir must be a task subdirectory of tmp')
    work.mkdir(parents=True, exist_ok=True)
    os.environ.update(DLSS5TOOL_SETTINGS_PATH=str(work / 'settings.json'),
                      DLSS5TOOL_QUEUE_PATH=str(work / 'queue.json'),
                      DLSS5TOOL_DISABLE_UPDATE_CHECK='1', DLSS5TOOL_LANG=args.language)
    from PIL import ImageGrab
    from dlss5tool import gui, ui_theme, i18n
    from dlss5tool.realtime import NR, PresetStore, effective_nr_skin
    from dlss5tool.realtime_shortcuts import DEFAULT_HOTKEYS
    from tests.test_realtime_inspector import parameter

    ui_theme.claim_app_identity('DLSS5Tool.UIProbe')
    ui_theme.enable_dpi_awareness()
    client = mock.Mock(events=queue.Queue(), generation=1, settings={})
    client.send.return_value = 1
    def configure_hotkeys(bindings):
        client.hotkeys = dict(bindings)
        client.generation += 1
        client.events.put(dict(event='ready', hotkey_bindings=dict(bindings), configurable_hotkeys=True,
                               independent_stop=True, hotkeys={k: True for k in bindings}, _generation=client.generation))
    client.configure_hotkeys.side_effect = configure_hotkeys
    errors = []
    with ExitStack() as stack:
        for name, value in [('RealtimeClient', client), ('PresetStore', PresetStore(work / 'realtime.json')),
                            ('list_windows', [])]:
            stack.enter_context(mock.patch('dlss5tool.realtime_ui.' + name, return_value=value))
        # Even manual snapshot clicks must never target a real HWND.
        stack.enter_context(mock.patch('dlss5tool.realtime_source_preview.SnapshotJob', side_effect=RuntimeError('Synthetic preview only')))
        stack.enter_context(mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=False))
        root = tk.Tk()
        root.report_callback_exception = lambda *error: errors.append(str(error[1]))
        app = gui.App(root)
        root.title('DLSS5Tool · isolated panel preview')
        root.geometry(args.geometry)
        app._select_workbench_mode(args.mode)
        app._apply_ui_theme(args.theme, persist=False)
        if args.mode == 'local':
            def finish_local():
                editor = app._local_adjustments
                print(json.dumps(dict(mode='local', language=args.language, theme=args.theme,
                    callback_errors=errors, native_started=client.start.called,
                    row_resets=sum(row.reset_button is not None for row in editor.rows.values()),
                    summary_visible=bool(editor.summary.winfo_ismapped()),
                    geometry=root.geometry()), ensure_ascii=False), flush=True)
                app._on_close()
            faulthandler.cancel_dump_traceback_later()
            root.after(max(1000, args.hold_seconds * 1000), finish_local)
            root.protocol('WM_DELETE_WINDOW', finish_local)
            root.mainloop()
            if errors or client.start.called:
                raise SystemExit(1)
            return
        ui = app._realtime_workspace
        ui._gpu_sampling = True
        descriptors = [parameter('style', label=r'NR Style\n(0 Default, 1 Natural, 2 Cinematic)', default=0, integer=True, step=1),
                       parameter('intensity', label='NR Intensity'),
                       parameter('localToneStrength', label='Local Tone Strength'),
                       parameter('localStructureStrength', label='Local Structure Strength'),
                       parameter('skinStructureStrength', label='Skin Structure Strength'),
                       parameter('useAutoMask', label='Automatic Mask', default=0, maximum=1, integer=True, step=1),
                       parameter('uiCorrection', label='NR UI Correction', default=0, maximum=1, integer=True, step=1),
                       parameter('inputResolutionPercent', label='Input Resolution (%)', default=100,
                                 minimum=25, maximum=100, integer=True, step=1)]
        descriptors.extend([
            parameter('multiPass', default=1, minimum=1, maximum=3, integer=True, step=1),
            parameter('pass2_intensity', label='NR Intensity'),
            parameter('pass3_intensity', label='NR Intensity'),
            parameter('residualMultiplier', label='Residual Multiplier', minimum=1),
            parameter('residualSaturation', label='Residual Saturation Multiplier')])
        effects = {NR: dict(name=NR, parameters=descriptors, available=True)}
        if args.full_catalog:
            directory = ROOT / 'runtime/realtime/effects'
            for path in directory.rglob('*.hlsl'):
                name = str(path.relative_to(directory).with_suffix(''))
                effects.setdefault(name, dict(name=name, parameters=[], available=True))
        client.events.put(dict(event='catalog', effects=list(effects.values()), _generation=1))
        client.events.put(dict(event='ready', hotkey_bindings=dict(DEFAULT_HOTKEYS), configurable_hotkeys=True,
                               independent_stop=True, hotkeys={k: True for k in DEFAULT_HOTKEYS}, _generation=1))
        ui.windows = [dict(hwnd=123, pid=123, title='Example source (not captured)', application='example.exe')]
        ui.target.configure(values=['Example source (not captured)'])
        ui.target.current(0)
        ui.stop_hint.set(i18n.tr('realtime.safety.protected'))

        def prepare():
            if args.show_shortcuts:
                ui._open_shortcuts()
            if args.scenario != 'idle':
                ui._active = ui._render_confirmed = True
                ui._native_state = 2
                ui._run_id = 12
                ui._metrics_run_id = 12
                ui._session_target = ui.windows[0]
                ui._running_config = effective_nr_skin(ui.collect())
                ui._applied_effects = deepcopy(ui._running_config['effects'])
                ui._parameter_modes = {(0, item['name']): 1 for item in descriptors}
                ui._metrics_compact = i18n.tr('realtime.metrics_compact', real=60, gpu='8.2 ms', quality_gpu='1.1 ms')
                ui.metrics.set(i18n.tr('realtime.metrics', capture=60, nr=60, real=60, generated='0.0',
                                      submitted=60, age='10.1 ms', gpu='8.2 ms', quality_gpu='1.1 ms', discarded=0))
                ui.gpu_load.set(i18n.tr('realtime.gpu_prefix') + 'Example GPU · 42% / 3200 MiB / 120 W')
                ui.status.set(i18n.tr('realtime.running'))
            if args.scenario == 'restart':
                ui.controls['frame_rate'][0].set('90')
            elif args.scenario == 'syncing':
                before = deepcopy(ui._applied_effects)
                after = deepcopy(before)
                after[0]['parameters']['intensity'] = .6
                ui._receive_overlay_settings([dict(event='settings_requested', token=1, run_id=12,
                    previous_effects=before, effects=after, sync_enabled=True, sync_mode=0, frame_rate=60)])
            elif args.scenario == 'stopped':
                ui._active = ui._render_confirmed = False
                ui._native_state = 0
                ui.status.set(i18n.tr('realtime.stopped'))
            elif args.scenario == 'details':
                ui.recipe_help_widget.label.focus_set()
                ui.metrics_section.toggle()
            ui._notify_session()
            if args.inspector_width is not None:
                ui._set_inspector_width(args.inspector_width * ui._layout_scale)
            if args.expand_presets:
                ui.presets_section.toggle()
            if args.page == 'protection':
                ui._focus_page('protection', ui.region_preview)
            elif args.page != 'effects':
                ui._focus_page(args.page)
            # Start the capture delay after scenario layout completes. On a
            # busy/high-DPI desktop, two timers measured from startup can both
            # expire before Tk processes the scenario's native paint events.
            faulthandler.cancel_dump_traceback_later()
            root.after(max(1000, args.hold_seconds * 1000), finish)

        def finish():
            try:
                root.update_idletasks()
                user = ctypes.WinDLL('user32', use_last_error=True)
                user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user.GetAncestor.restype = wintypes.HWND
                hwnd = user.GetAncestor(root.winfo_id(), 2)
                shot = work / f'{args.language}-{args.theme}-{args.scenario}-{args.page}.png'
                if not args.no_screenshot:
                    ImageGrab.grab(window=hwnd).save(shot)
                result = dict(image=None if args.no_screenshot else str(shot), geometry=root.geometry(), callback_errors=errors,
                              editor_state=ui._editor_state, apply_visible=bool(ui.apply_button.winfo_ismapped()),
                              metrics=ui.metrics_summary.get(), details_collapsed=ui.metrics_section.collapsed,
                              protection_collapsed=ui.protection_section.collapsed,
                              inspector_scroll=ui._pages['effects'].master.yview(),
                              stage_scroll=ui.stage_canvas.yview(),
                              stage_scrollbar=bool(ui._scroll_bars[ui.stage_scroll].winfo_ismapped()),
                              stage_top_offset=ui.stage_content.winfo_rooty()-ui.stage_canvas.winfo_rooty(),
                              inspector_width=ui.inspector.winfo_width(),
                              splitter_visible=bool(ui.splitter.winfo_ismapped()),
                              start_visible=bool(ui.start_button.winfo_ismapped()),
                              startup_controls={name: dict(mapped=bool(widget.winfo_ismapped()),
                                  size=[widget.winfo_width(), widget.winfo_height()],
                                  position=[widget.winfo_rootx(), widget.winfo_rooty()],
                                  items=len(widget.find_all())) for name, widget in
                                  [('output', ui.output_selector), ('output_settings', ui.output_details_button)]},
                              native_started=client.start.called)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            finally:
                app._on_close()

        root.after(500, prepare)
        root.protocol('WM_DELETE_WINDOW', finish)
        root.mainloop()
    if errors or client.start.called:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
