import ctypes as C,json,os,sys,time
from pathlib import Path
task=Path(sys.argv[1]); mode=sys.argv[2]; root=task.parents[1]
sys.path.insert(0,str(root))
from dlss5tool import adapter_probe as ap,adapter_inventory
def blocked_collect(host):
 k=C.WinDLL('kernel32',use_last_error=True)
 k.GetCurrentProcess.restype=C.c_void_p
 k.GetProcessTimes.argtypes=[C.c_void_p]+[C.c_void_p]*4
 values=[C.c_uint64() for _ in range(4)]
 assert k.GetProcessTimes(k.GetCurrentProcess(),*(C.byref(v) for v in values))
 (task/(mode+'-ready.json')).write_text(json.dumps(dict(pid=os.getpid(),created=values[0].value)),encoding='utf-8')
 time.sleep(120)
 raise RuntimeError('fixture should have been retired')
adapter_inventory.collect=blocked_collect
assert ap.dispatch(sys.argv[3:])
