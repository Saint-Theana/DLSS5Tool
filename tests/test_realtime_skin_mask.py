"""Combined NR skin mask uses native pairs without losing draft memory."""
from copy import deepcopy
import time
import unittest
from unittest import mock

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime import (NR, NR_SKIN_PAIRS, effective_nr_skin, restore_nr_skin_memory,
                               nr_preset, apply_nr_preset, portable_config, validate_config)
from tests import test_realtime_inspector as inspector
from tests.test_realtime_inspector import parameter


class SkinConfigTests(unittest.TestCase):
    def test_effective_pairs_do_not_mutate_presets_or_third_party_parameters(self):
        params = dict(skinStructureStrength=.7, useAutoMask=0,
                      pass2_skinStructureStrength=0, pass2_useAutoMask=1,
                      pass3_skinStructureStrength=1.2345, pass3_useAutoMask=1)
        config = validate_config({'effects': [dict(name=NR, parameters=params),
                                             dict(name='ThirdParty/Filter', parameters=params)]})
        original = deepcopy(config)
        effective = effective_nr_skin(config)
        self.assertEqual(config, original)
        actual = effective['effects'][0]['parameters']
        for strength, mask in NR_SKIN_PAIRS[:2]:
            self.assertEqual((actual[strength], actual[mask]), (0, 0))
        self.assertEqual(actual['pass3_skinStructureStrength'], 1.2345)
        self.assertEqual(effective['effects'][1], original['effects'][1])
        self.assertEqual(restore_nr_skin_memory(effective, config), config)
        self.assertEqual(portable_config(config)['effects'], config['effects'])
        self.assertEqual(apply_nr_preset(config, nr_preset(config))['effects'], config['effects'])

    def test_memory_restore_cannot_save_unconfirmed_values_or_different_chain(self):
        draft = validate_config({'effects': [dict(name=NR, parameters=dict(
            skinStructureStrength=.8, useAutoMask=1, intensity=1.5))]})
        actual = deepcopy(draft)
        actual['effects'][0]['parameters'].update(skinStructureStrength=0, useAutoMask=0, intensity=1)
        self.assertEqual(restore_nr_skin_memory(actual, draft), actual)
        draft['effects'][0]['parameters']['useAutoMask'] = 0
        saved = restore_nr_skin_memory(actual, draft)
        self.assertEqual(saved['effects'][0]['parameters']['skinStructureStrength'], .8)
        self.assertEqual(saved['effects'][0]['parameters']['intensity'], 1)
        draft['effects'][0]['scale'] = [2, 2]
        self.assertEqual(restore_nr_skin_memory(actual, draft), actual)

    def test_partial_metadata_keeps_legacy_independent_fields(self):
        for params in ({'useAutoMask': 1}, {'skinStructureStrength': .5}):
            config = validate_config({'effects': [dict(name=NR, parameters=params)]})
            self.assertEqual(effective_nr_skin(config), config)


class SkinInspectorTests(unittest.TestCase):
    setUp = inspector.RealtimeInspectorTests.setUp
    tearDown = inspector.RealtimeInspectorTests.tearDown
    event = inspector.RealtimeInspectorTests.event
    status = inspector.RealtimeInspectorTests.status

    def catalog(self):
        inspector.RealtimeInspectorTests.catalog(self)
        self.items.append(parameter('skinStructureStrength', label='Skin Structure Strength', default=0))
        self.items.append(parameter('multiPass', default=1, minimum=1, maximum=3, integer=True, step=1))
        for prefix in ('pass2_', 'pass3_'):
            self.items.extend([
                parameter(prefix + 'skinStructureStrength', label='Skin Structure Strength', default=0),
                parameter(prefix + 'useAutoMask', label='Automatic Mask', default=0, maximum=1, integer=True, step=1),
            ])
        self.ui._select_effect()

    def running(self, *, strength=.85, enabled=1):
        self.catalog()
        self.ui.parameters['skinStructureStrength'][1].set(str(strength))
        self.ui.parameters['useAutoMask'][1].set(str(enabled))
        self.ui._parameter_committed()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._run_id = 12
        self.ui._running_config = effective_nr_skin(self.ui.collect())
        self.ui._applied_effects = deepcopy(self.ui._running_config['effects'])
        self.ui._parameter_modes = {(0, item['name']): 1 for item in self.items}
        self.ui._last_status_request = time.monotonic()
        self.ui._refresh_editor_state()
        self.client.send.reset_mock()

    def test_combined_rows_preserve_fields_and_match_local_media(self):
        self.catalog()
        self.assertEqual(set(self.ui.parameters), {p['name'] for p in self.items})
        for strength, mask in NR_SKIN_PAIRS:
            row = self.ui.parameter_rows[strength]
            self.assertIsNotNone(row.enable_toggle)
            self.assertEqual(row.enable_toggle.cget('text'), i18n.tr('label.skin_mask'))
            self.assertEqual(self.ui.parameter_rows[mask].winfo_manager(), '')
            self.assertEqual(str(row.field.cget('state')), 'disabled')
            self.assertEqual(row.slider.cget('state'), 'disabled')
        self.assertEqual(self.ui.collect()['effects'][0]['parameters']['useAutoMask'], 0)

    def test_switch_remembers_value_zero_is_effectively_off_and_reset_undo_are_paired(self):
        self.catalog()
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        self.assertEqual(str(row.field.cget('state')), 'normal')
        row.number_text.set('1.2345'); row._commit_input()
        row.enable_toggle.invoke()
        self.assertEqual(row.value(), 1.2345)
        self.assertEqual(str(row.field.cget('state')), 'disabled')
        self.assertEqual(self.ui.collect()['effects'][0]['parameters']['skinStructureStrength'], 1.2345)
        self.assertEqual(effective_nr_skin(self.ui.collect())['effects'][0]['parameters']['skinStructureStrength'], 0)
        row.enable_toggle.invoke()
        self.assertEqual(row.value(), 1.2345)
        self.assertEqual(self.ui.parameter_sections['look']._title, self.ui._parameter_groups['look'][0])
        with mock.patch('dlss5tool.realtime_ui.messagebox.askokcancel', return_value=True):
            self.ui._reset_current_effect()
        self.assertEqual((row.value(), self.ui.parameters['useAutoMask'][1].get()), (0, '0'))
        self.ui.undo_button.invoke()
        self.assertEqual((row.value(), self.ui.parameters['useAutoMask'][1].get()), (1.2345, '1'))
        row.number_text.set('0'); row._commit_input()
        self.assertTrue(row.enable_display.get())
        effective = effective_nr_skin(self.ui.collect())['effects'][0]['parameters']
        self.assertEqual((effective['skinStructureStrength'], effective['useAutoMask']), (0, 0))
        self.client.start.assert_not_called()

    def test_off_memory_survives_effect_switch_reorder_and_preset_round_trip(self):
        self.catalog()
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        row.variable.set('.7'); row.commit()
        row.enable_toggle.invoke()
        draft = self.ui.collect()
        self.store.save('mask off', draft)
        self.store.save_nr('mask off', draft)
        effects = deepcopy(draft['effects']) + [dict(name='ThirdParty\\Color', parameters={'amount': 1})]
        self.ui._commit_effects(effects, 1)
        self.ui._move(-1)
        self.ui.chain.selection_set(1); self.ui._select_effect()
        row = self.ui.parameter_rows['skinStructureStrength']
        self.assertEqual(row.value(), .7)
        self.assertFalse(row.enable_display.get())
        self.ui.apply_config(self.store.data['presets']['mask off'])
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        self.assertEqual(row.value(), .7)
        self.ui.apply_config(apply_nr_preset(self.ui.collect(), self.store.data['nr_presets']['mask off']))
        self.assertEqual(self.ui.parameter_rows['skinStructureStrength'].value(), .7)
        self.assertFalse(self.ui.parameter_rows['skinStructureStrength'].enable_display.get())

    def test_live_switch_waits_for_both_values_and_saves_memory_not_pending_drafts(self):
        self.running()
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        self.assertEqual(self.ui._live_expected, {(0, 'skinStructureStrength'): 0, (0, 'useAutoMask'): 0})
        self.assertTrue(row.unapplied)
        applied = deepcopy(self.ui._applied_effects)
        applied[0]['parameters']['useAutoMask'] = 0
        self.status(applied)
        self.assertEqual(self.ui._editor_state, 'applying')
        self.ui.parameters['intensity'][1].set('1.6')
        applied[0]['parameters']['skinStructureStrength'] = 0
        self.status(applied)
        self.assertFalse(row.unapplied)
        saved = self.store.data['session']['effects'][0]['parameters']
        self.assertEqual((saved['skinStructureStrength'], saved['useAutoMask']), (.85, 0))
        self.assertEqual(saved['intensity'], 1)
        self.assertEqual(row.value(), .85)
        self.client.start.assert_not_called()

    def test_mask_zero_switch_is_saved_without_native_changes(self):
        self.running(strength=0, enabled=0)
        self.ui.parameter_rows['skinStructureStrength'].enable_toggle.invoke()
        self.client.send.assert_not_called()
        self.assertEqual(self.ui._editor_state, 'clean')
        self.assertEqual(self.store.data['session']['effects'][0]['parameters']['useAutoMask'], 1)

    def test_restart_parameter_blocks_partial_skin_submission(self):
        self.running()
        self.ui._parameter_modes[(0, 'useAutoMask')] = 2
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        self.assertEqual(self.ui._editor_state, 'restart')
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()
        self.ui.undo_button.invoke()
        self.assertEqual(row.value(), .85)
        self.assertTrue(row.enable_display.get())
        self.assertEqual(self.ui._editor_state, 'clean')

    def test_quick_off_on_queues_latest_pair_until_previous_confirmation(self):
        self.running()
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        off = effective_nr_skin(self.ui.collect())['effects']
        row.enable_toggle.invoke()
        self.assertTrue(self.ui._queued_parameter_apply)
        self.assertEqual(self.client.send.call_count, 2)
        self.status(off)
        self.assertEqual(self.ui._live_expected, {(0, 'skinStructureStrength'): .85, (0, 'useAutoMask'): 1})
        self.status(effective_nr_skin(self.ui.collect())['effects'])
        self.assertEqual(self.ui._editor_state, 'clean')
        self.assertEqual(row.value(), .85)
        self.assertTrue(row.enable_display.get())
        self.client.start.assert_not_called()

    def test_recovery_reuses_effective_values_and_restores_off_memory(self):
        self.running(enabled=0)
        remembered = self.ui.collect()
        target = dict(hwnd=123, pid=456, title='test', application='test.exe')
        self.ui._known_settings = {}
        self.ui._recovering = True
        self.ui._recovery_target = (target, remembered)
        self.ui._recovery.put(None)
        self.event(dict(event='log', message='recovery complete'))
        sent = self.client.start.call_args.args[1]['effects'][0]['parameters']
        self.assertEqual((sent['skinStructureStrength'], sent['useAutoMask']), (0, 0))
        self.assertEqual(self.ui.parameter_rows['skinStructureStrength'].value(), .85)
        self.assertFalse(self.ui.parameter_rows['skinStructureStrength'].enable_display.get())

    def test_start_and_confirm_send_effective_values_keep_remembered_session(self):
        self.catalog()
        self.ui.parameters['skinStructureStrength'][1].set('.65')
        raw = self.ui.collect()
        target = dict(hwnd=123, pid=456, title='test', application='test.exe')
        with mock.patch.object(self.ui, '_run_preflight', return_value=(raw, [])), \
             mock.patch.object(self.ui, 'selected_window', return_value=target):
            self.ui.start()
        sent = self.client.start.call_args.args[1]
        self.assertEqual(sent['effects'][0]['parameters']['skinStructureStrength'], 0)
        self.assertEqual(self.ui.parameter_rows['skinStructureStrength'].value(), .65)
        self.event(dict(event='state', state=1, run_id=12))
        self.event(dict(event='state', state=2, run_id=12))
        self.event(dict(event='status', state=2, run_id=12, effects=sent['effects'], metrics={'submitted': 1}))
        self.assertEqual(self.ui._editor_state, 'clean')
        self.assertEqual(self.store.data['session']['effects'][0]['parameters']['skinStructureStrength'], .65)
        self.assertEqual(self.ui._known_good[1]['effects'][0]['parameters']['skinStructureStrength'], .65)

    def test_overlay_unrelated_save_preserves_off_memory_and_conflicts_still_block(self):
        self.running(enabled=0)
        self.ui._known_good = ({'hwnd': 123}, self.ui.collect())
        before = deepcopy(self.ui._applied_effects)
        after = deepcopy(before)
        after[0]['parameters']['intensity'] = 1.2
        self.event(dict(event='settings_requested', token=88, run_id=12, previous_effects=before,
                        effects=after, sync_enabled=True, frame_rate=60, sync_mode=0))
        self.assertEqual(self.ui.parameter_rows['skinStructureStrength'].value(), .85)
        self.assertFalse(self.ui.parameter_rows['skinStructureStrength'].enable_display.get())
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), 1.2)
        saved = self.store.data['session']['effects'][0]['parameters']
        self.assertEqual(saved['skinStructureStrength'], .85)
        self.assertEqual(self.ui._known_good[1]['effects'][0]['parameters']['skinStructureStrength'], .85)
        self.ui.parameters['intensity'][1].set('1.4')
        after[0]['parameters']['intensity'] = 1.3
        self.event(dict(event='settings_requested', token=89, run_id=12, previous_effects=before,
                        effects=after, sync_enabled=True, frame_rate=60, sync_mode=0))
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), 1.4)
        self.assertEqual(self.store.data['session']['effects'][0]['parameters']['intensity'], 1.2)

    def test_pass_disable_blocks_input_keeps_memory_and_theme_layout_bilingual(self):
        self.catalog()
        for language in ('zh_CN', 'en_US'):
            i18n.set_language(language)
            self.ui._select_effect()
            self.ui.parameters['multiPass'][1].set('3')
            for strength, mask in NR_SKIN_PAIRS:
                row = self.ui.parameter_rows[strength]
                if not row.enable_display.get():
                    row.enable_toggle.invoke()
                row.variable.set('.75'); row.commit()
            self.ui.parameters['multiPass'][1].set('1')
            for strength, mask in NR_SKIN_PAIRS[1:]:
                row = self.ui.parameter_rows[strength]
                row.enable_toggle.invoke()
                row.slider._nudge(1)
                row._commit_input()
                self.assertEqual(row.value(), .75)
                self.assertTrue(row.enable_display.get())
                self.assertEqual(row.enable_toggle.cget('state'), 'disabled')
            for theme in ('dark', 'light'):
                self.ui.apply_theme(ui_theme.tokens(theme))
                for size in ('800x600', '1000x680'):
                    self.root.geometry(size)
                    self.root.update()
                    row = self.ui.parameter_rows['skinStructureStrength']
                    switch, field = row.enable_toggle, row.field
                    self.assertIsNone(row.reset_button)
                    self.assertGreater(field.winfo_width(), 60)
                    self.assertLessEqual(switch.winfo_rootx() + switch.winfo_width(), field.winfo_rootx())
                    self.assertLessEqual(field.winfo_rootx() + field.winfo_width(), row.winfo_rootx() + row.winfo_width())
            self.ui.parameters['multiPass'][1].set('3')
            for strength, mask in NR_SKIN_PAIRS:
                self.assertEqual(str(self.ui.parameter_rows[strength].field.cget('state')), 'normal')

    def test_invalid_strength_is_not_silently_clamped_and_reset_repairs_both(self):
        self.catalog()
        row = self.ui.parameter_rows['skinStructureStrength']
        row.enable_toggle.invoke()
        row.number_text.set('not a number'); row._commit_input()
        self.assertEqual(self.ui._editor_state, 'invalid')
        with mock.patch('dlss5tool.realtime_ui.messagebox.askokcancel', return_value=True):
            self.ui._reset_current_effect()
        self.assertEqual(self.ui._editor_state, 'idle')
        self.assertEqual(row.value(), 0)
        self.assertFalse(row.enable_display.get())
        self.ui.undo_button.invoke()
        self.assertEqual(self.ui._editor_state, 'invalid')
        self.assertEqual(row.variable.get(), 'not a number')


if __name__ == '__main__':
    unittest.main()
