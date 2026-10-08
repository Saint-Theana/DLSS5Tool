"""Control plane contracts, independent of GPU and desktop contents."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest import mock

from dlss5tool.realtime import (DEFAULT_CONFIG, PresetStore, RealtimeClient, validate_config,
                               merge_overlay_effects, nr_preset, apply_nr_preset, performance_profile, portable_config)


class RealtimeConfigTests(unittest.TestCase):
    def test_new_session_windowed_default_preserves_old_presets(self):
        self.assertTrue(DEFAULT_CONFIG['windowed'])
        self.assertTrue(validate_config(DEFAULT_CONFIG)['windowed'])
        self.assertFalse(validate_config({})['windowed'])
        self.assertFalse(validate_config({'windowed': False})['windowed'])
        self.assertTrue(validate_config({'windowed': True})['windowed'])
        self.assertEqual(validate_config({'capture_method': 1})['capture_method'], 1)

    def test_nr_missing_pass_count_defaults_to_one_but_explicit_presets_survive(self):
        from dlss5tool.realtime import NR
        self.assertEqual(DEFAULT_CONFIG['effects'][0]['parameters']['multiPass'], 1)
        source = {'effects': [{'name': NR, 'parameters': {'pass3_intensity': 1.5}}]}
        value = validate_config(source)
        self.assertEqual(value['effects'][0]['parameters']['multiPass'], 1)
        self.assertNotIn('multiPass', source['effects'][0]['parameters'])
        source['effects'][0]['parameters']['multiPass'] = 3
        self.assertEqual(validate_config(source)['effects'][0]['parameters']['multiPass'], 3)

    def test_portable_preset_excludes_machine_selection(self):
        source = validate_config({'gpu_index': 3, 'gpu_vendor': 0x10de, 'gpu_device': 1,
                                  'monitor_mode': 2, 'monitor_id': 'machine-specific'})
        value = portable_config(source)
        self.assertEqual(value['gpu_index'], -1)
        self.assertEqual((value['monitor_id'], value['monitor_mode']), ('', 0))
        self.assertNotIn('gpu_vendor', value)
        self.assertNotIn('gpu_device', value)
        self.assertEqual(value['effects'], source['effects'])
        self.assertEqual(source['gpu_index'], 3)

    def test_nr_only_preserves_other_effects_and_devices(self):
        config = validate_config({'gpu_index': 2, 'frame_rate': 45})
        config['effects'].append({'name': 'DLSS\\DLSS_SR', 'parameters': {'quality': 2}, 'scale': [2, 2]})
        preset = nr_preset(DEFAULT_CONFIG)
        preset['quality']['total'] = .25
        result = apply_nr_preset(config, preset)
        self.assertEqual(result['effects'][1], config['effects'][1])
        self.assertEqual(result['frame_rate'], 45)
        self.assertEqual(result['gpu_index'], 2)
        self.assertEqual(result['quality']['total'], .25)
        preset['runtime'] = 'evil.dll'
        with self.assertRaises(ValueError): apply_nr_preset(config, preset)

    def test_performance_profile_never_downgrades_quality(self):
        for name in ('balanced', 'game', 'eco', 'quality'):
            result = performance_profile(DEFAULT_CONFIG, name)
            self.assertEqual(result['quality'], DEFAULT_CONFIG['quality'])
            self.assertEqual(result['effects'], DEFAULT_CONFIG['effects'])
    def test_defaults_are_isolated(self):
        value = validate_config({})
        value['quality']['regions'].append([0, 0, 1, 1])
        self.assertEqual(DEFAULT_CONFIG['quality']['regions'], [])

    def test_import_rejects_paths_and_nan(self):
        for value in ({'host': 'x.exe'}, {'runtime': 'x.dll'}, {'frame_rate': float('nan')},
                      {'frame_rate': True}, {'gpu_index': 1.5}, {'window_scale': 0},
                      {'effects': [{'name': '../escape'}]}, {'effects': []},
                      {'quality': {'total': float('inf')}}, {'quality': {'regions': [[0, 0, 0, 1]]}},
                      {'quality': {'regions': [[0, 0, 1, 1]] * 5}}, {'quality': {'protection': 1}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config(value)

    def test_incompatible_windowed_modes_rejected(self):
        for value in ({'windowed': True, 'game_mode': True}, {'windowed': True, 'capture_method': 1}):
            with self.assertRaises(ValueError):
                validate_config(value)

    def test_preset_normalizes_legacy_config(self):
        value = validate_config({'effects': [{'name': 'Bilinear'}]})
        self.assertIn('quality', value)
        self.assertEqual(value['window_scale'], 1)

    def test_overlay_three_way_merge_preserves_unrelated_edits(self):
        before = [{'name': 'Bilinear', 'parameters': {'a': 1, 'b': 1}}]
        after = [{'name': 'Bilinear', 'parameters': {'a': 2, 'b': 1}}]
        current = {'effects': [{'name': 'Bilinear', 'parameters': {'a': 1, 'b': 3}}]}
        self.assertEqual(merge_overlay_effects(current, before, after)['effects'][0]['parameters'], {'a': 2, 'b': 3})
        current['effects'][0]['parameters']['a'] = 4
        with self.assertRaises(ValueError):
            merge_overlay_effects(current, before, after)


class RealtimeStoreTests(unittest.TestCase):
    def setUp(self):
        work = Path(__file__).resolve().parents[1] / 'tmp/realtime-integration-20261003'
        work.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='unit-', dir=work)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'presets.json'

    def test_save_reload_and_casefold_application(self):
        store = PresetStore(self.path)
        store.save(' test ', {}, 'C:/Games/Example.EXE')
        store.save_session({'frame_rate': 30})
        loaded = PresetStore(self.path)
        self.assertEqual(loaded.for_application('c:/games/example.exe'), validate_config({}))
        self.assertEqual(loaded.data['session']['frame_rate'], 30)

    def test_local_runtime_and_nr_presets_reload_but_do_not_export_paths(self):
        store = PresetStore(self.path)
        store.save_runtime_directory(self.path.parent)
        store.save_nr('NR only', DEFAULT_CONFIG)
        loaded = PresetStore(self.path)
        self.assertEqual(loaded.data['local']['runtime_directory'], str(self.path.parent))
        self.assertEqual(loaded.data['nr_presets']['NR only'], nr_preset(DEFAULT_CONFIG))
        self.assertNotIn('local', nr_preset(DEFAULT_CONFIG))

    def test_failed_replace_preserves_data_and_cleans_owned_pending(self):
        store = PresetStore(self.path)
        store.save('old', {})
        content = self.path.read_bytes()
        old = deepcopy(store.data)
        with mock.patch('dlss5tool.realtime.os.replace', side_effect=OSError('denied')):
            with self.assertRaises(OSError):
                store.save('new', {})
        self.assertEqual(store.data, old)
        self.assertEqual(self.path.read_bytes(), content)
        self.assertFalse(self.path.with_suffix('.json.pending').exists())

    def test_corrupt_tables_fail_without_overwriting(self):
        for data in ([], {'version': 2}, {'version': 1, 'presets': []}):
            self.path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                PresetStore(self.path)


class RealtimeClientTests(unittest.TestCase):
    def test_runtime_commands_never_relaunch_after_crash(self):
        client = RealtimeClient()
        client.launch = mock.Mock(side_effect=AssertionError('must not launch'))
        for command in ('stop', 'status', 'quality', 'screenshot', 'set_parameter'):
            with self.assertRaises(RuntimeError): client.send(command)
        client.launch.assert_not_called()
    def test_stale_event_never_enters_current_generation(self):
        client = RealtimeClient(); client.generation = 2
        client._put({'event': 'state', 'state': 2}, 1)
        self.assertTrue(client.events.empty())
        client._put({'event': 'state', 'state': 0}, 2)
        self.assertEqual(client.events.get_nowait()['_generation'], 2)

    def test_bounded_events_report_overflow(self):
        client = RealtimeClient(); client.events = queue.Queue(maxsize=2)
        for _ in range(4): client._put({'event': 'status'})
        self.assertEqual(client.events.qsize(), 2)
        self.assertTrue(any(client.events.get_nowait()['event'] == 'error' for _ in range(2)))

    def test_close_does_not_relaunch_dead_child(self):
        client = RealtimeClient()
        client.process = mock.Mock()
        client.process.poll.return_value = 0
        client.launch = mock.Mock(side_effect=AssertionError('must not launch'))
        client.close()
        client.launch.assert_not_called()
        self.assertIsNone(client.process)


if __name__ == '__main__':
    unittest.main()
