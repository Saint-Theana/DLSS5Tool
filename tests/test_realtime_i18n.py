import ast
from pathlib import Path
import re
import unittest

from dlss5tool import i18n
from dlss5tool.realtime_labels import (effect_key, effect_text, parameter_label, EFFECT_CATEGORIES,
                                     effect_category, effect_description)


class RealtimeLocalizationTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_realtime_ui_and_caption_have_catalogued_keys_and_no_hardcoded_chinese(self):
        root = Path(__file__).resolve().parents[1]
        keys = set()
        for file in ('realtime_shortcuts.py', 'realtime_shortcuts_ui.py', 'realtime_ui.py', 'realtime_source_preview.py', 'realtime_snapshot.py', 'realtime_controls.py', 'caption_button.py', 'realtime_labels.py', 'realtime.py', 'realtime_logs.py', 'realtime_readiness.py', 'realtime_effects.py'):
            tree = ast.parse((root / 'dlss5tool' / file).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertFalse(re.search('[\u4e00-\u9fff]', node.value), (file, node.value))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr' and node.args and isinstance(node.args[0], ast.Constant):
                    keys.add(node.args[0].value)
        for lang in i18n.SUPPORTED_LANGUAGES:
            self.assertFalse(keys - i18n.catalog_keys(lang))

    def test_unknown_third_party_labels_remain_readable(self):
        self.assertEqual(effect_text('Custom future parameter'), 'Custom future parameter')
        self.assertEqual(effect_text(r'Custom\nlabel'), 'Custom\nlabel')
        self.assertNotEqual(effect_key('Optical Flow Accumulation'), effect_key('Optical Flow Accumulation+'))

    def test_user_log_summaries_and_known_native_errors_are_bilingual(self):
        from dlss5tool.realtime_logs import event_summary, native_message, _NATIVE_ERRORS, _NATIVE_LOCALIZED
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            messages = [event_summary({'event': 'ready', 'hotkeys': {'stop': False, 'compare': True}}),
                        event_summary({'event': 'devices', 'monitors': [], 'adapters': []}),
                        event_summary({'event': 'catalog', 'effects': []}),
                        native_message({'event': 'error', 'code': 17})]
            for source in _NATIVE_ERRORS:
                messages.append(native_message({'event': 'error', 'message': source}))
            for key in _NATIVE_LOCALIZED:
                messages.append(native_message({'event': 'error', 'message': i18n.tr_for('zh_CN', 'realtime.native.' + key)}))
            for message in messages:
                self.assertNotIn('realtime.', message)
                self.assertEqual(bool(re.search('[\u4e00-\u9fff]', message)), language == 'zh_CN')
            for kind in ('ack', 'status', 'gpu_load', 'settings', 'future_protocol_event'):
                self.assertIsNone(event_summary({'event': kind, 'ok': True}))
            unknown = native_message({'event': 'error', 'message': 'Future failure 0xBAD', 'hresult': -123})
            self.assertIn('Future failure 0xBAD', unknown)
            self.assertIn('-123', unknown)

    def test_dependency_messages_exist_in_both_languages(self):
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            for suffix, args in [('resolution', {}), ('flow', {'method': 'NVIDIA'}), ('pass', {'count': 3})]:
                message = i18n.tr('realtime.editor.requires_' + suffix, **args)
                self.assertNotIn('realtime.editor.', message)
                self.assertNotIn('{', message)

    def test_installed_effects_have_localized_categories_and_help(self):
        root = Path(__file__).resolve().parents[1] / 'runtime/realtime/effects'
        names = [str(path.relative_to(root).with_suffix('')) for path in root.rglob('*.hlsl')]
        names += ['ThirdParty\\Unknown', 'DLSS\\DLSS_SR', 'DLSSFG\\DLSS_FrameGeneration']
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            for key in EFFECT_CATEGORIES:
                self.assertIn('realtime.effects.category.' + key, i18n.catalog_keys(language))
            for name in names:
                self.assertIn(effect_category(name), EFFECT_CATEGORIES)
                for brief in (False, True):
                    help_text = effect_description(name, brief=brief)
                    self.assertNotIn('realtime.effects.', help_text)
                    self.assertEqual(bool(re.search('[\u4e00-\u9fff]', help_text)), language == 'zh_CN')

    def test_core_metadata_translation_and_backend_disambiguation(self):
        i18n.set_language('zh_CN')
        self.assertEqual(effect_text('Reflection / Glow Control'), '反射／辉光控制')
        self.assertEqual(effect_text('Local Tone Strength'), i18n.tr('label.local_tone'))
        self.assertEqual(effect_text('Highest Quality (Very High Cost)'), '最高画质（极高开销）')
        self.assertEqual(effect_text('DLSSNR · Pass 2'), 'DLSSNR · 第 2 遍')
        self.assertEqual(parameter_label({'name': 'amdOpticalFlowMode', 'label': 'OF Quality'}), 'AMD 光流质量')
        i18n.set_language('en_US')
        self.assertEqual(effect_text('Local Tone Strength'), i18n.tr('label.local_tone'))

    def test_nr_terms_match_local_media_and_pass_help_is_bilingual(self):
        from dlss5tool.realtime_labels import parameter_hint
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            for source, key in [('NR Intensity', 'strength'), ('Local Tone Strength', 'local_tone'),
                                ('Local Structure Strength', 'local_structure'),
                                (r'NR Style\n(0 Default, 1 Natural, 2 Cinematic)', 'style')]:
                self.assertEqual(effect_text(source), i18n.tr('label.' + key))
            for prefix in ('', 'pass2_', 'pass3_'):
                for name in ('style', 'intensity', 'localToneStrength', 'localStructureStrength',
                             'skinStructureStrength', 'useAutoMask', 'uiCorrection', 'residualMultiplier'):
                    hint = parameter_hint(prefix + name)
                    self.assertTrue(hint)
                    self.assertNotIn('realtime.', hint)
                    self.assertEqual(bool(re.search('[\u4e00-\u9fff]', hint)), language == 'zh_CN')

    def test_all_installed_effect_labels_groups_and_options_are_catalogued(self):
        effects = Path(__file__).resolve().parents[1] / 'runtime/realtime/effects'
        if not effects.is_dir():
            self.skipTest('Optional realtime runtime is not installed')
        count = 0
        for file in effects.rglob('*.hlsl'):
            for line in file.read_text(encoding='utf-8-sig').splitlines():
                match = re.match(r'//!\s*(LABEL|GROUP|OPTION)\s+(.+)', line)
                if match:
                    text = match[2].split(' ', 1)[1] if match[1] == 'OPTION' else match[2]
                    for lang in i18n.SUPPORTED_LANGUAGES:
                        self.assertIn(effect_key(text), i18n.catalog_keys(lang), (file, text))
                    count += 1
        self.assertGreater(count, 100)

    def test_configuration_errors_format_fields_in_both_languages(self):
        from dlss5tool.realtime import validate_config
        for language in ('zh_CN', 'en_US'):
            i18n.set_language(language)
            for config in ({'windowed': 1}, {'gpu_index': 1.5}, {'quality': {'total': float('inf')}}):
                with self.assertRaises(ValueError) as error:
                    validate_config(config)
                message = str(error.exception)
                self.assertNotIn('{field}', message)
                self.assertNotIn('realtime.error.', message)
                self.assertEqual(bool(re.search('[\u4e00-\u9fff]', message)), language == 'zh_CN')

    def test_ui_correction_is_explicitly_experimental(self):
        from dlss5tool.realtime_labels import parameter_hint
        for language, marker, caveat in (('zh_CN', '实验性', '尚未验证'),
                                          ('en_US', 'experimental', 'unverified')):
            i18n.set_language(language)
            self.assertIn(marker, effect_text('NR UI Correction'))
            for prefix in ('', 'pass2_', 'pass3_'):
                self.assertIn(caveat, parameter_hint(prefix + 'uiCorrection'))


if __name__ == '__main__':
    unittest.main()
