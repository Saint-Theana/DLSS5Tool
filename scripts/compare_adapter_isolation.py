"""Summarize exact-process memory for the adapter-isolation P0 task.

Band assessment is a declared bounded observation, not an hour-scale proof or
the original 32 GiB incident. Controller-stopped pilots never pass acceptance.
"""
import argparse
import json
from pathlib import Path
import statistics as S
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_p0_stability import checked_path,save


def read(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def lines(path):
    return [json.loads(v) for v in path.read_text(encoding='utf-8').splitlines()] if path.is_file() else []


def curve(points):
    if len(points)<10:return None
    count=max(1,len(points)//5)
    start=S.median(v[0] for v in points[:count]); end=S.median(v[0] for v in points[-count:])
    first=S.median(v[1] for v in points[:count]); last=S.median(v[1] for v in points[-count:])
    windows=[S.median(v[1] for v in points[i*len(points)//5:(i+1)*len(points)//5]) for i in range(5)]
    return dict(samples=len(points),start_median_bytes=first,end_median_bytes=last,
        delta_bytes=last-first,measured_span_seconds=end-start,
        mib_per_minute=(last-first)/1024**2/max(end-start,.001)*60,
        window_medians_bytes=windows,window_median_range_bytes=max(windows)-min(windows))


def analyze(directory):
    result=read(directory/'result.json')
    events=lines(directory/'events.jsonl'); samples=read(directory/'memory-samples.json',[])
    worker=read(directory/'worker-result.json')
    stop=read(directory/'controller-stop.json')
    out=dict(label=directory.name,processing_and_exit_passed=result['processing_and_exit_passed'] and not stop,
        safety_error=result['safety_error'],recovery=result['recovery'],remaining=result['remaining_before_recovery'],
        peak_tree_private_bytes=result['peak_tree_private_bytes'],elapsed_seconds=result['elapsed_seconds'],
        arguments=result['run_arguments'],source_comparison=read(directory/'source-comparison.json'),
        evidence_exclusion=stop,worker=worker)
    image_events=[e for e in events if e['event']=='image-complete']
    if image_events:
        groups=[]
        for residue in range(3):
            group=[e for e in image_events if e['cycle']>=6 and e['cycle']%3==residue]
            if not group:continue
            first,last=group[0],group[-1]
            groups.append(dict(size_group=residue,cycles=[v['cycle'] for v in group],
                private_delta_bytes=last['memory']['private_bytes']-first['memory']['private_bytes'],
                python_delta_bytes=last['python_bytes']-first['python_bytes'],
                tk_counts=[v['tk_images'] for v in group]))
        out['gui_same_size_after_two_rounds']=groups
        out['gui_within_declared_band']=bool(len(groups)==3 and len(image_events)>=30 and all(
            abs(g['private_delta_bytes'])<=16*1024**2 and abs(g['python_delta_bytes'])<=8*1024**2 and
            len(set(g['tk_counts']))==1 for g in groups))
        return out
    maps=[]
    for path in directory.glob('*-frame-memory-regions.jsonl'):maps.extend(lines(path))
    maps.sort(key=lambda v:v['wall'])
    idle=next((e for e in events if e['event']=='idle-start'),None)
    end=next((e['wall'] for e in events if e['event']=='idle-end'),None)
    if idle:
        begin=idle['wall']+10
    else:
        progress=next((e for e in events if e['event']=='native-progress'),None)
        begin=(progress['wall'] if progress else samples[0]['wall'])+60 if samples else 0
    end=end or next((e['wall'] for e in reversed(events) if e['event']=='closed'),None)
    end=end or (samples[-1]['wall'] if samples else 0)
    if maps:
        identity=maps[0]['pid'],maps[0]['created']
    else:
        candidates={}
        for sample in samples:
            if begin<=sample['wall']<=end:
                for p in sample['processes']:
                    if 'private_bytes' in p:candidates.setdefault((p['pid'],p['created']),[]).append(p['private_bytes'])
        identity=max(candidates,key=lambda k:S.median(candidates[k])) if candidates else None
    points=[]
    for sample in samples:
        if begin<=sample['wall']<=end:
            for p in sample['processes']:
                if identity==(p['pid'],p['created']) and 'private_bytes' in p:
                    points.append((sample['wall'],p['private_bytes']))
    out['process_identity']=dict(pid=identity[0],created=identity[1]) if identity else None
    out['private_commit']=private=curve(points)
    out['latter_half_private_commit']=curve(points[len(points)//2:])
    if maps:
        selected=[v for v in maps if v['wall']<=end]
        if len(selected) >= 2:
            first,last=selected[0],selected[-1]
            out['native_heap']=dict(first_allocated=first['default_heap'].get('allocated'),
                last_allocated=last['default_heap'].get('allocated'),
                allocated_delta=last['default_heap']['allocated']-first['default_heap']['allocated'],
                measured_span_seconds=last['wall']-first['wall'],
                private_commit_delta_by_type={k:last['private_commit_by_type'][k]-first['private_commit_by_type'][k]
                                             for k in first['private_commit_by_type']},
                sequential_region_query_errors=[v['private_commit_query_errors'] for v in selected],
                warm_heap=curve([(v['wall'],v['default_heap']['allocated']) for v in selected if v['wall']>=begin]))
        else:
            out['native_heap']=dict(available=False, snapshots=len(selected),
                reason='At least two heap snapshots are required for a measured delta')
    enough=bool(points and points[-1][0]-points[0][0]>=280)
    out['within_declared_private_commit_band']=bool(enough and private and abs(private['delta_bytes'])<=16*1024**2 and
        abs(private['mib_per_minute'])<=.25 and private['window_median_range_bytes']<=16*1024**2 and not stop)
    return out


def analyze_controls(task):
    directory=task/'standalone-controls'
    provenance=read(directory/'provenance.json')
    if not provenance:return None
    results=[]
    for entry in provenance['results']:
        rows=lines(directory/(entry['label']+'.jsonl'))
        samples=[v for v in rows if v['event']=='sample' and v['seconds']>=10]
        results.append(dict(**entry,
            private_commit=curve([(v['seconds'],v['private_bytes']) for v in samples]),
            native_heap=curve([(v['seconds'],v['heap_allocated']) for v in samples]),
            modules=[v['name'] for v in rows if v['event']=='module'],
            adapters=[v for v in rows if v['event']=='adapter']))
    return dict(source_sha256=provenance['source_sha256'],binary_sha256=provenance['binary_sha256'],
        concurrent_workload=provenance['concurrent_workload'],limitation=provenance['limitation'],
        initial_exclusion_seconds=10,results=results)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); task=checked_path(args.task); output=checked_path(args.output)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file() or not output.is_relative_to(task):
        parser.error('Use a registered tmp task and output inside it')
    result=dict(declared_native_band=dict(warmup_seconds=60,idle_initial_exclusion_seconds=10,
        median_delta_max_bytes=16*1024**2,absolute_mib_per_minute_max=.25,window_median_range_max_bytes=16*1024**2),
        limits='Sequential metadata snapshots can race allocation/free; no claim about the original incident or other driver environments',
        cases=[analyze(p) for p in sorted(task.iterdir()) if p.is_dir() and (p/'result.json').is_file()],
        standalone_controls=analyze_controls(task))
    save(output,result)
    print(json.dumps([dict(label=v['label'],passed=v['processing_and_exit_passed'],
        mib_per_minute=(v.get('private_commit') or {}).get('mib_per_minute'),
        native_band=v.get('within_declared_private_commit_band'),gui_band=v.get('gui_within_declared_band'))
        for v in result['cases']],ensure_ascii=False))


if __name__=='__main__':main()
