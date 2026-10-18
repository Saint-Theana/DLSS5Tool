"""Bounded real NR -> local composition -> isolated NVENC production routes."""
import argparse
import ctypes as C
import gc
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dlss5tool import frame_generation as fg, gui, residual_composition as rc
from dlss5tool.gpu_export_runtime import load_components,create_video_writer
from dlss5tool.video_export import find_ffmpeg,probe_video_stream
from scripts.diagnose_composer_lifetime import memory_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True);parser.add_argument('--dll',type=Path,required=True)
    parser.add_argument('--label',default='final')
    args=parser.parse_args();task=args.task.resolve();assert (task/'TASK.md').is_file()
    components=load_components();assert components
    report={'cases':[],'memory_before':memory_snapshot()}
    handoff=rc.compose_to_gpu_writer
    events=[]
    def observed(*a,**k):
        result=handoff(*a,**k)
        if result:
            bridge=rc._native_state.bridge
            stat=bridge.library.dlss5_quality_stats
            stat.argtypes=[C.c_void_p,C.POINTER(C.c_uint64),C.POINTER(C.c_uint64)];stat.restype=C.c_int
            readbacks,frames=C.c_uint64(),C.c_uint64()
            assert stat(bridge.handle,C.byref(readbacks),C.byref(frames))
            events.append(dict(readbacks=readbacks.value,gpu_frames=frames.value))
        return result
    def writer(*a,**k):return create_video_writer(*a,gpu_options=components,**k)
    with mock.patch.object(rc,'_native_library_path',return_value=str(args.dll.resolve())), \
         mock.patch.object(rc,'compose_to_gpu_writer',observed), \
         mock.patch.object(gui,'FFmpegVideoWriter',writer):
        for profile in ('srgb','hdr10_pq','hdr10_hlg'):
            source=task/f'pipeline-{args.label}-source-{profile}.mp4'
            hdr=profile!='srgb';transfer='smpte2084' if profile=='hdr10_pq' else 'arib-std-b67'
            codec=(['-c:v','libx265','-preset','ultrafast','-x265-params',
                    'pools=2:frame-threads=1:log-level=error:colorprim=9:colormatrix=9:transfer='+('16' if profile=='hdr10_pq' else '18'),
                    '-pix_fmt','yuv420p10le','-color_primaries','bt2020','-colorspace','bt2020nc','-color_trc',transfer]
                   if hdr else ['-c:v','libx264','-preset','fast','-pix_fmt','yuv420p'])
            subprocess.run([find_ffmpeg(),'-v','error','-n','-f','lavfi','-i','testsrc2=size=1280x800:rate=30',
                            '-frames:v','6',*codec,str(source)],check=True,timeout=30)
            meta=probe_video_stream(find_ffmpeg(),source);assert meta['profile']==profile
            settings=dict(host_backend='v2',host_auto_fallback=False,host_in_flight=1,
                guidance_mode=0,intensity=.5,local_tone=.5,local_struct=.5,skin_struct=.5,
                hdr_mode=True,output_mix=1,output_view=0,host_zero_fast_path=True,
                nr_quality={'total':.8,'color':.7},nr_residual={'residualSaturation':.6})
            for route in (('generic','gui') if hdr else ('generic',)):
                events.clear();output=task/f'pipeline-{args.label}-{route}-{profile}.mp4'
                if route=='generic':
                    result=fg.export_video(source,output,multiplier=1,scale=1,enhance=True,
                        settings=settings,gpu_export=components,log_dir=task/f'pipeline-{args.label}-{profile}-logs')
                    assert result['composition_gpu_frames']==6
                else:
                    app=SimpleNamespace(_guidance_started=lambda *a:None,logln=lambda *a:None,
                        _raise_if_export_cancelled=lambda:None,set_progress=lambda *a:None,
                        root=SimpleNamespace(update=lambda:None))
                    export_settings=dict(super_resolution_scale=1,nvenc_preset='p5',
                        quality_profile='high',rate_control='quality',video_bitrate_mbps=20,output_size=None)
                    result=gui.App._export_hdr_video(app,str(source),meta,str(output),6,30,1280,800,
                        settings,export_settings,0,1)
                assert len(events)==6 and events[-1]==dict(readbacks=0,gpu_frames=6),events
                assert getattr(rc._native_state,'bridge',None) is None
                actual=probe_video_stream(find_ffmpeg(),output)
                assert actual['frames']==6 and actual['profile']==profile,actual
                if hdr:assert actual['pixel_format']=='yuv420p10le'
                gc.collect()
                report['cases'].append(dict(profile=profile,route=route,result=result,
                    handoff_events=events.copy(),output=actual,memory_after=memory_snapshot()))
                print(json.dumps(dict(profile=profile,route=route,status='complete',events=len(events))),flush=True)
    report['memory_after']=memory_snapshot()
    with (task/f'pipeline-{args.label}.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2,ensure_ascii=False)


if __name__=='__main__':main()
