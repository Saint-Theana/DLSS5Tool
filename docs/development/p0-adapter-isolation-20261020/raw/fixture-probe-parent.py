import ctypes as C,json,os,sys,time
from pathlib import Path
task=Path(sys.argv[1]); mode=sys.argv[2]; root=task.parents[1]
sys.path.insert(0,str(root))
from dlss5tool import adapter_probe as ap
def identity(process):
 k=C.WinDLL('kernel32',use_last_error=True)
 k.GetProcessTimes.argtypes=[C.c_void_p]+[C.c_void_p]*4
 values=[C.c_uint64() for _ in range(4)]
 assert k.GetProcessTimes(int(process._handle),*(C.byref(v) for v in values))
 return dict(pid=process.pid,created=values[0].value)
def command(handle,host,nonce):
 return [sys.executable,'-I','-S','-B',str(task/'fixture-probe-child.py'),str(task),mode,ap.WORKER_FLAG,str(handle),host,nonce]
ap._command=command
make_job=ap._make_job
def owned_job(process):
 job=make_job(process)
 if mode=='before-go':
  (task/(mode+'-ready.json')).write_text(json.dumps(identity(process)),encoding='utf-8')
  time.sleep(120)
 return job
ap._make_job=owned_job
ap.get_inventory(str(root/'runtime/dlssnr_host_v2.dll'))
