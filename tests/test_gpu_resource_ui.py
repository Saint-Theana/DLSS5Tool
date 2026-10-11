"""Run each case in a fresh process with appearance_validation.py."""
import threading
from pathlib import Path
import unittest
import numpy as np
from unittest import mock
from tests import test_workbench_ui as workbench
from dlss5tool import gui


class ResourceUiTests(unittest.TestCase):
    setUp = workbench.WorkbenchUiTests.setUp
    tearDown = workbench.WorkbenchUiTests.tearDown

    def test_export_blocks_realtime_without_cancelling_or_changing_settings(self):
        app = self.app
        app._select_workbench_mode('realtime')
        before = app._collect_settings()
        app._exporting = True
        try:
            app._realtime_workspace.start()
            self.client.start.assert_not_called()
            self.assertFalse(app._export_cancel_event.is_set())
            self.assertEqual(app._collect_settings(), before)
            self.assertIn('导出', app._realtime_workspace.status.get())
        finally:
            app._exporting = False

    def test_release_yields_ui_and_requires_explicit_retry(self):
        app = self.app
        app._select_workbench_mode('realtime')
        finished = threading.Event()
        app._play_dlss_thread = threading.Thread(target=lambda: finished.wait(3))
        app._play_dlss_thread.start()
        app._live = live = mock.Mock()
        tick = []
        self.root.after(0, lambda: tick.append(True))
        try:
            self.assertFalse(app._can_start_realtime())
            self.root.update()
            self.assertEqual(tick, [True])
            self.assertFalse(app._can_start_realtime())
            self.assertFalse(app._local_gpu_allowed())
            live.close.assert_not_called()
        finally:
            finished.set()
            app._gpu_release_thread.join(4)
        app._poll_gpu_release()
        live.close.assert_called_once()
        self.assertTrue(app._can_start_realtime())
        self.client.start.assert_not_called()

    def test_realtime_stopping_blocks_all_local_gpu_entry_points(self):
        app = self.app
        app._select_workbench_mode('realtime')
        ui = app._realtime_workspace
        self.client.send.reset_mock()
        ui._stop_requested = True
        app._select_workbench_mode('local')
        try:
            self.assertFalse(app._local_gpu_allowed())
            self.assertFalse(app._start_prefetch())
            self.assertIsNone(app._shared_ready())
            with mock.patch.object(gui.messagebox, 'showinfo') as info:
                app.export_dlss()
                app.start_export_queue()
                app._start_guidance_export()
                self.assertEqual(info.call_count, 3)
            self.client.send.assert_not_called()
        finally:
            ui._stop_requested = False
        self.assertTrue(app._local_gpu_allowed())

    def test_export_reserves_before_wait_and_cleans_failed_admission(self):
        app = self.app
        app._select_workbench_mode('realtime')
        def wait():
            self.assertTrue(app._exporting)
            self.assertFalse(app._can_start_realtime())
            return False
        with mock.patch.object(app, '_wait_play_dlss', side_effect=wait):
            with self.assertRaises(RuntimeError):
                app._begin_export_ui('test')
        self.assertFalse(app._exporting)

    def test_image_export_reports_late_conflict_without_writing(self):
        app = self.app
        settings = app._collect_settings()
        with mock.patch.object(gui, 'read_still', return_value=(np.zeros((16, 16, 3), np.uint8), None)), \
                mock.patch.object(app, '_begin_export_ui', side_effect=RuntimeError('late conflict')), \
                mock.patch.object(app, '_process_still_image') as process:
            result = app._export_image_source(str(Path(self.temp.name)/'source.png'), settings, notify=False)
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'late conflict')
        process.assert_not_called()

    def test_release_failure_does_not_claim_gpu_idle(self):
        app = self.app
        app._select_workbench_mode('realtime')
        app._live = live = mock.Mock()
        live.close.side_effect = RuntimeError('close failed')
        self.assertFalse(app._can_start_realtime())
        app._gpu_release_thread.join(4)
        app._poll_gpu_release()
        self.assertFalse(app._can_start_realtime())
        self.assertEqual(app._gpu_resource_snapshot()['occupants'][0]['phase'], 'failed')
        self.assertIs(app._live, live)

    def test_deep_diagnostics_cannot_enter_during_release(self):
        app = self.app
        app._gpu_release_error = 'release failed'
        with mock.patch.object(gui.messagebox, 'showinfo') as info, \
                mock.patch.object(gui.messagebox, 'askyesno') as ask:
            app.export_diagnostics(deep=True)
            info.assert_called_once()
            ask.assert_not_called()
