"""One workbench, two persistent sessions; no native capture needed."""
from copy import deepcopy
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest import mock

from dlss5tool import gui
from dlss5tool.realtime import PresetStore


class WorkbenchUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        env = mock.patch.dict(os.environ, {
            'DLSS5TOOL_SETTINGS_PATH': str(directory / 'settings.json'),
            'DLSS5TOOL_QUEUE_PATH': str(directory / 'queue.json'),
        })
        env.start()
        self.addCleanup(env.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app = gui.App(self.root)
        self.root.update()
        self.client = mock.Mock(events=queue.Queue(), generation=1, settings={})
        self.client.send.return_value = 1
        self.client.start.return_value = 2
        for name, value in [('RealtimeClient', self.client),
                            ('PresetStore', PresetStore(directory / 'realtime.json')),
                            ('list_windows', [])]:
            patch = mock.patch('dlss5tool.realtime_ui.' + name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.app._on_close()
        self.assertEqual(self.errors, [])

    def test_switch_retains_widgets_media_position_queue_and_realtime_draft(self):
        app = self.app
        local_canvas, tabs, jobs = app.canvas, app.workspace_tabs, app._queue_jobs
        app._frame = 37
        app._select_workbench_mode('realtime')
        workspace = app._realtime_workspace
        workspace.quality_controls['total'].set('.45')
        workspace.regions.insert('1.0', '0 0.8 1 1')
        draft = deepcopy(workspace.collect())
        app._select_workbench_mode('local')
        app._select_workbench_mode('realtime')
        self.assertIs(workspace, app._realtime_workspace)
        self.assertEqual(workspace.collect(), draft)
        self.assertIs(app.canvas, local_canvas)
        self.assertIs(app.workspace_tabs, tabs)
        self.assertIs(app._queue_jobs, jobs)
        self.assertEqual(app._frame, 37)
        self.client.start.assert_not_called()
        self.assertNotIn('stop', [call.args[0] for call in self.client.send.call_args_list])
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))

    def test_stop_remains_available_in_local_mode_and_waiting_state(self):
        app = self.app
        app._select_workbench_mode('realtime')
        ui = app._realtime_workspace
        ui._native_state = 4
        ui._session_target = {'title': 'Owned test window'}
        ui._notify_session()
        app._select_workbench_mode('local')
        self.root.deiconify()
        self.root.update()
        self.assertTrue(app._realtime_stop.winfo_ismapped())
        self.assertEqual(app._realtime_stop.cget('state'), 'normal')
        self.assertIn('Owned test window', app._realtime_summary.get())
        app._stop_realtime()
        self.client.send.assert_called_with('stop')

    def test_realtime_status_hides_local_idle_chips_but_keeps_background_jobs(self):
        app = self.app
        app._select_workbench_mode('realtime')
        app._refresh_status_chips()
        for widget in (app._status_host, app._status_chips, app._status_metric):
            self.assertFalse(widget.winfo_manager())
        app._exporting = True
        app._refresh_status_chips()
        self.assertEqual(app._status_host.winfo_manager(), 'pack')
        self.assertFalse(app._status_metric.winfo_manager())
        app._exporting = False
        app._select_workbench_mode('local')
        app._refresh_status_chips()
        for widget in (app._status_host, app._status_chips, app._status_metric):
            self.assertEqual(widget.winfo_manager(), 'pack')

    def test_realtime_does_not_receive_local_playback_shortcuts_or_drops(self):
        app = self.app
        app._select_workbench_mode('realtime')
        self.assertFalse(app._preview_tab_selected())
        with mock.patch.object(app, 'toggle_play') as play:
            self.assertIsNone(app.on_space())
            play.assert_not_called()
        self.assertEqual(app._on_drop(mock.Mock()), 'none')

    def test_detached_preview_is_hidden_and_restored_without_recreation(self):
        app = self.app
        app.detach_preview()
        detached = app._detached_preview_window
        app._select_workbench_mode('realtime')
        self.assertEqual(detached.state(), 'withdrawn')
        app._select_workbench_mode('local')
        self.assertIs(app._detached_preview_window, detached)
        self.assertEqual(detached.state(), 'normal')

    def test_workspace_creation_failure_leaves_local_mode_usable(self):
        self.root.deiconify()
        self.root.update()
        previous_theme = self.app._ui_theme_name
        for enabled in (False, True):
            with self.subTest(animations=enabled), \
                    mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=enabled), \
                    mock.patch('dlss5tool.realtime_ui.RealtimeWorkspace', side_effect=ValueError('invalid preset')), \
                    mock.patch.object(gui.messagebox, 'showerror') as error:
                self.app._select_workbench_mode('realtime')
                self.assertEqual(self.app._workbench_mode, 'local')
                self.assertEqual(self.app._mode_var.get(), 'local')
                self.assertIsNone(self.app._realtime_workspace)
                self.assertEqual(self.app._ui_theme_name, previous_theme)
                self.assertIsNone(self.app._mode_transition.cover)
                self.assertIsNone(self.app._mode_transition.notice)
                self.assertIsNone(self.app._mode_transition._after)
                self.assertEqual(self.app._mode_transition.title, gui.tr('workbench.mode.local'))
                error.assert_called_once()

    def test_both_themes_and_sizes_keep_controls_inside_workbench(self):
        app = self.app
        app._select_workbench_mode('realtime')
        workspace = app._realtime_workspace
        self.root.deiconify()
        for geometry in ('1000x680', '1280x800'):
            self.root.geometry(geometry)
            for theme in ('light', 'dark'):
                app._apply_ui_theme(theme, persist=False)
                self.root.update()
                self.assertFalse(app._realtime_stop.winfo_ismapped())
                for widget in (workspace.start_button, workspace.stop_button, workspace.target):
                    self.assertTrue(widget.winfo_ismapped(), str(widget))
                    self.assertGreater(widget.winfo_width(), 20, str(widget))
                    self.assertGreater(widget.winfo_height(), 20, str(widget))
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
                self.assertEqual(workspace.region_preview.cget('bg'), app._ui['canvas'])
                for item in workspace.tabs._tabs:
                    workspace.tabs.select(item['frame'])
                    self.root.update()
                    self.assertTrue(item['frame'].winfo_ismapped())

    def test_closing_cancels_poll_and_closes_native_client_once(self):
        self.app._select_workbench_mode('realtime')
        workspace = self.app._realtime_workspace
        workspace.close()
        workspace.close()
        self.assertTrue(workspace._closed)
        self.client.close.assert_called_once()

    def test_logs_share_bottom_slot_toggle_and_preserve_separate_scroll(self):
        app = self.app
        self.root.deiconify()
        self.root.update()
        self.assertTrue(app._log_open)
        app.log.configure(state='normal')
        app.log.insert('end', '\n'.join(f'local {i}' for i in range(100)))
        app.log.configure(state='disabled')
        app.log.yview_moveto(.3)
        self.root.update()
        local_scroll = app.log.yview()
        app._select_workbench_mode('realtime')
        workspace = app._realtime_workspace
        self.root.update()
        self.assertEqual(len(workspace.tabs._tabs), 4)
        self.assertIs(workspace.log.frame.master, self.root)
        self.assertFalse(app.log.winfo_ismapped())
        self.assertTrue(workspace.log.winfo_ismapped())
        self.assertEqual(self.root.pack_slaves()[-3:], [app._progress_rule, workspace.log.frame, app._status_bar])
        self.assertGreaterEqual(workspace.log.winfo_rooty(), app._mode_host.winfo_rooty() + app._mode_host.winfo_height())
        workspace.log.configure(state='normal')
        workspace.log.insert('end', '\n'.join(f'realtime {i}' for i in range(100)) + '\n')
        workspace.log.configure(state='disabled')
        workspace.log.yview_moveto(.25)
        self.root.update()
        realtime_scroll = workspace.log.yview()[0]
        app.toggle_log_panel()
        self.assertEqual(workspace.log.frame.winfo_manager(), '')
        self.assertEqual(app.log.frame.winfo_manager(), '')
        app._select_workbench_mode('local')
        self.assertEqual(app.log.frame.winfo_manager(), '')
        app.toggle_log_panel()
        self.root.update()
        self.assertEqual(app.log.yview(), local_scroll)
        self.assertIn('local 99', app.log.get('1.0', 'end'))
        app._select_workbench_mode('realtime')
        self.root.update()
        self.assertAlmostEqual(workspace.log.yview()[0], realtime_scroll)
        self.assertNotIn('local 99', workspace.log.get('1.0', 'end'))
        self.client.events.put(dict(event='log', message='new message'))
        workspace.window.after_cancel(workspace._after)
        workspace._poll()
        self.root.update()
        self.assertAlmostEqual(workspace.log.yview()[0], realtime_scroll, delta=.01)
        self.assertIn('new message', workspace.log.get('1.0', 'end'))
        for theme in ('light', 'dark'):
            app._apply_ui_theme(theme, persist=False)
            self.assertEqual(workspace.log.cget('bg'), app._ui['log_bg'])
            self.assertEqual(workspace.log.cget('fg'), app._ui['log_fg'])
        self.client.start.assert_not_called()

    def test_quick_export_includes_realtime_session_from_local_mode_without_probes(self):
        app = self.app
        app._select_workbench_mode('realtime')
        workspace = app._realtime_workspace
        workspace._active = True
        workspace._run_id = 7
        workspace._session_target = {'title': 'Test Target', 'pid': 101, 'application': 'test.exe'}
        workspace.quality_controls['total'].set('unfinished draft')
        app._select_workbench_mode('local')
        captured = {}
        output = str(Path(self.temp.name) / 'report.log')
        def writer(path, context, on_progress=None, *, deep=False):
            captured.update(thread=threading.get_ident(), deep=deep, context=context)
            on_progress(5, 6, 'saving')
            return {'path': path}
        with mock.patch.object(gui.filedialog, 'asksaveasfilename', return_value=output), \
             mock.patch.object(gui.support_diagnostics, 'write_report', side_effect=writer), \
             mock.patch.object(gui.messagebox, 'showinfo'), \
             mock.patch.object(app, '_ensure_shared_cache_pool', side_effect=AssertionError('quick export allocated cache')):
            app.export_diagnostics()
            deadline = time.monotonic() + 5
            while app._diagnosing and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(app._diagnosing)
        self.assertNotEqual(captured['thread'], threading.get_ident())
        self.assertFalse(captured['deep'])
        snapshot = captured['context']['realtime']
        self.assertEqual(snapshot['session']['run_id'], 7)
        self.assertEqual(snapshot['draft_fields']['quality']['total'], 'unfinished draft')
        self.assertEqual(captured['context']['workbench_mode'], 'local')
        self.assertTrue(workspace._active)
        self.client.start.assert_not_called()

    def test_deep_diagnostic_gate_and_shared_export_entry(self):
        app = self.app
        app._select_workbench_mode('realtime')
        ui = app._realtime_workspace
        ui._active = True
        app._select_workbench_mode('local')
        with mock.patch.object(gui.messagebox, 'showinfo') as info, \
             mock.patch.object(gui.filedialog, 'asksaveasfilename') as dialog, \
             mock.patch.object(gui.support_diagnostics, 'write_report') as writer:
            app.export_diagnostics(deep=True)
            info.assert_called_once()
            dialog.assert_not_called()
            writer.assert_not_called()
        ui._active = False
        app._deep_diagnosing = True
        ui.start()
        self.client.start.assert_not_called()
        app._deep_diagnosing = False
        with mock.patch.object(gui.messagebox, 'askyesno', return_value=False), \
             mock.patch.object(gui.filedialog, 'asksaveasfilename') as dialog:
            app.export_diagnostics(deep=True)
            dialog.assert_not_called()
        with mock.patch.object(ui, '_on_export_diagnostics') as callback:
            ui.export_diagnostics()
            callback.assert_called_once_with()

    def test_realtime_start_refreshes_idle_runtime_paths_and_blocks_export(self):
        app = self.app
        app._select_workbench_mode('realtime')
        ui = app._realtime_workspace
        ui.client.settings = {'mods_directory': 'old', 'dlss_runtime': 'old.dll'}
        with mock.patch.object(app, '_collect_host_settings', return_value={
                'mods_directory': 'new', 'dlss_runtime': '__bundled__'}):
            self.assertTrue(app._can_start_realtime())
        self.assertEqual(ui.client.settings['mods_directory'], 'new')
        ui.client.close.assert_called_once()
        ui.client.launch.assert_called()
        ui.client.send.assert_any_call('catalog')
        self.assertIsNone(ui._host_ready)
        self.assertIsNone(ui._catalog_generation)
        app._exporting = True
        self.assertFalse(app._can_start_realtime())
        app._exporting = False
        ui._active = True
        with mock.patch.object(gui.messagebox, 'showinfo') as info, \
             mock.patch.object(gui.filedialog, 'asksaveasfilename') as dialog:
            app.export_dlss()
            app.start_export_queue()
        self.assertEqual(info.call_count, 2)
        dialog.assert_not_called()

    def test_deep_export_rechecks_busy_after_save_dialog(self):
        app = self.app
        def choose_path(**kwargs):
            app._queue_running = True
            return str(Path(self.temp.name) / 'deep.log')
        try:
            with mock.patch.object(gui.messagebox, 'askyesno', return_value=True), \
                 mock.patch.object(gui.filedialog, 'asksaveasfilename', side_effect=choose_path), \
                 mock.patch.object(gui.messagebox, 'showinfo') as info, \
                 mock.patch.object(gui.support_diagnostics, 'write_report') as writer:
                app.export_diagnostics(deep=True)
                info.assert_called_once()
                writer.assert_not_called()
                self.assertFalse(app._diagnosing)
        finally:
            app._queue_running = False

    def test_deep_export_runs_off_ui_thread_and_clears_start_guard(self):
        app = self.app
        output = str(Path(self.temp.name) / 'deep.log')
        captured = {}
        def writer(path, context, on_progress=None, *, deep=False):
            captured.update(deep=deep, thread=threading.get_ident(), guarded=app._deep_diagnosing)
            return {'path': path}
        with mock.patch.object(gui.messagebox, 'askyesno', return_value=True), \
             mock.patch.object(gui.filedialog, 'asksaveasfilename', return_value=output), \
             mock.patch.object(gui.messagebox, 'showinfo'), \
             mock.patch.object(gui.support_diagnostics, 'write_report', side_effect=writer):
            app.export_diagnostics(deep=True)
            deadline = time.monotonic() + 5
            while app._diagnosing and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(app._diagnosing)
        self.assertFalse(app._deep_diagnosing)
        self.assertTrue(captured['deep'])
        self.assertTrue(captured['guarded'])
        self.assertNotEqual(captured['thread'], threading.get_ident())

    def test_cancelled_or_failed_export_does_not_leave_busy_state(self):
        app = self.app
        with mock.patch.object(gui.filedialog, 'asksaveasfilename', return_value=''), \
             mock.patch.object(gui.support_diagnostics, 'write_report') as writer:
            app.export_diagnostics()
            writer.assert_not_called()
            self.assertFalse(app._diagnosing)
        with mock.patch.object(gui.filedialog, 'asksaveasfilename', return_value=str(Path(self.temp.name) / 'report.log')), \
             mock.patch.object(gui.support_diagnostics, 'write_report', side_effect=PermissionError('locked')), \
             mock.patch.object(gui.messagebox, 'showerror') as error:
            app.export_diagnostics()
            deadline = time.monotonic() + 5
            while app._diagnosing and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            error.assert_called_once()
        self.assertFalse(app._diagnosing)
        self.assertFalse(app._deep_diagnosing)

    def test_realtime_nr_issue_opens_existing_local_module_editor(self):
        app = self.app
        app._select_workbench_mode('realtime')
        workspace = app._realtime_workspace
        workspace._on_nr_settings()
        self.root.update()
        self.assertEqual(app._workbench_mode, 'local')
        self.assertFalse(app._module_editor.collapsed)
        self.assertIs(app._realtime_workspace, workspace)
        self.client.start.assert_not_called()
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))

    def test_no_header_and_keyboard_switch_preserves_session(self):
        self.assertFalse(hasattr(self.app, '_workbench_header'))
        self.assertEqual(self.app._cycle_workbench_mode(), 'break')
        self.assertEqual(self.app._workbench_mode, 'realtime')
        self.assertEqual(self.app._caption_mode_button.mode, 'realtime')
        self.app._cycle_workbench_mode()
        self.assertEqual(self.app._workbench_mode, 'local')
        self.client.start.assert_not_called()

    def test_mode_menu_is_explicit_and_does_not_auto_start(self):
        menu = self.app._workbench_mode_menu(self.root)
        try:
            self.assertEqual(menu.entrycget(0, 'label'), '本地媒体')
            self.assertEqual(menu.entrycget(1, 'label'), '实时增强')
            menu.invoke(1)
            self.assertEqual(self.app._workbench_mode, 'realtime')
            self.client.start.assert_not_called()
        finally:
            menu.destroy()

    def test_caption_click_switches_immediately_without_menu_or_capture(self):
        self.app._apply_ui_theme('light', persist=False)
        button = self.app._caption_mode_button
        with mock.patch.object(tk.Menu, 'tk_popup') as post:
            button._events.append('click')
            button._dispatch_events()
            self.assertEqual(self.app._workbench_mode, 'realtime')
            self.assertEqual(button.mode, 'realtime')
            self.assertEqual(self.app._ui_theme_name, 'dark')
            self.assertEqual(button._label(), '切换到本地媒体')
            button._events.append('click')
            button._dispatch_events()
            self.assertEqual(self.app._workbench_mode, 'local')
            self.assertEqual(self.app._ui_theme_name, 'light')
            self.assertEqual(button._label(), '切换到实时增强')
            post.assert_not_called()
            self.client.start.assert_not_called()

    def test_theme_switch_does_not_flush_partial_palette_to_idle_callbacks(self):
        app = self.app
        app._select_workbench_mode('realtime')
        app._select_workbench_mode('local')
        app.detach_preview()
        self.root.update()
        detached = app._detached_preview_window

        def palette_snapshot():
            return (
                app._preview_canvas.cget('bg'), app.log.cget('bg'),
                app._docked_preview_pane['canvas'].cget('bg'),
                app._detached_preview_pane['canvas'].cget('bg'),
                app._realtime_workspace.region_preview.cget('bg'),
                app.export_btn._ui['panel'], app.workspace_tabs._ui['panel'],
                app._status_chips._ui['surface'],
            )

        for theme in ('dark', 'light', 'dark'):
            with self.subTest(theme=theme):
                painted = []
                timer = self.root.after_idle(lambda: painted.append(palette_snapshot()))
                try:
                    app._apply_ui_theme(theme, persist=False)
                    self.assertEqual(painted, [], 'Theme update flushed a partially recolored UI')
                    ui = app._ui
                    expected = (ui['panel'], ui['log_bg'], ui['canvas'], ui['canvas'],
                                ui['canvas'], ui['panel'], ui['panel'], ui['surface'])
                    self.assertEqual(palette_snapshot(), expected)
                    self.root.update_idletasks()
                    self.assertEqual(painted, [expected])
                    self.assertIs(app._detached_preview_window, detached)
                finally:
                    self.root.after_cancel(timer)

    def test_native_titlebars_are_updated_after_client_widgets(self):
        app = self.app
        app.detach_preview()
        app._apply_ui_theme('dark', persist=False)
        self.root.update()
        applied = []

        def titlebar(window, ui, dark):
            applied.append((window, ui, dark, app._preview_canvas.cget('bg'),
                            app.export_btn._ui['panel'], app.log.cget('bg')))

        with mock.patch.object(gui.ui_theme, 'apply_native_titlebar', side_effect=titlebar):
            app._apply_ui_theme('light', persist=False)
        self.assertEqual(len(applied), 2)
        for actual, window in zip(applied, (self.root, app._detached_preview_window)):
            self.assertEqual(actual, (window, app._ui, False, app._ui['panel'],
                                      app._ui['panel'], app._ui['log_bg']))

    def test_palette_changes_do_not_reselect_the_active_ttk_theme(self):
        style = gui.ttk.Style(self.root)
        self.assertEqual(style.theme_use(), 'clam')
        with mock.patch.object(gui.ui_theme.ttk, 'Style', return_value=style), \
                mock.patch.object(style, 'theme_use', wraps=style.theme_use) as select:
            self.app._apply_ui_theme('dark', persist=False)
            self.app._apply_ui_theme('light', persist=False)
        self.assertEqual(select.call_args_list, [mock.call(), mock.call()])

    def test_transition_cancels_on_rapid_switch_and_keeps_session_and_theme(self):
        self.root.deiconify()
        self.root.update()
        app = self.app
        with mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=True):
            app._apply_ui_theme('light', persist=False)
            app._select_workbench_mode('realtime')
            transition = app._mode_transition
            badge = transition.badge
            self.assertIs(badge.master, app._status_bar)
            self.assertEqual(transition.title, gui.tr('workbench.mode.realtime'))
            self.assertIsNone(transition.cover)
            self.assertIsNotNone(transition._after)
            self.assertEqual(app._ui_theme_name, 'dark')
            app._select_workbench_mode('local')
            self.assertIs(transition.badge, badge)
            self.assertEqual(transition.title, gui.tr('workbench.mode.local'))
            self.assertEqual(app._ui_theme_name, 'light')
            self.assertEqual(app._caption_mode_button.ui, app._ui)
            self.assertEqual(app._realtime_workspace._ui, app._ui)
            with mock.patch('dlss5tool.workbench_transition.time.monotonic',
                            return_value=transition._started + 1):
                # Drive the pending callback without leaving its scheduled copy.
                transition.host.after_cancel(transition._after)
                transition._notice_step()
            self.assertIsNone(transition.cover)
            self.assertIsNone(transition.notice)
            self.assertTrue(badge.winfo_exists())
            self.assertIsNone(transition._after)
            self.client.start.assert_not_called()
            self.assertNotIn('stop', [c.args[0] for c in self.client.send.call_args_list])

    def test_reduced_motion_switch_has_static_status_bar_feedback(self):
        self.root.deiconify()
        self.root.update()
        self.app._apply_ui_theme('light', persist=False)
        with mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=False):
            self.app._cycle_workbench_mode()
        self.assertEqual(self.app._ui_theme_name, 'dark')
        transition = self.app._mode_transition
        self.assertIsNone(transition.cover)
        self.assertIsNotNone(transition._after)
        self.assertEqual(transition.title, gui.tr('workbench.mode.realtime'))
        self.assertEqual(transition.badge.cget('bg'), self.app._ui['surface'])
        self.assertEqual(str(transition.badge.cget('takefocus')), '0')
        self.assertEqual(transition.badge.winfo_manager(), 'pack')
        self.assertIs(transition.badge.master, self.app._status_bar)
        self.assertIsNone(transition.notice)

    def test_mode_theme_inverts_current_choice_instead_of_binding_to_mode(self):
        app = self.app
        for initial, inverse in [('dark', 'light'), ('light', 'dark')]:
            with self.subTest(initial=initial):
                app._select_workbench_mode('local')
                app._apply_ui_theme(initial, persist=False)
                app._select_workbench_mode('realtime')
                self.assertEqual(app._ui_theme_name, inverse)
                app.toggle_ui_theme()  # Same action offered in More.
                self.assertEqual(app._ui_theme_name, initial)
                self.assertEqual(app._workbench_mode, 'realtime')
                self.assertEqual(app._realtime_workspace._ui, app._ui)
                app._select_workbench_mode('local')
                self.assertEqual(app._ui_theme_name, inverse)
                app.toggle_ui_theme()
                self.assertEqual(app._ui_theme_name, initial)
                self.assertEqual(app._workbench_mode, 'local')
                app._select_workbench_mode('realtime')
                self.assertEqual(app._ui_theme_name, inverse)

    def test_selecting_current_mode_does_not_toggle_theme_or_restart_feedback(self):
        self.root.deiconify()
        self.root.update()
        app = self.app
        for mode in ('realtime', 'local'):
            app._select_workbench_mode(mode)
            theme = app._ui_theme_name
            with mock.patch.object(app._mode_transition, 'begin') as begin, \
                    mock.patch.object(app, '_apply_ui_theme') as apply:
                app._select_workbench_mode(mode)
                begin.assert_not_called()
                apply.assert_not_called()
            self.assertEqual(app._ui_theme_name, theme)

    def test_manual_theme_change_keeps_mode_badge_and_cancels_highlight(self):
        self.root.deiconify()
        self.root.update()
        for enabled in (False, True):
            with self.subTest(animations=enabled), \
                    mock.patch('dlss5tool.workbench_transition.animations_enabled', return_value=enabled):
                self.app._cycle_workbench_mode()
                mode = self.app._workbench_mode
                transition = self.app._mode_transition
                self.assertIsNotNone(transition._after)
                self.app.toggle_ui_theme()
                self.assertEqual(self.app._workbench_mode, mode)
                self.assertIsNone(transition.cover)
                self.assertIsNone(transition.notice)
                self.assertIsNone(transition._after)
                self.assertEqual(transition.title, gui.tr('workbench.mode.' + mode))
                self.assertTrue(transition.badge.winfo_exists())

    def test_player_returns_to_single_row_below_old_1000px_threshold(self):
        # CI's desktop may be 1024 wide: allow the user's 1260-wide geometry
        # instead of letting Tk's default WM maxsize silently clamp this test.
        self.root.maxsize(2000, 1400)
        self.root.deiconify()
        self.root.geometry('1260x720')
        self.root.update()
        app = self.app
        self.assertLess(app.transport.winfo_width(), 1000)
        self.assertEqual(app.control_layout['mode'], 'wide', app.control_layout)
        self.assertLess(abs(app.play_btn.winfo_rooty() - app.fs_btn.winfo_rooty()), 8)
        # A detached narrow player wraps, then returns to one row when enlarged.
        app.detach_preview()
        window = app._detached_preview_window
        window.geometry('600x500')
        self.root.update()
        self.assertNotEqual(app.control_layout['mode'], 'wide')
        window.geometry('930x500')
        self.root.update()
        self.assertEqual(app.control_layout['mode'], 'wide')


if __name__ == '__main__':
    unittest.main()
