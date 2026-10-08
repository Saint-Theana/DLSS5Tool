"""Recipe/library/step-card regressions without a renderer or user-window capture."""
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime import NR, DEFAULT_CONFIG, PresetStore, portable_config
from dlss5tool.realtime_controls import EffectChainCards, InspectorChoice
from dlss5tool.realtime_effects import (RECIPES, PURPOSES, algorithm_group, grouped_algorithms,
                                      recipe_effects, new_effect, choice_issue, step_title, step_subtitle)
from dlss5tool.realtime_labels import effect_category
from tests import test_realtime_ui


FG = r'DLSSFG\DLSS_FrameGeneration'
ANIME = r'Anime4K\Anime4K_Restore_S'


def catalog():
    names = [NR, 'Lanczos', ANIME, r'Anime4K\Anime4K_Restore_L', FG,
             r'CuNNy\CuNNy-2x4C-NVL', r'CuNNy\CuNNy-4x4C-NVL', r'CuNNy\CuNNy-4x4C-NVL-DN',
             r'CAS\CAS', r'FXAA\FXAA_Medium', r'FXAA\FXAA_High', r'Sharpen\LumaSharpen',
             r'ThirdParty\One', r'ThirdParty\Two', 'FrameRate_Filter', r'XeSSFG\Missing']
    return {name: dict(name=name, available=name != r'XeSSFG\Missing', parameters=[]) for name in names}


class EffectWorkflowTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_recipes_explicit_steps_default_single_pass_and_keep_only_existing_fg(self):
        original = [new_effect(r'CAS\CAS'), dict(new_effect(FG), parameters={'quality': 2})]
        result = recipe_effects('enlarge', catalog(), original)
        self.assertEqual([e['name'] for e in result], [NR, 'Lanczos', FG])
        self.assertEqual(result[0]['parameters'], {'multiPass': 1})
        self.assertEqual(result[1]['scale'], [1.5, 1.5])
        self.assertEqual(result[2], original[1])
        result[2]['parameters']['quality'] = 4
        self.assertEqual(original[1]['parameters']['quality'], 2)
        self.assertEqual(recipe_effects('custom', {}, original), original)

    def test_missing_or_unavailable_recipe_does_not_substitute_backend(self):
        for available in (True, False):
            items = catalog()
            if available:
                del items['Lanczos']
            else:
                items['Lanczos']['available'] = False
            with self.assertRaises(ValueError):
                recipe_effects('enlarge', items, DEFAULT_CONFIG['effects'])

    def test_family_groups_preserve_distinct_operations_and_unknown_algorithms(self):
        self.assertEqual(algorithm_group(r'FXAA\FXAA_High'), algorithm_group(r'FXAA\FXAA_Medium'))
        for a, b in [(r'Anime4K\Anime4K_Restore_S', r'Anime4K\Anime4K_Upscale_S'),
                     (r'CuNNy\CuNNy-2x4C-NVL', r'CuNNy\CuNNy-2x4C-NVL-DN'),
                     (r'ThirdParty\One', r'ThirdParty\Two'),
                     (r'SMAA\SMAA_High', r'SMAA\SMAA_T2x_Experimental')]:
            self.assertNotEqual(algorithm_group(a), algorithm_group(b))

    def test_every_installed_native_id_remains_reachable_once(self):
        root = Path(__file__).resolve().parents[1] / 'runtime/realtime/effects'
        if not root.is_dir():
            self.skipTest('Optional realtime effects not installed')
        items = {str(p.relative_to(root).with_suffix('')): {} for p in root.rglob('*.hlsl')}
        groups = [group for purpose in PURPOSES for group in grouped_algorithms(items, purpose).values()]
        self.assertCountEqual([name for group in groups for name in group], items)
        self.assertLess(len(groups), len(items))

    def test_capability_and_overlap_warnings_are_not_compatibility_claims(self):
        self.assertTrue(choice_issue(r'XeSSFG\Missing', catalog(), [new_effect(NR)])[1])
        self.assertTrue(choice_issue(FG, catalog(), [new_effect(FG)])[1])
        self.assertFalse(choice_issue(FG, catalog(), [new_effect(FG)], replacing=0)[1])
        duplicate, blocked = choice_issue(r'CAS\CAS', catalog(), [new_effect(r'CAS\CAS')])
        self.assertFalse(blocked)
        self.assertIn(i18n.tr('realtime.workflow.duplicate'), duplicate)
        self.assertFalse(choice_issue(FG, catalog(), [new_effect('FrameRate_Filter')])[1])

    def test_scaling_sharpening_classification_and_bilingual_subtitles(self):
        self.assertEqual(effect_category(r'CAS\CAS_Scaling'), 'scale')
        self.assertEqual(effect_category(r'NIS\NVSharpen'), 'sharpen')
        for lang in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(lang)
            for name in catalog():
                for value in (step_title(name), step_subtitle(new_effect(name), catalog())):
                    self.assertNotIn('realtime.', value)

    def test_favorites_round_trip_is_local_and_runtime_setting_does_not_erase_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'presets.json'
            store = PresetStore(path)
            store.save_effect_favorites([NR, FG, NR])
            store.save_runtime_directory(directory)
            self.assertEqual(PresetStore(path).data['effect_favorites'], [NR, FG])
            self.assertNotIn('effect_favorites', portable_config(DEFAULT_CONFIG))
            before = path.read_bytes()
            for invalid in ('not a list', ['../effect'], [None], ['A'] * 257):
                with self.assertRaises(ValueError):
                    store.save_effect_favorites(invalid)
                self.assertEqual(path.read_bytes(), before)


class EffectWorkflowUiTests(unittest.TestCase):
    setUp = test_realtime_ui.RealtimeUiTests.setUp
    tearDown = test_realtime_ui.RealtimeUiTests.tearDown
    event = test_realtime_ui.RealtimeUiTests.event

    def load_catalog(self):
        self.event(dict(event='catalog', effects=list(catalog().values())))
        self.client.send.reset_mock()
        self.client.start.reset_mock()

    def choose_recipe(self, key):
        self.ui.recipe_choice.current(RECIPES.index(key))
        self.ui._preview_recipe()
        self.ui._use_recipe()

    def test_default_is_recipe_and_cards_with_full_catalog_collapsed(self):
        self.load_catalog()
        self.assertIsInstance(self.ui.chain, EffectChainCards)
        self.assertTrue(self.ui.add_section.collapsed)
        self.assertTrue(self.ui.library_section.collapsed)
        self.assertEqual(len(self.ui.recipe_choice.combo.cget('values')), 4)
        self.assertIn('DLSS NR', self.ui.chain.get(0))
        self.assertEqual(self.ui._guided_ids, [NR])
        self.assertEqual(set(self.ui._effect_ids), set(catalog()))
        self.client.start.assert_not_called()

    def test_recipe_and_undo_preserve_live_session_fg_and_other_settings(self):
        self.load_catalog()
        config = deepcopy(DEFAULT_CONFIG)
        config['effects'] = [new_effect(r'CAS\CAS'), dict(new_effect(FG), parameters={'mode': 2})]
        config['quality']['total'] = .7
        config['gpu_index'] = 2
        self.ui.apply_config(config)
        before = self.ui.collect()
        self.ui._active = self.ui._render_confirmed = True
        self.ui._running_config = deepcopy(before)
        self.ui._applied_effects = deepcopy(before['effects'])
        self.choose_recipe('enlarge')
        draft = self.ui.collect()
        self.assertEqual(draft['effects'][-1], before['effects'][-1])
        self.assertEqual({k: v for k, v in draft.items() if k != 'effects'}, {k: v for k, v in before.items() if k != 'effects'})
        self.assertEqual(self.ui._running_config, before)
        self.assertEqual(self.ui._editor_state, 'restart')
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()
        self.ui._undo_chain()
        self.assertEqual(self.ui.collect(), before)

    def test_recipe_preview_missing_and_custom_are_non_mutating(self):
        self.load_catalog()
        before = self.ui.collect()
        del self.ui.catalog['Lanczos']
        self.choose_recipe('enlarge')
        self.assertEqual(self.ui.collect(), before)
        self.choose_recipe('custom')
        self.assertFalse(self.ui.add_section.collapsed)
        self.assertTrue(self.ui.library_section.collapsed)
        self.assertEqual(self.ui.collect(), before)

    def test_guided_family_and_variants_retain_exact_native_name(self):
        self.load_catalog()
        self.ui.purpose_choice.current(PURPOSES.index('antialias'))
        self.ui._refresh_guided()
        self.assertEqual(len(self.ui.algorithm_choice.combo.cget('values')), 1)
        self.assertEqual(len(self.ui._guided_ids), 2)
        self.ui.variant_choice.current(self.ui._guided_ids.index(r'FXAA\FXAA_High'))
        self.ui._add_guided()
        self.assertEqual(self.ui.collect()['effects'][-1]['name'], r'FXAA\FXAA_High')
        self.assertEqual(self.ui.chain.curselection(), (1,))

    def test_step_variant_replaces_in_place_and_undo_preserves_parameters(self):
        self.load_catalog()
        effect = new_effect(r'FXAA\FXAA_High', 2)
        effect['parameters'] = {'customOldParameter': 1.7}
        self.ui.apply_config(dict(DEFAULT_CONFIG, effects=[effect]))
        variants = next(w for w in self.ui._parameter_widgets if isinstance(w, InspectorChoice) and len(w.combo.cget('values')) == 2)
        variants.current(1)
        variants.combo.event_generate('<<ComboboxSelected>>')
        self.root.update()
        result = self.ui.collect()['effects'][0]
        self.assertEqual(result['name'], r'FXAA\FXAA_Medium')
        self.assertEqual(result['parameters'], {})
        self.assertEqual(result['scale'], [2, 2])
        self.ui._undo_chain()
        self.assertEqual(self.ui.collect()['effects'][0], effect)

    def test_replacement_cancel_and_card_keyboard_keep_editor_selection(self):
        self.load_catalog()
        self.ui.apply_config(dict(DEFAULT_CONFIG, effects=[new_effect(NR), new_effect('Lanczos')]))
        self.ui.chain._nudge(1)
        self.assertEqual(self.ui.chain.curselection(), (1,))
        before = self.ui.collect()
        self.ui._choose_replacement()
        self.assertEqual(self.ui._replace_index, 1)
        self.ui._cancel_replacement()
        self.assertIsNone(self.ui._replace_index)
        self.assertEqual(self.ui.collect(), before)

    def test_selecting_another_card_cancels_old_replacement_target(self):
        self.load_catalog()
        self.ui.apply_config(dict(DEFAULT_CONFIG, effects=[new_effect(NR), new_effect('Lanczos')]))
        self.ui._choose_replacement()
        self.assertEqual(self.ui._replace_index, 0)
        self.ui.chain._nudge(1)
        self.assertIsNone(self.ui._replace_index)

    def test_reselecting_fg_preserves_custom_order_and_parameters(self):
        self.load_catalog()
        effects = [dict(new_effect(FG), parameters={'mode': 1}), new_effect('Lanczos')]
        self.ui.apply_config(dict(DEFAULT_CONFIG, effects=effects))
        before = self.ui.collect()
        self.ui._set_fluency()
        self.assertEqual(self.ui.collect(), before)
        self.assertIsNone(self.ui._chain_undo)

    def test_fg_is_independent_draft_only_and_rate_filter_is_not_removed(self):
        self.load_catalog()
        self.ui.apply_config(dict(DEFAULT_CONFIG, effects=[new_effect(NR), new_effect('FrameRate_Filter')]))
        self.ui.fg_choice.current(self.ui._fg_ids.index(FG) + 1)
        self.ui._set_fluency()
        self.assertEqual([e['name'] for e in self.ui.collect()['effects']], [NR, 'FrameRate_Filter', FG])
        self.ui.fg_choice.current(0)
        self.ui._set_fluency()
        self.assertEqual([e['name'] for e in self.ui.collect()['effects']], [NR, 'FrameRate_Filter'])
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()

    def test_unavailable_library_and_duplicate_fg_cannot_be_added(self):
        self.load_catalog()
        self.ui.effect_search.set('XeSSFG')
        before = self.ui.collect()
        self.ui._add()
        self.assertEqual(self.ui.collect(), before)
        self.ui.effect_search.set('DLSSFG')
        self.ui._add()
        after = self.ui.collect()
        self.ui._add()
        self.assertEqual(self.ui.collect(), after)
        self.assertEqual(len(after['effects']), 2)

    def test_library_favorites_and_search_do_not_change_draft(self):
        self.load_catalog()
        before = self.ui.collect()
        self.ui.effect_search.set('Lanczos')
        self.ui._toggle_favorite()
        self.ui.effect_search.set('')
        self.ui.favorites_only.set(True)
        self.ui._filter_effects()
        self.assertEqual(self.ui._effect_ids, ['Lanczos'])
        self.assertEqual(PresetStore(self.store.path).data['effect_favorites'], ['Lanczos'])
        self.ui._toggle_favorite()
        self.assertEqual(self.ui._effect_ids, [])
        self.assertEqual(self.ui.collect(), before)

    def test_invalid_draft_not_discarded_by_recipe_or_step_change(self):
        self.load_catalog()
        self.ui.scale_controls[2].set('unfinished')
        before = deepcopy(self.ui.config['effects'])
        self.choose_recipe('anime')
        self.assertEqual(self.ui.config['effects'], before)
        self.assertEqual(self.ui.scale_controls[2].get(), 'unfinished')
        self.client.start.assert_not_called()

    def test_card_actions_and_recipe_controls_fit_both_themes_at_minimum_size(self):
        self.load_catalog()
        self.ui.workflow_section.toggle()
        self.ui.fluency_section.toggle()
        for theme in ('dark', 'light'):
            ui = ui_theme.tokens(theme)
            ui_theme.apply_ttk(self.root, ui)
            self.ui.apply_theme(ui)
            for size in ('1000x680', '1280x800'):
                self.root.geometry(size)
                self.root.update()
                widgets = [self.ui.recipe_button, self.ui.recipe_choice, self.ui.fg_choice]
                widgets += self.ui.chain._cards[0][4]
                for widget in widgets:
                    pane = self.ui.stage if widget in (self.ui.recipe_button, self.ui.recipe_choice) else self.ui.inspector
                    self.assertGreater(widget.winfo_width(), 15)
                    self.assertGreaterEqual(widget.winfo_rootx(), pane.winfo_rootx())
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), pane.winfo_rootx() + pane.winfo_width())


if __name__ == '__main__':
    unittest.main()
