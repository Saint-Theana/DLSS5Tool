"""Compare archived P0 observations with a fresh bounded runtime task.

Reports measurements, never treats completed processing as a memory plateau.
Native idle comparisons follow one exact process identity to exclude updater
descendants appearing/disappearing during the sample window.
"""
import argparse
import gzip
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save

PAIRS = {'native-sr-off': 'native-sr-idle300',
         'native-nr-off': 'native-nr-full-idle',
         'native-composer-off': 'native-composer-r1',
         'images-off': 'images-trace', 'continuous-off': 'continuous-r1'}


def read_case(directory):
    directory = checked_path(directory)
    def data(name):
        path = checked_path(directory/name)
        compressed = checked_path(directory/(name+'.gz'))
        text = gzip.decompress(compressed.read_bytes()).decode('utf-8') if compressed.is_file() else path.read_text(encoding='utf-8')
        return [json.loads(line) for line in text.splitlines()] if name.endswith('.jsonl') else json.loads(text)
    return dict(result=data('result.json'), worker=data('worker-result.json'),
                events=data('events.jsonl'), samples=data('memory-samples.json'))


def window_stats(values):
    if len(values) < 20:
        return {'samples': len(values), 'sufficient_samples': False}
    count = max(1, len(values)//5)
    before = statistics.median(v[1] for v in values[:count])
    after = statistics.median(v[1] for v in values[-count:])
    span = (statistics.median(v[0] for v in values[-count:])-
            statistics.median(v[0] for v in values[:count]))
    return dict(samples=len(values), sufficient_samples=True,
                start_median_bytes=before, end_median_bytes=after,
                delta_bytes=after-before, median_time_span_seconds=span,
                mib_per_minute=(after-before)/max(span,.001)*60/1024**2,
                range_bytes=max(v[1] for v in values)-min(v[1] for v in values))


def measure(directory):
    case = read_case(directory)
    events, samples, result = case['events'], case['samples'], case['result']
    observed = dict(processing_and_exit=result['status'],
        elapsed_seconds=result['elapsed_seconds'], peak_tree_private_bytes=result['peak_tree_private_bytes'],
        safety_stop=result['safety_error'], remaining=result['remaining_before_recovery'],
        supervisor_recovery=result['recovery'], long_term_memory_plateau_verified=False)
    modules = directory/'native-modules.json'
    if modules.is_file():
        loaded = json.loads(modules.read_text(encoding='utf-8'))
        observed['overlay_modules'] = [path for path in loaded if 'nvspcap' in path.lower()]
    start = next((event['wall']+10 for event in events if event['event'] == 'idle-start'), None)
    end = next((event['wall'] for event in events if event['event'] == 'idle-end'), None)
    if start is not None and end is not None:
        idle = [sample for sample in samples if start <= sample['wall'] <= end]
        if idle:
            target = max((row for row in idle[-1]['processes'] if 'private_bytes' in row),
                         key=lambda row: row['private_bytes'])
            identity = target['pid'], target['created']
            values = [(sample['wall'],row['private_bytes']) for sample in idle for row in sample['processes']
                      if (row['pid'],row['created']) == identity and 'private_bytes' in row]
            observed['idle_worker'] = dict(pid=identity[0], created=identity[1],
                **window_stats(values), selection='largest private commit at end of idle window; exact PID+creation time')
            observed['idle_tree'] = window_stats([(s['wall'],s['private_bytes']) for s in idle])
    frames = [event for event in events if event['event'] == 'frame']
    if frames:
        values = [(s['wall'],s['private_bytes']) for s in samples
                  if frames[0]['wall']+20 <= s['wall'] <= frames[-1]['wall']]
        observed['post_warmup_tree'] = window_stats(values)
    images = [event for event in events if event['event'] == 'image-complete']
    if images:
        pid = events[0]['pid']
        values = []
        for event in images:
            value = dict(cycle=event['cycle'], source=event['source'])
            rows = [row for sample in samples if event['wall'] <= sample['wall'] <= event['wall']+.5
                    for row in sample['processes'] if row['pid'] == pid and 'private_bytes' in row]
            value['sampled_main_private_bytes'] = statistics.median(r['private_bytes'] for r in rows) if rows else None
            for key in ('memory','python_bytes','tk_images','source_cache_bytes','dlss_cache_bytes','overlay_modules'):
                if key in event:
                    value[key] = event[key]
            values.append(value)
        observed['gui_cycles'] = values
        differences = []
        for before, after in zip(values, values[3:]):
            if before['source'] != after['source'] or 'memory' not in before or 'memory' not in after:
                continue
            differences.append(dict(source=before['source'], before_cycle=before['cycle'], after_cycle=after['cycle'],
                private_delta_bytes=after['memory']['private_bytes']-before['memory']['private_bytes'],
                python_delta_bytes=after['python_bytes']-before['python_bytes'],
                tk_images_before=before['tk_images'], tk_images_after=after['tk_images']))
        observed['gui_same_source_cycle_differences'] = differences
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True, help='Archived evidence directory containing raw/')
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline, task, output = checked_path(args.baseline), checked_path(args.task), checked_path(args.output)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file():
        parser.error('Use a registered tmp task')
    if not output.is_relative_to(task):
        parser.error('Comparison output must stay inside its task')
    pairs = []
    for current, prior in PAIRS.items():
        if not (task/current/'result.json').is_file():
            continue
        pairs.append(dict(case=current, baseline_case=prior,
            before=measure(baseline/'raw'/prior), after=measure(task/current)))
    save(output, dict(scope='User-reported overlay switch off; module inventory determines whether no-overlay isolation was achieved',
        baseline=str(baseline), task=str(task), pairs=pairs))
    for pair in pairs:
        row = {'case': pair['case']}
        for key in ('before', 'after'):
            value = pair[key]
            row[key] = dict(status=value['processing_and_exit'], overlay_modules=value.get('overlay_modules'),
                            idle_worker_mib_per_minute=value.get('idle_worker',{}).get('mib_per_minute'),
                            post_warmup_tree_delta_mib=value.get('post_warmup_tree',{}).get('delta_bytes',0)/1024**2)
        print(json.dumps(row, ensure_ascii=False))


if __name__ == '__main__':
    main()
