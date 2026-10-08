"""Range/display regressions using actual float32 metadata, no native rendering."""
from copy import deepcopy
import struct
import unittest
from unittest import mock

from dlss5tool import app_settings, i18n, ui_theme
from dlss5tool.parameter_values import clean_step, format_number
from dlss5tool.realtime import (NR, NR_RANGE_PARAMETERS, validate_config, nr_extended_range,
    effective_nr_skin, restore_nr_skin_memory, nr_preset, apply_nr_preset)
from dlss5tool.parameter_transfer import from_realtime, to_realtime
from tests import test_parameter_unification as common, test_realtime_inspector as inspector
from tests import test_workbench_ui as workbench


def f32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


class NumberRangeTests(unittest.TestCase):
    def test_float32_step_tail_does_not_become_display_precision(self):
        self.assertEqual(clean_step(f32(.05)), .05)
        for value, expected in ((1, '1.00'), (0, '0.00'), (f32(.35), '0.35'),
                                (.12345, '0.12345'), (.35000001, '0.35000001')):
            self.assertEqual(format_number(value, f32(.05)), expected)
        self.assertEqual(format_number(3, 1), '3')
        self.assertEqual(format_number(.001, f32(.001)), '0.001')
        self.assertEqual(format_number('bad', f32(.05)), 'bad')

    def test_range_schema_presets_native_boundary_and_legacy_detection(self):
        draft = common.config()
        self.assertFalse(nr_extended_range(draft['effects'][0]))
        draft['effects'][0]['extended_range'] = True
        self.assertEqual(apply_nr_preset(draft, nr_preset(draft)), draft)
        actual = effective_nr_skin(draft)
        self.assertNotIn('extended_range', actual['effects'][0])
        self.assertEqual(restore_nr_skin_memory(actual, draft), draft)
        draft['effects'][0]['extended_range'] = False
        self.assertNotIn('extended_range', validate_config(draft)['effects'][0])
        draft['effects'][0]['parameters']['pass3_intensity'] = 1.6
        self.assertTrue(nr_extended_range(draft['effects'][0]))
        for value in ('yes', 1, None):
            draft['effects'][0]['extended_range'] = value
            with self.assertRaises(ValueError):
                validate_config(draft)
        draft['effects'][0].update(name='ThirdParty/Filter', extended_range=True)
        with self.assertRaises(ValueError):
            validate_config(draft)

    def test_copy_obeys_selected_target_range(self):
        draft = common.config()
        values = from_realtime(draft, common.catalog(), 1)
        values['intensity'] = ('1.5', True)
        before = deepcopy(draft)
        with self.assertRaises(ValueError):
            to_realtime(values, draft, common.catalog())
        self.assertEqual(draft, before)
        draft['effects'][0]['extended_range'] = True
        _, target = to_realtime(values, draft, common.catalog())
        self.assertEqual(target['effects'][0]['parameters']['intensity'], 1.5)
        values['intensity'] = ('2.5', True)
        with self.assertRaises(ValueError):
            to_realtime(values, draft, common.catalog())

    def test_local_load_migrates_high_values_without_opening_for_invalid_data(self):
        self.assertFalse(app_settings.validate({})['enable_5x'])
        for raw in (1.25, '3.25', 5):
            saved = app_settings.validate({'skin_struct': raw, 'enable_5x': False})
            self.assertTrue(saved['enable_5x'])
            self.assertEqual(saved['skin_struct'], float(raw))
        for raw in ('bad', float('inf'), float('nan'), 6):
            self.assertFalse(app_settings.validate({'intensity': raw})['enable_5x'])


class RealtimeRangeTests(unittest.TestCase):
    setUp = inspector.RealtimeInspectorTests.setUp
    tearDown = inspector.RealtimeInspectorTests.tearDown
    event = inspector.RealtimeInspectorTests.event

    def prepare(self):
        data = common.catalog()[NR]
        for item in data['parameters']:
            if not item['integer']:
                item['step'] = f32(.05)
        self.event(dict(event='catalog', effects=[dict(data, name=NR)]))

    def test_default_range_and_native_format_with_unchanged_catalog(self):
        self.prepare()
        self.assertFalse(self.ui.extended_range.get())
        for name in NR_RANGE_PARAMETERS:
            row = self.ui.parameter_rows[name]
            self.assertEqual(row.slider.cget('to'), 1)
            self.assertEqual(row.descriptor['max'], 2)
            self.assertEqual(row.descriptor['step'], f32(.05))
            self.assertEqual(row.slider.cget('resolution'), .05)
            self.assertEqual(row.number_text.get(), '0.00' if 'skin' in name else '1.00')
        row = self.ui.parameter_rows['intensity']
        row.number_text.set('1.5'); row._commit_input()
        self.assertEqual(self.ui._editor_state, 'invalid')
        self.assertIn(i18n.tr('parameter.expand_hint'), row.feedback.cget('text'))
        self.ui.range_toggle.invoke()
        self.assertEqual(row.value(), 1.5)
        self.assertEqual(row.slider.cget('to'), 2)
        self.client.start.assert_not_called()

    def test_loaded_legacy_later_pass_and_disabled_memory_open_range(self):
        self.prepare()
        draft = common.config()
        draft['effects'][0]['parameters']['pass3_intensity'] = 1.6
        draft['effects'][0]['disabled_parameters'] = ['pass3_intensity']
        self.ui.apply_config(draft)
        self.assertTrue(self.ui.extended_range.get())
        row = self.ui.parameter_rows['pass3_intensity']
        self.assertEqual(row.value(), 1.6)
        self.assertFalse(row.enabled_variable.get())
        self.assertEqual(row.slider.cget('to'), 2)
        with mock.patch('dlss5tool.realtime_ui.messagebox.showwarning') as warning:
            self.ui.range_toggle.invoke()
        warning.assert_called_once()
        self.assertTrue(self.ui.extended_range.get())
        self.assertEqual(row.value(), 1.6)

    def test_range_only_toggle_does_not_apply_draft_or_restart(self):
        self.prepare()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._running_config = effective_nr_skin(self.ui.collect())
        self.ui._applied_effects = deepcopy(self.ui._running_config['effects'])
        self.ui._parameter_modes = {(0, name): 1 for name in self.ui.parameters}
        self.client.send.reset_mock()
        self.ui.parameters['intensity'][1].set('.6')
        self.ui.range_toggle.invoke()
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()
        self.assertTrue(self.store.data['session']['effects'][0]['extended_range'])
        self.assertEqual(self.store.data['session']['effects'][0]['parameters']['intensity'], 1)
        self.ui.range_toggle.invoke()
        self.assertNotIn('extended_range', self.store.data['session']['effects'][0])
        self.assertEqual(self.ui.parameters['intensity'][1].get(), '.6')

    def test_undo_reopens_required_range_and_preserves_high_values(self):
        self.prepare()
        self.ui.range_toggle.invoke()
        row = self.ui.parameter_rows['intensity']
        row.number_text.set('1.65'); row._commit_input()
        row.reset_button.invoke()
        self.ui.range_toggle.invoke()
        self.assertFalse(self.ui.extended_range.get())
        self.ui.undo_button.invoke()
        self.assertTrue(self.ui.extended_range.get())
        self.assertEqual(row.value(), 1.65)

    def test_bilingual_range_tooltips_toggle_and_number_fields_fit(self):
        self.prepare()
        for language in ('zh_CN', 'en_US'):
            i18n.set_language(language)
            self.ui._select_effect()
            for theme in ('dark', 'light'):
                self.ui.apply_theme(ui_theme.tokens(theme))
                self.root.geometry('800x600')
                self.root.update()
                for expanded in (True, False):
                    self.ui.range_toggle.invoke()
                    row = self.ui.parameter_rows['intensity']
                    hint = i18n.tr('parameter.range_hint', minimum='0.00', maximum='2.00' if expanded else '1.00')
                    self.assertIn(hint, row.help_text)
                    self.assertTrue(all(hint in tip.text for tip in row._tooltips))
                    self.assertLessEqual(row.enable_toggle.winfo_rootx() + row.enable_toggle.winfo_width(), row.field.winfo_rootx())
                    self.assertEqual(self.ui.range_toggle.winfo_width(), self.ui.range_toggle.winfo_reqwidth())


class LocalRangeTests(unittest.TestCase):
    setUp = workbench.WorkbenchUiTests.setUp
    tearDown = workbench.WorkbenchUiTests.tearDown

    def test_block_closure_without_clipping_and_do_not_rerender_for_range_only(self):
        app = self.app
        editor, settings = app._local_adjustments, app._settings
        with mock.patch.object(app, 'on_settings_change') as render:
            settings['v_enable_5x'].set(True)
            app._on_5x_toggle()
            render.assert_not_called()
        row = editor.rows['intensity']
        row.number_text.set('350%'); row._commit_input()
        row.enable_toggle.invoke()
        settings['v_enable_5x'].set(False)
        with mock.patch('dlss5tool.gui.messagebox.showwarning') as warning:
            app._on_5x_toggle()
        warning.assert_called_once()
        self.assertTrue(settings['v_enable_5x'].get())
        self.assertEqual(row.value(), 3.5)
        self.assertEqual(row.slider.cget('to'), 5)
        row.reset_button.invoke()
        settings['v_enable_5x'].set(False)
        app._on_5x_toggle()
        self.assertEqual(row.slider.cget('to'), 1)
        editor.undo()
        self.assertTrue(settings['v_enable_5x'].get())
        self.assertEqual(row.value(), 3.5)
        self.assertEqual(row.slider.cget('to'), 5)

    def test_invalid_text_prevents_closure_and_precision_is_not_lost(self):
        app = self.app
        app._settings['v_enable_5x'].set(True)
        app._on_5x_toggle()
        row = app._local_adjustments.rows['intensity']
        row.number_text.set('unfinished')
        app._settings['v_enable_5x'].set(False)
        with mock.patch('dlss5tool.gui.messagebox.showwarning'):
            app._on_5x_toggle()
        self.assertEqual(row.variable.get(), 'unfinished')
        self.assertTrue(app._settings['v_enable_5x'].get())
        row.number_text.set('.12345'); row._commit_input()
        app._settings['v_enable_5x'].set(False)
        app._on_5x_toggle()
        self.assertEqual(row.value(), .12345)
        self.assertEqual(row.number_text.get(), '0.12345')


if __name__ == '__main__':
    unittest.main()
