"""Same-card consumer, single lease, fallback and never-double-encode contracts."""
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from dlss5tool import residual_composition as rc
from dlss5tool.video_export import write_composed_frame


@pytest.fixture
def context():
    source=np.full((12,16,4),30,np.uint8)
    processed=np.full_like(source,50)
    library=mock.Mock()
    def prepare(handle,w,h,fmt,descriptor):
        descriptor[:]=[10,65536,4096,256]
        return 1
    library.dlss5_quality_gpu_prepare.side_effect=prepare
    library.dlss5_quality_compose_gpu.return_value=1
    bridge=SimpleNamespace(library=library,handle=1,gpu_bindings=[])
    lease=SimpleNamespace(pointer=SimpleNamespace(value=123),size=4096,close=mock.Mock())
    writer=SimpleNamespace(width=16,height=12,adapter_luid=7,
        import_shared_output=mock.Mock(return_value=lease),write_device=mock.Mock(),write=mock.Mock())
    settings={'nr_quality':{'total':.7},'_composition_adapter':{'luid_high':0,'luid_low':7}}
    with mock.patch.object(rc,'NATIVE_COMPOSITION_MIN_PIXELS',1), \
            mock.patch.object(rc,'_native_library_path',return_value='candidate.dll'), \
            mock.patch.object(rc,'_native_bridge',return_value=bridge), \
            mock.patch.object(rc,'release_native_composer') as release:
        yield source,processed,settings,writer,bridge,lease,release


def test_same_consumer_reuses_one_slot_and_ack_before_next_dispatch(context):
    a,b,s,w,bridge,lease,_=context
    for _ in range(6):assert rc.compose_to_gpu_writer(a,b,s,w)
    assert len(bridge.gpu_bindings)==1
    w.import_shared_output.assert_called_once()
    assert w.write_device.call_count==6
    assert w.write_device.call_args.args==(123,4096,'rgba',7,256)
    w.write.assert_not_called()


@pytest.mark.parametrize('reason',['different_gpu','small','view','mix','cpu_sink','source_only','shape','old_dll'])
def test_cpu_consumers_and_unsupported_contracts_retain_fallback(context,reason):
    a,b,s,w,bridge,_,_=context
    options={}
    if reason=='different_gpu':w.adapter_luid=8
    elif reason=='small':a,b=a[:1,:1],b[:1,:1]
    elif reason=='view':options['view']=2
    elif reason=='mix':options['mix']=.7
    elif reason=='cpu_sink':del w.import_shared_output
    elif reason=='source_only':s['nr_quality']['total']=0
    elif reason=='shape':b=b[:2,:2]
    elif reason=='old_dll':del bridge.library.dlss5_quality_gpu_prepare
    with mock.patch.object(rc,'NATIVE_COMPOSITION_MIN_PIXELS',2 if reason=='small' else 1):
        assert not rc.compose_to_gpu_writer(a,b,s,w,**options)
    w.write_device.assert_not_called()


def test_dispatch_failure_can_fallback_before_encode(context):
    a,b,s,w,bridge,_,release=context
    bridge.library.dlss5_quality_compose_gpu.return_value=0
    assert not rc.compose_to_gpu_writer(a,b,s,w)
    w.write_device.assert_not_called();release.assert_called_once()


@pytest.mark.parametrize('stage',['import','encode'])
def test_consumer_failure_propagates_without_retry(context,stage):
    a,b,s,w,_,_,_=context
    (w.import_shared_output if stage=='import' else w.write_device).side_effect=RuntimeError('consumer failed')
    with pytest.raises(RuntimeError,match='consumer failed'):
        write_composed_frame(w,a,b,settings=s,order='rgb')
    w.write.assert_not_called()


def test_failed_gpu_dispatch_writes_cpu_frame_once(context):
    a,b,s,w,bridge,_,_=context
    bridge.library.dlss5_quality_compose_gpu.return_value=0
    with mock.patch.object(rc,'_native_compose',return_value=None):
        assert not write_composed_frame(w,a,b,settings=s,order='rgb')
    w.write.assert_called_once()
    assert w.write.call_args.args[0].shape==(12,16,3)


@pytest.mark.parametrize('profile,code',[('hdr10_pq',5),('hdr10_hlg',6)])
def test_hdr_declares_transfer_and_nearest_even_quantization(context,profile,code):
    a,b,s,w,bridge,_,_=context
    a,b=a.astype(np.float16)/255,b.astype(np.float16)/255
    assert rc.compose_to_gpu_writer(a,b,s,w,profile=profile)
    args=bridge.library.dlss5_quality_compose_gpu.call_args.args
    assert args[5]==2  # linear float32 upload, no intermediate half quantization.
    assert args[6][31]==code
    assert w.write_device.call_args.args[2]=='rgba16f'


def test_native_owner_closes_consumer_lease_before_gpu_resource():
    order=[]
    lease=SimpleNamespace(close=lambda:order.append('consumer'))
    lib=SimpleNamespace(dlss5_quality_destroy=lambda _:order.append('producer'))
    bindings=[('binding',lease)]
    rc._destroy_native_bridge(lib,1,bindings)
    assert order==['consumer','producer'] and bindings==[]


@pytest.mark.parametrize('mix',[0,.7,1,1.7])
def test_rgba_path_is_exactly_equivalent_to_bgr_roundtrip(mix):
    import cv2
    from dlss5tool.video_export import compose_output_frame,compose_sdr_rgba
    rng=np.random.default_rng(33)
    a=rng.integers(0,256,(21,25,4),np.uint8)
    b=rng.integers(0,256,a.shape,np.uint8)
    settings={'nr_quality':{'total':.7,'color':.5},'nr_residual':{'residualLightness':.8}}
    with mock.patch.object(rc,'_native_compose',return_value=None):
        expected=cv2.cvtColor(compose_output_frame(cv2.cvtColor(a,cv2.COLOR_RGBA2BGR),
            cv2.cvtColor(b,cv2.COLOR_RGBA2BGR),mix=mix,settings=settings),cv2.COLOR_BGR2RGBA)
        actual=compose_sdr_rgba(a,b,mix,settings=settings)
    assert np.array_equal(actual,expected)


@pytest.mark.parametrize('profile,dtype',[('srgb',np.uint8),('scrgb',np.float32)])
def test_native_wire_snapshots_can_be_borrowed_without_mutation(profile,dtype):
    a=np.full((8,8,4),.5 if dtype==np.float32 else 50,dtype)
    b=a.copy();a.flags.writeable=b.flags.writeable=False
    base,nr,_,_=rc._native_inputs(a,b,order='rgb',profile=profile)
    assert base is a and nr is b
    assert not base.flags.writeable and not nr.flags.writeable
