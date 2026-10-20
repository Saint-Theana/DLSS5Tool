"""Retire the unsuccessful VM-only probe after all measured runs finish."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.verify_p0_stability import checked_path, save

root = checked_path(Path.cwd())
task = checked_path(root/'tmp/p0-completion-20261020')
case = task/'native-composer-resize-long'
result = json.loads((case/'result.json').read_text())
assert result['status'] == 'passed' and not result['remaining_before_recovery'] and not result['recovery']
assert json.loads((case/'source-comparison.json').read_text())['unchanged']
manifest = {v['file']:v for v in json.loads((case/'run-manifest-after.json').read_text())['files']}
changed = []


def replace_once(text, before, after):
    assert text.count(before) == 1, before[:80]
    return text.replace(before, after)


def update(name, content):
    path = checked_path(root/name)
    original = path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == manifest[name]['sha256'], name
    snapshot = checked_path(task/('source-measured-'+path.name))
    assert not snapshot.exists()
    snapshot.write_bytes(original)
    if isinstance(content,str) and b'\r\n' in original:
        content = content.replace('\n','\r\n')
    after = content.encode('utf-8') if isinstance(content,str) else content
    path.write_bytes(after)
    changed.append(dict(file=name,before_sha256=hashlib.sha256(original).hexdigest(),
                        after_sha256=hashlib.sha256(after).hexdigest(),snapshot=snapshot.name))
    return ''.join(difflib.unified_diff(original.decode().replace('\r\n','\n').splitlines(True),
                                      after.decode().replace('\r\n','\n').splitlines(True),
                                      fromfile='measured/'+name,tofile='final/'+name))


name = 'scripts/verify_p0_stability.py'
text = (root/name).read_text(encoding='utf-8')
text = replace_once(text,"('HEAP_TRACE','native_heap_trace.dll'), ('VIRTUAL_TRACE','native_heap_trace.dll')):",
                         "('HEAP_TRACE','native_heap_trace.dll')):")
text = replace_once(text,"'DLSS5TOOL_P0_THREAD_ACTIVITY','DLSS5TOOL_P0_VIRTUAL_TRACE',",
                         "'DLSS5TOOL_P0_THREAD_ACTIVITY',")
text = replace_once(text,'    cycle_trace, cycle_patches = None, 0\n','')
text = replace_once(text,'''            if index == 1:
                from scripts.profile_native_frame_memory import start_heap_trace
                cycle_trace, cycle_patches = start_heap_trace(work, event, virtual=True)
            if cycle_trace is not None:
                assert cycle_trace.trace_dump(str(work/f'native-virtual-{index}.jsonl')) == 0
''','')
text = replace_once(text,'''    finally:
        try:
            if not closed:
                app._export_cancel_event.set()
                app._exporting = app._queue_running = False
                app._on_close()
        finally:
            if cycle_trace is not None:
                try:
                    assert cycle_trace.trace_dump(str(work/'native-virtual-final.jsonl')) == 0
                finally:
                    restored = cycle_trace.trace_end()
                    event('virtual-trace-ended', restored=restored, patches=cycle_patches)
                    assert restored == cycle_patches
''','''    finally:
        if not closed:
            app._export_cancel_event.set()
            app._exporting = app._queue_running = False
            app._on_close()
''')
patch = update(name,text)
name = 'scripts/profile_native_frame_memory.py'
text = (root/name).read_text(encoding='utf-8')
text = replace_once(text,'def start_heap_trace(work, event, *, virtual=False):','def start_heap_trace(work, event):')
text = replace_once(text,"    flag = 'DLSS5TOOL_P0_VIRTUAL_TRACE' if virtual else 'DLSS5TOOL_P0_HEAP_TRACE'\n    if os.environ.get(flag) != '1':",
                         "    if os.environ.get('DLSS5TOOL_P0_HEAP_TRACE') != '1':")
text = replace_once(text,'    patches = trace.trace_begin_virtual() if virtual else trace.trace_begin()',
                         '    patches = trace.trace_begin()')
text = replace_once(text,"    event('virtual-trace-start' if virtual else 'heap-trace-start', patches=patches,\n          scope='diagnostic process IAT, virtual commits >=64KiB' if virtual else 'diagnostic process IAT, default heap')",
                         "    event('heap-trace-start', patches=patches, scope='diagnostic process IAT, default heap')")
patch += update(name,text)
name = 'scripts/native_heap_trace.cpp'
original = subprocess.check_output(['git','show','6e3db90:'+name],cwd=root)
patch += update(name,original)
(task/'post-acceptance-diagnostics.patch').write_text(patch,encoding='utf-8')
save(task/'post-acceptance-diagnostics.json',dict(reason='VM trace did not cover the large texture allocations and did not meet slot-restoration gate; preserve failed experiment, remove unused feature from final tooling',
    production_code_changed=False,changes=changed))
print(json.dumps(dict(retired_experimental_feature='P0_VIRTUAL_TRACE',changed_files=len(changed))))
