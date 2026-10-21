"""Admission regression tests requiring no GPU, OpenCV or model downloads."""
import unittest
from unittest import mock

from dlss5tool import i18n, memory_budget as mb

GIB = 1024**3


def memory(free=8 * GIB, commit=8 * GIB):
    return dict(total_physical_bytes=32 * GIB,
                free_physical_bytes=free, free_commit_bytes=commit)


class AdmissionRefreshTests(unittest.TestCase):
    def test_user_diagnostic_snapshot_does_not_deny_13_mib(self):
        snapshot = dict(total_physical_bytes=34181894144,
                        free_physical_bytes=14868754432,
                        free_commit_bytes=6649380864)
        expected = 6649380864 - 34181894144 // 8
        self.assertEqual(mb.memory_headroom_bytes(memory=snapshot), expected)
        with mock.patch.object(mb, 'system_memory', return_value=snapshot) as read:
            mb.require_memory_headroom(1728 * 960 * 4 * 2)
        read.assert_called_once_with()

    def test_stale_denial_recovers_after_cache_or_worker_release(self):
        with mock.patch.object(mb, 'system_memory', side_effect=[memory(free=GIB), memory()]) as read:
            mb.require_memory_headroom(13 * 1024**2)
        self.assertEqual(read.call_args_list, [mock.call(), mock.call(refresh=True)])

    def test_physical_commit_and_reserve_boundary_still_deny(self):
        for snapshot in (memory(free=0), memory(commit=0), memory(free=4 * GIB),
                         memory(commit=4 * GIB)):
            with self.subTest(snapshot=snapshot), mock.patch.object(mb, 'system_memory', return_value=snapshot):
                with self.assertRaises(MemoryError):
                    mb.require_memory_headroom(1)

    def test_unavailable_refresh_cannot_turn_known_denial_into_allowance(self):
        for unavailable in (None, dict(total_physical_bytes=0)):
            with self.subTest(unavailable=unavailable), mock.patch.object(
                    mb, 'system_memory', side_effect=[memory(commit=GIB), unavailable]):
                with self.assertRaisesRegex(MemoryError, 'fresh_snapshot=False'):
                    mb.require_memory_headroom(1)

    def test_initially_unknown_snapshot_retains_existing_policy(self):
        with mock.patch.object(mb, 'system_memory', return_value=None) as read:
            mb.require_memory_headroom(10 * GIB)
        read.assert_called_once_with()

    def test_exact_boundary_and_zero_allocation(self):
        with mock.patch.object(mb, 'system_memory', return_value=memory(free=4 * GIB + 13)):
            mb.require_memory_headroom(13)
            with self.assertRaises(MemoryError):
                mb.require_memory_headroom(14)
        with mock.patch.object(mb, 'system_memory', return_value=memory(free=0)):
            mb.require_memory_headroom(0)

    def test_diagnostic_numbers_come_from_same_fresh_snapshot(self):
        fresh = memory(free=7 * GIB, commit=4 * GIB + 12)
        original_language = i18n.get_language()
        try:
            for language in ('zh_CN', 'en_US'):
                i18n.set_language(language)
                with self.subTest(language=language), mock.patch.object(
                        mb, 'system_memory', side_effect=[memory(free=0), fresh]):
                    with self.assertRaises(MemoryError) as caught:
                        mb.require_memory_headroom(13)
                    message = str(caught.exception)
                    for field in ('required=13', 'available=12',
                                  f'physical_free={7 * GIB}', f'commit_free={4 * GIB + 12}',
                                  f'reserve={4 * GIB}', 'fresh_snapshot=True'):
                        self.assertIn(field, message)
                    self.assertNotIn('message.ram_headroom_details', message)
        finally:
            i18n.set_language(original_language)

    def test_cache_and_queue_limits_are_unchanged(self):
        with mock.patch.object(mb, 'system_memory', return_value=memory(free=GIB)):
            self.assertEqual(mb.cache_limit_bytes(8 * GIB, 8 * GIB), 5 * GIB)
            self.assertEqual(mb.bounded_frame_count(16, 1024), 0)
        with mock.patch.object(mb, 'system_memory', return_value=memory()):
            self.assertEqual(mb.bounded_frame_count(16, 256 * 1024**2), 4)

    def test_shutdown_command_still_works_under_pressure(self):
        connection = mock.Mock()
        connection.poll.return_value = True
        for operation in ('stop', 'close'):
            connection.recv.return_value = dict(operation=operation)
            with mock.patch.object(mb, 'system_memory', return_value=memory(free=0)) as read:
                self.assertEqual(mb.receive_worker_command(connection, 1024), dict(operation=operation))
            read.assert_not_called()

    def test_worker_still_denies_processing_and_idle_pressure(self):
        connection = mock.Mock()
        connection.recv.return_value = dict(operation='process')
        for ready in (True, False):
            connection.poll.return_value = ready
            with self.subTest(ready=ready), mock.patch.object(mb, 'system_memory', return_value=memory(free=0)):
                with self.assertRaises(MemoryError):
                    mb.receive_worker_command(connection, 1024)

    def test_forced_snapshot_bypasses_ttl_and_updates_shared_cache(self):
        def status(pointer):
            pointer._obj.total_physical = 32 * GIB
            pointer._obj.free_physical = 8 * GIB
            pointer._obj.free_commit = 9 * GIB
            return 1
        stale = memory(free=GIB)
        with mock.patch.object(mb, '_snapshot', stale), \
                mock.patch.object(mb, '_snapshot_time', 10.0), \
                mock.patch.object(mb.time, 'monotonic', return_value=10.1), \
                mock.patch.object(mb, '_status_function', return_value=mock.Mock(side_effect=status)) as function:
            self.assertIs(mb.system_memory(), stale)
            function.assert_not_called()
            fresh = mb.system_memory(refresh=True)
            self.assertEqual(fresh, memory(commit=9 * GIB))
            self.assertIs(mb.system_memory(), fresh)
            function.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
