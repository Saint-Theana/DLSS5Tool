"""Summarize P0 resize, GUI, and NVIDIA service controls without hiding failures."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_adapter_isolation import analyze, curve, lines, read
from scripts.verify_p0_stability import checked_path, save


def summarize(directory):
    out = analyze(directory)
    events = lines(directory/'events.jsonl')
    samples = read(directory/'memory-samples.json', [])
    idle = next((v for v in events if v['event'] == 'idle-start'), None)
    end = next((v['wall'] for v in events if v['event'] == 'idle-end'), None)
    if 'gui_same_size_after_two_rounds' in out and idle and end:
        pid = next(v['pid'] for v in events if v['event'] == 'starting')
        identities = {(p['pid'], p['created']) for s in samples for p in s['processes'] if p['pid'] == pid}
        if len(identities) != 1:
            raise ValueError('GUI PID has no unique observed creation time')
        identity = identities.pop()
        points = [(s['wall'],p['private_bytes']) for s in samples for p in s['processes']
                  if (p['pid'],p['created']) == identity and 'private_bytes' in p
                  and idle['wall']+10 <= s['wall'] <= end]
        out['gui_idle_private_commit'] = curve(points)
        out['gui_idle_last_minute'] = curve([v for v in points if v[0] >= end-60])
        out['gui_idle_identity'] = dict(pid=identity[0], created=identity[1])
        final_image = next(v for v in reversed(events) if v['event'] == 'image-complete')
        workers = []
        for label, field in (('NR','host_pid'), ('VSR','sr_pid')):
            target = final_image.get(field)
            identities = {(p['pid'],p['created']) for s in samples for p in s['processes'] if p['pid'] == target}
            if not target or len(identities) != 1:
                continue
            identity = identities.pop()
            points = [(s['wall'],p['private_bytes']) for s in samples for p in s['processes']
                      if (p['pid'],p['created']) == identity and 'private_bytes' in p
                      and idle['wall']+10 <= s['wall'] <= end]
            workers.append(dict(kind=label,pid=identity[0],created=identity[1],private_commit=curve(points)))
        out['gui_idle_sdk_workers'] = workers
    profiles = []
    for path in directory.glob('*-frame-memory.jsonl'):
        rows = lines(path)
        if not rows:
            continue
        first, last = rows[0], rows[-1]
        thread = dict(snapshots=len(rows), first=first.get('thread_activity'), last=last.get('thread_activity'))
        if len(rows) >= 2 and thread['first'] and thread['last']:
            thread.update(started_delta=thread['last']['started']-thread['first']['started'],
                          detached_delta=thread['last']['detached']-thread['first']['detached'])
        profiles.append(dict(file=path.name, snapshots=len(rows),
            first_private_bytes=first['memory_after_gc']['private_bytes'],
            last_private_bytes=last['memory_after_gc']['private_bytes'],
            thread_activity=thread,
            warning='Single snapshot does not measure growth' if len(rows) < 2 else None))
    out['profiles'] = profiles
    if out['arguments'].get('composer_resize') and not out['arguments'].get('run_seconds'):
        rows = lines(directory/'composer-frame-memory.jsonl')
        frames = out['arguments']['frames']
        # Exclude the extra final snapshot, whose count is not a submitted frame.
        rows = [r for r in rows if r['frame'] <= frames]
        groups = []
        for residue in (0, 1):
            group = [r for r in rows if r['frame'] > 6 and (r['frame']-1) % 2 == residue]
            if group:
                groups.append(dict(size_group=residue, frames=[r['frame'] for r in group],
                    private_delta_bytes=group[-1]['memory_after_gc']['private_bytes']-
                                        group[0]['memory_after_gc']['private_bytes']))
        out['short_resize_same_size_differences'] = groups
        out['short_resize_is_long_term_acceptance'] = False
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    task, output = checked_path(args.task), checked_path(args.output)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file() or not output.is_relative_to(task):
        parser.error('Use a registered task and output inside it')
    data = dict(criteria=read(task/'acceptance-criteria.json'),
                service_restart=read(task/'nvidia-service-restart-result.json'),
                cases=[summarize(p) for p in sorted(task.iterdir()) if (p/'result.json').is_file()],
                limitations='Synthetic local samples, exact process identities, bounded windows. '
                'Unrelated application private bytes are excluded. Processing success is separate from plateau acceptance.')
    save(output, data)
    for row in data['cases']:
        print(json.dumps(dict(label=row['label'], processing=row['processing_and_exit_passed'],
            native_band=row.get('within_declared_private_commit_band'), gui_band=row.get('gui_within_declared_band'),
            mib_per_minute=(row.get('private_commit') or {}).get('mib_per_minute'))))


if __name__ == '__main__':
    main()
