"""Bounded UI-only probe with isolated state and no selectable capture targets."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tkinter as tk
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--mode', choices=('local', 'realtime'), default='realtime')
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark',
                        help='Initial theme before selecting the requested mode')
    parser.add_argument('--language', choices=('zh_CN', 'en_US'), default='zh_CN')
    parser.add_argument('--cycle', action='store_true', help='Exercise two direct mode/theme transitions')
    parser.add_argument('--reduced-motion', action='store_true', help='Probe the non-moving fade without changing Windows settings')
    parser.add_argument('--geometry', default='1000x680+0+0')
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'tmp/workbench-ui-20261003')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if not work.is_relative_to((ROOT / 'tmp').resolve()) or work == (ROOT / 'tmp').resolve():
        parser.error('--work-dir must be a task subdirectory of tmp')
    work.mkdir(exist_ok=True)
    os.environ['DLSS5TOOL_SETTINGS_PATH'] = str(work / 'probe-settings.json')
    os.environ['DLSS5TOOL_QUEUE_PATH'] = str(work / 'probe-queue.json')
    os.environ['DLSS5TOOL_DISABLE_UPDATE_CHECK'] = '1'
    os.environ['DLSS5TOOL_LANG'] = args.language
    from dlss5tool import gui, paths, ui_theme
    from dlss5tool.realtime import PresetStore
    ui_theme.enable_dpi_awareness()
    with ExitStack() as stack:
        if args.reduced_motion:
            stack.enter_context(mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=False))
        stack.enter_context(mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[]))
        stack.enter_context(mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=PresetStore(work / 'probe-realtime.json')))
        original_path = paths.state_path
        stack.enter_context(mock.patch.object(paths, 'state_path', side_effect=lambda name: work / 'native' if name == 'realtime' else original_path(name)))
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(str(error[1]))
        app = gui.App(root)
        app._apply_ui_theme(args.theme, persist=False)
        root.title('DLSS5Tool · 双模式工作台设计检查')
        root.geometry(args.geometry)
        app._select_workbench_mode(args.mode)
        if args.cycle:
            root.after(1000, app._cycle_workbench_mode)
            root.after(1600, app._cycle_workbench_mode)
        def finish():
            workspace = app._realtime_workspace
            print(json.dumps({'mode': app._workbench_mode, 'theme': app._ui_theme_name,
                              'initial_theme': args.theme, 'reduced_motion': args.reduced_motion,
                              'language': app._ui_language, 'geometry': root.geometry(),
                              'transition_finished': (app._mode_transition.cover is None
                                                      and app._mode_transition.notice is None
                                                      and app._mode_transition._after is None),
                              'catalog_effects': len(workspace.catalog) if workspace else 0,
                              'parameter_controls': len(workspace.parameters) if workspace else 0,
                              'editor_state': workspace._editor_state if workspace else None,
                              'parameter_groups': list(workspace.parameter_sections) if workspace else [],
                              'parameter_sliders': sum(row.slider is not None for row in workspace.parameter_rows.values()) if workspace else 0,
                              'parameter_choices': sum(row.choice is not None for row in workspace.parameter_rows.values()) if workspace else 0,
                              'parameter_toggles': sum(row.toggle is not None for row in workspace.parameter_rows.values()) if workspace else 0,
                              'disabled_parameters': [name for name, row in workspace.parameter_rows.items() if not row.enabled] if workspace else [],
                              'inspector_tabs': len(workspace.tabs._tabs) if workspace else 0,
                              'bottom_log_visible': bool(workspace.log.winfo_ismapped()) if workspace else False,
                              'bottom_log_shared_parent': workspace.log.frame.master is root if workspace else False,
                              'local_log_hidden': not app.log.winfo_ismapped() if workspace else None,
                              'apply_button_visible': bool(workspace.apply_button.winfo_ismapped()) if workspace else False,
                              'session': workspace.session_summary() if workspace else None,
                              'toolbar_layout': app.control_layout['mode'],
                              'caption_installed': app._caption_mode_button.installed,
                              'caption_rect': app._caption_mode_button.rect,
                              'caption_surface': app._caption_mode_button.surface is not None,
                              'caption_visible': app._caption_mode_button._surface_visible,
                              'caption_error': app._caption_mode_button.error,
                              'callback_errors': errors}, ensure_ascii=False), flush=True)
            app._on_close()
        root.after(max(10, args.seconds) * 1000, finish)
        root.mainloop()


if __name__ == '__main__':
    main()
