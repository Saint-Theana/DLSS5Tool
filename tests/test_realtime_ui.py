"""Tk controller acceptance without capturing or interacting with other apps."""
from copy import deepcopy
from pathlib import Path
import queue
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest import mock

from dlss5tool.realtime import DEFAULT_CONFIG, PresetStore, NR
from dlss5tool.realtime_ui import RealtimeWorkspace
from dlss5tool import ui_theme, i18n


class RealtimeUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        ui_theme.apply_ttk(self.root, ui_theme.tokens('dark'))
        self.temp = tempfile.TemporaryDirectory(prefix='realtime-ui-')
        self.store = PresetStore(Path(self.temp.name) / 'presets.json')
        self.store.data['session'] = dict(deepcopy(DEFAULT_CONFIG), windowed=False)
        self.client = mock.Mock()
        self.client.events = queue.Queue()
        self.client.generation = 1
        self.client.settings = {}
        self.client.send.return_value = 1
        self.client.start.return_value = 2
        with mock.patch('dlss5tool.realtime_ui.RealtimeClient', return_value=self.client), mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=self.store), mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[]):
            self.ui = RealtimeWorkspace(self.root)
        self.ui.window.pack(fill='both', expand=True)
        self.root.geometry('1000x680')
        self.ui._gpu_sampling = True
        self.root.update()

    def tearDown(self):
        self.ui.close()
        self.root.destroy()
        self.temp.cleanup()
        i18n.set_language(i18n.DEFAULT_LANGUAGE)
        self.assertEqual(self.callback_errors, [])

    def test_stop_hint_reports_protected_and_unavailable_states(self):
        self.event({'event': 'ready', 'stop_hotkey_registered': True, 'independent_stop': True})
        self.assertEqual(self.ui.stop_hint.get(), i18n.tr('realtime.safety.protected'))
        self.event({'event': 'ready', 'stop_hotkey_registered': False})
        self.assertEqual(self.ui.stop_hint.get(), i18n.tr('realtime.safety.unavailable'))

    def test_parameter_shortcut_conflict_explains_main_window_fallback(self):
        self.event({'event': 'ready', 'hotkeys': {'stop': True, 'parameters': False}})
        self.assertEqual(self.ui._control_tip.text, i18n.tr('realtime.control.unavailable'))
        self.event({'event': 'ready', 'hotkeys': {'stop': True, 'parameters': True}})
        self.assertEqual(self.ui._control_tip.text, i18n.tr('realtime.control.help'))

    def test_fresh_store_defaults_to_windowed_without_overwriting_existing_session(self):
        self.ui.close()
        self.store.data.pop('session', None)
        with mock.patch('dlss5tool.realtime_ui.RealtimeClient', return_value=self.client), \
             mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=self.store), \
             mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[]):
            self.ui = RealtimeWorkspace(self.root)
        self.assertTrue(self.ui.output_mode.get())
        self.assertEqual(self.ui._display_targets['game_mode'].cget('state'), 'disabled')

    def test_output_selector_is_visible_and_keyboard_operable(self):
        self.assertFalse(self.ui.output_mode.get())
        self.ui._focus_page('display', self.ui.output_selector)
        self.root.update()
        self.assertTrue(self.ui.output_selector.winfo_ismapped())
        self.assertIs(self.ui.tabs._current, self.ui._pages['effects'].master.master)
        self.ui.output_selector._nudge(1)
        self.assertTrue(self.ui.collect()['windowed'])
        self.assertEqual(str(self.ui._display_targets['window_scale'].cget('state')), 'normal')
        self.ui.output_selector._nudge(-1)
        self.assertFalse(self.ui.collect()['windowed'])
        self.assertEqual(str(self.ui._display_targets['window_scale'].cget('state')), 'disabled')

    def test_windowed_choice_resolves_conflicts_without_starting(self):
        self.ui.controls['capture_method'][0].current(1)
        self.ui.controls['game_mode'][0].set(True)
        self.client.send.reset_mock()
        self.ui.output_selector._nudge(1)
        config = self.ui.collect()
        self.assertTrue(config['windowed'])
        self.assertEqual(config['capture_method'], 0)
        self.assertFalse(config['game_mode'])
        self.assertEqual(self.ui._display_targets['game_mode'].cget('state'), 'disabled')
        self.assertIn(i18n.tr('realtime.output.adjust_capture'), self.ui.output_hint.get())
        self.assertIn(i18n.tr('realtime.output.adjust_mouse'), self.ui.output_hint.get())
        self.client.start.assert_not_called()
        self.client.send.assert_not_called()
        self.ui.output_selector._nudge(-1)
        self.assertEqual(self.ui._display_targets['game_mode'].cget('state'), 'normal')
        self.assertFalse(self.ui.collect()['game_mode'])
        self.assertEqual(self.ui.collect()['capture_method'], 0)

    def test_dd_selection_keeps_windowed_mode_and_explains_fallback(self):
        self.ui.output_selector._nudge(1)
        self.ui.controls['capture_method'][0].current(1)
        self.ui.controls['capture_method'][0].combo.event_generate('<<ComboboxSelected>>')
        self.root.update_idletasks()
        self.assertTrue(self.ui.collect()['windowed'])
        self.assertEqual(self.ui.collect()['capture_method'], 0)
        self.assertIn(i18n.tr('realtime.output.adjust_capture'), self.ui.output_hint.get())

    def test_compatible_capture_and_unfinished_parameter_draft_are_preserved(self):
        for method in (0, 2, 3):
            self.ui.controls['capture_method'][0].current(method)
            self.ui.output_mode.set(True)
            self.ui._output_changed()
            self.assertEqual(self.ui.collect()['capture_method'], method)
        self.ui.quality_controls['total'].set('unfinished')
        self.ui.output_selector._nudge(-1)
        self.assertEqual(self.ui.quality_controls['total'].get(), 'unfinished')
        self.assertEqual(self.ui._editor_state, 'invalid')

    def test_running_output_change_waits_for_explicit_restart(self):
        running = self.ui.collect()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._running_config = deepcopy(running)
        self.ui._applied_effects = deepcopy(running['effects'])
        self.client.send.reset_mock()
        self.ui.output_selector._nudge(1)
        self.assertEqual(self.ui._editor_state, 'restart')
        self.assertEqual(self.ui._running_config, running)
        self.client.start.assert_not_called()
        self.client.send.assert_not_called()

    def test_preset_restores_output_selection_and_scale_without_migration(self):
        config = self.ui.collect()
        config.update(windowed=True, window_scale=1.75, capture_method=3)
        self.ui.apply_config(config)
        self.assertTrue(self.ui.output_mode.get())
        self.assertEqual(self.ui._display_targets['game_mode'].cget('state'), 'disabled')
        self.assertEqual(self.ui.collect(), config)
        self.ui.output_selector._nudge(-1)
        self.ui.output_selector._nudge(1)
        self.assertEqual(self.ui.collect()['window_scale'], 1.75)
        self.ui.apply_config(dict(deepcopy(DEFAULT_CONFIG), windowed=False))
        self.assertFalse(self.ui.output_mode.get())
        self.assertEqual(str(self.ui._display_targets['window_scale'].cget('state')), 'disabled')

    def test_output_mode_survives_saved_session_reload(self):
        self.ui.output_selector._nudge(1)
        self.ui.controls['window_scale'][0].set('1.5')
        config = self.ui.collect()
        self.store.save_session(config)
        self.ui.apply_config(PresetStore(self.store.path).data['session'])
        self.assertEqual(self.ui.collect(), config)

    def test_failed_cursor_recovery_is_visible(self):
        self.event({'event': 'cursor_restore', 'ok': False})
        self.assertEqual(self.ui.status.get(), i18n.tr('realtime.safety.cursor_failed'))

    def test_emergency_stop_cancels_pending_edits_and_restart(self):
        self.ui._active = True
        self.ui._queued_parameter_apply = True
        self.ui._recovery_target = ('source', {})
        self.event({'event': 'emergency_stop'})
        self.assertTrue(self.ui._stop_requested)
        self.assertFalse(self.ui._queued_parameter_apply)
        self.assertIsNone(self.ui._recovery_target)
        self.client.send.assert_any_call('stop')

    def test_abnormal_exit_disables_automatic_fullscreen_restart(self):
        self.ui._active = True
        self.ui._known_good = ({'hwnd': 42}, deepcopy(DEFAULT_CONFIG))
        self.event({'event': 'exited', 'returncode': 0xc0000421})
        self.assertIsNone(self.ui._recovery_target)

    def test_emergency_during_recovery_never_restarts_fullscreen(self):
        self.ui._recovering = True
        self.ui._recovery_target = ({'hwnd': 42}, deepcopy(DEFAULT_CONFIG))
        self.ui._recovery.put(None)
        self.event({'event': 'emergency_stop'})
        self.assertIsNone(self.ui._recovery_target)
        self.client.start.assert_not_called()


    def test_effect_editor_localizes_metadata_without_changing_parameter_ids(self):
        effect = self.ui.config['effects'][0]
        before = deepcopy(effect)
        descriptions = [
            ('shadowStructureMultiplier', 'Shadow / Structure Control', 'Detail Control', []),
            ('amdOpticalFlowMode', 'OF Quality', 'Detail Control', [[0, 'Performance'], [1, 'Quality']]),
            ('nvidiaOpticalFlowQuality', 'OF Quality', 'Detail Control', [[2, 'Balanced']]),
            ('style', r'NR Style\n(0 Default, 1 Natural, 2 Cinematic)', 'DLSSNR · Pass 1', []),
        ]
        parameters = [dict(name=name, label=label, group=group, choices=choices,
                           default=choices[0][0] if choices else 1, min=0, max=2 if name == 'style' else 5, step=1, integer=True)
                      for name, label, group, choices in descriptions]
        self.ui.catalog[effect['name']] = {'parameters': parameters}
        def label_text(widget):
            values = []
            if widget.winfo_class() == 'TLabel':
                values.append(str(widget.cget('text')))
            if hasattr(widget, '_title'):
                values.append(widget._title)
            if hasattr(widget, '_choices'):
                values.append(str(widget._choices))
            if widget.winfo_class() == 'TCombobox':
                values.append(str(widget.cget('values')))
            for child in widget.winfo_children():
                values.extend(label_text(child))
            return values
        for lang in ('zh_CN', 'en_US'):
            i18n.set_language(lang)
            self.ui._select_effect()
            labels = '\n'.join(label_text(self.ui.parameter_frame))
            if lang == 'zh_CN':
                for expected in ('阴影／结构控制', 'AMD 光流质量', 'NVIDIA 光流质量', '性能优先', '画面调整', '默认'):
                    self.assertIn(expected, labels)
                self.assertNotIn('OF Quality', labels)
                self.assertNotIn('Performance', labels)
            else:
                self.assertIn('AMD optical flow quality', labels)
                self.assertIn('Performance', labels)
                self.assertFalse(any('\u4e00' <= c <= '\u9fff' for c in labels))
            self.assertEqual(set(self.ui.parameters), {p['name'] for p in parameters})
            self.assertEqual(self.ui.config['effects'][0]['name'], before['name'])
            self.ui.parameters['style'][1].set('2')
            self.assertEqual(self.ui.collect()['effects'][0]['parameters']['style'], 2)

    def test_english_workspace_static_controls_and_session_use_english(self):
        self.ui.close()
        i18n.set_language('en_US')
        with mock.patch('dlss5tool.realtime_ui.RealtimeClient', return_value=self.client), \
             mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=self.store), \
             mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[]):
            self.ui = RealtimeWorkspace(self.root)
        def inspect(widget):
            for option in ('text', 'values'):
                try:
                    value = str(widget.cget(option))
                except tk.TclError:
                    continue
                self.assertFalse(any('\u4e00' <= c <= '\u9fff' for c in value), value)
                self.assertNotIn('realtime.', value)
            for child in widget.winfo_children():
                inspect(child)
        inspect(self.ui.window)
        self.assertIn('Idle', self.ui.session_summary()[0])
        self.assertIn('Not started', self.ui.status.get())

    def event(self, value):
        if self.ui._after:
            self.ui.window.after_cancel(self.ui._after)
        self.client.events.put(dict(value, _generation=1))
        self.ui._poll()

    def test_mousewheel_handles_tcl_popdown_strings_and_destroyed_widgets(self):
        combo = self.ui.effect_choice.combo
        combo.configure(values=[str(i) for i in range(40)])
        self.root.update_idletasks()
        popdown = str(self.root.tk.call('ttk::combobox::PopdownWindow', str(combo)))
        self.root.tk.call('ttk::combobox::Post', str(combo))
        try:
            for widget in (popdown + '.f.l', '.missing.popdown', str(combo), self.ui.log, None):
                with self.subTest(widget=str(widget)):
                    self.assertIsNone(self.ui.on_mousewheel(SimpleNamespace(widget=widget, delta=-120)))
        finally:
            self.root.tk.call('ttk::combobox::Unpost', str(combo))
        removed = tk.Label(self.ui.window)
        removed.destroy()
        self.assertIsNone(self.ui.on_mousewheel(SimpleNamespace(widget=removed, delta=-120)))
        self.assertIsNone(self.ui.on_mousewheel(SimpleNamespace(widget=combo, delta=0)))

    def test_mousewheel_still_scrolls_inspector_and_handles_empty_canvas(self):
        page, canvas = next(iter(self.ui._scroll_canvases.items()))
        with mock.patch.object(canvas, 'bbox', return_value=(0, 0, 100, 2000)), \
             mock.patch.object(canvas, 'yview_scroll') as scroll:
            self.assertEqual(self.ui.on_mousewheel(SimpleNamespace(widget=str(page), delta=-120)), 'break')
            scroll.assert_called_once_with(3, 'units')
        with mock.patch.object(canvas, 'bbox', return_value=None):
            self.assertEqual(self.ui.on_mousewheel(SimpleNamespace(widget=page, delta=120)), 'break')

    def test_log_summarizes_protocol_without_losing_diagnostic_details(self):
        self.event({'event': 'ready', 'protocol': 1, 'hotkeys': {'stop': True}, 'magpie_commit': 'technical-hash'})
        device_event = {'event': 'devices', 'monitors': [], 'adapters': [],
                        'runtime': {'nr': r'C:\private\runtime.dll'}, 'capabilities': {'dlss_nr': True}}
        self.event(device_event)
        for i in range(80):
            self.event({'event': 'ack', 'ok': True, 'id': i})
        self.event({'event': 'ack', 'ok': False, 'id': 99, 'message': 'No active session', 'code': 123})
        visible = self.ui.log.get('1.0', 'end')
        self.assertIn('[实时]', visible)
        self.assertIn('尚未开始增强', visible)
        self.assertIn('已发现 0 台显示器', visible)
        self.assertIn('123', visible)
        for token in ('_generation', 'quality_revision', 'technical-hash', 'private', '"event"', 'No active session'):
            self.assertNotIn(token, visible)
        snapshot = self.ui.diagnostics.snapshot()
        self.assertEqual(snapshot['latest']['devices']['runtime'], device_event['runtime'])
        self.assertEqual(snapshot['errors'][-1]['code'], 123)
        self.assertEqual(snapshot['errors'][-1]['message'], 'No active session')
        self.assertLess(len(visible.splitlines()), 8)

    def test_user_log_deduplicates_status_and_retains_bounded_tail(self):
        for _ in range(10):
            self.ui.status.set('same message')
        self.assertEqual(self.ui.log.get('1.0', 'end').count('same message'), 1)
        for i in range(550):
            self.ui._write_log(f'message {i}')
        self.assertLessEqual(int(self.ui.log.index('end-1c').split('.')[0]), 500)
        self.assertIn('message 549', self.ui.log.get('1.0', 'end'))

    def test_initialization_is_not_rendering_success(self):
        # This case checks first-session persistence, not the saved fullscreen
        # session used by the other UI fixtures.
        self.store.data.pop('session', None)
        import time
        selected = {'hwnd': 123, 'pid': 456, 'application': 'test.exe'}
        config = deepcopy(DEFAULT_CONFIG)
        self.ui._pending_start = (selected, config)
        self.ui._pending_since = time.monotonic()
        self.event({'event': 'state', 'state': 1, 'run_id': 3})
        self.event({'event': 'state', 'state': 2, 'run_id': 3})
        self.assertIsNone(self.ui._known_good)
        self.assertNotIn('session', self.store.data)
        self.event({'event': 'status', 'state': 2, 'run_id': 3, 'metrics': {'submitted': 1}})
        self.assertEqual(self.ui._known_good, (selected, config))
        self.assertEqual(self.store.data['session'], config)

    def test_stale_status_does_not_confirm_new_session(self):
        self.ui._run_id = 4
        self.event({'event': 'status', 'run_id': 3, 'metrics': {'submitted': 100}})
        self.assertIsNone(self.ui._last_metrics)

    def test_previous_running_status_cannot_confirm_queued_restart(self):
        self.ui._run_id = 3
        self.ui._pending_start = ({'hwnd': 123}, deepcopy(DEFAULT_CONFIG))
        self.ui._pending_since = __import__('time').monotonic()
        self.event({'event': 'status', 'state': 2, 'run_id': 3, 'metrics': {'submitted': 200}})
        self.assertIsNone(self.ui._known_good)

    def test_quality_waits_for_matching_ack_and_gpu_revision(self):
        self.ui._active = True
        self.ui._run_id = 3
        self.ui._running_config = deepcopy(DEFAULT_CONFIG)
        self.ui.quality_controls['total'].set('0.5')
        self.ui.apply_quality()
        self.event({'event': 'status', 'run_id': 3, 'quality_revision': 4, 'quality_applied_revision': 4})
        self.assertEqual(self.ui._running_config['quality']['total'], 1)
        self.event({'event': 'ack', 'id': 1, 'ok': True, 'run_id': 3, 'quality_revision': 5})
        self.event({'event': 'status', 'run_id': 3, 'quality_revision': 5, 'quality_applied_revision': 4})
        self.assertIsNotNone(self.ui._pending_quality)
        self.event({'event': 'status', 'run_id': 3, 'quality_revision': 5, 'quality_applied_revision': 5})
        self.assertIsNone(self.ui._pending_quality)
        self.assertEqual(self.store.data['session']['quality']['total'], 0.5)

    def test_running_native_error_requests_recovery(self):
        self.ui._active = True
        with mock.patch.object(self.ui, '_recover') as recover:
            self.event({'event': 'error', 'message': 'NR evaluate failed'})
            recover.assert_called_once_with('NR evaluate failed')

    def test_stopped_live_edit_sends_nothing(self):
        self.client.send.reset_mock()
        self.ui.live_parameters()
        self.client.send.assert_not_called()

    def test_restart_required_edit_is_not_partially_sent(self):
        self.ui._active = True
        self.ui._applied_effects = [{'name': NR, 'parameters': {'x': 0}, 'scale': [1, 1], 'scaling_type': 0}]
        self.ui.catalog = {NR: {'parameters': [{'name': 'x', 'default': 0}]}}
        self.ui.parameters = {'x': (0, tk.StringVar(self.root, value='1'), False)}
        self.ui._parameter_modes = {(0, 'x'): 2}
        self.client.send.reset_mock()
        self.ui.live_parameters()
        self.client.send.assert_not_called()
        self.assertIn('重启', self.ui.status.get())

    def test_start_ack_failure_requests_recovery(self):
        self.ui._pending_command = 2
        with mock.patch.object(self.ui, '_recover') as recover:
            self.event({'event': 'ack', 'id': 2, 'ok': False, 'message': 'unavailable'})
            recover.assert_called_once_with('unavailable')

    def test_idle_footer_explains_start_without_redundant_apply_action(self):
        self.root.geometry('800x600')
        self.root.update()
        button = self.ui.apply_button
        self.assertFalse(button.winfo_ismapped())
        self.assertEqual(button.cget('state'), 'disabled')
        footer = self.ui.editor_footer
        self.assertTrue(footer.winfo_ismapped())
        self.assertLessEqual(footer.winfo_rooty() + footer.winfo_height(), self.ui.window.winfo_rooty() + self.ui.window.winfo_height())


    def test_embedded_without_toplevel_or_automatic_capture(self):
        self.assertIs(self.ui.window.winfo_toplevel(), self.root)
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))
        self.client.start.assert_not_called()
        self.assertEqual([call.args[0] for call in self.client.send.call_args_list], ['catalog', 'devices'])

    def test_minimized_session_is_still_stoppable(self):
        self.event({'event': 'state', 'state': 4, 'run_id': 2})
        text, busy = self.ui.session_summary()
        self.assertTrue(busy)
        self.assertIn('等待源窗口', text)
        self.assertEqual(self.ui.stop_button.cget('state'), 'normal')
        self.client.send.reset_mock()
        self.ui.command('stop')
        self.client.send.assert_called_once_with('stop')
        self.event({'event': 'state', 'state': 0, 'run_id': 2})
        self.assertFalse(self.ui.session_summary()[1])

    def test_summary_is_running_target_not_editor_target_or_status_message(self):
        self.ui._session_target = {'title': '正在运行的游戏'}
        self.ui._active = self.ui._render_confirmed = True
        self.ui.windows = [{'hwnd': 2, 'pid': 3, 'title': '另一窗口', 'application': 'other.exe'}]
        self.ui.target.configure(values=['另一窗口'])
        self.ui.target.current(0)
        self.ui.status.set('预设已保存')
        self.assertEqual(self.ui.session_summary(), ('实时增强 · 运行中 · 正在运行的游戏', True))

    def test_refresh_never_silently_retargets_disappeared_window(self):
        old = {'hwnd': 2, 'pid': 3, 'title': 'old', 'application': 'old.exe'}
        new = dict(old, pid=4, title='reused handle')
        self.ui.windows = [old]
        self.ui.target.configure(values=['old'])
        self.ui.target.current(0)
        with mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[new]):
            self.ui.refresh()
        self.assertIsNone(self.ui.selected_window())

    def test_region_coordinates_follow_resized_canvas(self):
        from PIL import Image
        from dlss5tool.realtime_snapshot import Snapshot
        self.ui.source_preview.snapshot = Snapshot(Image.new('RGB', (640, 360), '#345678'), (1920, 1080))
        self.ui.source_preview.edit_regions()
        editor = self.ui.source_preview.editor
        self.root.update()
        left, top, right, bottom = editor.bounds()
        editor.begin(SimpleNamespace(x=left+(right-left)*.1, y=top+(bottom-top)*.2))
        editor.end(SimpleNamespace(x=left+(right-left)*.8, y=top+(bottom-top)*.9))
        editor.apply()
        self.assertEqual(self.ui.collect()['quality']['regions'], [[.1, .2, .8, .9]])
        self.root.geometry('840x640')
        self.root.update()
        self.assertEqual(self.ui.collect()['quality']['regions'], [[.1, .2, .8, .9]])


    def test_stop_during_recovery_cancels_restart_without_second_teardown(self):
        self.ui._recovering = True
        self.ui._recovery_target = ({'hwnd': 123}, deepcopy(DEFAULT_CONFIG))
        self.client.send.reset_mock()
        self.ui.command('stop')
        self.assertIsNone(self.ui._recovery_target)
        self.client.send.assert_not_called()
        self.ui._recovery.put(None)
        self.event({'event': 'log', 'message': 'probe'})
        self.client.start.assert_not_called()
        self.assertFalse(self.ui.session_summary()[1])

    def test_stale_status_during_stop_cannot_report_success(self):
        self.ui._run_id = 3
        self.ui._active = True
        self.ui.command('stop')
        self.event({'event': 'status', 'state': 2, 'run_id': 3, 'metrics': {'submitted': 200}})
        self.assertIn('停止中', self.ui.session_summary()[0])
        self.assertIsNone(self.ui._known_good)
        self.event({'event': 'status', 'state': 0, 'run_id': 3})
        self.assertFalse(self.ui.session_summary()[1])


if __name__ == '__main__': unittest.main()
