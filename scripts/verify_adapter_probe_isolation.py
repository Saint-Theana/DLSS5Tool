"""Exercise real adapter discovery inside an existing daemon processing worker.

Use a registered tmp task. Captures process identities/modules and query time;
does not create D3D devices, model sessions, media, or global driver settings.
"""
import argparse
import ctypes as C
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def worker(connection):
    from dlss5tool import adapter_probe,dlss_engine
    from scripts.profile_native_frame_memory import loaded_modules
    before=loaded_modules(); begin=time.monotonic()
    try:
        value=adapter_probe.get_inventory(dlss_engine.HOST_DLL_V2)
        first=time.monotonic()-begin
        start=time.monotonic(); cached=adapter_probe.get_inventory(dlss_engine.HOST_DLL_V2)
        cached_time=time.monotonic()-start
        after=loaded_modules()
        connection.send(dict(ok=True,worker_pid=os.getpid(),daemon=multiprocessing.current_process().daemon,
            inventory=value,cold_seconds=first,cached_seconds=cached_time,cached_equal=value==cached,
            newly_loaded_modules=sorted(set(after)-set(before)),
            gpu_modules_after=[p for p in after if any(s in p.lower() for s in ('nvcuda','nvwgf2umx','nvspcap','dlssnr_host'))]))
    except BaseException as error:
        connection.send(dict(ok=False,error=repr(error)))
    finally:
        adapter_probe.close(); connection.close()


def lifecycle(task):
    """Kill only fixture parents and verify kernel retirement of their child."""
    from scripts.ngx_updater_lifecycle_probe import Processes
    from scripts.verify_p0_stability import checked_path,save
    parent_source = '''import ctypes as C,json,os,sys,time
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
'''
    child_source = '''import ctypes as C,json,os,sys,time
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
'''
    for name,source in (('fixture-probe-parent.py',parent_source),('fixture-probe-child.py',child_source)):
        path=checked_path(task/name)
        if path.exists() and path.read_text(encoding='utf-8')!=source:
            raise FileExistsError(path)
        path.write_text(source,encoding='utf-8')
    processes=Processes(); results=[]
    for mode in ('before-go','after-go'):
        ready=checked_path(task/(mode+'-ready.json'))
        if ready.exists(): raise FileExistsError(ready)
        parent=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-S','-B',
            str(task/'fixture-probe-parent.py'),str(task),mode],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        observed={}; recovery=[]
        try:
            deadline=time.monotonic()+10
            while not ready.exists() and parent.poll() is None and time.monotonic()<deadline:
                for row in processes.snapshot():
                    if row['parent']==parent.pid:
                        identity=processes.identity(row)
                        if identity.get('created') is not None: observed[(identity['pid'],identity['created'])]=identity
                time.sleep(.05)
            assert ready.exists(),dict(mode=mode,parent_exit=parent.poll())
            identity=json.loads(ready.read_text(encoding='utf-8'))
            parent.terminate(); parent.wait(timeout=3)
            deadline=time.monotonic()+3; alive=True
            while time.monotonic()<deadline:
                row=next((r for r in processes.snapshot() if r['pid']==identity['pid']),None)
                alive=bool(row and processes.identity(row).get('created')==identity['created'])
                if not alive: break
                time.sleep(.05)
            assert not alive,dict(mode=mode,child=identity)
            results.append(dict(mode=mode,child=identity,parent_exit=parent.returncode,
                                child_retired_on_owner_loss=True))
        finally:
            if parent.poll() is None: parent.terminate(); parent.wait(timeout=3)
            for row in processes.snapshot():
                for previous in observed.values():
                    if row['pid']==previous['pid'] and processes.identity(row).get('created')==previous['created']:
                        recovery.append(processes.terminate_owned(previous))
            assert not recovery,recovery
    save(task/'probe-parent-loss.json',dict(status='passed',cases=results,
        scope='Owned fixture parents only; child native collection blocked for this lifecycle check'))
    print(json.dumps(results,ensure_ascii=False,indent=2))


def main():
    from scripts.verify_p0_stability import checked_path,save
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--lifecycle',action='store_true')
    args=parser.parse_args(); task=checked_path(args.task)
    if not task.is_relative_to(ROOT/'tmp') or not (task/'TASK.md').is_file():
        parser.error('Use a registered task under tmp/')
    if args.lifecycle:
        lifecycle(task)
        return
    context=multiprocessing.get_context('spawn'); parent,child=context.Pipe()
    process=context.Process(target=worker,args=(child,),daemon=True)
    process.start(); child.close()
    try:
        if not parent.poll(35): raise TimeoutError('Daemon inventory fixture timed out')
        result=parent.recv(); process.join(timeout=5)
        assert result['ok'],result
        assert result['daemon'] and result['cached_equal'] and not result['gpu_modules_after'],result
        assert not process.is_alive() and process.exitcode==0
        result['processing_worker_retired']=True
        result['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ('dlss5tool/adapter_probe.py','dlss5tool/adapter_inventory.py','dlss5tool/dlss_engine.py')}
        save(task/'daemon-probe-smoke.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        if process.is_alive(): process.terminate(); process.join(timeout=3)
        if process.is_alive(): process.kill(); process.join(timeout=3)
        parent.close()


if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
