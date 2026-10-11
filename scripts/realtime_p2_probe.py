"""Reproducible P2 checks against owned synthetic windows, never a game benchmark.

No downloads, display-setting changes, user presets, OBS control or private window
capture. Missing HDR/multi-device/game evidence always remains explicitly open.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool import mod_paths
from dlss5tool.realtime import DEFAULT_CONFIG, NR, performance_profile

PENDING = [
    'P2-03: HDR source -> FP16 processing -> output functional evidence is per-case; visual HDR acceptance still required',
    'P2-04: mixed DPI, physical cross-GPU and OBS coexistence; same-DPI monitor smoke is per-case only',
    'P2-05: selected real game baseline/capture/NR/SR-FG A/B and sustained load',
]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def inventory(host, folder, runtime_directory=None):
    """The host's read-only enumeration; never send start or enumerate windows."""
    folder.mkdir(parents=True, exist_ok=False)
    nr = Path(mod_paths.runtime_path({})).resolve()
    runtime = Path(runtime_directory).resolve() if runtime_directory else nr.parent
    if runtime_directory:
        nr = runtime / 'nvngx_dlssnr.dll'
        if not nr.is_file():
            raise FileNotFoundError(nr)
    environment = dict(os.environ, DLSS5_REALTIME_STATE_ROOT=str(folder),
        DLSS5_REALTIME_EFFECTS_ROOT=str(host.parent / 'effects'),
        DLSS5_REALTIME_RUNTIME_ROOT=str(runtime), DLSS5_REALTIME_NR_PATH=str(nr))
    commands = '\n'.join(json.dumps({'command': name, 'id': i}) for i, name in enumerate(('devices', 'quit'), 1)) + '\n'
    result = subprocess.run([str(host)], input=commands, cwd=folder, env=environment,
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    events = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    devices = next((e for e in events if e.get('event') == 'devices'), None)
    if result.returncode or devices is None:
        raise RuntimeError(f'Device enumeration failed: {result.returncode}; {result.stdout[-2000:]}')
    files = {'host': host, 'nr': nr, 'sr': runtime / 'nvngx_dlss.dll', 'fg': runtime / 'nvngx_dlssg.dll'}
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
        capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) if shutil.which('nvidia-smi') else None
    result = {'devices': devices,
              'gpu_driver': gpu.stdout.strip() if gpu and gpu.returncode == 0 else None,
              'files': {key: {'path': str(path), 'sha256': digest(path), 'size': path.stat().st_size}
                        for key, path in files.items() if path.is_file()}}
    write_json(folder / 'inventory.json', result)
    return result


def cases(devices, seconds=20, soak_seconds=180):
    base = deepcopy(DEFAULT_CONFIG)
    base.update(windowed=True, disable_topmost=True)
    for quality in range(1, 6):
        config = deepcopy(base)
        config['effects'][0]['parameters'].update(opticalFlowMethod=2, nvidiaOpticalFlowQuality=quality, antiFlicker=2)
        yield f'nvof-q{quality}', config, seconds, 'render'
    chain = deepcopy(base)
    chain['effects'] = [
        {'name': NR, 'parameters': {'opticalFlowMethod': 2, 'nvidiaOpticalFlowQuality': 2, 'antiFlicker': 2}, 'scale': [1, 1]},
        {'name': r'DLSS\DLSS_SR', 'parameters': {}, 'scale': [1.5, 1.5]},
        {'name': r'DLSSFG\DLSS_FrameGeneration', 'parameters': {}, 'scale': [1, 1]},
    ]
    for name in ('balanced', 'game', 'eco', 'quality'):
        yield 'chain-' + name, performance_profile(chain, name), seconds, 'fg'
    # Multiple logical adapters do not prove multiple physical boards.
    for adapter in devices.get('adapters', []):
        if adapter.get('software') or adapter.get('vendor') != 0x10de:
            continue
        config = deepcopy(chain)
        config['gpu_index'] = adapter['index']
        yield f'gpu-{adapter["index"]}-soak', config, soak_seconds, 'fg'
        break
    # A Tk source is SDR. Even successful output on an HDR monitor would not
    # prove an end-to-end HDR source. Only run the negative test on known SDR.
    monitors = devices.get('monitors', [])
    if monitors and all(m.get('hdr_active') is False for m in monitors):
        config = deepcopy(base)
        config['hdr'] = True
        yield 'sdr-rejects-hdr', config, seconds, 'hdr-reject'


def display_cases(devices, seconds):
    """Same-DPI two-screen smoke is not mixed-DPI or physical multi-GPU proof."""
    for index, monitor in enumerate(devices.get('monitors', [])):
        rect = monitor['rect']
        position = [rect[0] + 80, rect[1] + 80]
        base = deepcopy(DEFAULT_CONFIG)
        base.update(windowed=True, disable_topmost=True)
        yield f'display-{index}-sdr', base, seconds, 'render', position, False, None
        if monitor.get('hdr_active'):
            base['hdr'] = True
            yield f'display-{index}-hdr-nr', base, seconds, 'hdr', position, True, None
            chain = deepcopy(base)
            chain['effects'] += [{'name': r'DLSS\DLSS_SR', 'parameters': {}, 'scale': [1.5, 1.5]},
                                  {'name': r'DLSSFG\DLSS_FrameGeneration', 'parameters': {}, 'scale': [1, 1]}]
            yield f'display-{index}-hdr-chain', chain, seconds, 'hdr-fg', position, True, None
    monitors = devices.get('monitors', [])
    if len(monitors) >= 2:
        start, end = [m['rect'] for m in monitors[:2]]
        base = dict(deepcopy(DEFAULT_CONFIG), windowed=True, disable_topmost=True)
        yield 'source-between-displays', base, seconds, 'move', [start[0]+80, start[1]+80], False, [end[0]+80, end[1]+80]


def native_evidence(path):
    if not path.is_file():
        return {}
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    hdr_fields = {}
    in_hdr = False
    for line in lines:
        if 'LogHdrDiagnostics|HDR diagnostics' in line:
            in_hdr = True
        elif in_hdr and line.startswith('\t'):
            name, separator, value = line.strip().partition(': ')
            if separator:
                hdr_fields[name] = value
        else:
            in_hdr = False
    return {'log_sha256': digest(path), 'hdr': hdr_fields,
        'initialization': [line for line in lines if any(marker in line for marker in
            ('Frame Guidance NVOF initialized:', 'created=true', 'DLSSFG HDR bounded bridge enabled:'))][:20],
        'warnings': list(dict.fromkeys(re.sub(r'^.*?\|warning\|', '', line)
                        for line in lines if '|warning|' in line))[:30]}


def summarize(data, expectation, native=None):
    statuses = [e for e in data.get('events', []) if e.get('event') == 'status']
    rendered = [e for e in statuses if e.get('metrics', {}).get('real', 0) > 0]
    errors = data.get('native_failures', [])
    last = rendered[-1]['metrics'] if rendered else {}
    reasons = []
    if not data.get('exit_ok'):
        reasons.append('host did not exit cleanly')
    if expectation == 'hdr-reject':
        hdr_errors = [e for e in errors if 'HDR' in e.get('message', '').upper()]
        if rendered or not hdr_errors:
            reasons.append('expected explicit HDR rejection and zero rendered frames')
        if any(e not in hdr_errors for e in errors):
            reasons.append('unexpected non-HDR failure')
    else:
        if errors:
            reasons.append('native failure')
        if not rendered or last.get('real', 0) < 10:
            reasons.append('insufficient real frames')
        if expectation in ('fg', 'hdr-fg') and not last.get('generated', 0):
            reasons.append('no generated frames')
        if last.get('nr_failures', 0):
            reasons.append('NR evaluation failure')
        effects = data.get('config', {}).get('effects', [])
        for effect in effects:
            params = effect.get('parameters', {})
            if effect.get('name') == NR and params.get('opticalFlowMethod') == 2:
                initialization = (native or {}).get('initialization', [])
                quality = params.get('nvidiaOpticalFlowQuality', 2)
                if not any('Frame Guidance NVOF initialized:' in line for line in initialization) or not any(
                        f'opticalFlowQuality={quality} ' in line and 'created=true' in line for line in initialization):
                    reasons.append('requested NVOF quality not confirmed by native initialization')
        for a, b in zip(rendered, rendered[1:]):
            if a.get('run_id') != b.get('run_id'):
                reasons.append('unexpected session change')
                break
            if any(b['metrics'].get(k, 0) < a['metrics'].get(k, 0) for k in ('real', 'submitted', 'nr_evaluations')):
                reasons.append('frame counters regressed')
                break
        if any(e['metrics'].get('nr_failures', 0) for e in statuses):
            reasons.append('NR failure earlier in run')
        # Submitted counts publications, not necessarily real+generated frames
        # (static redraw and backend multi-frame publications can differ).
        if len(rendered) > 1:
            progress_time, count = rendered[0].get('probe_time', 0), rendered[0]['metrics']['submitted']
            for e in rendered[1:]:
                stamp = e.get('probe_time', 0)
                if stamp - progress_time > 15:
                    reasons.append('no sampled output progress for >15s')
                    break
                if e['metrics']['submitted'] > count:
                    progress_time, count = stamp, e['metrics']['submitted']
        for e in rendered:
            if any(isinstance(v, (float, int)) and not math.isfinite(v) for v in e['metrics'].values()):
                reasons.append('nonfinite metrics')
                break
        if expectation.startswith('hdr'):
            source = data.get('source_metadata') or {}
            if not (source.get('hdr') and source.get('format') == 10 and source.get('color_space') == 1):
                reasons.append('no owned FP16/scRGB HDR source evidence')
            hdr = (native or {}).get('hdr', {})
            if not all(hdr.get(k) == v for k, v in {'sourceFormat': '10', 'sourceDxgiColorSpace': '1',
                    'canonicalFormat': '10', 'displayHdrEnabled': 'true', 'fallbackReason': '(none)'}.items()):
                reasons.append('no native FP16/scRGB capture and HDR-display evidence')
        if expectation == 'move':
            moves = data.get('source_moves', [])
            if not moves or not all(m.get('ok') and (m.get('actual_rect') or [])[:2] == m.get('position') for m in moves):
                reasons.append('owned source move not confirmed')
            else:
                before = [e for e in rendered if e.get('probe_time', 0) <= moves[-1]['time']]
                if not before or not any(e.get('probe_time', 0) > moves[-1]['time'] + 2 and
                        e['metrics']['submitted'] > before[-1]['metrics']['submitted'] for e in rendered):
                    reasons.append('no output progress after source move')
        if data.get('source_metadata') and data.get('source_exit_code') != 0:
            reasons.append('owned source did not exit cleanly')
    steady = [e for e in rendered if e.get('probe_time', 0) >= 5]
    rates = None
    if len(steady) > 1:
        first, end = steady[0], steady[-1]
        dt = end['probe_time'] - first['probe_time']
        if dt > 0:
            rates = {k: (end['metrics'].get(k, 0) - first['metrics'].get(k, 0)) / dt
                     for k in ('real', 'generated', 'submitted') if end['metrics'].get(k) is not None and first['metrics'].get(k) is not None}
    return {'status': 'failed' if reasons else 'passed', 'expectation': expectation,
            'reasons': reasons, 'host_sha256': data.get('host_sha256'), 'config': data.get('config'),
            'duration_seconds': data.get('duration_seconds'), 'last_metrics': last,
            'source_metadata': data.get('source_metadata'), 'source_moves': data.get('source_moves', []),
            'native_evidence': native or {},
            'sampled_steady_rates': rates, 'gpu_sample_count': len(data.get('gpu_samples', [])),
            'gpu_samples': data.get('gpu_samples', []),
            'errors': [{k: e[k] for k in ('event', 'code', 'message') if k in e} for e in errors]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New task output directory')
    parser.add_argument('--host', type=Path, default=ROOT / 'runtime/realtime/dlss5_realtime_host.exe')
    parser.add_argument('--runtime-directory', type=Path)
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--display-only', action='store_true', help='Owned native SDR/HDR and monitor-move smoke')
    parser.add_argument('--source-exe', type=Path)
    parser.add_argument('--summarize', type=Path, help='Re-evaluate existing raw reports without launching anything')
    parser.add_argument('--case', action='append', help='Run only named cases; repeat to select more')
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--soak-seconds', type=float, default=180)
    args = parser.parse_args()
    if args.display_only and not args.source_exe:
        parser.error('--display-only requires --source-exe built from scripts/realtime_test_source.cpp')
    if not 10 <= args.seconds <= 60 or not 30 <= args.soak_seconds <= 1800:
        parser.error('seconds must be 10..60 and soak-seconds 30..1800')
    output, host = args.output.resolve(), args.host.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.summarize:
        folder = args.summarize.resolve()
        report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
        for name, entry in list(report['cases'].items()):
            path = folder / name / 'report.json'
            if not path.is_file():
                report['cases'][name] = {**entry, 'status': 'failed', 'reasons': ['raw report missing; cannot re-evaluate']}
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            native = native_evidence(folder / name / 'state/logs/realtime.log')
            result = summarize(data, entry['expectation'], native)
            result['report_sha256'] = digest(path)
            if result['host_sha256'] != report['environment']['files']['host']['sha256']:
                result['status'] = 'failed'
                result['reasons'].append('host binary mismatch')
            report['cases'][name] = result
        report['pending'] = PENDING
        report['full_p2_accepted'] = False
        report['summary_rebuilt_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'report.json', report)
        print(json.dumps({name: c['status'] for name, c in report['cases'].items()}))
        return int(any(c['status'] != 'passed' for c in report['cases'].values()))
    environment = inventory(host, output / 'inventory', args.runtime_directory)
    if args.source_exe:
        result = subprocess.run([str(args.source_exe.resolve()), '--inventory'], capture_output=True,
            text=True, encoding='utf-8', timeout=10, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        environment['display_probe'] = json.loads(result.stdout)
        environment['source_sha256'] = digest(args.source_exe)
    report = {'schema_version': 1, 'time_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'owned synthetic windows; no game or physical HDR performance claim',
              'environment': environment, 'cases': {}, 'pending': PENDING,
              'full_p2_accepted': False}
    write_json(output / 'report.json', report)
    if args.inventory_only:
        print(json.dumps(environment, ensure_ascii=False))
        return 0
    plan = (list(display_cases(environment['devices'], args.seconds)) if args.display_only else
            [(*p, [80, 80], False, None) for p in cases(environment['devices'], args.seconds, args.soak_seconds)])
    if args.case:
        unknown = set(args.case) - {p[0] for p in plan}
        if unknown:
            parser.error(f'Cases not available in this environment: {sorted(unknown)}')
        plan = [p for p in plan if p[0] in args.case]
    for name, config, duration, expectation, position, source_hdr, move in plan:
        config_path = output / f'{name}-config.json'
        write_json(config_path, config)
        command = [sys.executable, '-B', str(ROOT / 'scripts/realtime_window_probe.py'),
            '--host', str(host), '--output', str(output / name), '--config', str(config_path),
            '--seconds', str(duration), '--gpu-sampling', '--quiet']
        if args.runtime_directory:
            command += ['--runtime-directory', str(args.runtime_directory.resolve())]
        if args.source_exe:
            command += ['--source-exe', str(args.source_exe.resolve()), '--source-position', *map(str, position)]
        if source_hdr:
            command += ['--source-hdr']
        if move:
            command += ['--move-source', *map(str, move)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=duration + 35, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            (output / f'{name}.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
            path = output / name / 'report.json'
            if completed.returncode or not path.is_file():
                entry = {'status': 'failed', 'expectation': expectation,
                         'reasons': [f'probe process failed: {completed.returncode}; suite stopped']}
                report['cases'][name] = entry
                write_json(output / 'report.json', report)
                return 1
            else:
                entry = summarize(json.loads(path.read_text(encoding='utf-8')), expectation,
                                  native_evidence(output / name / 'state/logs/realtime.log'))
                entry['report_sha256'] = digest(path)
                if entry['host_sha256'] != environment['files']['host']['sha256']:
                    entry['status'] = 'failed'
                    entry['reasons'].append('host binary changed during suite')
        except subprocess.TimeoutExpired:
            # Do not start more GPU work after a missing teardown confirmation.
            entry = {'status': 'failed', 'expectation': expectation, 'reasons': ['probe process timed out; suite stopped']}
            report['cases'][name] = entry
            write_json(output / 'report.json', report)
            return 1
        report['cases'][name] = entry
        write_json(output / 'report.json', report)
        print(json.dumps({'case': name, 'status': entry['status'], 'reasons': entry['reasons']}, ensure_ascii=False), flush=True)
    return int(any(c['status'] != 'passed' for c in report['cases'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
