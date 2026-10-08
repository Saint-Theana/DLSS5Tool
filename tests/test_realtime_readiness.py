"""Passive checks, truthful summaries and same-workbench navigation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime import DEFAULT_CONFIG, NR, validate_config
from dlss5tool.realtime_readiness import StartIssue, chain_summary, check_start
from tests import test_realtime_ui
from tests.test_realtime_inspector import parameter


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.host = self.directory / 'host.exe'
        self.runtime = self.directory / 'nr.dll'
        self.host.touch()
        self.runtime.touch()
        patch = mock.patch('dlss5tool.realtime_readiness.mod_paths.runtime_info',
                           return_value={'path': str(self.runtime), 'fallback': False, 'ambiguous': False})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)

    def check(self, **overrides):
        args = dict(config=dict(deepcopy(DEFAULT_CONFIG), windowed=False), selected={'hwnd': 1, 'pid': 2},
                    settings={}, catalog={NR: {'available': True}}, host=self.host,
                    ready={'stop_hotkey_registered': True}, target_state='ready')
        args.update(overrides)
        return check_start(**args)

    def test_clear_check_is_passive_and_does_not_change_configuration(self):
        source = deepcopy(DEFAULT_CONFIG)
        with mock.patch('ctypes.WinDLL', side_effect=AssertionError('must not load a DLL')), \
             mock.patch('subprocess.Popen', side_effect=AssertionError('must not start a process')):
            self.assertEqual(self.check(config=source), [])
        self.assertEqual(source, DEFAULT_CONFIG)

    def test_target_host_nr_and_fullscreen_shortcut_blockers_have_routes(self):
        self.runtime.unlink()
        issues = self.check(selected=None, host=self.directory / 'missing.exe', ready={'stop_hotkey_registered': False})
        self.assertEqual({i.code: i.route for i in issues},
                         {'target': 'target', 'host': 'diagnostics', 'nr_missing': 'nr_runtime', 'hotkey': 'display'})
        self.assertTrue(all(i.blocking for i in issues))
        windowed = validate_config({'windowed': True})
        self.assertNotIn('hotkey', [i.code for i in self.check(config=windowed, ready={'stop_hotkey_registered': False})])

    def test_target_identity_missing_blocks_but_minimized_is_advisory(self):
        issue = self.check(target_state='missing')[0]
        self.assertEqual((issue.code, issue.blocking), ('target_gone', True))
        issue = self.check(target_state='minimized')[0]
        self.assertEqual((issue.code, issue.blocking), ('target_minimized', False))

    def test_handshake_features_and_catalog_unknown_are_not_false_compatibility_failures(self):
        config = validate_config({'effects': [{'name': 'DLSS\\DLSS_SR'}, {'name': 'DLSSFG\\DLSS_FrameGeneration'}]})
        issues = self.check(config=config, ready=None, catalog={})
        self.assertEqual({i.code for i in issues}, {'handshake', 'catalog_wait', 'features'})
        self.assertFalse(any(i.blocking for i in issues))
        self.assertIn('nvngx_dlss.dll', issues[-1].message)
        self.assertIn('nvngx_dlssg.dll', issues[-1].message)

    def test_effect_conflict_unavailable_and_hdr_capture_have_specific_actions(self):
        config = validate_config({'effects': [{'name': 'DLSSFG/A'}, {'name': 'XeSSFG/B'}], 'hdr': True, 'capture_method': 1})
        issues = self.check(config=config, catalog={'DLSSFG\\A': {'available': True}, 'XeSSFG\\B': {'available': False}})
        by_code = {i.code: i for i in issues}
        self.assertTrue(by_code['fg_conflict'].blocking)
        self.assertEqual(by_code['effect_unavailable'].effect_index, 1)
        self.assertEqual(by_code['hdr_capture'].route, 'display')

    def test_checks_host_launch_selection_not_new_resolver_selection(self):
        selection = dict(path=str(self.directory / 'launched-but-missing.dll'), fallback=True)
        with mock.patch('dlss5tool.realtime_readiness.mod_paths.runtime_info', side_effect=AssertionError('wrong snapshot')):
            issues = self.check(runtime_selection=selection)
        self.assertEqual(issues[0].code, 'nr_missing')
        self.assertIn('launched-but-missing.dll', issues[0].detail)

    def test_ordered_summary_handles_passes_unknown_effects_and_long_chains(self):
        effects = [{'name': NR, 'parameters': {'multiPass': 2}}, {'name': 'DLSS\\DLSS_SR'},
                   {'name': 'DLSSFG\\DLSS_FrameGeneration'}, {'name': 'Custom\\Example'}]
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            text = chain_summary(effects)
            self.assertLess(text.index('NR'), text.index('DLSS SR'))
            self.assertLess(text.index('DLSS SR'), text.index('DLSS FG'))
            self.assertIn('2', text)
            self.assertIn('Example', text)
            self.assertNotIn('realtime.', text)
            self.assertIn('1', chain_summary(effects + [effects[0]]))
            self.assertEqual(chain_summary(effects + [effects[0]], max_items=None).count('→'), 4)
        self.assertIn('?', chain_summary([{'name': NR, 'parameters': {'multiPass': 'incomplete'}}]))


    def test_windows_target_probe_checks_pid_and_minimized_state_without_activation(self):
        import ctypes
        from dlss5tool.realtime import target_window_state
        user = mock.Mock()
        user.IsWindow.return_value = True
        user.IsIconic.return_value = False
        def get_pid(hwnd, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_ulong)).contents.value = 34
            return 1
        user.GetWindowThreadProcessId.side_effect = get_pid
        with mock.patch('dlss5tool.realtime.ctypes.WinDLL', return_value=user):
            self.assertEqual(target_window_state({'hwnd': 12, 'pid': 34}), 'ready')
            self.assertEqual(target_window_state({'hwnd': 12, 'pid': 35}), 'missing')
            user.IsIconic.return_value = True
            self.assertEqual(target_window_state({'hwnd': 12, 'pid': 34}), 'minimized')
        user.SetForegroundWindow.assert_not_called()
        user.ShowWindow.assert_not_called()


class ReadinessUiTests(unittest.TestCase):
    setUp = test_realtime_ui.RealtimeUiTests.setUp
    tearDown = test_realtime_ui.RealtimeUiTests.tearDown
    event = test_realtime_ui.RealtimeUiTests.event

    def select_target(self):
        self.ui.windows = [dict(hwnd=12, pid=34, title='Owned test', application='test.exe')]
        self.ui.target.configure(values=['Owned test'])
        self.ui.target.current(0)

    def configure_checks(self):
        self.select_target()
        self.client.host = Path(self.temp.name) / 'host.exe'
        self.client.host.touch()
        nr = Path(self.temp.name) / 'nr.dll'
        nr.touch()
        self.client.runtime_selection = {'path': str(nr)}
        self.ui._host_ready = {'_generation': 1, 'stop_hotkey_registered': True}
        self.ui.catalog = {NR: {'available': True}}
        self.ui._catalog_generation = 1

    def test_start_checks_without_sending_commands_or_overwriting_running_state(self):
        self.configure_checks()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._session_target = {'title': 'Running target'}
        self.ui._running_config = deepcopy(DEFAULT_CONFIG)
        self.ui._queued_parameter_apply = self.ui._queued_quality_apply = True
        self.client.send.reset_mock()
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='missing'):
            self.ui.start()
        self.client.start.assert_not_called()
        self.client.send.assert_not_called()
        self.assertTrue(self.ui._render_confirmed)
        self.assertTrue(self.ui._queued_parameter_apply)
        self.assertTrue(self.ui._queued_quality_apply)
        self.assertEqual(self.ui._session_target['title'], 'Running target')
        self.assertTrue(self.ui.preflight_panel.winfo_manager())
        self.assertEqual(self.ui._preflight_issues[0].code, 'target_gone')

    def test_warning_requires_confirmation_and_continuation_rechecks_blockers(self):
        self.configure_checks()
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='minimized'):
            self.ui.start()
        self.client.start.assert_not_called()
        self.assertTrue(self.ui.continue_button.winfo_manager())
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='missing'):
            self.ui.continue_button.invoke()
        self.client.start.assert_not_called()
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='ready'):
            self.ui.start()
        self.client.start.assert_called_once()
        self.assertIsNotNone(self.ui._pending_start)
        self.assertFalse(self.ui._render_confirmed)
        self.assertNotIn('实际运行', self.ui.running_summary.get())

    def test_check_button_never_starts_and_draft_changes_invalidate_previous_result(self):
        self.configure_checks()
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='minimized'):
            self.ui.check_before_start()
        self.client.start.assert_not_called()
        self.ui.quality_controls['total'].set('.5')
        self.ui._refresh_editor_state()
        self.assertEqual(self.ui.continue_button.cget('state'), 'disabled')
        self.assertIn('重新检查', self.ui.preflight_status.get())

    def test_stale_handshake_cannot_reuse_previous_hotkey_or_runtime_snapshot(self):
        self.configure_checks()
        self.client.generation = 2
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='ready'), \
             mock.patch('dlss5tool.realtime_ui.check_start', return_value=[]) as checker:
            self.ui.check_before_start()
        self.assertIsNone(checker.call_args.kwargs['ready'])
        self.assertIsNone(checker.call_args.kwargs['runtime_selection'])
        self.assertEqual(checker.call_args.kwargs['catalog'], {})

    def test_invalid_draft_routes_to_parameter_group_without_starting(self):
        self.select_target()
        self.ui.quality_controls['total'].set('unfinished')
        self.ui.start()
        self.client.start.assert_not_called()
        self.assertEqual(self.ui._preflight_issues[0].route, 'protection')
        self.ui.locate_button.invoke()
        self.assertIs(self.ui.tabs._current, self.ui._pages['protection'].master.master)
        self.assertEqual(self.ui.quality_controls['total'].get(), 'unfinished')

    def test_summary_distinguishes_draft_pending_and_confirmed_running_chain(self):
        items = [parameter('multiPass', default=1, minimum=1, maximum=3, integer=True, step=1),
                 parameter('pass2_intensity'), parameter('pass3_intensity')]
        self.event({'event': 'catalog', 'effects': [dict(name=NR, parameters=items, available=True)]})
        self.ui._active = self.ui._render_confirmed = True
        self.ui._run_id = 8
        self.ui._running_config = self.ui.collect()
        self.ui._applied_effects = deepcopy(self.ui._running_config['effects'])
        self.ui.parameters['multiPass'][1].set('3')
        self.assertIn('待应用', self.ui.draft_summary.get())
        self.assertIn('3 遍', self.ui.draft_summary.get())
        self.assertIn('实际运行：NR 单遍', self.ui.running_summary.get())
        applied = deepcopy(self.ui._applied_effects)
        applied[0]['parameters']['multiPass'] = 3
        self.event(dict(event='status', state=2, run_id=8, effects=applied, metrics={'submitted': 1}))
        self.assertIn('实际运行：NR 3 遍', self.ui.running_summary.get())
        self.event(dict(event='state', state=4, run_id=8))
        self.assertIn('上次确认', self.ui.running_summary.get())
        self.event(dict(event='state', state=0, run_id=8))
        self.assertNotIn('实际运行', self.ui.running_summary.get())

    def test_failed_restart_keeps_last_confirmed_effects_and_summary(self):
        self.configure_checks()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._running_config = deepcopy(DEFAULT_CONFIG)
        self.ui._applied_effects = deepcopy(DEFAULT_CONFIG['effects'])
        self.ui._applied_effects[0]['parameters']['multiPass'] = 3
        self.client.start.side_effect = RuntimeError('test failure')
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='ready'), \
             mock.patch('dlss5tool.realtime_ui.messagebox.showerror'):
            self.ui.start()
        self.assertTrue(self.ui._render_confirmed)
        self.assertIn('实际运行：NR 3 遍', self.ui.running_summary.get())

    def test_preflight_messages_are_bilingual_and_not_raw_translation_keys(self):
        self.configure_checks()
        self.ui._host_ready['stop_hotkey_registered'] = False
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='missing'):
                self.ui.check_before_start()
            texts = [self.ui.preflight_status.get(), self.ui.preflight_message.get()]
            texts += [issue.message for issue in self.ui._preflight_issues]
            for text in texts:
                self.assertNotIn('realtime.', text)
                self.assertEqual(any('\u4e00' <= c <= '\u9fff' for c in text), language == 'zh_CN')

    def test_issue_navigation_and_inline_help_keep_same_workspace(self):
        self.configure_checks()
        self.ui._host_ready['stop_hotkey_registered'] = False
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='ready'):
            self.ui.check_before_start()
        page = self.ui.tabs._current
        with mock.patch.object(self.ui.output_selector, 'focus_set') as focus:
            self.ui.locate_button.invoke()
            focus.assert_called_once()
        self.assertIs(self.ui.tabs._current, page)
        self.assertFalse(self.ui.controls['windowed'][0].get())
        self.ui._preflight_issues = [StartIssue('nr_missing', 'nr_runtime', 'missing')]
        self.ui.preflight_choice.current(0)
        with mock.patch.object(self.ui, '_on_nr_settings') as nr_settings:
            self.ui._locate_preflight()
            nr_settings.assert_called_once()
        help_widget = self.ui.effect_help_widget
        self.assertFalse(hasattr(help_widget, 'details'))
        self.assertTrue(help_widget.tooltip.text)
        self.ui._focus_page('effects', help_widget.label)
        self.root.update()
        help_widget.label.event_generate('<Enter>')
        self.assertIsNotNone(help_widget.tooltip.tip)
        help_widget.label.event_generate('<Leave>')
        self.assertIsNone(help_widget.tooltip.tip)
        for theme in ('light', 'dark'):
            self.ui.apply_theme(ui_theme.tokens(theme))
        self.client.start.assert_not_called()

    def test_open_check_panel_preserves_start_stop_controls_at_minimum_size(self):
        self.configure_checks()
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='missing'):
            self.ui.check_before_start()
        for geometry in ('1000x680', '1280x800'):
            self.root.geometry(geometry)
            self.root.update()
            for button in (self.ui.start_button, self.ui.stop_button, self.ui.check_button, self.ui.locate_button):
                self.assertTrue(button.winfo_ismapped())
                self.assertGreater(button.winfo_width(), 20)
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())


if __name__ == '__main__':
    unittest.main()
