import threading
import unittest
from unittest import mock
from dlss5tool.gpu_resources import GpuResourceGuard, Occupancy, conflict


class ResourcePolicyTests(unittest.TestCase):
    def test_exclusive_owners_block_both_routes(self):
        for owner in ('export', 'diagnostics', 'backend', 'release'):
            for phase in ('starting', 'running', 'stopping', 'releasing', 'failed'):
                item = Occupancy(owner, phase)
                for operation in ('realtime', 'queue', 'preview', 'export'):
                    with self.subTest(owner=owner, phase=phase, operation=operation):
                        self.assertIs(conflict(operation, [item]), item)

    def test_queue_child_export_and_preview_cache_reuse(self):
        self.assertIsNone(conflict('export', [Occupancy('queue', 'running'), Occupancy('preview', 'running')]))
        self.assertIsNone(conflict('preview', [Occupancy('preview', 'running')]))
        self.assertIsNotNone(conflict('realtime', [Occupancy('preview', 'running')]))
        self.assertIsNotNone(conflict('diagnostics', [Occupancy('preview', 'running')]))
        self.assertIsNotNone(conflict('preview', [Occupancy('queue', 'running')]))

    def test_realtime_restart_owned_by_existing_state_machine(self):
        for phase in ('starting', 'running', 'stopping', 'releasing'):
            item = Occupancy('realtime', phase)
            self.assertIsNone(conflict('realtime', [item]))
            for operation in ('export', 'queue', 'preview'):
                self.assertIs(conflict(operation, [item]), item)

    def test_observed_tasks_clear_without_stale_leases(self):
        app = GpuResourceGuard()
        self.assertIsNone(app._gpu_conflict('realtime'))
        app._exporting = True
        self.assertEqual(app._gpu_conflict('realtime').owner, 'export')
        app._exporting = False
        self.assertIsNone(app._gpu_conflict('realtime'))
        app._gpu_release_error = 'close failed'
        self.assertEqual(app._gpu_conflict('realtime').phase, 'failed')

    def test_hidden_local_workbench_does_not_reallocate_after_handoff(self):
        app = GpuResourceGuard()
        app._workbench_mode = 'realtime'
        self.assertFalse(app._local_gpu_allowed())
        self.assertIsNone(app._gpu_conflict('realtime'))

    def make_app(self):
        app = GpuResourceGuard()
        for name in ('pause', '_freeze_preview_cache', '_cancel_after', '_shared_retire', '_cache_clear', 'set_status'):
            setattr(app, name, mock.Mock())
        app.root = mock.Mock()
        app._live_lock = threading.Lock()
        app._super_resolution_lock = threading.Lock()
        app._live = mock.Mock()
        return app

    def test_async_release_waits_for_old_worker(self):
        app = self.make_app()
        live = app._live
        wait = threading.Event()
        old = app._play_dlss_thread = threading.Thread(target=lambda: wait.wait(3))
        old.start()
        try:
            app._release_preview_for_realtime()
            self.assertTrue(app._gpu_release_thread.is_alive())
            self.assertFalse(app._local_gpu_allowed())
            live.close.assert_not_called()
        finally:
            wait.set()
            app._gpu_release_thread.join(4)
        live.close.assert_called_once()
        self.assertIsNone(app._live)
        self.assertIsNone(app._gpu_conflict('realtime'))

    def test_close_failure_blocks_admission(self):
        app = self.make_app()
        app._live.close.side_effect = RuntimeError('native close failed')
        app._release_preview_for_realtime()
        app._gpu_release_thread.join(4)
        self.assertEqual(app._gpu_conflict('realtime').phase, 'failed')
        self.assertIsNotNone(app._live)
