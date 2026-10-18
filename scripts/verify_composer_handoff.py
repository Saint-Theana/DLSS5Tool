"""Verify shared composer output and actual isolated NVENC consumption."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dlss5tool import dlss_engine,residual_composition as rc
from dlss5tool.cuda_session import CudaSession
from dlss5tool.cuda_interop import SharedCudaBuffer
from dlss5tool.gpu_export_process import ProcessGpuVideoWriter
from dlss5tool.gpu_export_runtime import load_components


class DiagnosticSink:
    """Read pixels ONLY in this verification sink, never production encoding."""
    def __init__(self,w,h,device):
        self.width,self.height=w,h
        self.cuda=CudaSession(device);self.adapter_luid=self.cuda.luid;self.frames=[]
    def import_shared_output(self,**descriptor):return SharedCudaBuffer(self.cuda,**descriptor)
    def write_device(self,pointer,nbytes,layout,luid,row_pitch,**_):
        assert luid==self.adapter_luid
        dtype={'rgba':np.uint8,'rgba16f':np.float16,'rgba32f':np.float32}[layout]
        raw=self.cuda.download(pointer,nbytes)
        self.frames.append(np.ndarray((self.height,self.width,4),dtype,buffer=raw,
            strides=(row_pitch,np.dtype(dtype).itemsize*4,np.dtype(dtype).itemsize)).copy())
    def close(self):self.cuda.close()


def run(dll,task,label):
    from dlss5tool.video_export import classify_color_info,find_ffmpeg
    adapter=dlss_engine.available_render_adapters()[0]
    luid=adapter['luid_high'],adapter['luid_low']
    components=load_components()
    assert components,'Existing verified GPU export runtime required'
    report={'dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),'adapter':adapter,'cases':[]}
    w,h=1280,800
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    x=np.stack((.15+.5*xx/w,.2+.4*yy/h,.3+.1*np.sin(xx/37),np.ones_like(xx)),-1)
    changed=x.copy();changed[...,:3]+=.03*np.sin(yy[...,None]/29)
    settings={'_composition_adapter':adapter,'nr_quality':{'total':.8,'color':.7,'luminance':1.1},
              'nr_residual':{'residualSaturation':.6,'residualLightness':1.2}}
    with mock.patch.object(rc,'_native_library_path',return_value=str(dll)):
        for profile in ('srgb','hdr10_pq','hdr10_hlg'):
            hdr=profile!='srgb';dtype=np.float16 if hdr else np.uint8
            base=x.astype(dtype) if hdr else np.rint(x*255).astype(dtype)
            processed=changed.astype(dtype) if hdr else np.rint(changed*255).astype(dtype)
            with mock.patch.object(rc,'_native_compose',return_value=None):
                expected=rc.compose(base,processed,settings,profile=profile)
            production_reference=rc.compose(base,processed,settings,profile=profile)
            rc.release_native_composer()
            sink=DiagnosticSink(w,h,adapter['cuda_index'])
            try:
                assert rc.compose_to_gpu_writer(base,processed,settings,sink,profile=profile)
                raw=sink.frames[-1]
                error=float(np.max(np.abs(raw[...,:3].astype(np.float32)-expected[...,:3].astype(np.float32))))
                raw_difference=np.abs(raw[...,:3].astype(np.float32)-production_reference[...,:3].astype(np.float32))
                print(json.dumps(dict(profile=profile,raw_mean_error=float(raw_difference.mean()),raw_max_error=float(raw_difference.max()),raw_equal_fraction=float(np.mean(raw==production_reference)))),flush=True)
                assert error <= (.0005 if hdr else 1),error
            finally:
                rc.release_native_composer();sink.close()
            # Exact transport gate uses the actual GPU-produced pixels through
            # CPU upload as a control. Keep CPU math parity as a separate gate.
            production_reference=raw
            metadata=(classify_color_info(dict(color_transfer='smpte2084' if profile=='hdr10_pq' else 'arib-std-b67',
                color_primaries='bt2020',color_space='bt2020nc',pix_fmt='yuv420p10le')) if hdr else None)
            options={k:components[k] for k in ('native_library','sdr_ptx','hdr_ptx')}
            paths=[];counts=[]
            for gpu in (False,True):
                path=task/f'handoff-{label}-{profile}-{"gpu" if gpu else "cpu"}.mp4'
                writer=ProcessGpuVideoWriter(path,w,h,30,hdr_metadata=metadata,
                    device_ordinal=adapter['cuda_index'],**options)
                try:
                    for _ in range(6):
                        if gpu:
                            assert rc.compose_to_gpu_writer(base,processed,settings,writer,profile=profile)
                        else:
                            writer.write(production_reference if hdr else production_reference[...,:3][...,::-1].copy())
                    if gpu:
                        bridge=rc._native_bridge(luid)
                        stats=bridge.library.dlss5_quality_stats
                        stats.argtypes=[C.c_void_p,C.POINTER(C.c_uint64),C.POINTER(C.c_uint64)]
                        stats.restype=C.c_int
                        readbacks,frames=C.c_uint64(),C.c_uint64()
                        assert stats(bridge.handle,C.byref(readbacks),C.byref(frames))
                        assert readbacks.value==0 and frames.value==6
                        counts=[readbacks.value,frames.value]
                    rc.release_native_composer()
                    writer.finish()
                except BaseException:
                    rc.release_native_composer();writer.abort();raise
                paths.append(path)
            decoded=[]
            for path in paths:
                command=[find_ffmpeg(),'-v','error','-i',str(path),'-f','rawvideo','-pix_fmt',
                         'rgb48le' if hdr else 'rgb24','pipe:1']
                decoded.append(np.frombuffer(subprocess.run(command,check=True,stdout=subprocess.PIPE).stdout,
                    dtype=np.uint16 if hdr else np.uint8))
            assert decoded[0].size==decoded[1].size==w*h*3*6
            diff=np.abs(decoded[0].astype(np.float32)-decoded[1].astype(np.float32))/(64 if hdr else 1)
            # Lossy encoding can amplify a tiny composition rounding difference.
            print(json.dumps(dict(profile=profile,raw_error=error,encoded_mean=float(diff.mean()),encoded_p999=float(np.percentile(diff,99.9)),encoded_max=float(diff.max()))),flush=True)
            assert diff.mean()<.25 and np.percentile(diff,99.9)<4,(profile,float(diff.mean()),float(diff.max()))
            report['cases'].append(dict(profile=profile,pixel_error=error,frames=6,
                native_cpu_readbacks=counts[0],native_gpu_frames=counts[1],
                encoded_mean_error_in_10_or_8_bit_codes=float(diff.mean()),
                encoded_p999_error=float(np.percentile(diff,99.9)),outputs=[str(p) for p in paths]))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,required=True);parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--label',default='verified')
    args=parser.parse_args();assert (args.task/'TASK.md').is_file()
    result=run(args.dll.resolve(),args.task.resolve(),args.label)
    with (args.task/f'handoff-{args.label}.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))
