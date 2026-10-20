"""Archive bounded P0 evidence, excluding reconstructible media and binaries."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save

BATCHES = ('related.xml', 'closed-proxy.xml', 'runtime-tests.xml', 'tk-rerun.xml',
           'pressure-final.xml', 'pressure-owner-final.xml',
           'pipeline-association.xml', 'fg-tk-rerun.xml')
CASE_FILES = {'result.json', 'worker-result.json', 'events.jsonl', 'memory-samples.json',
              'console.log', 'settings.json', 'native-modules.json',
              'sr-frame-memory.jsonl', 'nr-frame-memory.jsonl',
              'idle-frame-memory.jsonl', 'device-frame-memory.jsonl',
              'cuda-frame-memory.jsonl', 'adapters-frame-memory.jsonl',
              'composer-frame-memory.jsonl', 'gui-modules.jsonl'}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024**2), b''):
            value.update(block)
    return value.hexdigest()


def collect(task, output, *, runtime_only=False):
    files = []
    for directory, names, leaves in os.walk(task, followlinks=False):
        for name in names+leaves:
            checked_path(Path(directory)/name)  # reject junctions as well as symlinks
        files.extend(Path(directory)/name for name in leaves)
    output.mkdir(exist_ok=False)
    archive = []
    for source in sorted(files):
        relative = source.relative_to(task)
        selected = (len(relative.parts) == 1 and source.suffix in ('.xml', '.patch', '.json', '.cmd', '.cpp', '.py', '.jsonl') or
                    source.name == 'TASK.md' or
                    len(relative.parts) == 2 and (source.name in CASE_FILES or
                        source.name.endswith('-frame-memory-regions.jsonl') or
                        source.name.startswith(('native-heap-', 'trace-self-')) and source.suffix == '.jsonl') or
                    relative.as_posix() == 'logging-candidate/build.cmd')
        if not selected:
            continue
        data = source.read_bytes()
        compressed = source.name == 'memory-samples.json'
        target = checked_path(output/'raw'/relative)
        if compressed:
            target = target.with_suffix(target.suffix+'.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.compress(data, mtime=0) if compressed else data)
        restored = gzip.decompress(target.read_bytes()) if compressed else target.read_bytes()
        assert hashlib.sha256(restored).hexdigest() == digest(source)
        archive.append(dict(source=str(relative), file=str(target.relative_to(output)),
                            source_bytes=len(data), source_sha256=digest(source),
                            archived_sha256=digest(target)))

    batches, identities = [], {}
    for name in (() if runtime_only else BATCHES):
        cases = ET.parse(task/name).findall('.//testcase')
        failures = []
        for case in cases:
            key = (case.get('classname'), case.get('name'))
            failed = case.find('failure') is not None or case.find('error') is not None
            skipped = case.find('skipped') is not None
            identities[key] = dict(passed=not failed and not skipped, batch=name)
            if failed:
                failures.append(dict(classname=key[0], name=key[1]))
        batches.append(dict(file=name, tests=len(cases), failures=failures))

    results = []
    for directory in sorted(task.iterdir()):
        if not (directory/'result.json').is_file():
            continue
        result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
        worker = json.loads((directory/'worker-result.json').read_text(encoding='utf-8'))
        samples = json.loads((directory/'memory-samples.json').read_text(encoding='utf-8'))
        events = [json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        entry = dict(label=directory.name, processing_and_exit=result['status'],
            elapsed_seconds=result['elapsed_seconds'], peak_private_bytes=result['peak_tree_private_bytes'],
            samples=result['samples'], supervisor_safety_stop=result['safety_error'],
            supervisor_recovery=result['recovery'], remaining=result['remaining_before_recovery'],
            long_term_memory_plateau_verified=False)
        start = next((e['wall']+10 for e in events if e['event'] == 'idle-start'), None)
        end = next((e['wall'] for e in events if e['event'] == 'idle-end'), None)
        if start and end:
            idle = [s for s in samples if start <= s['wall'] <= end]
            if len(idle) >= 20:
                count = max(1, len(idle)//5)
                delta = (statistics.median(s['private_bytes'] for s in idle[-count:])-
                         statistics.median(s['private_bytes'] for s in idle[:count]))
                span = (statistics.median(s['wall'] for s in idle[-count:])-
                        statistics.median(s['wall'] for s in idle[:count]))
                entry['idle_private_delta_bytes'] = delta
                entry['idle_private_bytes_per_second'] = delta/span
                entry['idle_measured_span_seconds'] = span
        entry['worker'] = worker
        if directory.name == 'continuous-hdr':
            entry['evidence_exclusion'] = 'Fixture lacked PQ tags; completed SDR processing, invalid as HDR acceptance'
        if directory.name == 'native-sr-logging':
            entry['evidence_exclusion'] = 'Candidate initialization timed out; no valid frames or memory comparison'
        results.append(entry)

    tracked = ['dlss5tool/'+name+'.py' for name in ('gui', 'dlss_host_process', 'render_cache',
               'shared_render_preview', 'memory_budget', 'super_resolution')]
    tracked += ['scripts/verify_p0_stability.py', 'scripts/profile_native_frame_memory.py',
                'scripts/collect_p0_stability.py', 'scripts/compare_p0_stability.py',
                'scripts/inspect_native_allocations.py', 'scripts/native_heap_trace.cpp',
                'scripts/summarize_native_heap_trace.py',
                'tests/test_gui_module_reload.py',
                'tests/test_p0_owner_retirement.py', 'tests/test_p0_runtime_pressure.py']
    runtimes = ['runtime/'+name+'.dll' for name in ('vsr_host', 'nvngx_vsr', 'nvngx_dlssnr',
                'dlssnr_host_v2', 'dlss5_quality')]
    manifest = [dict(file=name, bytes=(ROOT/name).stat().st_size, sha256=digest(ROOT/name))
                for name in tracked+runtimes]
    selected_sources = {r['source'] for r in archive}
    omitted = [dict(file=str(path.relative_to(task)), bytes=path.stat().st_size, sha256=digest(path))
               for path in files if path.suffix in ('.mp4', '.png', '.dll', '.cpp')
               and str(path.relative_to(task)) not in selected_sources]
    summary = dict(scope='Synthetic local samples on a 64 GiB single-GPU machine; not the original 32 GiB incident',
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        python=sys.version, windows=platform.platform(), batches=batches,
        runtime_only=runtime_only,
        distinct_passed=sum(v['passed'] for v in identities.values()),
        latest_unresolved=[dict(classname=k[0], name=k[1], **v) for k,v in identities.items() if not v['passed']],
        cases=results, source_and_runtime_manifest=manifest, archive=archive,
        omitted_reconstructible_files=omitted,
        cleanup_not_yet_performed=True)
    save(output/'verification-summary.json', summary)
    print(json.dumps(dict(distinct_passed=summary['distinct_passed'],
        unresolved=summary['latest_unresolved'], cases=len(results), archived_files=len(archive),
        archived_bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-only', action='store_true',
                        help='Explicit runtime comparison with no repeated unit-test batches')
    args = parser.parse_args()
    task, output = checked_path(args.task), checked_path(args.output)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file():
        parser.error('Use a registered task under tmp/')
    if output == ROOT/'docs/development' or not output.is_relative_to(ROOT/'docs/development'):
        parser.error('Output must be a new evidence directory under docs/development/')
    collect(task, output, runtime_only=args.runtime_only)


if __name__ == '__main__':
    main()
