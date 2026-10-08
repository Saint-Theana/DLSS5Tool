"""Summarize owned synthetic probes without retaining full protocol/title logs.

This records evidence, not a blanket hardware-compatibility or performance pass.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'tmp/realtime-integration-20261003'
CASES = {
    'nr-sr-fg-final': 'combined_chain_and_live_parameter',
    'nr-static-quality-final': 'static_quality_redraw',
    'input-hotkey': 'manual_owned_window_click_and_emergency_stop',
    'gdi-windowed': 'capture_output',
    'dwm-windowed': 'capture_output',
    'wgc-fullscreen': 'capture_output',
    'dd-diagnostic': 'environment_capture_timeout_not_passed',
    'dd-explicit-wgc-fallback': 'explicit_wgc_fallback_not_dd_success',
    'hdr-preflight-fixed': 'sdr_environment_correctly_rejects_hdr',
    'nr-protocol-lifecycle': 'stale_session_rejected_and_source_lifecycle',
    'ui-rollback': 'known_good_restored_after_native_rejection',
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def summarize():
    result = {'schema_version': 1, 'date': '2026-10-03',
              'scope': 'owned synthetic windows only, not a game benchmark',
              'environment': 'RTX 4070 SUPER; one 1024x768 SDR virtual display',
              'current_host_sha256': digest(ROOT / 'runtime/realtime/dlss5_realtime_host.exe'),
              'not_accepted': ['real-game anti-cheat and relative input', 'game concurrent load and long soak',
                               'HDR display end-to-end', 'mixed DPI and physical multi-monitor/multi-GPU',
                               'OBS coexistence', 'real-scene high-motion subjective quality'],
              'cases': {}}
    for label, meaning in CASES.items():
        path = WORK / f'probe-{label}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        statuses = [e for e in data.get('events', []) if e.get('event') == 'status']
        rendered = [e for e in statuses if e.get('metrics', {}).get('real', 0) > 0]
        entry = {'interpretation': meaning, 'report_sha256': digest(path),
                 'host_sha256_at_probe': data.get('host_sha256'),
                 'rendered': data.get('rendered'), 'exit_ok': data.get('exit_ok'),
                 'quality_confirmed': data.get('quality_confirmed'),
                 'parameter_test': data.get('parameter_test'), 'parameter_confirmed': data.get('parameter_confirmed'),
                 'config': data.get('config'),
                 'last_rendered_metrics': rendered[-1]['metrics'] if rendered else None,
                 'states': [{'state': e['state'], 'run_id': e.get('run_id')} for e in data.get('events', []) if e.get('event') == 'state'],
                 'errors': [{k: e[k] for k in ('event', 'code', 'message') if k in e} for e in data.get('native_failures', [])],
                 'source_clicks': data.get('source_clicks', [])}
        if label == 'ui-rollback':
            entry.update(success=data['success'], active_config=data['active_config'],
                         saved_known_good=data.get('saved_session') == data['active_config'], status=data['status'])
        if 'static-quality' in label:
            entry['quality_timeline'] = [
                {'quality_revision': e.get('quality_revision'), 'applied': e.get('quality_applied_revision'),
                 **{k: e.get('metrics', {}).get(k) for k in ('captured', 'nr_evaluations', 'submitted', 'generated')}}
                for e in statuses]
        result['cases'][label] = entry
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/development/REALTIME_ACCEPTANCE_20261003.json')
    args = parser.parse_args()
    result = summarize()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(result["cases"])} evidence cases: {args.output}')


if __name__ == '__main__':
    main()
