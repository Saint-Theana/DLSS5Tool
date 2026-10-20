"""Archive reference comparison curves and provenance without claiming a cure."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save
from scripts.compare_adapter_isolation import curve
from scripts.analyze_p0_completion import summarize


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reference(directory):
    result = read(directory/'result.json')
    samples = read(directory/'memory-samples.json')
    # Earlier pilot schemas did not yet record the worker PID. Match the
    # original loaded host DLL in the inventories where available instead.
    first = read(directory/'first-output.json') if (directory/'first-output.json').is_file() else None
    close = read(directory/'normal-close.json') if (directory/'normal-close.json').is_file() else None
    end = read(directory/'idle-end.json') if (directory/'idle-end.json').is_file() else None
    pid = first.get('pid') if first else result['started_pid']
    if not pid:
        return dict(label=directory.name, excluded='Pilot did not record its worker identity', result=result)
    begin = first['wall']+10 if first else samples[0]['wall']+20
    finish = (end or close or dict(wall=samples[-1]['wall']))['wall']
    identities = {(r['pid'], r['created']) for s in samples for r in s['processes'] if r['pid']==pid}
    if len(identities) != 1:
        raise ValueError('No unique creation time for '+directory.name)
    points = [(s['wall'],r['private_bytes']) for s in samples if begin<=s['wall']<=finish
              for r in s['processes'] if r['pid']==pid and 'private_bytes' in r]
    data = dict(label=directory.name, process_identity=dict(pid=pid,created=identities.pop()[1]),
        private_commit=curve(points), latter_half_private_commit=curve(points[len(points)//2:]),
        observation_window=dict(begin=begin,end=finish),
        normal_processing_and_exit=not result['failure'] and not result['recovery'] and result['exit_code']==0,
        failure=result['failure'], recovery=result['recovery'], remaining=result['remaining'],
        binary_manifest_unchanged=result['source_and_binary_unchanged'], plateau_verified=False,
        arguments=result['arguments'])
    inventories=read(directory/'modules.json')
    modules={m['path'] for row in inventories for m in row['inventory'].get('modules',[])}
    data['relevant_modules']=[v for v in sorted(modules) if any(k in v.lower() for k in
        ('nvspcap','nvmessagebus','nvcuda','nvwgf2umx','nvngx_dlssnr','160_e658703'))]
    data['module_query_errors']=[r for r in inventories if 'error' in r['inventory']]
    thread_path=directory/'thread-activity.json'
    if thread_path.is_file():
        rows=read(thread_path)
        a,b=rows[0],rows[-1]
        data['thread_notifications']=dict(snapshots=len(rows),span_seconds=b['wall']-a['wall'],
            started_delta=b['thread_activity']['started']-a['thread_activity']['started'],
            detached_delta=b['thread_activity']['detached']-a['thread_activity']['detached'],
            last=b['thread_activity'])
    etw_path=directory/'external-threads.json'
    if etw_path.is_file():
        etw=read(etw_path)
        if etw['pid'] != pid or etw['created'] != data['process_identity']['created']:
            raise ValueError('ETW process identity mismatch')
        attribution=[]
        for group in etw['addresses']:
            matches={}
            for snapshot in inventories:
                for module in snapshot['inventory'].get('modules',[]):
                    if Path(module['path']).name.lower()!='nvmessagebus.dll':
                        continue
                    binary=Path(module['path']).read_bytes()
                    pe=struct.unpack_from('<I',binary,0x3c)[0]
                    if binary[pe:pe+4] != b'PE\0\0':
                        raise ValueError('Invalid PE image')
                    image_size=struct.unpack_from('<I',binary,pe+24+56)[0]
                    offset=group['start_address']-module['base']
                    if 0<=offset<image_size:
                        matches[(module['path'],offset)]=dict(module=module['path'],offset=offset,
                            image_size=image_size,module_sha256=digest(binary))
            if len(matches)!=1:
                raise ValueError('Ambiguous ETW address attribution')
            attribution.append(dict(**group,**next(iter(matches.values()))))
        data['external_thread_activity']=dict(**etw,attribution=attribution,
            note='A thread already alive at the start can produce one extra stop event. No DLL injection.')
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    task,output=checked_path(args.task),checked_path(args.output)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file():
        parser.error('Registered repository task required')
    if not output.is_relative_to(ROOT/'docs/development') or output==ROOT/'docs/development':
        parser.error('Use a new evidence subdirectory')
    cases=[reference(p) for p in sorted(task.iterdir()) if (p/'result.json').is_file()
           and not p.name.startswith(('native-','counter-'))]
    project=[summarize(p) for p in task.iterdir() if p.name.startswith('native-') and (p/'result.json').is_file()]
    output.mkdir(exist_ok=False)
    archive=[]
    for path in sorted(task.rglob('*')):
        checked_path(path)
        if not path.is_file() or path.suffix.lower() not in ('.json','.jsonl','.log','.md','.cmd'):
            continue
        # Stock shaders/runtime configs are reconstructible and covered by the
        # hash manifest. Do not mistake these copied dependency files for logs.
        relative=path.relative_to(task)
        if relative.parts[0]=='veyra':
            continue
        data=path.read_bytes()
        target=checked_path(output/'raw'/relative)
        compressed=path.name=='memory-samples.json'
        if compressed:
            target=target.with_suffix(target.suffix+'.gz')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(gzip.compress(data,mtime=0) if compressed else data)
        restored=gzip.decompress(target.read_bytes()) if compressed else target.read_bytes()
        if restored!=data:
            raise ValueError('Archive verification failed')
        archive.append(dict(source=str(relative),file=str(target.relative_to(output)),
                            source_bytes=len(data),source_sha256=digest(data),
                            archived_sha256=digest(target.read_bytes())))
    sources=[]
    for name in ('verify_upstream_p0.py','summarize_upstream_p0.py','native_external_thread_activity.cpp',
                 'native_thread_activity.cpp','profile_thread_activity.py'):
        source=checked_path(ROOT/'scripts'/name);data=source.read_bytes()
        target=checked_path(output/'sources'/name);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        sources.append(dict(file=str(source.relative_to(ROOT)),sha256=digest(data),bytes=len(data)))
    save(output/'summary.json',dict(reference_cases=cases,project_cases=project,
        criteria=read(task/'criteria.json'),sources=sources,
        limitations='Bounded synthetic single-GPU observations. Reference NR runtimes differ; '
        'standalone uses the same NR runtime as this project. Stock Veyra 1.4.4 is the pinned reference, '
        'not current 2.x. No Magpie stock binary was tested. Shutdown/recovery failures are preserved. '
        'Concurrent processes are attributed by PID+creation time, no throughput comparison.',
        archive=archive,archive_verified=True))
    for row in cases:
        print(json.dumps(dict(label=row['label'],curve=row.get('private_commit'),
                              excluded=row.get('excluded')),ensure_ascii=False))
    print(json.dumps(dict(archived_files=len(archive),archived_bytes=sum(p.stat().st_size
          for p in output.rglob('*') if p.is_file()))))


if __name__=='__main__':
    main()
