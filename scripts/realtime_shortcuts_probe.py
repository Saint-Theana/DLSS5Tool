"""Bounded native shortcut registration/rollback check. Never starts rendering or injects keys."""
import argparse
import json
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dlss5tool.realtime import RealtimeClient
    from dlss5tool.realtime_safety import WindowsStopControl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    directory = args.work_dir.resolve()
    if directory == ROOT / 'tmp' or not directory.is_relative_to(ROOT / 'tmp'):
        parser.error('--work-dir must be a task subdirectory of tmp')
    baseline = dict(stop='Ctrl+Shift+F19', compare='Ctrl+Shift+F20',
                    profiler='Ctrl+Shift+F21', parameters='Ctrl+Shift+F22')
    changed = {k: v.replace('Ctrl+Shift', 'Ctrl+Alt+Shift') for k, v in baseline.items()}
    client = RealtimeClient(host=args.host)
    client.hotkeys = baseline
    occupied = None
    with mock.patch('dlss5tool.realtime.paths.state_path', return_value=directory / 'native-state'):
        try:
            client.launch()
            assert client._handshake.wait(8), 'Initial handshake timeout'
            assert client._handshake_event['hotkey_bindings'] == baseline
            assert client._handshake_event['independent_stop'] is True
            assert all(client._handshake_event['hotkeys'].values()), 'Test keys already occupied'
            client.configure_hotkeys(changed)
            assert client._handshake_event['hotkey_bindings'] == changed
            released = WindowsStopControl(baseline['stop'])
            try:
                assert released.registered, 'Old stop key was not released'
            finally:
                released.close()
            occupied = WindowsStopControl('Ctrl+Alt+Shift+F23')
            assert occupied.registered, 'Conflict fixture key already in use'
            rejected = False
            try:
                client.configure_hotkeys(dict(changed, stop='Ctrl+Alt+Shift+F23'))
            except RuntimeError:
                rejected = True
            assert rejected, 'Occupied emergency key was accepted'
            assert client.hotkeys == changed, 'Previous mapping lost'
            assert client._handshake_event['hotkey_bindings'] == changed
            assert all(client._handshake_event['hotkeys'].values()), 'Previous registrations not restored'
            assert client._handshake_event['independent_stop'] is True
            print(json.dumps(dict(ok=True, rebound=True, old_key_released=True,
                                  conflict_rejected=True, rollback_registered=True,
                                  independent_stop=True, rendering_started=False)))
        finally:
            client.close()
            if occupied:
                occupied.close()
    for chord in changed.values():
        released = WindowsStopControl(chord)
        try:
            assert released.registered, 'Shortcut registration leaked after close'
        finally:
            released.close()


if __name__ == '__main__':
    main()
