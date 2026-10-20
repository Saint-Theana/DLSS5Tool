"""Summarize diagnostic allocation metadata without claiming complete tracing."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def heap_trace(path):
    data = rows(path)
    modules = [r for r in data if r['kind'] == 'module']
    stacks = [r for r in data if r['kind'] == 'stack']
    def resolve(address):
        value = int(address, 16)
        for module in modules:
            base = int(module['base'], 16)
            if base <= value < base+module['size']:
                return dict(module=module['path'], offset=hex(value-base))
        return dict(address=address, module=None)
    by_caller = defaultdict(int)
    for stack in stacks:
        frames = [resolve(f) for f in stack['frames']]
        stack['resolved'] = frames
        by_caller[frames[0]['module'] if frames else '<no frames>'] += stack['live']
    summary = next(r for r in data if r['kind'] == 'summary')
    return dict(file=path.name, **{k:v for k,v in summary.items() if k != 'kind'},
        observed_live_bytes=sum(r['live'] for r in stacks),
        live_by_first_captured_module=dict(by_caller),
        largest_observed_live_stacks=sorted(stacks, key=lambda r:r['live'], reverse=True)[:8],
        limitations='IAT coverage only; no release through cached function pointers or subsequently loaded imports. '
                    'Unobserved releases can overstate live bytes; failed frees can understate them. '
                    'Optimized tail calls can omit frames; no private NVIDIA symbols. '
                    'Instrumentation changes allocation timing and has fixed native table overhead.')


def memory_map(directory):
    files = list(directory.glob('*-frame-memory-regions.jsonl'))
    assert len(files) == 1, files
    events = rows(directory/'events.jsonl')
    end = next(r['wall'] for r in events if r['event'] == 'idle-end')
    samples = [r for r in rows(files[0]) if r['wall'] <= end]
    first, last = samples[0], samples[-1]
    assert len({(r['pid'],r['created']) for r in samples}) == 1
    return dict(file=files[0].name, pid=first['pid'], created=first['created'],
        samples=len(samples), measured_span_seconds=last['wall']-first['wall'],
        first={key:first[key] for key in ('wall','default_heap','private_commit_by_type')},
        last={key:last[key] for key in ('wall','default_heap','private_commit_by_type')},
        heap_allocated_delta=last['default_heap']['allocated']-first['default_heap']['allocated'],
        heap_committed_delta=last['default_heap']['committed']-first['default_heap']['committed'],
        private_commit_delta_by_type={key:last['private_commit_by_type'][key]-first['private_commit_by_type'][key]
                                     for key in first['private_commit_by_type']},
        allocation_query_errors_by_sample=[r['private_commit_query_errors'] for r in samples],
        limitations='Sequential metadata queries, not atomic. Concurrently freed regions can fail queries; '
                    'only the default heap is summarized, not all DLL-owned private heaps.')


def summarize(task):
    cases = []
    for directory in sorted(task.iterdir()):
        if not directory.is_dir() or not (directory/'result.json').is_file():
            continue
        result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
        cases.append(dict(case=directory.name,
            processing_and_exit_passed=result['processing_and_exit_passed'],
            plateau_verified=False, safety_error=result['safety_error'],
            remaining=result['remaining_before_recovery'], recovery=result['recovery'],
            memory_map=memory_map(directory),
            heap_traces=[heap_trace(path) for path in sorted(directory.glob('native-heap-*.jsonl'))]))
    return dict(scope='Only each exact diagnostic process; unrelated application private bytes are excluded',
                cases=cases)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    task, output = checked_path(args.task), checked_path(args.output)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file() or not output.is_relative_to(task):
        parser.error('Use a registered tmp task and an output inside it')
    result = summarize(task)
    save(output, result)
    print(json.dumps([dict(case=r['case'], heap_delta=r['memory_map']['heap_allocated_delta']) for r in result['cases']]))
