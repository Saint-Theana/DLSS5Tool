"""Safety deadlines and transport tests never register a real global hotkey."""
import queue
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from dlss5tool.realtime import RealtimeClient
from dlss5tool.realtime_safety import RealtimeSafety, STOP_TIMEOUT, WRITE_TIMEOUT


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.process = mock.Mock()
        self.process.poll.return_value = None
        self.platform = mock.Mock()
        self.safety = RealtimeSafety(lambda: None, self.events.append)
        self.safety.bind(self.process)
        self.safety.starting()

    def test_healthy_static_source_has_no_frame_timeout(self):
        self.safety.check(100000, self.platform)
        self.process.terminate.assert_not_called()

    def test_repeated_stop_never_extends_deadline(self):
        self.safety.request_stop(now=0)
        self.safety.request_stop(now=1)
        self.safety.check(STOP_TIMEOUT, self.platform)
        self.process.terminate.assert_called_once()
        self.assertEqual(self.events[0]['reason'], 'stop_timeout')

    def test_native_idle_ack_disarms_stop(self):
        self.safety.request_stop(now=0)
        self.safety.observe({'event': 'state', 'state': 0})
        self.safety.check(10, self.platform)
        self.process.terminate.assert_not_called()

    def test_queued_idle_status_does_not_disarm_stop(self):
        self.safety.request_stop(now=0)
        self.safety.observe({'event': 'status', 'state': 0})
        self.safety.check(10, self.platform)
        self.process.terminate.assert_called_once()

    def test_quit_deadline_survives_idle_ack(self):
        self.safety.request_stop(quitting=True, now=0)
        self.safety.observe({'event': 'state', 'state': 0})
        self.safety.check(10, self.platform)
        self.process.terminate.assert_called_once()

    def test_native_toolbar_stop_also_gets_deadline(self):
        with mock.patch('dlss5tool.realtime_safety.time.monotonic', return_value=0):
            self.safety.observe({'event': 'state', 'state': 3})
        self.safety.check(STOP_TIMEOUT, self.platform)
        self.process.terminate.assert_called_once()

    def test_blocked_write_arms_independent_termination(self):
        self.safety.writing(True, now=0)
        self.safety.check(WRITE_TIMEOUT, self.platform)
        self.assertEqual(self.events[0]['reason'], 'write_timeout')
        self.process.terminate.assert_called_once()

    def test_completed_write_disarms_only_write_deadline(self):
        self.safety.request_stop(now=0)
        self.safety.writing(True, now=0)
        self.safety.writing(False)
        self.safety.check(10, self.platform)
        self.process.terminate.assert_called_once()

    def test_abnormal_exit_restores_cursor_once_after_death(self):
        self.safety.request_stop(now=0)
        self.safety.check(STOP_TIMEOUT, self.platform)
        self.platform.restore_cursor.assert_not_called()
        self.process.poll.return_value = 1
        self.safety.check(3, self.platform)
        self.safety.check(4, self.platform)
        self.platform.restore_cursor.assert_called_once()

    def test_idle_host_exit_does_not_touch_another_app_cursor(self):
        self.safety.observe({'event': 'state', 'state': 0})
        self.process.poll.return_value = 0
        self.safety.check(10, self.platform)
        self.platform.restore_cursor.assert_not_called()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.client = RealtimeClient()
        self.client.process = mock.Mock()
        self.client.process.poll.return_value = None
        self.client._outgoing = queue.Queue(maxsize=2)
        self.client._safety = mock.Mock()

    def test_ui_send_does_not_write_to_pipe(self):
        sequence = self.client.send('parameters')
        self.assertEqual(sequence, 1)
        self.assertIn('parameters', self.client._outgoing.get_nowait())
        self.client.process.stdin.write.assert_not_called()
        self.client.process.stdin.flush.assert_not_called()

    def test_stop_arms_deadline_before_queueing(self):
        self.client.send('stop')
        self.client._safety.request_stop.assert_called_once_with(quitting=False)

    def test_full_queue_arms_quit_deadline_without_blocking(self):
        self.client.send('status')
        self.client.send('status')
        with self.assertRaises(RuntimeError):
            self.client.send('stop')
        self.client._safety.request_stop.assert_any_call(quitting=True)

    @unittest.skipUnless(os.name == 'nt', 'Windows host transport')
    def test_real_unread_pipe_cannot_block_send_or_close(self):
        folder = Path(__file__).resolve().parents[1] / 'tmp/realtime-parameter-fix-20261007'
        folder.mkdir(parents=True, exist_ok=True)
        real_popen = subprocess.Popen
        platform = mock.Mock(registered=False)
        platform.pressed.return_value = False
        def child(*args, **kwargs):
            return real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        with tempfile.TemporaryDirectory(dir=folder) as directory, \
                mock.patch('dlss5tool.realtime.paths.state_path', return_value=Path(directory)), \
                mock.patch('dlss5tool.realtime_safety.WindowsStopControl', return_value=platform), \
                mock.patch('dlss5tool.realtime.subprocess.Popen', side_effect=child):
            client = RealtimeClient(host=sys.executable)
            client.launch()
            process = client.process
            try:
                start = time.monotonic()
                client.send('quality', payload='x' * 500000)
                self.assertLess(time.monotonic() - start, 1)
                time.sleep(.1)  # Writer now fills the unread pipe, independently of Tk.
                start = time.monotonic()
                client.close()
                self.assertLess(time.monotonic() - start, 5)
                self.assertIsNotNone(process.poll())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
                client.close()


if __name__ == '__main__':
    unittest.main()
