"""Discoverability and navigation regressions; mock engine, no screen capture."""
from copy import deepcopy
import unittest

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime_controls import InspectorGroup
from tests import test_realtime_inspector as inspector


class RealtimeWorkspaceTests(unittest.TestCase):
    setUp = inspector.RealtimeInspectorTests.setUp
    tearDown = inspector.RealtimeInspectorTests.tearDown
    catalog = inspector.RealtimeInspectorTests.catalog
    dependencies = inspector.RealtimeInspectorTests.dependencies
    running = inspector.RealtimeInspectorTests.running
    event = inspector.RealtimeInspectorTests.event

    def test_library_shortcut_is_visible_from_every_page_and_keeps_unfinished_draft(self):
        self.catalog()
        ui = self.ui
        row = ui.parameter_rows['intensity']
        row.number_text.set('unfinished')
        self.client.send.reset_mock()
        for page in ('effects', 'display', 'runtime'):
            ui._focus_page(page)
            self.root.update()
            self.assertTrue(ui.library_button.winfo_ismapped())
            ui.library_button.invoke()
            self.root.update()
            self.assertIs(ui.tabs._current, ui._pages['workflow'].master.master)
            self.assertTrue(ui.search_entry.winfo_ismapped())
            self.assertIs(ui.parameter_rows['intensity'], row)
            self.assertEqual(row.number_text.get(), 'unfinished')
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()

    def test_all_catalog_entries_and_unavailable_effects_remain_searchable(self):
        self.catalog()
        ui = self.ui
        ui.catalog['ThirdParty\\Unavailable'] = dict(name='ThirdParty\\Unavailable', available=False, parameters=[])
        ui._filter_effects()
        before = deepcopy(ui.collect())
        self.assertEqual(ui.library_button.cget('text'), i18n.tr('realtime.workspace.library_count', count=3))
        ui.effect_search.set('Unavailable')
        self.assertEqual(ui._effect_ids, ['ThirdParty\\Unavailable'])
        self.assertEqual(ui.library_add.cget('state'), 'disabled')
        ui.favorites_only.set(True)
        ui._filter_effects()
        self.assertEqual(ui._effect_ids, [])
        ui.reset_filters_button.invoke()
        self.assertEqual(set(ui._effect_ids), set(ui.catalog))
        self.assertFalse(ui.favorites_only.get())
        self.assertEqual(ui.effect_search.get(), '')
        self.assertEqual(ui.collect(), before)

    def test_replacement_is_explicit_and_cancel_does_not_change_chain(self):
        self.catalog()
        ui = self.ui
        before = deepcopy(ui.collect())
        ui.effect_search.set('no match')
        ui._choose_replacement()
        self.root.update()
        self.assertEqual(ui._replace_index, 0)
        self.assertTrue(ui.library_cancel.winfo_ismapped())
        self.assertIn(i18n.tr('realtime.workflow.replacing', index=1), ui.replacement_status.get())
        self.assertEqual(ui._effect_ids[ui.effect_choice.current()], before['effects'][0]['name'])
        ui.library_cancel.invoke()
        self.assertIsNone(ui._replace_index)
        self.assertEqual(ui.collect(), before)
        self.client.start.assert_not_called()

    def test_parameter_groups_are_single_level_and_keep_expansion_when_rebuilt(self):
        self.dependencies()
        ui = self.ui
        for section in ui.parameter_sections.values():
            self.assertIs(section.master, ui.parameter_frame)
        ui.parameter_sections['color'].toggle()
        ui._select_effect()
        self.assertFalse(ui.parameter_sections['color'].collapsed)
        self.assertTrue(ui.parameter_sections['advanced'].collapsed)
        self.assertIsInstance(ui.workflow_section, InspectorGroup)
        self.assertIsInstance(ui.library_section, InspectorGroup)

    def test_pass_headers_are_visible_not_covered_and_wrap_in_both_languages(self):
        for lang in ('zh_CN', 'en_US'):
            i18n.set_language(lang)
            self.dependencies()
            self.ui._set_inspector_width(360)
            self.root.update()
            for theme in ('light', 'dark'):
                ui_theme.apply_ttk(self.root, ui_theme.tokens(theme))
                self.ui.apply_theme(ui_theme.tokens(theme))
                for count in (2, 3):
                    section = self.ui.parameter_sections['pass' + str(count)]
                    self.ui._focus_page('effects', section)
                    self.root.update()
                    header = section._header
                    toggle = self.ui.pass_toggles[count][1]
                    self.assertTrue(header.winfo_ismapped())
                    self.assertEqual(toggle.cget('text'), i18n.tr('realtime.editor.enable_pass'))
                    self.assertIs(self.root.winfo_containing(header.winfo_rootx() + 12,
                                  header.winfo_rooty() + header.winfo_height() // 2), header)
                    text_item = next(item for item in header.find_all() if header.type(item) == 'text')
                    bounds = header.bbox(text_item)
                    self.assertLessEqual(bounds[2], header.winfo_width())
                    self.assertLessEqual(bounds[3], header.winfo_height())
                    self.assertLessEqual(header.winfo_rootx()+header.winfo_width(), toggle.winfo_rootx())
            self.assertEqual(self.ui.parameter_rows['multiPass'].value(), 1)
        self.client.start.assert_not_called()

    def test_session_rail_stays_compact_at_wide_sizes(self):
        for size in ('1000x680', '1600x1000'):
            self.root.geometry(size)
            self.ui._splitter_reset()
            self.root.update()
            self.assertGreaterEqual(self.ui.stage.winfo_width(), 320)
            self.assertLessEqual(self.ui.stage.winfo_width(), 400)
            self.assertGreater(self.ui.inspector.winfo_width(), self.ui.stage.winfo_width())

    def test_fluency_and_raw_device_fields_route_to_their_actual_pages(self):
        self.catalog()
        ui = self.ui
        for widget, route in ((ui.fg_choice, 'display'), (ui.controls['sync_mode'][0], 'display'),
                              (ui._display_targets['monitor_id'], 'runtime'),
                              (ui._display_targets['gpu_index'], 'runtime'), (ui.regions, 'runtime')):
            ui._focus_page('effects', widget)
            self.root.update()
            self.assertIs(ui.tabs._current, ui._pages[route].master.master)
            self.assertTrue(widget.winfo_ismapped())
        self.client.start.assert_not_called()

    def test_device_pickers_reflect_saved_ids_without_replacing_them_on_discovery(self):
        ui = self.ui
        config = ui.collect()
        config.update(gpu_index=7, monitor_mode=3, monitor_id='fixture-monitor')
        ui.apply_config(config)
        self.event(dict(event='devices', monitors=[dict(id='fixture-monitor', name='Fixture', rect=[0, 0, 1920, 1080])],
                        adapters=[dict(index=7, name='Fixture GPU')]))
        self.assertEqual(ui.monitor_picker.current(), 0)
        self.assertEqual(ui.gpu_picker.current(), 1)
        self.assertEqual(ui.collect()['gpu_index'], 7)
        self.event(dict(event='devices', monitors=[], adapters=[]))
        self.assertIn('7', ui.gpu_picker.get())
        self.assertIn('fixture-monitor', ui.monitor_picker.get())
        self.assertEqual(ui.collect()['gpu_index'], 7)

    def test_bound_preset_is_visible_outside_collapsed_presets(self):
        ui = self.ui
        self.store.data['presets']['Fixture preset'] = ui.collect()
        self.store.data['applications']['fixture.exe'] = 'Fixture preset'
        ui.windows = [dict(hwnd=1, pid=2, application='fixture.exe', title='Fixture')]
        ui.target.configure(values=['Fixture'])
        ui.target.current(0)
        ui._notify_session()
        self.assertTrue(ui.presets_section.collapsed)
        self.assertEqual(ui.preset_binding_label.winfo_manager(), 'pack')
        self.assertIn('Fixture preset', ui.preset_binding.get())
        self.client.start.assert_not_called()

    def test_tab_keyboard_navigation_and_region_summary_are_non_mutating(self):
        self.catalog()
        ui = self.ui
        ui.regions.insert('1.0', '0 0 .2 .2\n.8 .8 1 1')
        ui._draw_regions()
        self.assertIn(i18n.tr('realtime.workspace.regions', count=2), ui.source_preview.message.get())
        before = deepcopy(ui.collect())
        self.client.send.reset_mock()
        self.assertTrue(ui.tabs._header.bind('<Left>'))
        self.assertTrue(ui.tabs._header.bind('<Right>'))
        for index in (1, 2, 3, 0):
            self.assertEqual(ui._switch_editor_tab(1), 'break')
            self.assertIs(ui.tabs._current, ui.tabs._tabs[index]['frame'])
        self.assertEqual(ui.collect(), before)
        self.client.send.assert_not_called()
        self.client.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
