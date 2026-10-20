"""Process ownership, bounded protocol, shared inventory and early entry routing."""
import copy
import json
import multiprocessing
from pathlib import Path
import runpy
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

from dlss5tool import adapter_probe as ap
from dlss5tool import dlss_engine
from dlss5tool import residual_composition as rc


def inventory(low=10):
    return dict(adapters=[dict(id='dxgi:10DE:2684:12345678:00000001:0000000300000000:P000001000',
        name='Fixture RTX',preference_index=0,vendor_id=0x10DE,device_id=0x2684,
        subsys_id=0x12345678,revision=1,dedicated_video_memory=12*1024**3,
        luid_high=0,luid_low=low,d3d12_feature_level='12_0',cuda_index=0,pci_bus_id='0000:01:00.0')],
        cuda_identity_available=True,warnings=[])


@pytest.fixture
def host(tmp_path):
    path=tmp_path/'host.dll'
    path.write_bytes(b'fixture')
    return path


def test_cached_inventory_is_defensive_and_refresh_replaces_it(host):
    probe=ap.AdapterProbe()
    with mock.patch.object(probe,'_exchange',side_effect=[inventory(10),inventory(20)]) as exchange:
        first=probe.get(host)
        first['adapters'][0]['luid_low']=999
        assert probe.get(host)['adapters'][0]['luid_low']==10
        assert probe.get(host,refresh=True)['adapters'][0]['luid_low']==20
        assert exchange.call_count==2
    probe.close()


def test_runtime_file_change_invalidates_inventory(host):
    probe=ap.AdapterProbe()
    with mock.patch.object(probe,'_exchange',side_effect=[inventory(10),inventory(20)]) as exchange:
        probe.get(host)
        host.write_bytes(b'changed fixture')
        assert probe.get(host)['adapters'][0]['luid_low']==20
        assert exchange.call_count==2
    probe.close()


def test_concurrent_refreshes_share_one_probe(host):
    probe=ap.AdapterProbe()
    entered,leave=threading.Event(),threading.Event()
    results=[]
    def exchange(*_):
        entered.set()
        assert leave.wait(3)
        return inventory()
    def get():
        results.append(probe.get(host,refresh=True))
    with mock.patch.object(probe,'_exchange',side_effect=exchange) as execute:
        threads=[threading.Thread(target=get) for _ in range(4)]
        for thread in threads: thread.start()
        assert entered.wait(1)
        time.sleep(.05)
        leave.set()
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive()
        assert execute.call_count==1
        assert len(results)==4 and all(v==results[0] for v in results)
    probe.close()


def test_concurrent_failure_is_shared_and_next_call_can_retry(host):
    probe=ap.AdapterProbe()
    entered,leave=threading.Event(),threading.Event()
    errors=[]
    def exchange(*_):
        entered.set(); assert leave.wait(3)
        raise ap.AdapterProbeError('fixture failure')
    def get():
        try: probe.get(host)
        except ap.AdapterProbeError as error: errors.append(str(error))
    with mock.patch.object(probe,'_exchange',side_effect=exchange) as execute:
        threads=[threading.Thread(target=get) for _ in range(2)]
        for thread in threads: thread.start()
        assert entered.wait(1); time.sleep(.05); leave.set()
        for thread in threads: thread.join(3)
        assert execute.call_count==1 and errors==['fixture failure']*2
    with mock.patch.object(probe,'_exchange',return_value=inventory()) as execute:
        assert probe.get(host)['adapters']
        execute.assert_called_once()
    probe.close()


def test_invalidating_inflight_probe_cannot_publish_stale_result(host):
    probe=ap.AdapterProbe()
    errors=[]
    def exchange(*_):
        probe.invalidate()
        return inventory()
    with mock.patch.object(probe,'_exchange',side_effect=exchange):
        with pytest.raises(ap.AdapterProbeError,match='失效'): probe.get(host)
    assert probe._cache is None
    with mock.patch.object(probe,'_exchange',return_value=inventory(20)):
        assert probe.get(host)['adapters'][0]['luid_low']==20
    probe.close()


def test_precancelled_lookup_never_allocates_process(host):
    probe=ap.AdapterProbe(); cancel=threading.Event(); cancel.set()
    with mock.patch.object(probe,'_exchange') as exchange:
        with pytest.raises(ap.AdapterProbeError,match='取消'): probe.get(host,cancel=cancel)
        exchange.assert_not_called()
    probe.close()


def test_failed_retirement_remains_owned_and_blocks_new_child(host):
    probe=ap.AdapterProbe(); owner=mock.Mock(); probe._process=owner
    owner.poll.return_value=None
    with mock.patch.object(ap,'_retire',side_effect=RuntimeError('still alive')), \
            mock.patch.object(probe,'_exchange') as exchange:
        with pytest.raises(ap.AdapterProbeError,match='still alive'): probe.get(host)
        assert probe._process is owner
        exchange.assert_not_called()
        with pytest.raises(ap.AdapterProbeError): probe.get(host)
        exchange.assert_not_called()
    with mock.patch.object(ap,'_retire'),mock.patch.object(probe,'_exchange',return_value=inventory()):
        assert probe.get(host)['adapters']
    probe.close()


def test_close_cancels_inflight_owner_and_does_not_cache_result(host):
    probe=ap.AdapterProbe(); entered=threading.Event(); errors=[]
    def exchange(*_):
        entered.set(); assert probe._stop.wait(3)
        return inventory()
    def get():
        try: probe.get(host)
        except ap.AdapterProbeError as error: errors.append(str(error))
    with mock.patch.object(probe,'_exchange',side_effect=exchange):
        thread=threading.Thread(target=get); thread.start(); assert entered.wait(1)
        probe.close(); thread.join(2)
        assert not thread.is_alive() and errors and probe._cache is None
        with pytest.raises(ap.AdapterProbeError,match='关闭'): probe.get(host)


def test_close_failure_keeps_global_owner_until_retry():
    probe=ap.AdapterProbe(); owner=mock.Mock(); probe._process=owner
    owner.poll.return_value=None
    with mock.patch.object(ap,'_default',probe), mock.patch.object(ap,'_retire',side_effect=RuntimeError('still alive')):
        with pytest.raises(RuntimeError,match='still alive'): ap.close()
        assert ap._default is probe and probe._process is owner
        with mock.patch.object(ap,'_retire'):
            ap.close()
        assert ap._default is None


class FakeProcess:
    pid=3456
    def __init__(self,code=None): self.code=code; self.terminated=False
    def poll(self): return self.code
    def wait(self,timeout=None):
        if self.code is None: raise subprocess.TimeoutExpired('fixture',timeout)
        return self.code
    def terminate(self): self.terminated=True; self.code=1
    def kill(self): self.terminate()


@pytest.fixture(autouse=True)
def no_native_job_for_fake_processes(monkeypatch):
    # Synthetic PIDs in these transport tests must never reach Win32 APIs.
    make_job=ap._make_job
    monkeypatch.setattr(ap,'_make_job',lambda process:None if isinstance(process,FakeProcess) else make_job(process))


def test_timeout_retires_child_and_keeps_retry_available(host):
    probe=ap.AdapterProbe(timeout=.05); child=FakeProcess(); receiver,sender=mock.Mock(),mock.Mock()
    receiver.poll.return_value=False
    with mock.patch.object(ap.multiprocessing,'Pipe',return_value=(receiver,sender)), \
            mock.patch.object(ap,'_spawn',return_value=child):
        with pytest.raises(ap.AdapterProbeError,match='超时'): probe.get(host)
    assert child.terminated and probe._process is None and probe._cache is None
    receiver.close.assert_called_once()
    probe.close()


@pytest.mark.parametrize('mutation', ['nonce','pid','version','ok','oversize','json','inventory','exit'])
def test_protocol_or_exit_failure_cannot_publish_inventory(host,mutation):
    probe=ap.AdapterProbe(); child=FakeProcess(0); receiver,sender=mock.Mock(),mock.Mock()
    def spawn(_sender,_host,nonce):
        reply=dict(version=ap.PROTOCOL,nonce=nonce,pid=child.pid,ok=True,inventory=inventory())
        if mutation=='nonce': reply['nonce']='wrong'
        if mutation=='pid': reply['pid']+=1
        if mutation=='version': reply['version']=999
        if mutation=='ok': reply['ok']='yes'
        if mutation=='inventory': reply['inventory']['adapters'][0]['luid_low']=2**32
        if mutation=='exit': child.code=3
        receiver.recv_bytes.return_value=json.dumps(reply).encode()
        if mutation=='json': receiver.recv_bytes.return_value=b'not json'
        if mutation=='oversize': receiver.recv_bytes.side_effect=OSError('bad message length')
        receiver.poll.return_value=True
        return child
    with mock.patch.object(ap.multiprocessing,'Pipe',return_value=(receiver,sender)),mock.patch.object(ap,'_spawn',side_effect=spawn):
        with pytest.raises(ap.AdapterProbeError): probe.get(host)
    assert probe._cache is None and probe._process is None
    receiver.recv_bytes.assert_called_once_with(ap.MAX_MESSAGE)
    probe.close()


def test_empty_inventory_is_success_not_a_query_failure(host):
    probe=ap.AdapterProbe()
    with mock.patch.object(probe,'_exchange',return_value=dict(adapters=[],cuda_identity_available=False,warnings=[])):
        assert probe.get(host)['adapters']==[]
    probe.close()


@pytest.mark.parametrize('mutation', ['duplicate','name','bool','cuda','pci','status','warning'])
def test_inventory_rejects_invalid_device_or_status(mutation):
    value=inventory(); record=value['adapters'][0]
    if mutation=='duplicate': value['adapters'].append(copy.deepcopy(record))
    if mutation=='name': record['name']='X'*129
    if mutation=='bool': record['luid_low']=True
    if mutation=='cuda': record['cuda_index']=-1
    if mutation=='pci': record['pci_bus_id']='X'*33
    if mutation=='status': value['cuda_identity_available']='yes'
    if mutation=='warning': value['warnings']=[0]
    with pytest.raises(ap.AdapterProbeError): ap._validate_inventory(value)


def test_engine_queries_only_service_and_clones_returned_records():
    from dlss5tool import adapter_inventory
    with mock.patch.object(ap,'get_inventory',return_value=inventory()) as query, \
            mock.patch.object(adapter_inventory,'collect',side_effect=AssertionError('parent native query')):
        assert dlss_engine.available_render_adapters(refresh=True)==inventory()['adapters']
        query.assert_called_once_with(dlss_engine.HOST_DLL_V2,refresh=True,cancel=None)


def test_composer_refresh_invalidates_thread_local_adapter_cache():
    with mock.patch.object(rc,'_native_state',threading.local()), \
            mock.patch.object(dlss_engine,'available_render_adapters',side_effect=[inventory(10)['adapters'],inventory(20)['adapters']]) as scan:
        assert rc._composition_adapter({})==(0,10)
        ap._changed()
        assert rc._composition_adapter({})==(0,20)
        assert scan.call_count==2


def test_composer_never_caches_old_inventory_under_new_generation():
    def scan(): ap._changed(); return inventory(10)['adapters']
    with mock.patch.object(rc,'_native_state',threading.local()),mock.patch.object(dlss_engine,'available_render_adapters',side_effect=scan):
        assert rc._composition_adapter({})==(0,10)
        assert rc._native_state.adapter is None


def test_changed_actual_device_invalidates_inventory_and_reports_error():
    def selected(pointer):
        value=pointer._obj; value.luid_high=0; value.luid_low=999; return 1
    library=mock.Mock(); library.dlssnr_selected_adapter.side_effect=selected
    with mock.patch.object(dlss_engine,'invalidate_render_adapters') as invalidate:
        with pytest.raises(RuntimeError,match='显卡信息已变化'):
            dlss_engine._selected_render_adapter(library,inventory()['adapters'],inventory()['adapters'][0])
        invalidate.assert_called_once_with()
    assert dlss_engine.is_render_adapter_error(ap.AdapterProbeError('显卡探测超时'))


@pytest.mark.parametrize('entry',['gui.py','dlss5tool/__main__.py'])
def test_worker_dispatch_precedes_gui_and_installation_lock(entry):
    root=Path(__file__).resolve().parents[1]
    with mock.patch.object(ap,'dispatch',return_value=True) as dispatch, \
            mock.patch.object(multiprocessing,'freeze_support'), \
            mock.patch.dict(sys.modules,{'dlss5tool.gui':None,'dlss5tool.update_helper':None}):
        with pytest.raises(SystemExit) as result: runpy.run_path(str(root/entry),run_name='__main__')
        assert result.value.code==0
        dispatch.assert_called_once_with()


def test_frozen_probe_reuses_current_executable_with_internal_flag():
    with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'executable','C:/fixture/App.exe'):
        assert ap._command(123,'C:/fixture/host.dll','a'*32)==['C:/fixture/App.exe',ap.WORKER_FLAG,'123','C:/fixture/host.dll','a'*32]


def test_source_probe_uses_isolated_base_interpreter_without_site_imports():
    with mock.patch.object(sys,'frozen',False,create=True),mock.patch.object(sys,'_base_executable','C:/fixture/python.exe',create=True):
        command=ap._command(123,'host.dll','a'*32)
    assert command[:4]==['C:/fixture/python.exe','-I','-S','-B']
    assert Path(command[4]).name=='adapter_probe.py'


def test_malformed_internal_entry_never_opens_gui():
    with pytest.raises(SystemExit) as result: ap.dispatch([ap.WORKER_FLAG,'bad'])
    assert result.value.code==2
    assert ap.dispatch([]) is False


def test_spawn_failure_closes_both_pipe_ends_and_allows_retry(host):
    probe=ap.AdapterProbe(); receiver,sender=mock.Mock(),mock.Mock()
    with mock.patch.object(ap.multiprocessing,'Pipe',return_value=(receiver,sender)), \
            mock.patch.object(ap,'_spawn',side_effect=OSError('spawn denied')):
        with pytest.raises(ap.AdapterProbeError,match='spawn denied'): probe.get(host)
    receiver.close.assert_called_once(); sender.close.assert_called_once()
    assert not probe._busy and probe._process is None
    probe.close()


def test_keyboard_interrupt_is_reraised_after_owned_child_retirement(host):
    probe=ap.AdapterProbe(); process=FakeProcess()
    def exchange(*_): probe._process=process; raise KeyboardInterrupt()
    with mock.patch.object(probe,'_exchange',side_effect=exchange):
        with pytest.raises(KeyboardInterrupt): probe.get(host)
    assert process.terminated and probe._process is None and probe._cache is None
    probe.close()


def test_close_timeout_retains_service_and_can_be_retried(host):
    probe=ap.AdapterProbe(); entered,leave=threading.Event(),threading.Event(); errors=[]
    def exchange(*_): entered.set(); assert leave.wait(3); return inventory()
    def get():
        try: probe.get(host)
        except ap.AdapterProbeError as error: errors.append(str(error))
    with mock.patch.object(probe,'_exchange',side_effect=exchange):
        thread=threading.Thread(target=get); thread.start(); assert entered.wait(1)
        with pytest.raises(ap.AdapterProbeError,match='尚在退出'): probe.close(timeout=.01)
        assert probe._busy and probe._closed
        leave.set(); thread.join(2); assert not thread.is_alive() and errors
        probe.close()


def test_cancelled_waiter_does_not_cancel_another_lookup(host):
    probe=ap.AdapterProbe(); entered,leave=threading.Event(),threading.Event(); result=[]
    def exchange(*_): entered.set(); assert leave.wait(3); return inventory()
    with mock.patch.object(probe,'_exchange',side_effect=exchange):
        thread=threading.Thread(target=lambda:result.append(probe.get(host)))
        thread.start(); assert entered.wait(1)
        cancel=threading.Event(); cancel.set()
        with pytest.raises(ap.AdapterProbeError,match='取消'): probe.get(host,cancel=cancel)
        assert not probe._stop.is_set()
        leave.set(); thread.join(2); assert result
    probe.close()


def test_actual_device_must_match_requested_physical_gpu():
    records=inventory()['adapters']; other=copy.deepcopy(records[0])
    other.update(id=other['id'][:-1]+'1',luid_low=20)
    records.append(other)
    def selected(pointer): pointer._obj.luid_low=20; return 1
    library=mock.Mock(); library.dlssnr_selected_adapter.side_effect=selected
    with mock.patch.object(dlss_engine,'invalidate_render_adapters'):
        with pytest.raises(RuntimeError,match='显卡信息已变化'):
            dlss_engine._selected_render_adapter(library,records,records[0])


def test_legacy_actual_identity_without_v2_inventory_remains_supported():
    def selected(pointer):
        pointer._obj.luid_low=20; pointer._obj.vendor_id=0x10DE
        pointer._obj.description='Legacy RTX'; return 1
    library=mock.Mock(); library.dlssnr_selected_adapter.side_effect=selected
    with mock.patch.object(dlss_engine,'invalidate_render_adapters') as invalidate:
        actual=dlss_engine._selected_render_adapter(library,[],{})
    assert actual['luid_low']==20 and actual['name']=='Legacy RTX'
    invalidate.assert_not_called()


def test_gui_probe_close_failure_keeps_window_and_retries():
    from dlss5tool import gui
    app=gui.App.__new__(gui.App)
    app.root=mock.Mock(); app._gpu_thread_alive=lambda _thread:False
    app._cancel_after=mock.Mock(); app._diagnosing=False
    app._exporting=app._queue_running=app._update_downloading=False
    app._cleanup_video_export=mock.Mock(); app.set_status=mock.Mock()
    with mock.patch.object(dlss_engine,'close_adapter_probe',side_effect=[RuntimeError('probe alive'),None]) as close:
        app._on_close()
        app.set_status.assert_called_with('probe alive')
        app.root.destroy.assert_not_called()
        app._render_gpu_scan_thread=mock.Mock()
        app._render_gpu_scan_thread.is_alive.return_value=True
        app._on_close()
        assert close.call_count==2
        app.root.after.assert_called_once_with(50,app._on_close)
        app.root.destroy.assert_not_called()


@pytest.mark.parametrize('kind',['job','pipe'])
def test_failed_independent_probe_owner_is_retained_until_retry(host,kind):
    probe=ap.AdapterProbe(); bad,good=mock.Mock(),mock.Mock()
    bad.close.side_effect=RuntimeError('owner still live')
    if kind=='job': probe._job=bad
    else: probe._connections=[bad,good]
    with mock.patch.object(probe,'_exchange') as exchange:
        with pytest.raises(ap.AdapterProbeError,match='owner still live'): probe.get(host)
        exchange.assert_not_called()
        assert probe._job is bad if kind=='job' else probe._connections==[bad]
    if kind=='pipe': good.close.assert_called_once_with()
    bad.close.side_effect=None
    with mock.patch.object(probe,'_exchange',return_value=inventory()):
        assert probe.get(host)['adapters']
    probe.close()


def test_child_start_gate_is_sent_only_after_job_assignment(host):
    probe=ap.AdapterProbe(); child=FakeProcess(0); receiver,sender=mock.Mock(),mock.Mock(); order=[]
    def spawn(_sender,_host,nonce):
        receiver.recv_bytes.return_value=json.dumps(dict(version=ap.PROTOCOL,nonce=nonce,
            pid=child.pid,ok=True,inventory=inventory())).encode()
        receiver.poll.return_value=True
        return child
    def job(_process): order.append('job'); return None
    def go(data):
        assert order==['job']
        assert json.loads(data)['operation']=='start'
        order.append('go')
    receiver.send_bytes.side_effect=go
    with mock.patch.object(ap.multiprocessing,'Pipe',return_value=(receiver,sender)), \
            mock.patch.object(ap,'_spawn',side_effect=spawn),mock.patch.object(ap,'_make_job',side_effect=job):
        assert probe.get(host)['adapters']
    assert order==['job','go']
    probe.close()
