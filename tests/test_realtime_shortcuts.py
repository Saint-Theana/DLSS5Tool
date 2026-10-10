"""Shortcut parsing, atomic preferences, rollback and UI: no real key injection."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime import DEFAULT_CONFIG, PresetStore, RealtimeClient
from dlss5tool.realtime_shortcuts import DEFAULT_HOTKEYS, parse_hotkey, validate_hotkeys, native_hotkeys
from tests import test_realtime_inspector


CUSTOM = dict(DEFAULT_HOTKEYS, stop='Ctrl+Shift+F10', compare='Ctrl+Shift+C')


class ShortcutTests(unittest.TestCase):
    def test_canonical_and_native_codes(self):
        self.assertEqual(parse_hotkey(' shift + ctrl + f10 '), ('Ctrl+Shift+F10', 6, 121))
        self.assertEqual(native_hotkeys(CUSTOM)['compare'], dict(label='Ctrl+Shift+C', modifiers=6, key=67))

    def test_invalid_reserved_duplicates_and_unknown_actions(self):
        for value in (None, '', 'F10', 'Shift+A', 'Ctrl+Ctrl+A', 'Ctrl+F12', 'Win+A',
                      'Alt+F4', 'Alt+Shift+F4', 'Ctrl+Space', 'Ctrl+F25', 'Ctrl+Alt+Delete'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_hotkey(value)
        for value in (dict(CUSTOM, compare=CUSTOM['stop']), dict(CUSTOM, other='Ctrl+K'), {}):
            with self.assertRaises(ValueError):
                validate_hotkeys(value)

    def test_local_persistence_preserves_session_presets_and_runtime_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'presets.json'
            store = PresetStore(path)
            store.save_session(DEFAULT_CONFIG)
            store.save('Keep', DEFAULT_CONFIG)
            store.save_runtime_directory(folder)
            store.save_hotkeys(CUSTOM)
            store.save_runtime_directory(folder)
            loaded = PresetStore(path)
            self.assertEqual(loaded.data['local']['hotkeys'], CUSTOM)
            self.assertEqual(loaded.data['session'], DEFAULT_CONFIG)
            self.assertIn('Keep', loaded.data['presets'])
            before = path.read_bytes()
            with self.assertRaises(OSError), mock.patch('dlss5tool.realtime.os.replace', side_effect=OSError('fixture')):
                loaded.save_hotkeys(DEFAULT_HOTKEYS)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(loaded.data['local']['hotkeys'], CUSTOM)

    def configure(self, fail=False, legacy=False):
        client = RealtimeClient()
        def launch():
            bindings = dict(client.hotkeys)
            client._handshake_event = dict(event='ready', hotkeys={k: not (fail and bindings == CUSTOM and k == 'stop') for k in bindings})
            if not legacy:
                client._handshake_event['hotkey_bindings'] = bindings
            client._handshake.set()
        with mock.patch.object(client, 'close'), mock.patch.object(client, 'launch', side_effect=launch):
            if fail or legacy:
                with self.assertRaises(RuntimeError):
                    client.configure_hotkeys(CUSTOM)
                self.assertEqual(client.hotkeys, DEFAULT_HOTKEYS)
            else:
                client.configure_hotkeys(CUSTOM)
                self.assertEqual(client.hotkeys, CUSTOM)

    def test_success_applies_all_bindings(self):
        self.configure()

    def test_occupied_stop_rolls_back(self):
        self.configure(fail=True)

    def test_old_host_cannot_report_custom_shortcuts_as_working(self):
        self.configure(legacy=True)

    def test_safety_factory_receives_custom_stop(self):
        from dlss5tool.realtime_safety import RealtimeSafety
        platform = mock.Mock(registered=True)
        platform.pressed.return_value = False
        with mock.patch('dlss5tool.realtime_safety.WindowsStopControl', return_value=platform) as factory:
            safety = RealtimeSafety(lambda: None, lambda _: None, hotkey=CUSTOM['stop'])
            try:
                safety.start()
                self.assertTrue(safety.registered)
                factory.assert_called_once_with(CUSTOM['stop'])
            finally:
                safety.close()


class ShortcutUiTests(unittest.TestCase):
    setUp = test_realtime_inspector.RealtimeInspectorTests.setUp
    tearDown = test_realtime_inspector.RealtimeInspectorTests.tearDown
    event = test_realtime_inspector.RealtimeInspectorTests.event
    catalog = test_realtime_inspector.RealtimeInspectorTests.catalog

    def test_reset_is_confirmed_scoped_and_undoable(self):
        self.catalog()
        self.root.update_idletasks()
        self.assertEqual(self.ui.parameter_more.cget('icon'), 'more')
        self.assertTrue(self.ui.parameter_more._icon_only)
        self.assertLessEqual(self.ui.parameter_more.winfo_width(), ui_theme.scale_px(self.root, 40))
        self.ui.parameters['intensity'][1].set('1.45')
        self.ui._parameter_committed()
        before = deepcopy(self.ui.collect())
        self.assertTrue(all(row.reset_button is None for row in self.ui.parameter_rows.values()))
        for row in self.ui.parameter_rows.values():
            self.assertNotIn(i18n.tr('realtime.editor.default', value=row.descriptor['default']), row.help_text)
        with mock.patch('dlss5tool.realtime_ui.messagebox.askokcancel', return_value=False):
            self.ui._reset_current_effect()
        self.assertEqual(self.ui.collect(), before)
        with mock.patch('dlss5tool.realtime_ui.messagebox.askokcancel', return_value=True):
            self.ui._reset_current_effect()
        self.assertEqual(self.ui.parameter_rows['intensity'].value(), 1)
        self.assertEqual(self.ui.collect()['quality'], before['quality'])
        self.ui.undo_button.invoke()
        self.assertEqual(self.ui.collect(), before)

    def test_dynamic_ready_labels_and_dialog(self):
        self.event(dict(event='ready', independent_stop=True, hotkey_bindings=CUSTOM,
                        hotkeys={k: True for k in CUSTOM}))
        self.assertIn(CUSTOM['stop'], self.ui.stop_hint.get())
        self.ui._open_shortcuts()
        self.root.update_idletasks()
        dialog = self.ui._shortcut_dialog
        self.assertIn(CUSTOM['compare'], dialog.states['compare'].get())
        dialog.values['stop'].set('Ctrl+F12')
        dialog.save()
        self.assertEqual(dialog.message.get(), i18n.tr('realtime.shortcuts.invalid'))

    def test_running_disallows_rebinding(self):
        self.ui._active = True
        self.assertFalse(self.ui._change_shortcuts(CUSTOM))
        self.client.configure_hotkeys.assert_not_called()
        self.ui._active = False

    def test_verified_binding_is_persisted_on_ui_thread(self):
        self.ui._shortcut_changing = True
        self.ui._shortcut_persist = True
        self.client.hotkeys = dict(CUSTOM)
        self.ui._shortcut_result.put((CUSTOM, None))
        self.assertTrue(self.ui._finish_shortcuts())
        self.assertEqual(PresetStore(self.store.path).data['local']['hotkeys'], CUSTOM)
        self.assertFalse(self.ui._shortcut_changing)

    def test_failed_registration_never_persists_candidate(self):
        self.store.save_hotkeys(DEFAULT_HOTKEYS)
        self.ui._shortcut_changing = True
        self.ui._shortcut_persist = True
        self.ui._shortcut_result.put((CUSTOM, 'fixture conflict'))
        self.assertTrue(self.ui._finish_shortcuts())
        self.assertEqual(PresetStore(self.store.path).data['local']['hotkeys'], DEFAULT_HOTKEYS)
        self.assertIn('fixture conflict', self.ui.status.get())

    def test_disk_failure_requests_rollback_without_overwriting_settings(self):
        self.store.save_hotkeys(DEFAULT_HOTKEYS)
        self.ui._shortcut_changing = True
        self.ui._shortcut_persist = True
        self.ui._shortcut_previous = dict(DEFAULT_HOTKEYS)
        self.client.hotkeys = dict(CUSTOM)
        self.ui._shortcut_result.put((CUSTOM, None))
        with mock.patch.object(self.store, 'save_hotkeys', side_effect=OSError('disk fixture')), \
                mock.patch.object(self.ui, '_change_shortcuts') as rollback:
            self.assertFalse(self.ui._finish_shortcuts())
            rollback.assert_called_once_with(DEFAULT_HOTKEYS, persist=False)
        self.assertEqual(PresetStore(self.store.path).data['local']['hotkeys'], DEFAULT_HOTKEYS)

    def test_reopen_restores_saved_bindings_without_touching_parameter_memory(self):
        self.store.save_hotkeys(CUSTOM)
        self.ui.close()
        from dlss5tool.realtime_ui import RealtimeWorkspace
        with mock.patch('dlss5tool.realtime_ui.RealtimeClient', return_value=self.client), \
                mock.patch('dlss5tool.realtime_ui.PresetStore', return_value=PresetStore(self.store.path)), \
                mock.patch('dlss5tool.realtime_ui.list_windows', return_value=[]):
            self.ui = RealtimeWorkspace(self.root)
        self.assertEqual(self.client.hotkeys, CUSTOM)

    def test_dialog_duplicate_and_running_state_do_not_submit(self):
        self.ui._open_shortcuts()
        dialog = self.ui._shortcut_dialog
        dialog.values['compare'].set(dialog.values['stop'].get())
        dialog.save()
        self.assertEqual(dialog.message.get(), i18n.tr('realtime.shortcuts.duplicate'))
        self.ui._active = True
        dialog.save()
        self.assertEqual(dialog.apply.cget('state'), 'disabled')
        self.client.configure_hotkeys.assert_not_called()
        self.ui._active = False

    def test_duplicate_catalog_after_hotkey_change_preserves_draft_and_undo(self):
        self.catalog()
        row = self.ui.parameter_rows['intensity']
        row.variable.set('1.25')
        row.commit()
        undo = deepcopy(self.ui._undo_parameters)
        self.event(dict(event='catalog', effects=list(self.ui.catalog.values())))
        self.assertIs(self.ui.parameter_rows['intensity'], row)
        self.assertEqual(row.value(), 1.25)
        self.assertEqual(self.ui._undo_parameters, undo)


if __name__ == '__main__':
    unittest.main()
