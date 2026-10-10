"""Startup restores UI preferences without starting capture or changing theme."""
import os
from pathlib import Path
import queue
import tempfile
import tkinter as tk
import traceback
import unittest
from unittest import mock

from dlss5tool import app_settings, gui
from dlss5tool.realtime import PresetStore


class WorkbenchSettingsTests(unittest.TestCase):
    def test_log_defaults_open_and_validates_saved_preference(self):
        self.assertTrue(app_settings.validate({})['ui_log_open'])
        for value in (None, '', 'false', [], {}):
            self.assertTrue(app_settings.validate({'ui_log_open': value})['ui_log_open'])
        for value in (False, True):
            self.assertIs(app_settings.startup_settings({'ui_log_open': value})['ui_log_open'], value)

    def test_legacy_settings_keep_theme_and_default_to_local(self):
        for theme in ('light', 'dark'):
            settings = app_settings.startup_settings({'ui_theme': theme})
            self.assertEqual(settings['workbench_mode'], 'local')
            self.assertEqual(settings['ui_theme'], theme)

    def test_invalid_modes_fall_back_safely(self):
        for mode in (None, '', 'bad', 'enhancement', 1, [], {}):
            with self.subTest(mode=mode):
                self.assertEqual(app_settings.validate({'workbench_mode': mode})['workbench_mode'], 'local')
        self.assertEqual(app_settings.validate({'workbench_mode': ' REALTIME '})['workbench_mode'], 'realtime')

    def test_mode_and_theme_roundtrip_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'settings.json')
            for mode in ('local', 'realtime'):
                for theme in ('light', 'dark'):
                    with self.subTest(mode=mode, theme=theme):
                        app_settings.save({'workbench_mode': mode, 'ui_theme': theme}, path)
                        settings = app_settings.startup_settings(app_settings.load(path))
                        self.assertEqual((settings['workbench_mode'], settings['ui_theme']), (mode, theme))


class WorkbenchStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        env = mock.patch.dict(os.environ, {
            'DLSS5TOOL_SETTINGS_PATH': str(directory / 'settings.json'),
            'DLSS5TOOL_QUEUE_PATH': str(directory / 'queue.json'),
            'DLSS5TOOL_DISABLE_UPDATE_CHECK': '1',
        })
        env.start()
        self.addCleanup(env.stop)
        self.client = mock.Mock(events=queue.Queue(), generation=1, settings={})
        self.client.send.return_value = 1
        self.client.start.return_value = 2
        # Install before App construction: restoring realtime creates its UI.
        for name, value in [('RealtimeClient', self.client),
                            ('PresetStore', PresetStore(directory / 'realtime.json')),
                            ('list_windows', [])]:
            patch = mock.patch('dlss5tool.realtime_ui.' + name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        self.app = None
        self.errors = []

    def tearDown(self):
        self.close_app()
        self.assertEqual(self.errors, [])

    def open_app(self, *, visible=False):
        self.root = tk.Tk()
        if not visible:
            self.root.withdraw()
        self.root.report_callback_exception = lambda *error: self.errors.append(''.join(traceback.format_exception(*error)))
        self.app = gui.App(self.root)
        # Finish one-time startup layout before simulating user edits/close.
        # update_idletasks does not consume the 300 ms preference-save timer.
        self.root.update_idletasks()
        return self.app

    def close_app(self):
        if self.app is not None:
            app, self.app = self.app, None
            app._on_close()

    def test_log_choice_survives_restart_in_both_modes(self):
        for mode in ('local', 'realtime'):
            with self.subTest(mode=mode):
                app_settings.save({'workbench_mode': mode})
                app = self.open_app()
                panel = app.log if mode == 'local' else app._realtime_workspace.log
                self.assertTrue(app._log_open)
                self.assertEqual(panel.frame.winfo_manager(), 'pack')
                app.toggle_log_panel()
                self.assertIsNotNone(app._settings_save_after)
                self.assertFalse(app._collect_persisted_settings()['ui_log_open'])
                self.close_app()
                self.assertFalse(app_settings.load()['ui_log_open'])
                app = self.open_app()
                panel = app.log if mode == 'local' else app._realtime_workspace.log
                self.assertFalse(app._log_open)
                self.assertFalse(panel.frame.winfo_manager())
                app.toggle_log_panel()
                self.close_app()
                app = self.open_app()
                self.assertTrue(app._log_open)
                self.close_app()

    def assert_restored(self, mode, theme):
        app = self.app
        self.assertEqual(app._workbench_mode, mode)
        self.assertEqual(app._mode_var.get(), mode)
        self.assertEqual(app._caption_mode_button.mode, mode)
        self.assertEqual(app._ui_theme_name, theme)
        self.assertEqual(app._mode_transition.title, gui.tr('workbench.mode.' + mode))
        self.assertIsNone(app._mode_transition._after)
        self.assertEqual(app._mode_transition._strength, 0)
        self.assertEqual(app.canvas.cget('bg'), app._ui['canvas'])
        if mode == 'realtime':
            workspace = app._realtime_workspace
            self.assertEqual(workspace.window.winfo_manager(), 'pack')
            self.assertEqual(app._studio.winfo_manager(), '')
            self.assertEqual(workspace.region_preview.cget('bg'), app._ui['canvas'])
            self.assertFalse(workspace._active)
            self.assertIsNone(workspace._run_id)
        else:
            self.assertEqual(app._studio.winfo_manager(), 'pack')
            self.assertIsNone(app._realtime_workspace)
        self.client.start.assert_not_called()
        self.assertFalse({'start', 'stop', 'restart'} & {call.args[0] for call in self.client.send.call_args_list})

    def test_close_before_debounce_and_reopen_restores_all_four_pairs(self):
        for mode in ('local', 'realtime'):
            for theme in ('light', 'dark'):
                with self.subTest(mode=mode, theme=theme):
                    app = self.open_app()
                    app._select_workbench_mode(mode)
                    if app._ui_theme_name != theme:
                        app.toggle_ui_theme()
                    # No event pump: closing must flush the pending preference.
                    self.close_app()
                    settings = app_settings.load()
                    self.assertEqual((settings['workbench_mode'], settings['ui_theme']), (mode, theme))
                    self.open_app()
                    self.assert_restored(mode, theme)
                    self.root.update()
                    self.assert_restored(mode, theme)
                    self.close_app()

    def test_first_launch_defaults_to_local_light(self):
        self.open_app()
        self.assert_restored('local', 'light')

    def test_startup_does_not_rewrite_saved_pair_or_schedule_switch_highlight(self):
        app_settings.save({'workbench_mode': 'realtime', 'ui_theme': 'light'})
        with mock.patch.object(app_settings, 'save', wraps=app_settings.save) as save:
            app = self.open_app(visible=True)
            self.assert_restored('realtime', 'light')
            save.assert_not_called()
            self.assertIsNone(app._settings_save_after)
        self.root.update()
        self.assert_restored('realtime', 'light')
        self.assertTrue(app._mode_transition.badge.winfo_ismapped())

    def test_realtime_restore_failure_keeps_local_and_saved_theme_usable(self):
        for theme in ('light', 'dark'):
            with self.subTest(theme=theme):
                app_settings.save({'workbench_mode': 'realtime', 'ui_theme': theme})
                with mock.patch('dlss5tool.realtime_ui.RealtimeWorkspace', side_effect=ValueError('invalid preset')), \
                        mock.patch.object(gui.messagebox, 'showerror') as error:
                    self.open_app()
                self.assert_restored('local', theme)
                error.assert_called_once()
                self.root.update()
                self.close_app()
                self.assertEqual(app_settings.load()['workbench_mode'], 'local')

    def test_detached_player_stays_hidden_until_returning_to_local(self):
        app_settings.save({'workbench_mode': 'realtime', 'ui_theme': 'dark', 'preview_detached': True})
        app = self.open_app(visible=True)
        self.root.update()
        window = app._detached_preview_window
        self.assertIsNotNone(window)
        self.assertEqual(window.state(), 'withdrawn')
        self.assertEqual(app._detached_preview_placeholder.winfo_manager(), '')
        self.assertTrue(app._collect_persisted_settings()['preview_detached'])
        app.detach_preview()
        self.assertEqual(window.state(), 'withdrawn')
        app._select_workbench_mode('local')
        self.root.update()
        self.assertIs(app._detached_preview_window, window)
        self.assertEqual(window.state(), 'normal')
        self.assertEqual(app._detached_preview_placeholder.winfo_manager(), 'pack')
        # A deliberate switch still follows the established theme inversion.
        self.assertEqual(app._ui_theme_name, 'light')
        app._select_workbench_mode('realtime')
        self.assertEqual(window.state(), 'withdrawn')
        self.assertEqual(app._detached_preview_placeholder.winfo_manager(), '')
        self.client.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
