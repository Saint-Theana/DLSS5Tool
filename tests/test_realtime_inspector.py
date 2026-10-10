"""Scoped inspector regressions; no capture or native rendering required."""
from copy import deepcopy
from types import SimpleNamespace
import time
import tkinter as tk
import unittest
from unittest import mock

from tests import test_realtime_ui
from dlss5tool import i18n, ui_theme
from dlss5tool.realtime import NR
from dlss5tool.realtime_labels import inspector_groups


def parameter(name, *, label=None, default=1, minimum=0, maximum=2,
              step=.05, integer=False, choices=(), group='Detail Control'):
    return dict(name=name, label=label or name, default=default, min=minimum,
                max=maximum, step=step, integer=integer, choices=list(choices), group=group)


class RealtimeInspectorTests(unittest.TestCase):
    setUp = test_realtime_ui.RealtimeUiTests.setUp
    event = test_realtime_ui.RealtimeUiTests.event

    def tearDown(self):
        self.root.update_idletasks()
        test_realtime_ui.RealtimeUiTests.tearDown(self)

    def catalog(self):
        self.items = [
            parameter('style', label=r'NR Style\n(0 Default, 1 Natural, 2 Cinematic)', default=0, integer=True, step=1),
            parameter('intensity', label='NR Intensity'),
            parameter('residualMultiplier', label='Residual Multiplier', minimum=1),
            parameter('residualSaturation', label='Residual Saturation Multiplier'),
            parameter('useAutoMask', label='Automatic Mask', default=0, maximum=1, integer=True, step=1),
            parameter('inputResolutionPercent', label='Input Resolution (%)', default=100, minimum=25, maximum=100, integer=True, step=1),
            parameter('nvidiaOpticalFlowQuality', label='OF Quality', default=2, minimum=1, maximum=5,
                      integer=True, step=1, choices=[(1, 'Performance'), (2, 'Balanced'), (5, 'Highest Quality (Very High Cost)')]),
            parameter('pass2_intensity', label='NR Intensity'),
            parameter('future', label='Third party new parameter', group='Future controls'),
        ]
        self.event({'event': 'catalog', 'effects': [dict(name=NR, parameters=self.items, available=True),
                    dict(name='ThirdParty\\Color', label='Color adjustment', parameters=[parameter('amount')], available=True)]})
        # These legacy inspector scenarios exercise the entire native range.
        # Normal-range defaults and migration are covered in test_parameter_range.
        if self.ui.extended_range is not None and not self.ui.extended_range.get():
            self.ui.range_toggle.invoke()

    def running(self):
        self.catalog()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._run_id = 12
        self.ui._running_config = self.ui.collect()
        self.ui._applied_effects = deepcopy(self.ui._running_config['effects'])
        self.ui._parameter_modes = {(0, item['name']): 1 for item in self.items}
        self.ui._last_status_request = time.monotonic()
        self.ui._refresh_editor_state()
        self.client.send.reset_mock()

    def status(self, effects):
        self.event(dict(event='status', run_id=12, state=2, effects=effects, metrics={},
                        parameter_modes=[dict(effect=i, name=name, mode=mode)
                                         for (i, name), mode in self.ui._parameter_modes.items()]))

    def test_all_parameters_kept_and_control_types_match_metadata(self):
        self.catalog()
        self.assertEqual(set(self.ui.parameters), {item['name'] for item in self.items})
        self.assertIsNotNone(self.ui.parameter_rows['intensity'].slider)
        self.assertIsNotNone(self.ui.parameter_rows['useAutoMask'].toggle)
        self.assertIsNotNone(self.ui.parameter_rows['nvidiaOpticalFlowQuality'].choice)
        self.assertIsNone(self.ui.parameter_rows['nvidiaOpticalFlowQuality'].slider)
        self.assertFalse(self.ui.parameter_sections['look'].collapsed)
        self.assertTrue(self.ui.parameter_sections['advanced'].collapsed)
        self.assertIn('native:Future controls', self.ui.parameter_sections)
        grouped = inspector_groups(NR, self.items)
        self.assertEqual(sorted(p['name'] for _, _, group in grouped for p in group), sorted(self.ui.parameters))
        self.assertIn('DLSS NR', self.ui.chain.get(0))
        self.assertNotIn('\\', self.ui.chain.get(0))

    def test_sparse_enum_and_style_chips_store_native_numeric_values(self):
        self.catalog()
        row = self.ui.parameter_rows['nvidiaOpticalFlowQuality']
        row.display.set(row.choice_labels[2])
        row._choose()
        style = self.ui.parameter_rows['style']
        style.display.set(style.choice_labels[2])
        style._choose()
        self.ui.parameter_rows['useAutoMask'].toggle.invoke()
        params = self.ui.collect()['effects'][0]['parameters']
        self.assertEqual(params['nvidiaOpticalFlowQuality'], 5)
        self.assertEqual(params['style'], 2)
        self.assertEqual(params['useAutoMask'], 1)
        self.client.start.assert_not_called()

    def test_compact_numeric_display_and_exact_keyboard_input(self):
        self.catalog()
        row = self.ui.parameter_rows['intensity']
        row.variable.set('1.2000000000000002')
        self.assertEqual(row.number_text.get(), '1.20')
        row.variable.set('1.2345')
        self.assertEqual(row.number_text.get(), '1.2345')
        row.number_text.set('1.65')
        self.assertEqual(self.ui.collect()['effects'][0]['parameters']['intensity'], 1.65)
        row._commit_input()
        self.assertEqual(row.value(), 1.65)
        row.number_text.set('not a number')
        row._commit_input()
        self.assertEqual(self.ui._editor_state, 'invalid')

    def test_search_filters_without_modifying_chain_or_draft(self):
        self.catalog()
        self.ui.parameters['intensity'][1].set('1.45')
        before = self.ui.collect()
        self.ui.effect_search.set('color')
        self.assertEqual(self.ui._effect_ids, ['ThirdParty\\Color'])
        self.assertEqual(self.ui.collect(), before)
        self.ui._add()
        self.assertEqual(self.ui.collect()['effects'][0]['parameters']['intensity'], 1.45)
        self.assertEqual(self.ui.collect()['effects'][1]['name'], 'ThirdParty\\Color')
        self.ui.effect_search.set('missing search result')
        self.assertEqual(self.ui._effect_ids, [])
        self.ui._add()
        self.assertEqual(len(self.ui.config['effects']), 2)

    def test_release_submits_once_and_waits_for_matching_native_values(self):
        self.running()
        self.root.update()
        slider = self.ui.parameter_rows['intensity'].slider
        point = SimpleNamespace(x=slider.winfo_width() * .8)
        slider._on_down(point)
        slider._on_drag(point)
        self.client.send.assert_not_called()
        slider._on_up(point)
        self.client.send.assert_called_once()
        self.assertEqual(self.client.send.call_args.args, ('set_parameter',))
        self.assertEqual(self.ui._editor_state, 'applying')
        self.status(deepcopy(self.ui._applied_effects))
        self.assertTrue(self.ui._live_expected)
        applied = deepcopy(self.ui._applied_effects)
        applied[0]['parameters']['intensity'] = self.ui.parameter_rows['intensity'].value()
        self.status(applied)
        self.assertFalse(self.ui._live_expected)
        self.assertEqual(self.ui._editor_state, 'clean')

    def test_edit_while_applying_keeps_latest_value_for_next_commit(self):
        self.running()
        row = self.ui.parameter_rows['intensity']
        row.variable.set('1.2'); row.commit()
        row.variable.set('1.7'); row.commit()
        self.assertEqual(self.client.send.call_count, 1)
        first = deepcopy(self.ui._applied_effects)
        first[0]['parameters']['intensity'] = 1.2
        self.status(first)
        self.assertEqual(self.client.send.call_count, 2)
        self.assertEqual(self.client.send.call_args.kwargs['value'], 1.7)
        self.assertEqual(row.value(), 1.7)

    def test_restart_required_and_chain_edits_never_auto_restart_or_partial_send(self):
        self.running()
        self.ui._parameter_modes[(0, 'inputResolutionPercent')] = 2
        self.ui.parameters['intensity'][1].set('1.5')
        row = self.ui.parameter_rows['inputResolutionPercent']
        row.variable.set('75'); row.commit()
        self.assertEqual(self.ui._editor_state, 'restart')
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()
        with mock.patch.object(self.ui, 'start') as restart:
            self.ui.apply_button.invoke()
            restart.assert_called_once()
        self.ui.effect_search.set('color'); self.ui._add()
        self.assertEqual(self.ui._editor_state, 'restart')
        self.client.send.assert_not_called()

    def test_bad_numeric_input_does_not_send_or_silently_clamp(self):
        self.running()
        row = self.ui.parameter_rows['intensity']
        for value in ('', 'oops', 'nan', 'inf', '10'):
            row.variable.set(value); row.commit()
            self.assertEqual(self.ui._editor_state, 'invalid', value)
            self.assertEqual(row.variable.get(), value)
            self.client.send.assert_not_called()
        row.variable.set('1.35'); row.commit()
        self.client.send.assert_called_once()

    def test_sections_drafts_and_theme_survive_editor_rebuild(self):
        self.catalog()
        self.ui.parameter_sections['advanced'].toggle()
        self.ui.parameters['intensity'][1].set('1.55')
        for theme in ('light', 'dark', 'light'):
            self.ui._select_effect()
            self.ui.apply_theme(ui_theme.tokens(theme))
            self.assertFalse(self.ui.parameter_sections['advanced'].collapsed)
            self.assertEqual(self.ui.parameters['intensity'][1].get(), '1.55')
            self.assertEqual(self.ui.parameter_rows['intensity'].slider.cget('background'), ui_theme.tokens(theme)['panel'])
            self.assertTrue(all(w.winfo_exists() for w in self.ui._parameter_widgets))

    def test_scale_units_and_footer_stay_visible_at_narrow_size(self):
        self.catalog()
        self.root.geometry('800x600')
        self.ui.parameter_sections['resolution'].toggle()
        _, kind, x, y = self.ui.scale_controls
        kind.current(2)
        kind.combo.event_generate('<<ComboboxSelected>>')
        x.set('1920'); y.set('1080')
        self.assertEqual(self.ui.collect()['effects'][0]['scale'], [1920, 1080])
        kind.current(1)
        kind.combo.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertFalse(self.ui.apply_button.winfo_ismapped())
        self.assertLessEqual(self.ui.editor_footer.winfo_rooty() + self.ui.editor_footer.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())
        self.assertEqual(self.ui.collect()['effects'][0]['scale'], [1920, 1080])

    def test_live_timeout_is_visible_and_stop_cancels_queued_edits(self):
        self.running()
        row = self.ui.parameter_rows['intensity']
        row.variable.set('1.5'); row.commit()
        self.ui._live_sent_at = time.monotonic() - 6
        self.event({'event': 'log', 'message': 'tick'})
        self.assertFalse(self.ui._live_expected)
        self.assertEqual(self.ui._editor_state, 'failed')
        self.assertIn(i18n.tr('realtime.editor.timeout'), self.ui.editor_status.get())
        self.ui.apply_button.invoke()
        self.assertEqual(self.ui._editor_state, 'applying')
        self.assertEqual(self.client.send.call_count, 2)
        self.client.start.assert_not_called()
        self.ui._queued_parameter_apply = True
        self.ui.command('stop')
        self.assertFalse(self.ui._queued_parameter_apply)

    def test_invalid_field_keeps_selected_effect_and_blocks_reorder(self):
        self.catalog()
        self.ui.effect_search.set('color'); self.ui._add()
        self.ui.parameters['amount'][1].set('bad value')
        self.ui._move(-1)
        self.ui._remove()
        self.assertEqual(len(self.ui.config['effects']), 2)
        self.assertEqual(self.ui.config['effects'][1]['name'], 'ThirdParty\\Color')
        self.ui.chain.selection_clear(0, 'end')
        self.ui.chain.selection_set(0)
        self.ui._select_effect()
        self.assertEqual(self.ui.chain.curselection(), (1,))
        self.assertEqual(self.ui.parameters['amount'][1].get(), 'bad value')

    def test_long_labels_reserve_numeric_field_width(self):
        self.catalog()
        self.ui.catalog[NR]['parameters'].append(parameter('long', label='A very long third-party parameter label ' * 6))
        self.ui._select_effect()
        for section in self.ui.parameter_sections.values():
            if section.collapsed:
                section.toggle()
        self.ui._focus_page('effects', self.ui.parameter_rows['long'])
        for theme in ('light', 'dark'):
            self.ui.apply_theme(ui_theme.tokens(theme))
            self.root.update()
            row = self.ui.parameter_rows['long']
            self.assertGreater(row.field.winfo_width(), 60)
            self.assertLessEqual(row.field.winfo_x() + row.field.winfo_width(), row.winfo_width())

    def test_quick_quality_edits_wait_for_revision_then_apply_latest_draft(self):
        self.running()
        self.ui.quality_controls['total'].set('.6')
        self.ui._quality_committed()
        self.ui.quality_controls['total'].set('.8')
        self.ui._quality_committed()
        self.assertEqual(self.client.send.call_count, 1)
        self.assertTrue(self.ui._queued_quality_apply)
        self.event(dict(event='ack', id=1, ok=True, run_id=12, quality_revision=3))
        self.event(dict(event='status', run_id=12, state=2, effects=self.ui._applied_effects,
                        quality_revision=3, quality_applied_revision=3))
        self.assertEqual(self.client.send.call_args.args, ('quality',))
        self.assertEqual(self.client.send.call_args.kwargs['quality']['total'], .8)
        self.assertEqual(self.ui._running_config['quality']['total'], .6)

    def dependencies(self):
        self.catalog()
        self.items.extend([
            parameter('enableInputResolutionScaling', default=0, maximum=1, integer=True, step=1),
            parameter('opticalFlowMethod', default=0, integer=True, step=1,
                      choices=[(0, 'None'), (1, 'AMDOF'), (2, 'NVOF')]),
            parameter('amdOpticalFlowMode', default=1, maximum=1, integer=True, step=1,
                      choices=[(0, 'Performance'), (1, 'Quality')]),
            parameter('multiPass', default=1, minimum=1, maximum=3, integer=True, step=1),
            parameter('pass2_style', default=0, integer=True, step=1),
            parameter('pass3_intensity'),
        ])
        self.ui._select_effect()

    def test_dependencies_disable_mouse_keyboard_and_keep_draft_values(self):
        self.dependencies()
        rows = self.ui.parameter_rows
        for name in ('inputResolutionPercent', 'amdOpticalFlowMode', 'nvidiaOpticalFlowQuality',
                     'pass2_intensity', 'pass2_style', 'pass3_intensity'):
            self.assertFalse(rows[name].enabled, name)
            self.assertTrue(rows[name].disabled_reason)
        style = rows['pass2_style']
        style.choice._nudge(1)
        self.root.update()
        _, start, end = style.choice._hits[-1]
        style.choice._on_click(SimpleNamespace(x=(start + end) / 2))
        self.assertEqual(style.value(), 0)
        rows['enableInputResolutionScaling'].toggle.invoke()
        self.assertTrue(rows['inputResolutionPercent'].enabled)
        rows['inputResolutionPercent'].variable.set('75')
        rows['enableInputResolutionScaling'].toggle.invoke()
        self.assertEqual(str(rows['inputResolutionPercent'].field.cget('state')), 'disabled')
        rows['enableInputResolutionScaling'].toggle.invoke()
        self.assertEqual(rows['inputResolutionPercent'].value(), 75)
        rows['opticalFlowMethod'].variable.set('1')
        self.assertTrue(rows['amdOpticalFlowMode'].enabled)
        self.assertFalse(rows['nvidiaOpticalFlowQuality'].enabled)
        rows['opticalFlowMethod'].variable.set('2')
        self.assertFalse(rows['amdOpticalFlowMode'].enabled)
        self.assertTrue(rows['nvidiaOpticalFlowQuality'].enabled)
        rows['multiPass'].variable.set('2')
        self.assertTrue(style.enabled)
        self.assertFalse(rows['pass3_intensity'].enabled)
        style.choice._nudge(1)
        self.assertEqual(style.value(), 1)
        rows['multiPass'].variable.set('3')
        self.assertTrue(rows['pass3_intensity'].enabled)
        rows['multiPass'].variable.set('1')
        for theme in ('light', 'dark'):
            self.ui.apply_theme(ui_theme.tokens(theme))
            self.assertFalse(style.enabled)
            style.choice._nudge(1)
            self.assertEqual(style.value(), 1)
        self.client.start.assert_not_called()

    def test_optional_pass_switches_default_off_and_preserve_values(self):
        self.dependencies()
        second, third = self.ui.pass_toggles[2], self.ui.pass_toggles[3]
        self.assertEqual(self.ui.collect()['effects'][0]['parameters']['multiPass'], 1)
        self.assertFalse(second[0].get())
        self.assertFalse(third[0].get())
        self.assertEqual(third[1].cget('state'), 'disabled')
        self.assertNotIn(i18n.tr('realtime.editor.pass_off'), self.ui.parameter_sections['pass2']._title)
        self.ui.parameter_sections['pass2'].toggle()
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 1)
        third[1].invoke()
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 1)
        second[1].invoke()
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 2)
        third[1].invoke()
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 3)
        self.ui.parameters['pass3_intensity'][1].set('1.6')
        second[1].invoke()
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 1)
        self.assertFalse(third[0].get())
        self.assertFalse(self.ui.parameter_rows['pass3_intensity'].enabled)
        second[1].invoke()
        third[1].invoke()
        self.assertEqual(self.ui.parameter_rows['pass3_intensity'].value(), 1.6)
        self.client.start.assert_not_called()

    def test_pass_switch_import_undo_and_restart_follow_existing_editor(self):
        self.dependencies()
        config = self.ui.collect()
        config['effects'][0]['parameters']['multiPass'] = 3
        self.ui.apply_config(config)
        self.assertTrue(self.ui.pass_toggles[2][0].get())
        self.assertTrue(self.ui.pass_toggles[3][0].get())
        self.ui._active = self.ui._render_confirmed = True
        self.ui._run_id = 12
        self.ui._running_config = self.ui.collect()
        self.ui._applied_effects = deepcopy(self.ui._running_config['effects'])
        self.ui._parameter_modes = {(0, 'multiPass'): 2}
        self.client.send.reset_mock()
        self.ui.pass_toggles[3][1].invoke()
        self.assertEqual(self.ui._editor_state, 'restart')
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()
        self.ui._undo_parameter_edit()
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 3)
        self.assertTrue(self.ui.pass_toggles[3][0].get())
        for theme in ('light', 'dark'):
            self.ui.apply_theme(ui_theme.tokens(theme))
            self.root.update_idletasks()
            self.assertEqual(self.ui.pass_toggles[3][1].cget('state'), 'normal')

    def test_pass_headers_keep_toggle_visible_and_advanced_reset_does_not_disable_passes(self):
        self.dependencies()
        self.ui.parameters['multiPass'][1].set('3')
        self.ui._focus_page('effects', self.ui.parameter_sections['pass2'])
        for geometry in ('1000x680', '1280x800'):
            self.root.geometry(geometry)
            self.root.update()
            for count in (2, 3):
                section = self.ui.parameter_sections['pass' + str(count)]
                toggle = self.ui.pass_toggles[count][1]
                self.assertTrue(toggle.winfo_ismapped())
                self.assertGreater(toggle.winfo_width(), 20)
                self.assertLessEqual(toggle.winfo_rootx() + toggle.winfo_width(),
                                     section.winfo_rootx() + section.winfo_width())
                self.assertLessEqual(section._header.winfo_rootx() + section._header.winfo_width(),
                                     toggle.winfo_rootx())
        self.ui._reset_parameters(self.ui._parameter_groups['advanced'][1])
        self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 3)

    def test_incomplete_third_party_nr_metadata_keeps_pass_count_accessible(self):
        self.catalog()
        self.items.append(parameter('multiPass', default=1, minimum=1, maximum=3, integer=True, step=1))
        self.ui._select_effect()
        self.assertFalse(self.ui.pass_toggles)
        self.assertEqual(self.ui.parameter_rows['multiPass'].winfo_manager(), 'pack')

    def test_only_unapplied_feedback_is_visible_not_default_comparisons(self):
        self.running()
        row = self.ui.parameter_rows['intensity']
        self.assertFalse(row.nondefault)
        self.assertFalse(row.unapplied)
        row.variable.set('1.5')
        self.assertTrue(row.nondefault)
        self.assertTrue(row.unapplied)
        self.assertEqual(self.ui.parameter_sections['look']._title, self.ui._parameter_groups['look'][0])
        row.commit()
        self.assertTrue(row.unapplied)
        applied = deepcopy(self.ui._applied_effects)
        applied[0]['parameters']['intensity'] = 1.5
        self.status(applied)
        self.assertTrue(row.nondefault)
        self.assertFalse(row.unapplied)
        self.assertIsNone(row.reset_button)
        with mock.patch('dlss5tool.realtime_ui.messagebox.askokcancel', return_value=True):
            self.ui._reset_current_effect()
        self.assertFalse(row.nondefault)
        self.assertTrue(row.unapplied)
        self.assertNotIn(i18n.tr('realtime.workspace.adjusted', count=1), self.ui.parameter_sections['look']._title)

    def test_group_reset_is_batched_and_undo_restores_values_without_restart(self):
        self.running()
        self.ui.parameters['intensity'][1].set('1.5')
        self.ui.parameters['style'][1].set('2')
        self.ui._parameter_committed()
        self.status(self.ui.collect()['effects'])
        self.client.send.reset_mock()
        self.ui._reset_parameters(['intensity', 'style'])
        calls = [c for c in self.client.send.call_args_list if c.args == ('set_parameter',)]
        self.assertEqual({c.kwargs['name']: c.kwargs['value'] for c in calls}, {'intensity': 1, 'style': 0})
        self.assertEqual(len(calls), 2)
        self.ui.undo_button.invoke()  # Queue latest values until reset confirmation.
        self.assertEqual(self.ui.parameters['intensity'][1].get(), '1.5')
        self.assertEqual(self.ui.parameters['style'][1].get(), '2')
        reset = deepcopy(self.ui._applied_effects)
        reset[0]['parameters'].update(intensity=1, style=0)
        self.status(reset)
        self.assertEqual(self.ui._live_expected, {(0, 'intensity'): 1.5, (0, 'style'): 2})
        self.client.start.assert_not_called()

    def test_reset_repairs_invalid_input_and_undo_is_one_step(self):
        self.catalog()
        row = self.ui.parameter_rows['intensity']
        row.variable.set('1.5'); row.commit()
        self.ui.undo_button.invoke()
        self.assertEqual(row.value(), 1)
        self.assertEqual(self.ui.undo_button.cget('state'), 'disabled')
        row.number_text.set('1.00'); row._commit_input()
        self.assertEqual(self.ui.undo_button.cget('state'), 'disabled')
        row.variable.set('bad')
        with mock.patch('dlss5tool.realtime_ui.messagebox.askokcancel', return_value=True):
            self.ui._reset_current_effect()
        self.assertEqual(row.value(), 1)
        self.ui.undo_button.invoke()
        self.assertEqual(row.variable.get(), 'bad')
        self.assertEqual(self.ui._editor_state, 'invalid')
        self.client.start.assert_not_called()

    def test_scale_group_reset_and_undo_retain_units_and_values(self):
        self.catalog()
        _, mode, x, y = self.ui.scale_controls
        mode.current(2)
        mode.combo.event_generate('<<ComboboxSelected>>')
        x.set('1920'); y.set('1080')
        self.ui._reset_parameters(['inputResolutionPercent'], scale=True)
        self.assertEqual((mode.current(), x.get(), y.get()), (0, '1', '1'))
        self.ui.undo_button.invoke()
        self.assertEqual((mode.current(), x.get(), y.get()), (2, '1920', '1080'))

    def test_group_reset_with_restart_parameter_does_not_partially_send(self):
        self.running()
        self.ui.parameters['intensity'][1].set('1.5')
        self.ui.parameters['style'][1].set('2')
        self.ui._parameter_committed()
        self.status(self.ui.collect()['effects'])
        self.ui._parameter_modes[(0, 'style')] = 2
        self.client.send.reset_mock()
        self.ui._reset_parameters(['intensity', 'style'])
        self.assertEqual(self.ui._editor_state, 'restart')
        self.assertIn(i18n.tr('realtime.editor.reason_parameters', count=1), self.ui.editor_status.get())
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()

    def test_stale_ack_does_not_fail_live_edit_and_retry_waits_for_confirmation(self):
        self.running()
        row = self.ui.parameter_rows['intensity']
        row.variable.set('1.5'); row.commit()
        self.event(dict(event='ack', id=99, ok=False, run_id=12, message='unrelated action failed'))
        self.assertEqual(self.ui._editor_state, 'applying')
        self.assertEqual(self.ui.status.get(), 'unrelated action failed')
        self.event(dict(event='ack', id=1, ok=False, run_id=11, message='old session'))
        self.assertEqual(self.ui._editor_state, 'applying')
        self.event(dict(event='ack', id=1, ok=False, run_id=12, message='rejected'))
        self.assertEqual(self.ui._editor_state, 'failed')
        self.ui.apply_button.invoke()
        self.assertEqual(self.ui._editor_state, 'applying')
        self.assertTrue(row.unapplied)
        applied = deepcopy(self.ui._applied_effects)
        applied[0]['parameters']['intensity'] = 1.5
        self.status(applied)
        self.assertEqual(self.ui._editor_state, 'clean')
        self.client.start.assert_not_called()

    def test_quality_timeout_can_retry_and_restart_reason_is_specific(self):
        self.running()
        self.ui.quality_controls['total'].set('.6')
        self.ui._quality_committed()
        self.ui._pending_quality['sent_at'] = time.monotonic() - 6
        self.event(dict(event='log', message='tick'))
        self.assertEqual(self.ui._editor_state, 'failed')
        self.ui.apply_button.invoke()
        self.assertEqual(self.ui._editor_state, 'applying')
        self.assertIsNotNone(self.ui._pending_quality)
        self.ui._pending_quality = None
        _, mode, _, _ = self.ui.scale_controls
        mode.current(1)
        mode.combo.event_generate('<<ComboboxSelected>>')
        self.assertEqual(self.ui._editor_state, 'restart')
        self.assertIn(i18n.tr('realtime.editor.reason_scale'), self.ui.editor_status.get())
        self.client.start.assert_not_called()

    def test_native_quality_rejection_without_run_id_is_retryable(self):
        self.running()
        self.ui.quality_controls['total'].set('.6')
        self.ui._quality_committed()
        self.event(dict(event='ack', id=1, ok=False, run_id=11, message='stale quality'))
        self.assertIsNotNone(self.ui._pending_quality)
        self.event(dict(event='ack', id=1, ok=False, message='quality rejected'))
        self.assertIsNone(self.ui._pending_quality)
        self.assertEqual(self.ui._editor_state, 'failed')
        self.assertIn('quality rejected', self.ui.editor_status.get())
        self.ui.apply_button.invoke()
        self.assertEqual(self.ui._editor_state, 'applying')
        self.client.start.assert_not_called()

    def test_effect_categories_and_descriptions_do_not_edit_chain(self):
        from dlss5tool.realtime_labels import EFFECT_CATEGORIES
        self.catalog()
        self.ui.catalog['CRT\\Example'] = {'available': True, 'parameters': []}
        self.ui.catalog['XeSS\\Example'] = {'available': False, 'parameters': []}
        before = self.ui.collect()
        self.ui.effect_category.current(EFFECT_CATEGORIES.index('crt'))
        self.ui._filter_effects()
        self.assertEqual(self.ui._effect_ids, ['CRT\\Example'])
        self.assertIn('CRT', self.ui.effect_help.get())
        self.assertIn('1', self.ui.effect_count.get())
        self.assertEqual(self.ui.collect(), before)
        self.ui.effect_category.current(0)
        self.ui._filter_effects()
        # The advanced library retains unavailable entries with an explanation.
        self.assertIn('XeSS\\Example', self.ui._effect_ids)
        self.ui.effect_choice.current(self.ui._effect_ids.index('XeSS\\Example'))
        self.ui._describe_effect_choice()
        self.ui._add()
        self.assertEqual(self.ui.collect(), before)
        self.assertIn('ThirdParty\\Color', self.ui._effect_ids)

    def test_diagnostic_snapshot_keeps_invalid_raw_draft_and_errors_without_commands(self):
        self.running()
        self.ui.parameters['intensity'][1].set('invalid number')
        original = deepcopy(self.ui.config)
        self.client.send.reset_mock()
        snapshot = self.ui.diagnostic_snapshot()
        self.assertEqual(snapshot['draft_fields']['effect']['parameters']['intensity'], 'invalid number')
        self.assertEqual(snapshot['running_config']['effects'][0]['parameters']['intensity'], 1)
        self.assertTrue(snapshot['journal']['errors'])
        self.assertEqual(self.ui.config, original)
        self.client.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
