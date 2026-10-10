"""No real applications are captured: geometry, lifecycle and compact presets."""
from copy import deepcopy
import io
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

from dlss5tool import i18n, ui_theme
from dlss5tool.realtime import DEFAULT_CONFIG, nr_preset
from dlss5tool.realtime_snapshot import (Snapshot, SnapshotError, SnapshotJob, fitted_rect,
                                       normalized_point, source_crop)
from tests import test_realtime_ui


class SnapshotGeometryTests(unittest.TestCase):
    def test_letterbox_roundtrip_excludes_margins(self):
        bounds = fitted_rect((1920, 1080), 640, 400)
        self.assertEqual(bounds, (0, 20, 640, 380))
        self.assertIsNone(normalized_point(200, 10, bounds))
        self.assertEqual(normalized_point(320, 200, bounds), (.5, .5))
        self.assertEqual(normalized_point(-20, 900, bounds, clamp=True), (0, 1))
        bounds = fitted_rect((500, 1000), 800, 600)
        self.assertEqual(bounds, (250, 0, 550, 600))
        self.assertIsNone(normalized_point(0, 200, bounds))

    def test_native_frame_title_scrollbars_and_maximized_geometry(self):
        options = dict(window=(100, 100, 916, 639), frame=(107, 100, 909, 632),
                       client=(108, 131, 891, 631), native_frame=True, style=0x00c40000, border=1)
        self.assertEqual(source_crop(**options), (108, 131, 908, 631))
        self.assertEqual(source_crop(**options, title_bar=True), (108, 101, 908, 631))
        self.assertEqual(source_crop(**options, monitor=(0, 0, 850, 600)), (108, 131, 850, 600))

    def test_borderless_and_custom_nonclient_match_native_crop(self):
        options = dict(window=(100, 100, 900, 600), frame=(100, 100, 900, 600),
                       client=(104, 130, 879, 579), native_frame=False)
        self.assertEqual(source_crop(**options, style=0), (100, 100, 900, 600))
        self.assertEqual(source_crop(**options, style=0x00c40000), (104, 130, 879, 579))
        self.assertEqual(source_crop(**options, style=0x00f40000), (104, 130, 896, 596))

    def test_worker_timeout_and_cancel_terminate_process(self):
        with mock.patch('dlss5tool.realtime_snapshot.multiprocessing.get_context') as get:
            context = get.return_value
            parent, child = mock.Mock(), mock.Mock()
            context.Pipe.return_value = parent, child
            parent.poll.return_value = False
            context.Process.return_value.is_alive.return_value = True
            job = SnapshotJob({'hwnd': 1, 'pid': 2})
            job.deadline = 0
            with self.assertRaisesRegex(SnapshotError, 'timeout'): job.poll()
            context.Process.return_value.terminate.assert_called_once()
            parent.close.assert_called_once(); child.close.assert_called_once()

    def test_job_result_decodes_then_releases_worker(self):
        payload = io.BytesIO(); Image.new('RGB', (20, 10), '#123456').save(payload, format='PNG')
        with mock.patch('dlss5tool.realtime_snapshot.multiprocessing.get_context') as get:
            context = get.return_value
            parent, child = mock.Mock(), mock.Mock(); context.Pipe.return_value = parent, child
            parent.poll.return_value = True
            parent.recv.return_value = ('ok', (200, 100), payload.getvalue())
            job = SnapshotJob({'hwnd': 1, 'pid': 2})
            result = job.poll()
            self.assertEqual(result.image.size, (20, 10)); self.assertEqual(result.source_size, (200, 100))
            parent.close.assert_called_once()


class SourcePreviewUiTests(unittest.TestCase):
    setUp = test_realtime_ui.RealtimeUiTests.setUp
    tearDown = test_realtime_ui.RealtimeUiTests.tearDown

    def select(self, hwnd=101, pid=202):
        self.ui.windows = [dict(hwnd=hwnd, pid=pid, title='Synthetic', application='synthetic.exe')]
        self.ui.target.configure(values=['Synthetic']); self.ui.target.current(0)

    def snapshot(self):
        self.select(); self.ui._notify_session()
        preview = self.ui.source_preview
        preview.snapshot = Snapshot(Image.new('RGB', (640, 360), '#345678'), (1920, 1080))
        preview.draw(); preview._update_controls()
        return preview

    def editor(self, regions=()):
        self.ui.regions.delete('1.0', 'end')
        self.ui.regions.insert('1.0', '\n'.join(' '.join(map(str, r)) for r in regions))
        preview = self.snapshot(); preview.edit_regions(); self.root.update()
        return preview.editor

    def point(self, editor, x, y):
        left, top, right, bottom = editor.bounds()
        return SimpleNamespace(x=left+(right-left)*x, y=top+(bottom-top)*y)

    def test_select_requests_once_but_window_list_refresh_does_not_capture(self):
        self.select()
        with mock.patch('dlss5tool.realtime_source_preview.SnapshotJob') as job:
            job.return_value.poll.return_value = None
            self.ui._target_changed()
            job.assert_called_once()
            for _ in range(3): self.ui._notify_session(); self.ui.source_preview.poll()
            job.assert_called_once()
            with mock.patch('dlss5tool.realtime_ui.list_windows', return_value=self.ui.windows): self.ui.refresh()
            job.assert_called_once()

    def test_running_cancels_capture_and_retains_only_matching_snapshot(self):
        preview = self.snapshot()
        image = preview.snapshot
        job = preview.job = mock.Mock()
        self.ui._active = True; self.ui._notify_session()
        job.cancel.assert_called_once(); self.assertIsNone(preview.job)
        self.assertIs(preview.snapshot, image)
        with mock.patch('dlss5tool.realtime_source_preview.SnapshotJob') as create:
            preview.request(); preview.poll(); preview.edit_regions()
            create.assert_not_called()
        self.select(102, 203); self.ui._target_changed()
        self.assertIsNone(preview.snapshot)
        self.assertEqual(preview.message.get(), i18n.tr('realtime.preview.paused_empty'))
        self.ui._active = False; self.ui._notify_session()
        self.assertFalse(preview.busy)

    def test_target_identity_and_capture_bounds_invalidate_snapshot(self):
        preview = self.snapshot()
        self.ui.controls['capture_title_bar'][0].set(True); self.ui._editor_changed()
        self.assertIsNone(preview.snapshot)
        self.assertTrue(preview.key[2])
        self.ui.controls['capture_method'][0].current(2); self.ui._notify_session()
        self.assertFalse(preview.key[2])
        job = preview.job = mock.Mock()
        self.select(101, 999); self.ui._notify_session()
        job.cancel.assert_called_once()

    def test_target_change_hides_obsolete_preflight(self):
        self.ui._present_preflight(None, [])
        self.select()
        with mock.patch('dlss5tool.realtime_source_preview.SnapshotJob'):
            self.ui._target_changed()
        self.assertFalse(self.ui.preflight_panel.winfo_manager())
        self.assertIsNone(self.ui._preflight_signature)

    def test_failure_is_preview_only_and_never_calls_start(self):
        self.select(); self.ui._notify_session()
        preview = self.ui.source_preview
        preview.job = mock.Mock(); preview.job.poll.side_effect = SnapshotError('timeout')
        before = self.ui.collect(); preview.poll()
        self.assertEqual(preview.message.get(), i18n.tr('realtime.preview.error.timeout'))
        self.assertIsNone(preview.snapshot); self.assertEqual(before, self.ui.collect())
        self.client.start.assert_not_called()

    def test_close_cancels_capture_without_saving_pixels(self):
        job = self.ui.source_preview.job = mock.Mock()
        self.ui.close(); job.cancel.assert_called_once()

    def test_start_cancels_snapshot_before_starting_native_capture(self):
        preview = self.snapshot()
        calls = []
        preview.job = mock.Mock(); preview.job.cancel.side_effect = lambda: calls.append('cancel')
        self.client.start.side_effect = lambda *args: calls.append('start') or 2
        with mock.patch.object(self.ui, '_run_preflight', return_value=(self.ui.collect(), [])):
            self.ui.start()
        self.assertEqual(calls, ['cancel', 'start'])
        self.assertTrue(preview.busy)

    def test_preset_load_closes_old_region_draft_without_applying_it(self):
        editor = self.editor()
        editor.begin(self.point(editor, .1, .1)); editor.end(self.point(editor, .4, .4))
        self.ui.apply_config(DEFAULT_CONFIG)
        self.assertIsNone(self.ui.source_preview.editor)
        self.assertEqual(self.ui.collect()['quality']['regions'], [])

    def test_refresh_failure_drops_previous_pixels(self):
        preview = self.snapshot()
        with mock.patch('dlss5tool.realtime_source_preview.SnapshotJob', side_effect=OSError):
            preview.request()
        self.assertIsNone(preview.snapshot)
        self.assertEqual(preview.edit_button.cget('state'), 'disabled')

    def test_preset_menu_survives_posting_and_routes_import_and_export(self):
        with mock.patch('tkinter.Menu.tk_popup'), mock.patch('tkinter.Menu.grab_release'), \
             mock.patch.object(self.ui, 'import_config') as importing, mock.patch.object(self.ui, 'export_config') as exporting:
            self.ui._preset_menu()
            menu = self.ui._preset_popup
            self.assertTrue(menu.winfo_exists())
            menu.invoke(0); menu.invoke(1)
            importing.assert_called_once(); exporting.assert_called_once()

    def test_nr_type_export_and_import_roundtrip_preserve_output(self):
        import json
        path = self.store.path.parent/'quality.json'
        original = self.ui.collect()
        self.ui.preset_scope.set('nr'); self.ui._preset_scope_changed()
        with mock.patch('dlss5tool.realtime_ui.filedialog.asksaveasfilename', return_value=str(path)):
            self.ui.export_config()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['kind'], 'nr-only')
        config = deepcopy(original); config['window_scale'] = 2.0; self.ui.apply_config(config)
        with mock.patch('dlss5tool.realtime_ui.filedialog.askopenfilename', return_value=str(path)):
            self.ui.import_config()
        self.assertEqual(self.ui.collect()['window_scale'], 2.0)
        self.client.start.assert_not_called()

    def test_region_editing_is_draft_until_apply_and_can_move_resize_delete(self):
        editor = self.editor()
        editor.begin(self.point(editor, .1, .2)); editor.end(self.point(editor, .4, .6))
        self.assertEqual(self.ui.collect()['quality']['regions'], [])
        editor.begin(self.point(editor, .2, .3)); editor.end(self.point(editor, .3, .4))
        self.assertAlmostEqual(editor.regions[0][0], .2)
        editor.begin(self.point(editor, .5, .7)); editor.end(self.point(editor, .8, .9))
        self.assertAlmostEqual(editor.regions[0][2], .8)
        editor.apply()
        self.assertEqual(self.ui.collect()['quality']['regions'], [[.2, .3, .8, .9]])
        self.assertTrue(self.ui.collect()['quality']['protection'])
        self.ui.source_preview.edit_regions(); editor = self.ui.source_preview.editor
        editor.selected = 0; editor.delete(); editor.close()
        self.assertEqual(len(self.ui.collect()['quality']['regions']), 1)

    def test_letterbox_clicks_and_fifth_region_are_rejected(self):
        editor = self.editor([[.1, .1, .2, .2], [.3, .1, .4, .2], [.5, .1, .6, .2], [.7, .1, .8, .2]])
        editor.begin(SimpleNamespace(x=0, y=0)); self.assertIsNone(editor.drag)
        editor.begin(self.point(editor, .5, .8)); self.assertEqual(len(editor.regions), 4)
        self.assertEqual(editor.hint.get(), i18n.tr('realtime.regions_limit'))
        before = self.ui.collect()
        self.ui._active = True; self.ui._notify_session()
        self.assertIsNone(self.ui.source_preview.editor); self.assertEqual(self.ui.collect(), before)

    def test_compact_preset_scope_routes_actions_and_preserves_selections(self):
        self.store.data['presets']['full'] = deepcopy(DEFAULT_CONFIG)
        self.store.data['nr_presets'] = {'nr': nr_preset(DEFAULT_CONFIG)}
        self.ui.preset_choice.configure(values=['full']); self.ui.preset_choice.set('full')
        self.ui.nr_choice.configure(values=['nr']); self.ui.nr_choice.set('nr')
        self.ui._preset_scope_changed()
        self.assertEqual(self.ui.preset_load.cget('state'), 'normal')
        with mock.patch.object(self.ui, 'load_preset') as full, mock.patch.object(self.ui, 'load_nr') as nr:
            self.ui.preset_load.invoke(); full.assert_called_once(); nr.assert_not_called()
            self.ui.preset_scope.set('nr'); self.ui._preset_scope_changed(); self.root.update()
            self.ui.preset_load.invoke(); nr.assert_called_once()
        self.assertTrue(self.ui.nr_export.get()); self.assertFalse(self.ui.bind_app_toggle.winfo_manager())
        self.assertFalse(self.ui.preset_choice.winfo_manager())
        self.ui.preset_scope.set('full'); self.ui._preset_scope_changed()
        self.assertEqual(self.ui.preset_choice.get(), 'full'); self.assertEqual(self.ui.nr_choice.get(), 'nr')
        self.assertFalse(self.ui.nr_export.get())
        self.client.start.assert_not_called()

    def test_narrow_preset_actions_wrap_below_picker(self):
        self.ui.presets_section.toggle()
        self.root.geometry('840x680'); self.root.update()
        self.assertEqual(self.ui.preset_actions.grid_info()['row'], 1)
        self.assertLessEqual(self.ui.preset_actions.winfo_width(), self.ui.preset_row.winfo_width())

    def test_source_icons_and_border_fit_both_languages_and_themes(self):
        preview = self.ui.source_preview
        self.root.deiconify()
        self.root.geometry('800x680')
        for theme in ('light', 'dark'):
            colors = ui_theme.tokens(theme)
            preview.apply_theme(colors)
            self.assertEqual(int(preview.canvas.cget('highlightthickness')), 1)
            self.assertEqual(preview.canvas.cget('highlightbackground'), colors['line'])
            for language in i18n.SUPPORTED_LANGUAGES:
                for button, action, icon in ((preview.refresh_button, 'refresh', 'retry'),
                                             (preview.edit_button, 'regions', 'scan')):
                    button.configure(text=i18n.tr_for(language, 'realtime.preview.'+action))
                    self.root.update()
                    self.assertTrue(button._icon_only)
                    self.assertIsNotNone(button._icon_image)
                    self.assertEqual(button.cget('icon'), icon)
                    self.assertLessEqual(button.winfo_width(), 40)
                    self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),
                                         preview.winfo_rootx()+preview.winfo_width())
                    self.assertTrue(button.bind('<FocusIn>'))

    def test_placeholder_follows_source_and_busy_state(self):
        preview = self.ui.source_preview
        def text():
            return [preview.canvas.itemcget(item, 'text') for item in preview.canvas.find_all()
                    if preview.canvas.type(item) == 'text']
        self.assertEqual(text(), [i18n.tr('realtime.preview.placeholder')])
        self.select(); self.ui._notify_session()
        self.assertEqual(text(), [i18n.tr('realtime.preview.placeholder_selected')])
        self.ui._active = True; self.ui._notify_session()
        self.assertEqual(text(), [i18n.tr('realtime.preview.placeholder_busy')])
        self.ui._active = False; self.ui._notify_session()
        self.assertEqual(text(), [i18n.tr('realtime.preview.placeholder_selected')])

    def test_wrapped_placeholder_keeps_icon_clear_of_text(self):
        preview = self.ui.source_preview
        previous = i18n.get_language()
        try:
            for language in i18n.SUPPORTED_LANGUAGES:
                i18n.set_language(language)
                with mock.patch.object(preview.canvas, 'winfo_width', return_value=240), \
                     mock.patch.object(preview.canvas, 'winfo_height', return_value=180):
                    preview.draw()
                items = {preview.canvas.type(item): preview.canvas.bbox(item) for item in preview.canvas.find_all()}
                self.assertGreaterEqual(items['text'][1]-items['image'][3], 10)
                self.assertGreaterEqual(items['image'][1], 0)
                self.assertLessEqual(items['text'][3], 180)
        finally:
            i18n.set_language(previous)
