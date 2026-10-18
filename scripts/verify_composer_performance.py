"""1080p ABBA composition+encoding and bounded native lifecycle observations."""
import argparse
import ctypes as C
import gc
import json
from pathlib import Path
import statistics
import sys
import time
from unittest import mock

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dlss5tool import dlss_engine,residual_composition as rc
from dlss5tool.gpu_export_process import ProcessGpuVideoWriter
from dlss5tool.gpu_export_runtime import load_components
from dlss5tool.video_export import classify_color_info
from scripts.diagnose_composer_lifetime import memory_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,required=True);parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--lifetime-only',action='store_true');parser.add_argument('--label',default='native')
    parser.add_argument('--cycles',type=int,default=16);parser.add_argument('--warmup-cycles',type=int,default=4)
    args=parser.parse_args();task=args.task.resolve();assert (task/'TASK.md').is_file()
    adapter=dlss_engine.available_render_adapters()[0]
    components=load_components();assert components
    options={k:components[k] for k in ('native_library','sdr_ptx','hdr_ptx')}
    settings={'_composition_adapter':adapter,'nr_quality':{'total':.8,'color':.7},
              'nr_residual':{'residualSaturation':.6,'residualLightness':1.2}}
    w,h=1920,1080
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    x=np.stack((.15+.5*xx/w,.2+.4*yy/h,.3+.1*np.sin(xx/37),np.ones_like(xx)),-1)
    y=x.copy();y[...,:3]+=.03*np.sin(yy[...,None]/29)
    report={'adapter':adapter,'size':[w,h],'runs':[],'lifetime':[]}
    with mock.patch.object(rc,'_native_library_path',return_value=str(args.dll.resolve())):
        for profile in (() if args.lifetime_only else ('srgb','hdr10_pq','hdr10_hlg')):
            hdr=profile!='srgb'
            base=x.astype(np.float16) if hdr else np.rint(x*255).astype(np.uint8)
            processed=y.astype(np.float16) if hdr else np.rint(y*255).astype(np.uint8)
            metadata=classify_color_info(dict(color_transfer='smpte2084' if profile=='hdr10_pq' else 'arib-std-b67',
                color_primaries='bt2020',color_space='bt2020nc',pix_fmt='yuv420p10le')) if hdr else None
            for run,gpu in enumerate((False,True,True,False)):
                path=task/f'perf-{args.label}-{profile}-{run}.mp4'
                writer=ProcessGpuVideoWriter(path,w,h,30,hdr_metadata=metadata,
                    device_ordinal=adapter['cuda_index'],**options)
                pid=writer._proc.pid;durations=[]
                try:
                    for i in range(12):
                        started=time.perf_counter()
                        if gpu:assert rc.compose_to_gpu_writer(base,processed,settings,writer,profile=profile)
                        else:
                            result=rc.compose(base,processed,settings,profile=profile)
                            writer.write(result if hdr else result[...,:3][...,::-1].copy())
                        durations.append((time.perf_counter()-started)*1000)
                    result=None
                    rc.release_native_composer();writer.finish()
                except BaseException:
                    rc.release_native_composer();writer.abort();raise
                gc.collect()
                row=dict(profile=profile,gpu_handoff=gpu,run=run,ms=durations,
                    warm_median_ms=statistics.median(durations[4:]),memory_after=memory_snapshot(),encoder_pid=pid,
                    encoder_closed=writer._closed,bridge_released=getattr(rc._native_state,'bridge',None) is None)
                assert row['encoder_closed'] and row['bridge_released']
                report['runs'].append(row)
                print(json.dumps({k:row[k] for k in ('profile','gpu_handoff','run','warm_median_ms')}),flush=True)
        base=np.rint(x*255).astype(np.uint8);processed=np.rint(y*255).astype(np.uint8)
        for cycle in range(args.cycles):
            result=rc.compose(base,processed,settings)
            result=None;rc.release_native_composer();gc.collect()
            snapshot=memory_snapshot()
            library=C.CDLL(str(args.dll.resolve()))
            counts=(C.c_uint64*3)()
            library.dlss5_quality_lifetime.argtypes=[C.POINTER(C.c_uint64)]
            library.dlss5_quality_lifetime.restype=None
            library.dlss5_quality_lifetime(counts)
            snapshot['native_lifetime']=list(counts)
            assert counts[0]==counts[1] and counts[2]==0,list(counts)
            report['lifetime'].append(snapshot)
            print(json.dumps(dict(cycle=cycle,**snapshot)),flush=True)
        stable=[r['private_bytes'] for r in report['lifetime'][args.warmup_cycles:]]
        report['post_warm_private_range_bytes']=max(stable)-min(stable)
        report['post_warm_private_end_minus_start']=stable[-1]-stable[0]
        report['warmup_cycles']=args.warmup_cycles
        report['settled_memory']=[]
        for _ in range(3):
            time.sleep(1)
            report['settled_memory'].append(memory_snapshot())
        report['settled_minus_first_closed_private_bytes']=(report['settled_memory'][-1]['private_bytes']
            -report['lifetime'][0]['private_bytes'])
        # A bounded diagnostic, not the user's long workload acceptance.
    with (task/f'performance-{args.label}.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k.startswith('post_warm')}),flush=True)
    # WDDM deferred destruction is observable even with zero COM references.
    # Gate ownership and the *settled* baseline, not instantaneous working set.
    # Keep the immediate range in the report, including earlier rejected runs.
    assert report['settled_minus_first_closed_private_bytes']<32*1024**2


if __name__=='__main__':main()
