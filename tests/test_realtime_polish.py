"""Lifecycle-aware presentation; no native enhancement or source capture."""
from copy import deepcopy
from unittest import TestCase, mock

from dlss5tool import i18n, ui_theme
from tests import test_realtime_inspector as inspector


class RealtimePolishTests(TestCase):
    setUp = inspector.RealtimeInspectorTests.setUp
    tearDown = inspector.RealtimeInspectorTests.tearDown
    catalog = inspector.RealtimeInspectorTests.catalog
    running = inspector.RealtimeInspectorTests.running
    event = inspector.RealtimeInspectorTests.event

    def test_idle_is_compact_and_empty_target_cannot_start(self):
        self.catalog()
        ui = self.ui
        self.assertTrue(ui.tools_section.collapsed)
        self.assertFalse(ui.runtime_info.winfo_manager())
        self.assertFalse(ui.output_hint_widget.winfo_manager())
        self.assertEqual(ui.start_button.cget('state'), 'disabled')
        ui.start_button.invoke()
        self.client.start.assert_not_called()
        self.assertFalse(ui.parameter_sections['look'].collapsed)
        ui.windows = [dict(hwnd=1, pid=2, application='fixture.exe', title='Fixture')]
        ui.target.configure(values=['Fixture'])
        ui.target.current(0)
        ui._notify_session()
        self.assertEqual(ui.start_button.cget('state'), 'normal')

    def test_tools_follow_output_confirmation_and_preserve_user_collapse(self):
        self.running()
        ui = self.ui
        before = deepcopy(ui.collect())
        ui._render_confirmed = False
        ui._notify_session()
        self.assertTrue(ui.tools_section.collapsed)
        ui._render_confirmed = True
        ui._notify_session()
        self.assertFalse(ui.tools_section.collapsed)
        self.assertTrue(all(b.cget('state') == 'normal' for b in ui.presentation_buttons.values()))
        ui.tools_section.toggle()
        ui._notify_session()
        self.assertTrue(ui.tools_section.collapsed)
        ui._stop_requested = True
        ui._notify_session()
        self.assertTrue(all(b.cget('state') == 'disabled' for b in ui.presentation_buttons.values()))
        self.assertEqual(ui.stop_button.cget('state'), 'normal')
        self.assertEqual(ui.collect(), before)
        self.client.send.assert_not_called()

    def test_runtime_details_need_current_run_data(self):
        self.running()
        ui = self.ui
        ui._notify_session()
        self.assertFalse(ui.runtime_info.winfo_manager())
        ui._metrics_compact = 'Fixture metrics'
        ui._metrics_run_id = ui._run_id
        ui._sync_footer()
        self.assertEqual(ui.runtime_info.winfo_manager(), 'pack')
        ui._run_id += 1
        ui._sync_footer()
        self.assertFalse(ui.runtime_info.winfo_manager())
        ui._active = ui._render_confirmed = False
        ui._native_state = 0
        ui._notify_session()
        self.assertFalse(ui.runtime_info.winfo_manager())

    def test_manual_check_is_advanced_but_issues_stay_on_session_rail(self):
        ui = self.ui
        ui._focus_page('runtime', ui.check_button)
        self.root.update()
        self.assertIs(ui.tabs._current, ui._pages['runtime'].master.master)
        self.assertTrue(ui.check_button.winfo_ismapped())
        ui.check_button.invoke()
        self.root.update()
        self.assertTrue(ui.preflight_panel.winfo_ismapped())
        self.client.start.assert_not_called()

    def test_shortcut_notice_is_compact_but_details_and_stop_fault_survive(self):
        ui = self.ui
        self.event(dict(event='ready', hotkeys=dict(stop=False, parameters=False, compare=False)))
        self.assertEqual(ui.shortcut_notice.winfo_manager(), 'pack')
        self.assertEqual(ui.stop_hint_label.winfo_manager(), 'pack')
        self.assertFalse(ui.status_label.winfo_manager())
        self.assertIn(i18n.tr('realtime.overlay_parameters'), ui._shortcut_details)
        with mock.patch.object(ui, '_open_shortcuts') as show:
            ui.shortcut_details_button.invoke()
        show.assert_called_once()
        self.assertTrue(ui.log.tag_ranges('warning'))
        self.event(dict(event='ready', hotkeys=dict(stop=True, parameters=True, compare=True)))
        self.assertFalse(ui.shortcut_notice.winfo_manager())
        self.assertFalse(ui.stop_hint_label.winfo_manager())
        self.assertIn(i18n.tr('realtime.control.unavailable'), ui.log.get('1.0', 'end'))

    def test_error_log_is_tagged_and_remains_visible_with_closed_logs(self):
        self.event(dict(event='error', message='Fixture engine error'))
        self.assertTrue(self.ui.log.tag_ranges('error'))
        self.assertEqual(self.ui.status_label.winfo_manager(), 'pack')
        for name in ('light', 'dark'):
            self.ui.apply_theme(ui_theme.tokens(name))
            self.assertEqual(self.ui.log.tag_cget('error', 'foreground'), ui_theme.tokens(name)['danger'])

    def test_thin_divider_retains_drag_area_and_saved_width(self):
        ui = self.ui
        ui._set_inspector_width(510)
        before = ui._inspector_user_width
        for name in ('light', 'dark'):
            ui.apply_theme(ui_theme.tokens(name))
            self.root.update()
            ui._paint_splitter(False)
            self.assertGreaterEqual(ui.splitter.winfo_width(), 6)
            self.assertEqual(float(ui.splitter.itemcget('divider', 'width')), 1)
            ui._paint_splitter(True)
            self.assertEqual(float(ui.splitter.itemcget('divider', 'width')), 2)
            self.assertEqual(ui._inspector_user_width, before)

    def test_common_group_remembers_explicit_collapse_after_rebuild(self):
        self.catalog()
        ui = self.ui
        self.assertFalse(ui.parameter_sections['look'].collapsed)
        ui.parameter_sections['look'].toggle()
        ui._select_effect()
        self.assertTrue(ui.parameter_sections['look'].collapsed)
