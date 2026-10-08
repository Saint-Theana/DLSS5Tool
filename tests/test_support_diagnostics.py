"""Scoped support-export tests; never start a native host or GPU probe."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from dlss5tool import support_diagnostics as support, i18n


class SupportDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        runtime = mock.patch.object(support, 'runtime_summary', return_value={'path': r'C:\Private\nvngx_dlssnr.dll', 'source': 'bundled'})
        runtime.start()
        self.addCleanup(runtime.stop)

    def test_default_report_is_passive_and_contains_both_modes_redacted(self):
        log_dir = self.root / 'logs'
        log_dir.mkdir()
        (log_dir / 'realtime.log').write_text('Secret Game failed 0xBAD00002 C:\\Private\\runtime.dll\n', encoding='utf-8')
        context = {'settings': {'ui_language': 'en_US'}, 'workbench_mode': 'local',
                   'ui_log': r'Local C:\Users\Alice\movie.mp4',
                   'realtime': {'session': {'target': {'title': 'Secret Game', 'application': r'C:\Games\Private\game.exe'}},
                                'draft_fields': {'intensity': 'bad value'}, 'running_config': {'intensity': 1},
                                'message': 'Secret Game failed 0xBAD00002'},
                   '_diagnostic_io': {'realtime_logs': str(log_dir)}}
        original = deepcopy(context)
        output = self.root / 'support.json'
        with mock.patch.object(support.diagnostics, 'write_diagnostic_report') as probe:
            support.write_report(output, context)
            probe.assert_not_called()
        text = output.read_text(encoding='utf-8')
        report = json.loads(text)
        self.assertEqual(context, original)
        for secret in ('Secret Game', 'Alice', 'Private', str(log_dir), '_diagnostic_io'):
            self.assertNotIn(secret, text)
        self.assertIn('0xBAD00002', text)
        self.assertIn('runtime.dll', text)
        self.assertEqual(report['context']['realtime']['draft_fields']['intensity'], 'bad value')
        self.assertEqual(report['context']['realtime']['running_config']['intensity'], 1)
        self.assertEqual(report['diagnostic_kind'], 'snapshot-no-GPU-probes')

    def test_telemetry_and_logs_cannot_evict_error_or_lifecycle(self):
        journal = support.EventJournal()
        journal.append({'event': 'error', 'message': 'original failure'})
        journal.append({'event': 'state', 'state': 1, 'run_id': 2})
        for number in range(1800):
            journal.append({'event': 'status', 'metrics': {'submitted': number}})
            journal.append({'event': 'log', 'message': str(number)})
            journal.append({'event': 'ack', 'ok': True, 'id': number})
        snapshot = journal.snapshot()
        self.assertEqual(snapshot['errors'][0]['message'], 'original failure')
        self.assertEqual(snapshot['lifecycle'][0]['state'], 1)
        self.assertEqual(snapshot['latest']['status']['metrics']['submitted'], 1799)
        self.assertEqual(snapshot['dropped']['logs'], 1640)
        snapshot['errors'].clear()
        self.assertEqual(len(journal.snapshot()['errors']), 1)

    def test_native_logs_are_bounded_include_rotations_and_ignore_unrelated_files(self):
        logs = self.root / 'logs'
        logs.mkdir()
        (logs / 'realtime.log').write_bytes(b'a' * 300000 + b'last-line')
        (logs / 'realtime.1.log').write_text('older session', encoding='utf-8')
        (logs / 'private.txt').write_text('not part of report', encoding='utf-8')
        entries = support.read_native_logs(logs)
        self.assertEqual([item['file'] for item in entries], ['realtime.1.log', 'realtime.log'])
        self.assertTrue(entries[-1]['truncated'])
        self.assertTrue(entries[-1]['text'].endswith('last-line'))
        self.assertEqual(len(entries[-1]['text']), 256 * 1024)
        self.assertEqual(support.read_native_logs(self.root / 'missing'), [])

    def test_atomic_failure_preserves_old_report_and_removes_own_partial(self):
        output = self.root / 'support.log'
        output.write_text('previous report', encoding='utf-8')
        with mock.patch.object(support.os, 'replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                support.write_report(output, {'settings': {}})
        self.assertEqual(output.read_text(encoding='utf-8'), 'previous report')
        self.assertEqual(list(self.root.glob('.dlss5-diagnostic-*')), [])

    def test_deep_reuses_existing_probe_writer_then_redacts_private_intermediate(self):
        output = self.root / 'support.log'
        def probe(path, context, on_progress=None):
            self.assertNotEqual(Path(path), output)
            Path(path).write_text('Secret Game C:\\Private\\native.dll 0xBAD00002', encoding='utf-8')
        with mock.patch.object(support.diagnostics, 'write_diagnostic_report', side_effect=probe) as writer:
            support.write_report(output, {'settings': {'ui_language': 'en_US'}, 'target': {'title': 'Secret Game'}}, deep=True)
            writer.assert_called_once()
        text = output.read_text(encoding='utf-8')
        self.assertNotIn('Secret Game', text)
        self.assertNotIn('Private', text)
        self.assertIn('0xBAD00002', text)
        self.assertIn('not realtime capture', text)

    def test_redaction_handles_unc_slashes_quoted_titles_and_nan_drafts(self):
        raw = {'target': {'title': 'Private "Game"'}, 'message': 'Private "Game" 0x123',
               'paths': [r'\\secret-server\private-share\folder\runtime.dll', '/Users/private/game/runtime.dll'],
               'draft': float('nan')}
        result = support.Redactor(raw).clean(support.bounded(raw))
        text = json.dumps(result, ensure_ascii=False, allow_nan=False)
        for secret in ('private', 'Private', 'secret-server', 'Users'):
            self.assertNotIn(secret, text)
        self.assertIn('runtime.dll', text)
        self.assertEqual(result['draft'], 'nan')

    def test_localized_report_heading_and_timestamp_filename(self):
        for language in ('zh_CN', 'en_US'):
            output = self.root / (language + '.log')
            support.write_report(output, {'settings': {'ui_language': language}})
            self.assertTrue(output.read_text(encoding='utf-8').startswith(i18n.tr_for(language, 'diagnostics.report_title')))
        self.assertRegex(support.suggested_name('realtime'), r'DLSS5Tool-realtime-diagnostic-\d{8}-\d{6}\.log')
