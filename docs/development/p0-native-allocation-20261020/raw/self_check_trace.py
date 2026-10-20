import ctypes as C
import json
from pathlib import Path

root = Path(__file__).resolve().parent
output = root/'self-check-trace-r2'
output.mkdir(exist_ok=False)
client = C.WinDLL(str(root/'heap_trace_client.dll'))
client.test_allocate.argtypes = [C.c_size_t]
client.test_allocate.restype = C.c_void_p
client.test_reallocate.argtypes = [C.c_void_p, C.c_size_t]
client.test_reallocate.restype = C.c_void_p
client.test_free.argtypes = [C.c_void_p]
trace = C.WinDLL(str(root/'native_heap_trace.dll'))
trace.trace_dump.argtypes = [C.c_wchar_p]
patches = trace.trace_begin()
assert patches > 0, patches
def snapshot(name):
    path = output/(name+'.jsonl')
    assert trace.trace_dump(str(path)) == 0
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    modules = [r for r in rows if r['kind'] == 'module' and Path(r['path']).name == 'heap_trace_client.dll']
    assert len(modules) == 1
    base, size = int(modules[0]['base'],16), modules[0]['size']
    return sum(r['live'] for r in rows if r['kind'] == 'stack' and any(
        base <= int(f,16) < base+size for f in r['frames']))

p = None
try:
    p = client.test_allocate(16*1024**2)
    assert p and snapshot('trace-self-alloc') == 16*1024**2
    p = client.test_reallocate(p, 24*1024**2)
    assert p and snapshot('trace-self-realloc') == 24*1024**2
    assert client.test_free(p)
    p = None
    assert snapshot('trace-self-free') == 0
finally:
    if p:
        client.test_free(p)
    restored = trace.trace_end()
assert restored == patches, (restored, patches)
print(json.dumps(dict(status='passed', allocate_bytes=16*1024**2,
                     reallocate_bytes=24*1024**2, retained_after_free=0,
                     patched_slots=patches, restored_slots=restored)))
