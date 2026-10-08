"""The compact realtime controller keeps existing editing and safety semantics."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest import mock

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime_readiness import StartIssue
from tests import test_realtime_inspector as inspector


class RealtimeLayoutTests(unittest.TestCase):
    setUp = inspector.RealtimeInspectorTests.setUp
    tearDown = inspector.RealtimeInspectorTests.tearDown
    catalog = inspector.RealtimeInspectorTests.catalog
    running = inspector.RealtimeInspectorTests.running
    event = inspector.RealtimeInspectorTests.event

    def test_three_pages_and_common_parameters_first(self):
        self.catalog()
        ui = self.ui
        self.assertEqual([tab['text'] for tab in ui.tabs._tabs],
                         [i18n.tr('realtime.tab.effects'), i18n.tr('realtime.layout.output'), i18n.tr('realtime.layout.advanced')])
        self.assertIs(ui.tabs._current, ui._pages['effects'].master.master)
        children = ui._pages['effects'].pack_slaves()
        self.assertLess(children.index(ui.parameter_frame), children.index(ui.workflow_section))
        for section in (ui.presets_section, ui.protection_section, ui.residual_section,
                        ui.workflow_section, ui.fluency_section, ui.metrics_section):
            self.assertTrue(section.collapsed)
        self.assertFalse(ui.region_preview.winfo_ismapped())
        self.assertFalse(ui.log.frame.winfo_manager())
        self.assertIs(ui.parameter_rows['intensity'].master, ui.parameter_sections['look'].body)
        self.client.start.assert_not_called()

    def test_locate_reveals_moved_controls_and_all_collapsed_ancestors(self):
        self.catalog()
        ui = self.ui
        for route, widget, page in (
                ('effects', ui.chain, 'effects'),
                ('protection', ui.region_preview, 'effects'),
                ('protection', ui.residual_section, 'effects'),
                ('display', ui.controls['capture_method'][0], 'runtime'),
                ('runtime', ui.runtime_button, 'runtime')):
            with self.subTest(widget=str(widget)):
                ui._focus_page(route, widget)
                self.root.update()
                self.assertIs(ui.tabs._current, ui._pages[page].master.master)
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreater(widget.winfo_width(), 20)
        self.client.start.assert_not_called()

    def test_startup_settings_move_left_but_protection_stays_in_adjustments(self):
        self.catalog()
        ui = self.ui
        def belongs_to(widget, parent):
            while widget is not None:
                if widget is parent:
                    return True
                widget = getattr(widget, 'master', None)
            return False
        for widget in (ui.target, ui.recipe_choice, ui.chain_undo_button, ui.presets_section,
                       ui.output_selector, ui.output_details_button):
            self.assertTrue(belongs_to(widget, ui.stage_content))
            self.assertFalse(belongs_to(widget, ui.inspector))
        self.assertTrue(belongs_to(ui.protection_section, ui._pages['effects']))
        self.assertTrue(ui.protection_section.collapsed)
        self.assertNotIn(ui.recipe_frame, ui._pages['effects'].pack_slaves())
        self.assertLess(ui.recipe_frame.winfo_y(), ui.output_row.winfo_y())

    def test_left_navigation_preserves_right_tab_and_exposes_presets(self):
        self.catalog()
        ui = self.ui
        ui._focus_page('runtime')
        selected_tab = ui.tabs._current
        ui._focus_page('startup', ui.preset_choice)
        self.root.update()
        self.assertIs(ui.tabs._current, selected_tab)
        self.assertFalse(ui.presets_section.collapsed)
        self.assertGreaterEqual(ui.preset_choice.winfo_rooty(), ui.stage_canvas.winfo_rooty())
        self.assertLessEqual(ui.preset_choice.winfo_rooty()+ui.preset_choice.winfo_height(),
                             ui.stage_canvas.winfo_rooty()+ui.stage_canvas.winfo_height())
        ui._focus_page('display', ui.output_selector)
        self.root.update()
        self.assertIs(ui.tabs._current, selected_tab)
        self.assertLessEqual(ui.output_selector.winfo_rooty()+ui.output_selector.winfo_height(),
                             ui.stage_canvas.winfo_rooty()+ui.stage_canvas.winfo_height())

    def test_more_output_settings_is_navigation_only_and_summary_follows_draft(self):
        self.running()
        ui = self.ui
        before = deepcopy(ui._running_config)
        ui.parameters['intensity'][1].set('.7')
        row = ui.parameter_rows['intensity']
        ui.output_mode.set(not before['windowed'])
        ui._output_changed()
        self.assertEqual(ui._editor_state, 'restart')
        self.assertEqual(ui._running_config, before)
        mode = i18n.tr('realtime.output.windowed' if ui.output_mode.get() else 'realtime.output.fullscreen')
        self.assertEqual(ui.output_summary.get(), i18n.tr('realtime.layout.output_draft', mode=mode))
        ui.output_details_button.invoke()
        self.assertIs(ui.tabs._current, ui._pages['display'].master.master)
        self.assertIs(ui.parameter_rows['intensity'], row)
        self.assertEqual(row.value(), .7)
        self.client.start.assert_not_called()
        self.client.send.assert_not_called()

    def test_expanded_left_presets_scroll_without_hiding_stop_or_errors(self):
        self.running()
        ui = self.ui
        ui.presets_section.toggle()
        ui.metrics_section.toggle()
        ui.status.set('Fixture error')
        for theme in ('light', 'dark'):
            ui_theme.apply_ttk(self.root, ui_theme.tokens(theme))
            ui.apply_theme(ui_theme.tokens(theme))
            for size in ('800x600', '1000x680', '1280x800'):
                self.root.geometry(size)
                self.root.update()
                ui.stage_canvas.yview_moveto(1)
                self.root.update()
                for widget in (ui.stop_button, ui.start_button, ui.session_label, ui.status_label, ui.stop_hint_label):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreaterEqual(widget.winfo_rooty(), self.root.winfo_rooty())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                         self.root.winfo_rooty()+self.root.winfo_height())
                self.assertEqual(ui.stage_canvas.cget('bg'), ui_theme.tokens(theme)['canvas'])

    def test_fitting_content_hides_scrollbars_and_stays_at_top(self):
        self.catalog()
        ui = self.ui
        self.root.geometry('1600x1300')
        self.root.update()
        for theme in ('light', 'dark'):
            ui_theme.apply_ttk(self.root, ui_theme.tokens(theme))
            ui.apply_theme(ui_theme.tokens(theme))
            for route in ('effects', 'display', 'runtime'):
                ui._focus_page(route)
                self.root.update()
                for content in (ui.stage_content, ui._pages[route]):
                    canvas = content.master
                    bar = ui._scroll_bars[canvas.master]
                    self.assertLessEqual(content.winfo_reqheight(), canvas.winfo_height())
                    self.assertFalse(bar.winfo_ismapped())
                    canvas.yview_moveto(1)
                    canvas.yview_scroll(10, 'units')
                    self.root.update()
                    self.assertEqual(canvas.yview(), (0.0, 1.0))
                    self.assertEqual(content.winfo_rooty(), canvas.winfo_rooty())

    def test_overflow_scrolls_then_resets_after_resize_and_collapse(self):
        ui = self.ui
        self.root.geometry('1000x680')
        ui.presets_section.toggle()
        ui.metrics_section.toggle()
        self.root.update()
        self.assertTrue(ui._scroll_bars[ui.stage_scroll].winfo_ismapped())
        stop_y = ui.stop_button.winfo_rooty()
        before = ui.stage_canvas.yview()
        self.assertEqual(ui.on_mousewheel(SimpleNamespace(widget=ui.recipe_choice, delta=-120)), 'break')
        self.root.update()
        self.assertGreater(ui.stage_canvas.yview()[0], before[0])
        self.assertEqual(stop_y, ui.stop_button.winfo_rooty())
        ui.stage_canvas.yview_moveto(1)
        ui.presets_section.toggle()
        ui.metrics_section.toggle()
        self.root.geometry('1600x1300')
        self.root.update()
        self.assertFalse(ui._scroll_bars[ui.stage_scroll].winfo_ismapped())
        self.assertEqual(ui.stage_canvas.yview(), (0.0, 1.0))
        self.assertEqual(ui.stage_content.winfo_rooty(), ui.stage_canvas.winfo_rooty())

    def test_splitter_drag_uses_pointer_delta_without_sending_or_rebuilding(self):
        self.catalog()
        ui = self.ui
        row = ui.parameter_rows['intensity']
        row.number_text.set('unfinished')
        self.client.send.reset_mock()
        before = ui.inspector.winfo_width()
        ui.splitter.event_generate('<ButtonPress-1>', x=2, y=10, rootx=600, rooty=100)
        with mock.patch.object(ui, '_set_inspector_width', wraps=ui._set_inspector_width) as set_width:
            for x in (580, 560, 540):
                ui.splitter.event_generate('<B1-Motion>', x=2, y=10, rootx=x, rooty=100)
                self.root.update_idletasks()
                self.assertEqual(ui.inspector.winfo_width(), before)
                self.assertEqual(ui._splitter_preview.winfo_x(), ui.window.winfo_width()-(before+600-x))
            set_width.assert_not_called()
        self.assertTrue(ui._splitter_preview.winfo_ismapped())
        ui.splitter.event_generate('<ButtonRelease-1>', x=2, y=10, rootx=540, rooty=100)
        self.root.update()
        self.assertEqual(ui.inspector.winfo_width(), before + 60)
        self.assertIsNone(ui._splitter_drag)
        self.assertFalse(ui._splitter_preview.winfo_ismapped())
        self.assertIs(ui.parameter_rows['intensity'], row)
        self.assertEqual(row.number_text.get(), 'unfinished')
        self.assertEqual(ui.splitter.cget('cursor'), 'sb_h_double_arrow')
        self.client.start.assert_not_called()
        self.client.send.assert_not_called()

    def test_splitter_release_uses_latest_pointer_and_commits_once(self):
        ui = self.ui
        before = ui.inspector.winfo_width()
        ui._splitter_start(SimpleNamespace(x_root=600))
        ui._splitter_move(SimpleNamespace(x_root=580))
        with mock.patch.object(ui, '_set_inspector_width', wraps=ui._set_inspector_width) as set_width:
            ui._splitter_end(SimpleNamespace(x_root=530))
            ui._splitter_end(SimpleNamespace(x_root=500))
            set_width.assert_called_once_with(before + 70)
        self.root.update_idletasks()
        self.assertEqual(ui.inspector.winfo_width(), before + 70)
        # Press/release without moving does not turn auto layout into a manual width.
        ui._splitter_reset()
        ui._splitter_start(SimpleNamespace(x_root=600))
        ui._splitter_end(SimpleNamespace(x_root=600))
        self.assertIsNone(ui._inspector_user_width)

    def test_splitter_preview_clamps_and_cancels_without_commit(self):
        ui = self.ui
        before = ui.inspector.winfo_width()
        self.assertTrue(ui.splitter.bind('<Escape>'))
        for x in (-10000, 10000):
            ui._splitter_start(SimpleNamespace(x_root=600))
            ui._splitter_move(SimpleNamespace(x_root=x))
            self.root.update_idletasks()
            self.assertEqual(ui._splitter_pending_width, ui._clamp_inspector_width(before+600-x))
            self.assertGreaterEqual(ui._splitter_preview.winfo_x(), 320)
            self.assertEqual(ui.inspector.winfo_width(), before)
            self.assertEqual(ui._splitter_cancel(), 'break')
            ui._splitter_end(SimpleNamespace(x_root=x))
            self.assertEqual(ui.inspector.winfo_width(), before)
            self.assertFalse(ui._splitter_preview.winfo_manager())
            self.assertIsNone(ui._inspector_user_width)

    def test_splitter_hidden_or_closed_cleans_preview_without_applying(self):
        ui = self.ui
        before = ui.inspector.winfo_width()
        ui._splitter_start(SimpleNamespace(x_root=600))
        ui._splitter_move(SimpleNamespace(x_root=540))
        self.root.update_idletasks()
        ui.window.pack_forget()
        self.root.update()
        self.assertIsNone(ui._splitter_drag)
        self.assertFalse(ui._splitter_preview.winfo_manager())
        ui.window.pack(fill='both', expand=True)
        self.root.update()
        self.assertEqual(ui.inspector.winfo_width(), before)
        ui._splitter_start(SimpleNamespace(x_root=600))
        ui._splitter_move(SimpleNamespace(x_root=540))
        preview = ui._splitter_preview
        ui.close()
        self.assertFalse(preview.winfo_exists())
        self.assertIsNone(ui._inspector_user_width)

    def test_splitter_limits_preserve_panes_and_restore_user_width_after_resize(self):
        ui = self.ui
        ui._set_inspector_width(10000)
        self.root.update()
        self.assertGreaterEqual(ui.stage.winfo_width(), 320)
        ui._set_inspector_width(1)
        self.root.update()
        self.assertGreaterEqual(ui.inspector.winfo_width(), 360)
        ui._set_inspector_width(620)
        self.root.update()
        self.root.geometry('800x600')
        self.root.update()
        self.assertGreaterEqual(ui.stage.winfo_width(), 320)
        self.assertLessEqual(ui.stop_button.winfo_rootx()+ui.stop_button.winfo_width(),
                             ui.stage.winfo_rootx()+ui.stage.winfo_width())
        self.root.geometry('1280x800')
        self.root.update()
        self.assertEqual(ui.inspector.winfo_width(), 620)
        ui.window.pack_forget()
        ui.window.pack(fill='both', expand=True)
        self.root.update()
        self.assertEqual(ui.inspector.winfo_width(), 620)

    def test_splitter_keyboard_reset_and_theme(self):
        ui = self.ui
        before = ui.inspector.winfo_width()
        self.assertEqual(ui._splitter_nudge(16), 'break')
        self.root.update()
        self.assertEqual(ui.inspector.winfo_width(), before + 16)
        self.assertEqual(ui._splitter_nudge(-16), 'break')
        self.root.update()
        self.assertEqual(ui.inspector.winfo_width(), before)
        for binding in ('<Left>', '<Right>', '<Home>', '<Double-Button-1>'):
            self.assertTrue(ui.splitter.bind(binding))
        ui._splitter_reset()
        self.root.update()
        self.assertIsNone(ui._inspector_user_width)
        self.assertEqual(ui.inspector.winfo_width(), before)
        for theme in ('light', 'dark'):
            ui.apply_theme(ui_theme.tokens(theme))
            self.assertEqual(ui._splitter_preview.cget('bg'), ui_theme.tokens(theme)['accent'])
            ui._paint_splitter(True)
            self.assertEqual(ui.splitter.cget('bg'), ui_theme.tokens(theme)['accent'])
            ui._paint_splitter(False)
            self.assertEqual(ui.splitter.cget('bg'), ui_theme.tokens(theme)['line'])

    def test_switching_tabs_and_sections_does_not_send_or_discard_drafts(self):
        self.catalog()
        ui = self.ui
        row = ui.parameter_rows['intensity']
        row.number_text.set('unfinished')
        widgets = dict(ui.parameter_rows)
        self.client.send.reset_mock()
        for tab in ui.tabs._tabs:
            ui.tabs.select(tab['frame'])
        ui._focus_page('effects', ui.chain)
        ui.workflow_section.toggle()
        self.assertEqual(ui.parameter_rows, widgets)
        self.assertEqual(row.number_text.get(), 'unfinished')
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()

    def select_running_and_pending_targets(self):
        self.running()
        ui = self.ui
        original = dict(hwnd=10, pid=20, title='Running A', application='a.exe')
        pending = dict(hwnd=11, pid=21, title='Pending B', application='b.exe')
        ui.windows = [original, pending]
        ui.target.configure(values=['Running A', 'Pending B'])
        ui.target.current(0)
        ui._session_target = deepcopy(original)
        ui._notify_session()
        self.client.send.reset_mock()
        return original, pending

    def test_target_change_needs_explicit_apply_and_does_not_retarget_live_edits(self):
        original, pending = self.select_running_and_pending_targets()
        ui = self.ui
        ui.target.current(1)
        ui._target_changed()
        self.assertEqual(ui._session_target, original)
        self.assertIn('Running A', ui.session_text.get())
        self.assertNotIn('Pending B', ui.session_text.get())
        self.assertEqual(ui.target_hint.get(), i18n.tr('realtime.layout.target_pending'))
        self.assertEqual(ui._editor_state, 'restart')
        self.assertEqual(ui.apply_button.cget('text'), i18n.tr('realtime.layout.switch_target'))
        self.assertEqual(ui.start_button.cget('state'), 'disabled')
        self.assertEqual(ui.stop_button.cget('state'), 'normal')
        ui.parameters['intensity'][1].set('.7')
        ui._parameter_committed()
        ui.quality_controls['total'].set('.6')
        ui.apply_quality()
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()
        with mock.patch.object(ui, 'start') as start:
            ui.apply_button.invoke()
            start.assert_called_once()

    def test_reselect_running_target_removes_switch_action_without_restart(self):
        self.select_running_and_pending_targets()
        self.ui.target.current(1)
        self.ui._target_changed()
        self.ui.target.current(0)
        self.ui._target_changed()
        self.assertEqual(self.ui._editor_state, 'clean')
        self.assertFalse(self.ui.apply_button.winfo_manager())
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()

    def test_pending_quality_ack_does_not_allow_new_target_parameters_into_old_session(self):
        self.select_running_and_pending_targets()
        ui = self.ui
        ui.quality_controls['total'].set('.8')
        ui.apply_quality()
        pending_quality = deepcopy(ui._pending_quality)
        self.assertIsNotNone(pending_quality)
        self.client.send.reset_mock()
        ui.target.current(1)
        ui._target_changed()
        self.assertEqual(ui._editor_state, 'applying')
        ui.parameters['intensity'][1].set('.7')
        ui._parameter_committed()
        self.client.send.assert_not_called()
        self.assertEqual(ui._pending_quality, pending_quality)
        self.assertEqual(ui.collect()['effects'][0]['parameters']['intensity'], .7)
        self.client.start.assert_not_called()

    def test_unavailable_output_actions_disabled_until_confirmed(self):
        ui = self.ui
        ui._notify_session()
        self.assertTrue(all(button.cget('state') == 'disabled' for button in ui.presentation_buttons.values()))
        self.running()
        ui._notify_session()
        self.assertTrue(all(button.cget('state') == 'normal' for button in ui.presentation_buttons.values()))
        ui.command('stop')
        self.assertTrue(all(button.cget('state') == 'disabled' for button in ui.presentation_buttons.values()))

    def test_footer_controls_fit_small_window_in_both_themes(self):
        self.running()
        self.ui.controls['frame_rate'][0].set('90')
        for theme in ('light', 'dark'):
            ui_theme.apply_ttk(self.root, ui_theme.tokens(theme))
            self.ui.apply_theme(ui_theme.tokens(theme))
            for size in ('800x600', '1000x680', '1280x800'):
                with self.subTest(theme=theme, size=size):
                    self.root.geometry(size)
                    self.root.update()
                    for widget in (self.ui.start_button, self.ui.stop_button, self.ui.apply_button, self.ui.target):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertGreater(widget.winfo_width(), 20)
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())

    def test_standalone_logs_can_be_opened_and_hidden(self):
        self.ui._toggle_log()
        self.assertEqual(self.ui.log.frame.winfo_manager(), 'pack')
        self.ui._toggle_log()
        self.assertEqual(self.ui.log.frame.winfo_manager(), '')

    def test_errors_remain_visible_when_logs_are_collapsed(self):
        self.ui.status.set('Capture failed: fixture error')
        self.assertEqual(self.ui.status_label.winfo_manager(), 'pack')
        self.assertFalse(self.ui.log.frame.winfo_manager())
        self.ui.status.set(i18n.tr('realtime.running'))
        self.assertFalse(self.ui.status_label.winfo_manager())

    def test_invalid_hidden_parameter_is_revealed_without_losing_input(self):
        self.catalog()
        row = self.ui.parameter_rows['residualSaturation']
        row.number_text.set('unfinished')
        self.ui._preflight_issues = [StartIssue('invalid', 'effects', 'invalid parameter')]
        self.ui.preflight_choice.configure(values=['invalid parameter'])
        self.ui.preflight_choice.current(0)
        self.ui._locate_preflight()
        self.root.update()
        self.assertTrue(row.field.winfo_ismapped())
        self.assertEqual(row.number_text.get(), 'unfinished')
        self.client.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
