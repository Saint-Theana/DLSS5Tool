"""Never convert configuration/synthetic success to full hardware acceptance."""
from copy import deepcopy
import unittest
from unittest import mock
from pathlib import Path
import tempfile
from dlss5tool import i18n
from dlss5tool.realtime import DEFAULT_CONFIG
from dlss5tool.realtime import RealtimeClient
from tests import test_realtime_readiness as readiness
from scripts.realtime_p2_probe import cases, summarize, PENDING


class P2ReadinessTests(unittest.TestCase):
    setUp = readiness.ReadinessTests.setUp
    check = readiness.ReadinessTests.check

    def devices(self):
        return {'monitors': [{'id': 'primary', 'hdr_active': False}],
                'adapters': [{'index': 0, 'software': False, 'vendor': 0x10de}],
                'capabilities': {'amdoF': False, 'nvof': True}}

    def test_missing_devices_block_without_changing_selection(self):
        source = deepcopy(DEFAULT_CONFIG)
        self.assertEqual(self.check(config=source, devices=self.devices()), [])
        source.update(windowed=False, monitor_mode=3, monitor_id='removed', gpu_index=7)
        issues = self.check(config=source, devices=self.devices())
        self.assertEqual({i.code for i in issues}, {'gpu_missing', 'monitor_missing'})
        self.assertTrue(all(i.blocking for i in issues))
        self.assertEqual(source['gpu_index'], 7)

    def test_unknown_snapshot_does_not_invent_failure(self):
        source = dict(deepcopy(DEFAULT_CONFIG), hdr=True, gpu_index=7)
        for devices in (None, {}):
            self.assertEqual(self.check(config=source, devices=devices), [])

    def test_hdr_blocks_known_sdr_but_not_unknown_or_mixed_displays(self):
        source = dict(deepcopy(DEFAULT_CONFIG), hdr=True)
        self.assertEqual([i.code for i in self.check(config=source, devices=self.devices())], ['hdr_display'])
        for monitors in ([], [{'id': 'unknown'}], [{'id': 'active', 'hdr_active': True}],
                         [{'id': 'active', 'hdr_active': True}, {'id': 'sdr', 'hdr_active': False}]):
            self.assertEqual(self.check(config=source, devices=dict(self.devices(), monitors=monitors)), [])

    def test_software_and_wrong_vendor_are_actionable(self):
        source = dict(deepcopy(DEFAULT_CONFIG), gpu_index=0)
        for adapter, code in (({'index': 0, 'software': True}, 'gpu_software'),
                              ({'index': 0, 'vendor': 0x1002}, 'gpu_vendor')):
            self.assertEqual([i.code for i in self.check(config=source, devices=dict(self.devices(), adapters=[adapter]))], [code])
        source['effects'] = [{'name': 'Bilinear'}]
        self.assertEqual(self.check(config=source, catalog={'Bilinear': {'available': True}},
                         devices={'adapters': [{'index': 0, 'vendor': 0x1002}]}), [])

    def test_uncompiled_flow_is_explicit_bilingual_and_passive(self):
        source = deepcopy(DEFAULT_CONFIG)
        source['effects'][0]['parameters']['opticalFlowMethod'] = 1
        for language in i18n.SUPPORTED_LANGUAGES:
            i18n.set_language(language)
            with mock.patch('subprocess.Popen', side_effect=AssertionError('passive')):
                issue = self.check(config=source, devices=self.devices())[0]
            self.assertEqual((issue.code, issue.effect_index), ('flow_unavailable', 0))
            self.assertNotIn('realtime.', issue.message)
        self.assertEqual(source['effects'][0]['parameters']['opticalFlowMethod'], 1)


class P2UiTests(unittest.TestCase):
    setUp = readiness.ReadinessUiTests.setUp
    tearDown = readiness.ReadinessUiTests.tearDown
    event = readiness.ReadinessUiTests.event
    select_target = readiness.ReadinessUiTests.select_target
    configure_checks = readiness.ReadinessUiTests.configure_checks

    def test_device_snapshot_generation_and_navigation(self):
        self.configure_checks()
        self.ui._device_snapshot = {'_generation': self.client.generation, 'adapters': [], 'monitors': []}
        self.ui.controls['gpu_index'][0].set('7')
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='ready'):
            self.ui.start()
        self.client.start.assert_not_called()
        self.assertEqual(self.ui._preflight_issues[0].code, 'gpu_missing')
        with mock.patch.object(self.ui, '_focus_page') as focus:
            self.ui.locate_button.invoke()
            focus.assert_called_once_with('runtime', self.ui.gpu_picker)
        self.ui.locate_button.invoke()
        self.root.update()
        self.assertTrue(self.ui.gpu_picker.winfo_ismapped())
        self.client.generation += 1
        with mock.patch('dlss5tool.realtime_ui.target_window_state', return_value='ready'), \
             mock.patch('dlss5tool.realtime_ui.check_start', return_value=[]) as check:
            self.ui.check_before_start()
        self.assertIsNone(check.call_args.kwargs['devices'])

    def test_device_event_invalidates_previous_confirmation(self):
        self.configure_checks()
        before = self.ui._preflight_state(self.ui.collect())
        self.event(dict(event='devices', monitors=[], adapters=[], capabilities={'nvof': True}))
        self.assertNotEqual(before, self.ui._preflight_state(self.ui.collect()))
        self.assertEqual(self.ui._device_snapshot['_generation'], self.client.generation)


class P2EvidenceTests(unittest.TestCase):
    def test_probe_client_state_root_never_resolves_user_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / 'host.exe'
            host.touch()
            client = RealtimeClient(host=host, state_root=root / 'isolated')
            with mock.patch('dlss5tool.realtime.paths.state_path', side_effect=AssertionError('user state')), \
                 mock.patch('dlss5tool.realtime_safety.RealtimeSafety'), \
                 mock.patch('dlss5tool.realtime.subprocess.Popen', side_effect=OSError('test stop')) as launch:
                with self.assertRaises(OSError):
                    client.launch()
            self.assertEqual(launch.call_args.kwargs['cwd'], (root / 'isolated').resolve())
            self.assertEqual(launch.call_args.kwargs['env']['DLSS5_REALTIME_STATE_ROOT'], str((root / 'isolated').resolve()))

    def data(self):
        return {'exit_ok': True, 'native_failures': [], 'events': [dict(event='status', run_id=1,
            probe_time=t, metrics=dict(real=t*10, submitted=t*20, generated=t*10,
            nr_evaluations=t*10, nr_failures=0)) for t in (5, 6, 7)]}

    def test_chain_requires_generated_frames_and_clean_shutdown(self):
        data = self.data()
        self.assertEqual(summarize(data, 'fg')['status'], 'passed')
        data['events'][-1]['metrics']['generated'] = 0
        self.assertEqual(summarize(data, 'fg')['status'], 'failed')
        self.assertEqual(summarize(dict(self.data(), exit_ok=False), 'render')['status'], 'failed')

    def test_missing_frames_errors_stalls_nonfinite_fail(self):
        for change in ('empty', 'error', 'nan', 'stall', 'regress', 'session'):
            data = self.data()
            if change == 'empty': data['events'] = []
            if change == 'error': data['native_failures'] = [{'event': 'error', 'message': 'GPU error'}]
            if change == 'nan': data['events'][0]['metrics']['age'] = float('nan')
            if change == 'stall': data['events'][-1]['probe_time'] = 40
            if change == 'regress': data['events'][-1]['metrics']['real'] = 1
            if change == 'session': data['events'][-1]['run_id'] = 2
            with self.subTest(change=change):
                self.assertEqual(summarize(data, 'fg')['status'], 'failed')

    def test_hdr_negative_test_is_not_end_to_end_acceptance(self):
        data = dict(self.data(), events=[], native_failures=[{'event': 'error', 'message': 'HDR output unavailable'}])
        self.assertEqual(summarize(data, 'hdr-reject')['status'], 'passed')
        data['native_failures'].append({'event': 'fatal', 'message': 'unrelated error'})
        self.assertEqual(summarize(data, 'hdr-reject')['status'], 'failed')
        self.assertTrue(any('HDR source' in p for p in PENDING))

    def test_duplicate_adapters_not_counted_as_physical_boards(self):
        devices = {'adapters': [{'index': n, 'vendor': 0x10de} for n in range(5)],
                   'monitors': [{'hdr_active': True}, {'hdr_active': False}]}
        plan = list(cases(devices))
        self.assertEqual(len([p for p in plan if 'soak' in p[0]]), 1)
        self.assertNotIn('sdr-rejects-hdr', [p[0] for p in plan])
        self.assertEqual([p[1]['effects'][0]['parameters']['nvidiaOpticalFlowQuality']
                          for p in plan if p[0].startswith('nvof')], [1, 2, 3, 4, 5])

    def test_hdr_requires_capture_evidence_not_just_source_metadata(self):
        data = self.data()
        data.update(source_metadata={'hdr': True, 'format': 10, 'color_space': 1}, source_exit_code=0)
        self.assertEqual(summarize(data, 'hdr')['status'], 'failed')
        native = {'hdr': dict(sourceFormat='10', sourceDxgiColorSpace='1', canonicalFormat='10',
                              displayHdrEnabled='true', fallbackReason='(none)')}
        self.assertEqual(summarize(data, 'hdr', native)['status'], 'passed')
        native['hdr']['canonicalFormat'] = '28'
        self.assertEqual(summarize(data, 'hdr', native)['status'], 'failed')

    def test_nvof_quality_requires_native_initialization_not_config_alone(self):
        data = self.data()
        data['config'] = deepcopy(DEFAULT_CONFIG)
        data['config']['effects'][0]['parameters'].update(opticalFlowMethod=2, nvidiaOpticalFlowQuality=5)
        self.assertEqual(summarize(data, 'render')['status'], 'failed')
        native = {'initialization': ['Frame Guidance NVOF initialized: profile=1S',
                                      'created=true opticalFlowQuality=5 path=test']}
        self.assertEqual(summarize(data, 'render', native)['status'], 'passed')
        native['initialization'][1] = 'created=true opticalFlowQuality=2 path=test'
        self.assertEqual(summarize(data, 'render', native)['status'], 'failed')

    def test_move_requires_real_coordinates_and_post_move_progress(self):
        data = self.data()
        data['source_moves'] = [dict(time=5, ok=True, position=[-1000, 0], actual_rect=None)]
        self.assertEqual(summarize(data, 'move')['status'], 'failed')
        data['source_moves'][0]['actual_rect'] = [-1000, 0, -200, 450]
        data['events'][-1]['probe_time'] = 8
        self.assertEqual(summarize(data, 'move')['status'], 'passed')
        data['events'][-1]['metrics'] = deepcopy(data['events'][0]['metrics'])
        self.assertEqual(summarize(data, 'move')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
