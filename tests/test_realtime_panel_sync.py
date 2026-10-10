"""Overlay/editor synchronization and compact UI; never launch a capture host."""
from copy import deepcopy
import time
import unittest
from unittest import mock

from dlss5tool import i18n
from dlss5tool.realtime import NR, merge_overlay_effects
from tests import test_realtime_inspector as inspector_tests


class RealtimePanelSyncTests(unittest.TestCase):
    setUp = inspector_tests.RealtimeInspectorTests.setUp
    tearDown = inspector_tests.RealtimeInspectorTests.tearDown
    catalog = inspector_tests.RealtimeInspectorTests.catalog
    running = inspector_tests.RealtimeInspectorTests.running
    event = inspector_tests.RealtimeInspectorTests.event
    status = inspector_tests.RealtimeInspectorTests.status

    def request(self, before=None, *, token=88, changes=None, **sync):
        before = deepcopy(before if before is not None else self.ui._applied_effects)
        after = deepcopy(before)
        after[0].setdefault('parameters', {}).update(changes or {'intensity': .6})
        return dict(event='settings_requested', token=token, run_id=12, previous_effects=before,
                    effects=after, sync_enabled=sync.get('sync_enabled', True),
                    frame_rate=sync.get('frame_rate', 60), sync_mode=sync.get('sync_mode', 0))

    def test_overlay_updates_in_place_without_manual_apply_or_premature_confirmation(self):
        self.running()
        row = self.ui.parameter_rows['intensity']
        cards = list(self.ui.chain._cards)
        before = deepcopy(self.ui._running_config)
        with mock.patch.object(self.ui, 'apply_config', wraps=self.ui.apply_config) as rebuild:
            self.event(self.request())
            rebuild.assert_not_called()
        self.assertIs(self.ui.parameter_rows['intensity'], row)
        self.assertEqual(self.ui.chain._cards, cards)
        self.assertEqual(row.value(), .6)
        self.assertEqual(self.ui._running_config, before)
        self.assertEqual(self.ui._editor_state, 'applying')
        self.assertEqual(row.feedback.cget('text'), i18n.tr('realtime.editor.syncing'))
        self.assertFalse(self.ui.apply_button.winfo_manager())
        self.client.send.assert_any_call('save_result', token=88, ok=True, conflict=False)
        self.client.send.assert_any_call('status')
        self.assertFalse(any(c.args == ('set_parameter',) for c in self.client.send.call_args_list))
        self.status(deepcopy(before['effects']))
        self.assertEqual(self.ui._editor_state, 'applying')
        self.status(self.ui.collect()['effects'])
        self.assertEqual(self.ui._editor_state, 'clean')
        self.assertFalse(row.unapplied)

    def test_consecutive_drag_saves_are_persisted_once_and_all_receipted(self):
        self.running()
        first = self.request(token=1, changes={'intensity': .8})
        second = self.request(first['effects'], token=2, changes={'intensity': .5})
        if self.ui._after:
            self.ui.window.after_cancel(self.ui._after)
        self.client.events.put(dict(first, _generation=1))
        self.client.events.put(dict(second, _generation=1))
        with mock.patch.object(self.store, 'save_session', wraps=self.store.save_session) as save:
            self.ui._poll()
            save.assert_called_once()
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), .5)
        self.assertEqual(self.ui._overlay_expected, {(0, 'intensity'): .5})
        for token in (1, 2):
            self.client.send.assert_any_call('save_result', token=token, ok=True, conflict=False)

    def test_write_failure_does_not_mutate_widgets_or_ack_success(self):
        self.running()
        before = deepcopy(self.ui.config)
        with mock.patch.object(self.store, 'save_session', side_effect=OSError('disk unavailable')):
            self.event(self.request())
        self.assertEqual(self.ui.config, before)
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), 1)
        self.client.send.assert_any_call('save_result', token=88, ok=False, conflict=False)
        self.assertFalse(self.ui._overlay_expected)

    def test_unfinished_unrelated_inputs_and_local_undo_survive(self):
        self.running()
        style = self.ui.parameter_rows['style']
        style.variable.set('2')
        self.ui._parameter_committed()
        self.status(self.ui.collect()['effects'])
        self.ui.parameter_rows['residualSaturation'].number_text.set('unfinished')
        self.ui.quality_controls['total'].set('unfinished')
        self.ui._chain_undo = {'kept': True}
        self.event(self.request())
        self.assertEqual(self.ui.parameter_rows['residualSaturation'].number_text.get(), 'unfinished')
        self.assertEqual(self.ui.quality_controls['total'].get(), 'unfinished')
        self.assertEqual(self.ui._chain_undo, {'kept': True})
        self.assertIsNotNone(self.ui._undo_parameters)
        self.assertEqual(self.ui._undo_parameters['parameters']['intensity'], '0.6')
        self.assertEqual(self.ui._undo_parameters['parameters']['style'], '0')
        self.assertEqual(self.ui._editor_state, 'invalid')
        self.client.send.assert_any_call('save_result', token=88, ok=True, conflict=False)

    def test_same_field_conflict_preserves_local_draft(self):
        self.running()
        self.ui.parameter_rows['intensity'].number_text.set('unfinished')
        self.event(self.request())
        self.client.send.assert_any_call('save_result', token=88, ok=False, conflict=True)
        self.assertEqual(self.ui.parameter_rows['intensity'].number_text.get(), 'unfinished')

    def test_selected_second_effect_scroll_and_widget_identity_survive(self):
        self.running()
        config = self.ui.collect()
        config['effects'].append(dict(name='ThirdParty\\Color', parameters={'amount': 1}))
        self.ui.apply_config(config)
        self.ui._running_config = self.ui.collect()
        self.ui._applied_effects = deepcopy(config['effects'])
        self.ui.chain.selection_set(1)
        self.ui._select_effect()
        row = self.ui.parameter_rows['amount']
        self.root.update_idletasks()
        canvas = self.ui._pages['effects'].master
        canvas.yview_moveto(.4)
        self.root.update_idletasks()
        scroll = canvas.yview()
        self.event(self.request())
        self.root.update_idletasks()
        self.assertEqual(self.ui.chain.curselection(), (1,))
        self.assertIs(self.ui.parameter_rows['amount'], row)
        self.assertEqual(canvas.yview(), scroll)

    def test_restart_only_edit_is_not_reported_applied_until_new_output(self):
        self.running()
        self.ui._parameter_modes[(0, 'style')] = 2
        self.ui._session_target = {'hwnd': 42, 'title': 'test source'}
        request = self.request(changes={'style': 2}, frame_rate=90, sync_mode=1)
        self.event(request)
        self.assertEqual(self.ui.controls['frame_rate'][0].get(), '90')
        self.assertEqual(self.ui.controls['sync_mode'][0].current(), 1)
        self.assertEqual(self.ui._running_config['frame_rate'], 60)
        self.assertEqual(self.ui._editor_state, 'restart')
        self.assertEqual(self.ui.apply_button.cget('text'), i18n.tr('realtime.editor.restart_action'))
        self.client.start.assert_not_called()
        self.event(dict(event='state', state=1, run_id=13))
        self.event(dict(event='state', state=2, run_id=13))
        self.assertEqual(self.ui._editor_state, 'waiting')
        self.event(dict(event='status', state=2, run_id=13, effects=request['effects'], metrics={'submitted': 1},
                        parameter_modes=[dict(effect=0, name='style', mode=2)]))
        self.assertEqual(self.ui._running_config['frame_rate'], 90)
        self.assertEqual(self.ui._editor_state, 'clean')

    def test_frame_sync_conflict_does_not_overwrite_local_edit(self):
        self.running()
        self.ui.controls['frame_rate'][0].set('75')
        self.event(self.request(frame_rate=90))
        self.assertEqual(self.ui.controls['frame_rate'][0].get(), '75')
        self.client.send.assert_any_call('save_result', token=88, ok=False, conflict=True)

    def test_external_value_reenables_disabled_slider_and_its_needed_range(self):
        self.running()
        self.ui.parameter_toggles['intensity'].set(False)
        before = deepcopy(self.ui._applied_effects)
        before[0]['parameters']['intensity'] = 0
        self.ui._applied_effects = deepcopy(before)
        self.ui._running_config['effects'] = deepcopy(before)
        self.ui.extended_range.set(False)
        self.ui._update_range_controls()
        self.event(self.request(before, changes={'intensity': 1.3}))
        self.assertTrue(self.ui.parameter_toggles['intensity'].get())
        self.assertTrue(self.ui.extended_range.get())
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), 1.3)
        self.assertEqual(self.ui._editor_state, 'applying')

    def test_timeout_is_retryable_and_stop_discards_pending_confirmation(self):
        self.running()
        self.event(self.request())
        self.ui._overlay_sent_at = time.monotonic() - 6
        self.event(dict(event='log', message='tick'))
        self.assertEqual(self.ui._editor_state, 'failed')
        self.ui.apply_button.invoke()
        self.assertEqual(self.ui._editor_state, 'applying')
        self.ui.command('stop')
        self.assertFalse(self.ui._overlay_expected)
        self.assertFalse(self.ui._live_expected)

    def test_late_old_session_receipt_cannot_confirm_current_overlay(self):
        self.running()
        request = self.request()
        self.event(request)
        self.event(dict(event='status', run_id=11, state=2, effects=request['effects'], metrics={}))
        self.assertTrue(self.ui._overlay_expected)
        self.assertEqual(self.ui._editor_state, 'applying')

    def test_help_hover_only_never_expands_or_shifts_parameters(self):
        self.catalog()
        help_widget = self.ui.recipe_help_widget
        self.root.update()
        self.assertFalse(hasattr(help_widget, 'button'))
        self.assertFalse(hasattr(help_widget, 'details'))
        self.assertFalse(hasattr(help_widget, 'indicator'))
        self.assertIn(i18n.tr('realtime.workflow.recipe_hint'), help_widget.tooltip.text)
        before = (help_widget.winfo_height(), self.ui.parameter_frame.winfo_rooty())
        self.client.send.reset_mock()
        help_widget.label.event_generate('<Enter>')
        self.root.update_idletasks()
        self.assertIsNotNone(help_widget.tooltip.tip)
        help_widget.label.event_generate('<ButtonPress-1>')
        help_widget.label.event_generate('<ButtonRelease-1>')
        self.root.update_idletasks()
        self.assertEqual((help_widget.winfo_height(), self.ui.parameter_frame.winfo_rooty()), before)
        self.assertIsNone(help_widget.tooltip.tip)
        self.client.send.assert_not_called()
        self.assertFalse(self.ui.chain_summary_help.winfo_manager())
        self.assertTrue(self.ui.metrics_section.collapsed)

    def test_idle_and_clean_hide_apply_but_restart_action_fits_small_window(self):
        self.catalog()
        self.assertFalse(self.ui.apply_button.winfo_manager())
        self.running()
        self.assertFalse(self.ui.apply_button.winfo_manager())
        self.ui.controls['frame_rate'][0].set('90')
        self.ui._editor_changed()
        self.root.geometry('800x600')
        self.root.update()
        self.assertTrue(self.ui.apply_button.winfo_ismapped())
        self.assertLessEqual(self.ui.apply_button.winfo_rooty() + self.ui.apply_button.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())

    def test_stopped_metrics_are_explicitly_historical(self):
        self.running()
        self.ui._metrics_compact = '6.0 frames/s'
        self.ui._refresh_metrics_summary()
        self.assertEqual(self.ui.metrics_summary.get(), '6.0 frames/s')
        self.event(dict(event='state', state=0, run_id=12))
        self.assertEqual(self.ui.metrics_summary.get(), i18n.tr('realtime.metrics_previous', value='6.0 frames/s'))

    def test_sparse_native_defaults_do_not_produce_false_conflicts(self):
        config = dict(effects=[dict(name='Test', parameters={'value': 1})])
        before = [dict(name='Test', parameters={})]
        after = [dict(name='Test', parameters={'value': .7})]
        result = merge_overlay_effects(config, before, after, {'Test': {'value': 1}})
        self.assertEqual(result['effects'][0]['parameters']['value'], .7)

    def test_confirming_quality_does_not_erase_saved_restart_edits(self):
        self.running()
        self.ui._parameter_modes[(0, 'style')] = 2
        self.event(self.request(changes={'style': 2}, frame_rate=90))
        self.ui._running_config['quality']['total'] = .6
        self.ui._save_running_session()
        saved = self.store.data['session']
        self.assertEqual(saved['effects'][0]['parameters']['style'], 2)
        self.assertEqual(saved['frame_rate'], 90)
        self.assertEqual(saved['quality']['total'], .6)
        self.assertEqual(self.ui._running_config['effects'][0]['parameters']['style'], 0)
        self.assertEqual(self.ui._running_config['frame_rate'], 60)

    def test_overlay_save_preserves_newly_confirmed_quality(self):
        self.running()
        first = self.request()
        self.event(first)
        self.status(first['effects'])
        self.ui._running_config['quality']['total'] = .6
        self.event(self.request(first['effects'], token=89, changes={'intensity': .7}))
        self.assertEqual(self.store.data['session']['quality']['total'], .6)

    def test_local_commit_waits_for_overlay_then_sends_latest_value_once(self):
        self.running()
        first = self.request()
        self.event(first)
        self.client.send.reset_mock()
        self.ui.parameter_rows['intensity'].variable.set('.8')
        self.ui.parameter_rows['intensity'].commit()
        self.assertTrue(self.ui._queued_parameter_apply)
        self.client.send.assert_not_called()
        self.status(first['effects'])
        commands = [c for c in self.client.send.call_args_list if c.args == ('set_parameter',)]
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].kwargs['value'], .8)

    def test_apply_failure_leaves_draft_and_visible_retry(self):
        self.running()
        self.event(self.request())
        self.event(dict(event='status', state=2, run_id=12, effects=self.ui._applied_effects,
                        metrics={}, apply_failed=True,
                        parameter_modes=[dict(effect=0, name=n, mode=1) for n in ('intensity', 'style')]))
        self.assertFalse(self.ui._overlay_expected)
        self.assertEqual(self.ui._editor_state, 'failed')
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), .6)

    def test_stop_rejects_late_save_without_replacing_editor(self):
        self.running()
        self.ui.command('stop')
        self.event(self.request())
        self.client.send.assert_any_call('save_result', token=88, ok=False, conflict=False)
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), 1)

    def test_help_keyboard_focus_works_without_hover_and_escape_dismisses(self):
        self.catalog()
        help_widget = self.ui.recipe_help_widget
        self.root.update()
        help_widget.label.focus_force()
        self.root.update()
        self.assertIsNotNone(help_widget.tooltip.tip)
        help_widget.label.event_generate('<Escape>')
        self.root.update()
        self.assertIsNone(help_widget.tooltip.tip)
        self.ui.undo_button.focus_force()
        self.root.update()
        help_widget.label.focus_force()
        self.root.update()
        self.assertIsNotNone(help_widget.tooltip.tip)
        self.ui._focus_page('display')
        self.root.update()
        self.assertIsNone(help_widget.tooltip.tip)

    def test_help_updates_and_theme_changes_close_stale_tooltips(self):
        self.catalog()
        help_widget = self.ui.parameter_heading
        help_widget.tooltip._show()
        self.assertIsNotNone(help_widget.tooltip.tip)
        help_widget.set_details('Updated effect explanation')
        self.assertIsNone(help_widget.tooltip.tip)
        self.assertEqual(help_widget.tooltip.text, 'Updated effect explanation')
        help_widget.tooltip._show()
        help_widget.apply_theme(self.ui._ui)
        self.assertIsNone(help_widget.tooltip.tip)

    def test_undo_actions_use_distinct_return_arrow_icons(self):
        self.catalog()
        self.root.update()
        from dlss5tool import ui_icons
        self.assertNotEqual(ui_icons.LUCIDE['undo'], ui_icons.LUCIDE['retry'])
        for button in (self.ui.undo_button, self.ui.chain_undo_button):
            self.assertEqual(button.cget('icon'), 'undo')
            self.assertFalse(button._icon_only)
            self.assertIsNotNone(button._icon_image)
            self.assertTrue(any(button.type(item) == 'text' for item in button.find_all()))
        self.assertEqual(self.ui.undo_button.cget('text'), i18n.tr('realtime.polish.undo_parameters'))
        self.assertEqual(self.ui.chain_undo_button.cget('text'), i18n.tr('realtime.polish.undo_recipe'))

    def test_help_only_sections_use_existing_headers_without_empty_rows(self):
        self.catalog()
        from dlss5tool.realtime_controls import HoverHelp, InlineHelp
        for section in (self.ui.residual_section, self.ui.protection_section, self.ui.metrics_section):
            self.assertFalse(any(isinstance(child, InlineHelp) for child in section.body.winfo_children()))
            tips = [widget for widget in self.ui._theme_widgets
                    if isinstance(widget, HoverHelp) and widget.widget is section._header]
            self.assertEqual(len(tips), 1)
            self.assertTrue(tips[0].text)
        self.ui.residual_section._header.event_generate('<Enter>')
        tip = next(widget for widget in self.ui._theme_widgets
                   if isinstance(widget, HoverHelp) and widget.widget is self.ui.residual_section._header)
        self.assertIsNotNone(tip.tip)
        self.ui._focus_page('display')
        self.root.update()
        self.assertIsNone(tip.tip)

    def test_new_session_does_not_label_previous_samples_as_current(self):
        self.running()
        self.ui._metrics_compact = '60.0 frames/s'
        self.ui._metrics_run_id = 11
        self.ui._refresh_metrics_summary()
        self.assertEqual(self.ui.metrics_summary.get(), i18n.tr('realtime.metrics_previous', value='60.0 frames/s'))

    def test_recovery_does_not_keep_unconfirmed_overlay_as_rollback_baseline(self):
        self.running()
        original = deepcopy(self.ui._running_config)
        self.ui._known_good = ({'hwnd': 42}, deepcopy(original))
        self.ui._parameter_modes[(0, 'style')] = 2
        self.event(self.request(changes={'style': 2}, frame_rate=90))
        self.ui._recover('test failure')
        self.assertIsNone(self.ui._overlay_saved)
        self.assertEqual(self.ui._recovery_target[1], original)

    def test_fast_parameter_receipts_do_not_make_metrics_flicker(self):
        self.running()
        baseline = (12, 100, {'real': 60, 'submitted': 60})
        self.ui._last_metrics = baseline
        self.ui._metrics_compact = 'stable sample'
        event = dict(event='status', state=2, run_id=12, effects=self.ui._applied_effects,
                     metrics={'real': 66, 'submitted': 66}, parameter_modes=[])
        with mock.patch('dlss5tool.realtime_ui.time.monotonic', return_value=100.1):
            self.event(event)
        self.assertEqual(self.ui._last_metrics, baseline)
        self.assertEqual(self.ui._metrics_compact, 'stable sample')
        with mock.patch('dlss5tool.realtime_ui.time.monotonic', return_value=101.1):
            self.event(event)
        self.assertNotEqual(self.ui._metrics_compact, 'stable sample')

    def test_batch_reader_does_not_consume_emergency_event_after_recovery_barrier(self):
        self.running()
        self.client.events.put(dict(event='error', message='failure'))
        self.client.events.put(dict(event='emergency_stop'))
        batches = self.ui._event_batches()
        self.assertEqual(next(batches)[0]['event'], 'error')
        batches.close()
        self.assertEqual(self.client.events.get_nowait()['event'], 'emergency_stop')

    def test_batch_reader_never_merges_saves_across_state_events(self):
        self.running()
        first = self.request(token=1)
        barrier = dict(event='state', state=0, run_id=12)
        second = self.request(token=2)
        for event in (first, barrier, second):
            self.client.events.put(event)
        batches = self.ui._event_batches()
        self.assertEqual(next(batches), [first])
        batches.close()
        self.assertEqual(self.client.events.get_nowait(), barrier)
        self.assertEqual(self.client.events.get_nowait(), second)


if __name__ == '__main__':
    unittest.main()
