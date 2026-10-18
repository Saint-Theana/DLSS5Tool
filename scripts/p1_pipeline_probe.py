"""Bounded P1 research using existing production entry points, no app changes.

Wall timings include IPC/upload/wait/readback where applicable, not GPU kernel
timestamps. GPU counters are a paused inventory for PID/LUID attribution only.
All sources, outputs and native logs stay inside a pre-registered task folder.
"""
import argparse
from collections import defaultdict
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = ('nr', 'gui_sr_nr', 'sr_nr_fg', 'sr_fg_only', 'sr_fg_total_zero', 'sr_fg_basic_zero')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Profile:
    def __init__(self):
        self.lock = threading.Lock()
        self.times = defaultdict(list)
        self.components, self.hashes, self.completions = [], [], []
        self.inventory = None
        self.counter_seconds = 0.

    @contextmanager
    def timed(self, name):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter()-start)*1000
            with self.lock:
                self.times[name].append(elapsed)

    def wrap(self, name, function):
        def invoke(*args, **kwargs):
            with self.timed(name):
                return function(*args, **kwargs)
        return invoke

    def inventory_now(self):
        pids = {os.getpid(), *(c['pid'] for c in self.components if c.get('pid'))}
        expression = '|'.join(str(pid) for pid in sorted(pids))
        command = ("$ErrorActionPreference='Stop'; "
                   "$c=Get-Counter -Counter @('\\GPU Engine(*)\\Utilization Percentage',"
                   "'\\GPU Process Memory(*)\\Dedicated Usage') -MaxSamples 1; "
                   "$c.CounterSamples | Where-Object {$_.InstanceName -match '^pid_("+
                   expression+")_'} | Select-Object InstanceName,Path,CookedValue | ConvertTo-Json -Compress")
        start = time.perf_counter()
        try:
            executable = os.environ.get('P1_POWERSHELL', 'powershell.exe')
            result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-Command', command],
                capture_output=True, timeout=15, creationflags=NO_WINDOW)
            text = result.stdout.decode('utf-8', errors='replace').strip()
            data = json.loads(text) if result.returncode == 0 and text else []
            self.inventory = {'samples': data, 'pids': sorted(pids),
                'error': result.stderr.decode('utf-8', errors='replace')[-1000:] if result.returncode else None,
                'meaning': 'Paused inventory for PID/LUID attribution; not active utilization evidence'}
        except Exception as error:
            self.inventory = {'error': str(error), 'pids': sorted(pids)}
        self.counter_seconds += time.perf_counter()-start

    def complete(self, count):
        if count >= 4 and self.inventory is None:
            self.inventory_now()
        self.completions.append((count, time.perf_counter()))

    def summary(self):
        stages = {}
        for name, values in self.times.items():
            warm = values[4:] or values
            stages[name] = {'calls': len(values), 'total_ms': sum(values),
                'mean_ms': statistics.mean(values),
                'after_first_4_mean_ms': statistics.mean(warm),
                'after_first_4_median_ms': statistics.median(warm)}
        points = [(n,t) for n,t in self.completions if n >= 4]
        steady = ((points[-1][0]-points[0][0])/(points[-1][1]-points[0][1])
                  if len(points) > 1 else None)
        return {'stages': stages, 'steady_source_fps': steady,
                'components': self.components, 'raw_output_hashes': self.hashes,
                'gpu_counter_inventory': self.inventory, 'counter_pause_seconds': self.counter_seconds}


def instrument(stack, profile):
    import cv2
    from dlss5tool import frame_generation as fg, gui, residual_composition as rc, video_export as ve
    from dlss5tool.dlss_host_process import ProcessLive, _HostSession
    from dlss5tool.super_resolution import ProcessSuperResolution
    from dlss5tool.nvofa import OpticalFlow

    def component(kind, cls, pid_getter, log_getter=None):
        initialize, close = cls.__init__, cls.close
        def init(self, *args, **kwargs):
            with profile.timed(kind+'.initialize'):
                initialize(self, *args, **kwargs)
            record = {'stage': kind, 'pid': pid_getter(self)}
            if kind == 'nr':
                record['adapter'] = dict(self.adapter_info)
            if kind == 'fg':
                record['luid'] = self.luid
            self._p1_record = record
            profile.components.append(record)
        def finish(self, *args, **kwargs):
            record = getattr(self, '_p1_record', None)
            if record is not None and log_getter:
                try:
                    record['native_log'] = Path(log_getter(self)).read_text(encoding='utf-8', errors='replace')[:16000]
                except (OSError, AttributeError):
                    pass
            with profile.timed(kind+'.close'):
                return close(self, *args, **kwargs)
        stack.enter_context(mock.patch.object(cls, '__init__', init))
        stack.enter_context(mock.patch.object(cls, 'close', finish))

    component('nr', ProcessLive, lambda s:s._session._process.pid, lambda s:s._session.log_path)
    component('sr', ProcessSuperResolution, lambda s:s._process.pid, lambda s:s.log_path)
    component('fg', fg.NativeStream, lambda s:s.proc.pid, lambda s:s.log.name)
    for cls, method, name in ((ProcessLive,'process','nr.process'),
            (_HostSession,'copy_input','nr.copy_input'), (_HostSession,'copy_output','nr.copy_output'),
            (_HostSession,'request','nr.rpc'), (ProcessSuperResolution,'process','sr.process'),
            (fg.NativeStream,'process','fg.process'), (OpticalFlow,'calculate','flow.calculate')):
        stack.enter_context(mock.patch.object(cls, method, profile.wrap(name, getattr(cls, method))))

    writer = ve.FFmpegVideoWriter
    initialize, write, finish = writer.__init__, writer.write, writer.finish
    def writer_init(self, *args, **kwargs):
        with profile.timed('encoder.initialize'):
            initialize(self, *args, **kwargs)
        profile.components.append({'stage':'encoder','pid':self._proc.pid,
            'encoder': self.encoder_name, 'nvenc': self.uses_nvenc})
    def writer_write(self, frame):
        with profile.timed('audit.hash'):
            profile.hashes.append(hashlib.sha256(memoryview(frame).cast('B')).hexdigest())
        with profile.timed('encoder.write'):
            return write(self, frame)
    stack.enter_context(mock.patch.object(writer,'__init__',writer_init))
    stack.enter_context(mock.patch.object(writer,'write',writer_write))
    stack.enter_context(mock.patch.object(writer,'finish',profile.wrap('encoder.finish',finish)))

    for module, name, label in ((cv2,'cvtColor','cpu.cvtColor'),(cv2,'resize','cpu.resize'),
            (rc,'compose','compose.total'),(fg,'analysis_rgba8','cpu.analysis'),
            (fg,'inspect_source','source.inspect')):
        stack.enter_context(mock.patch.object(module,name,profile.wrap(label,getattr(module,name))))
    get_bridge = rc._native_bridge
    wrapped_libraries = set()
    def bridge():
        with profile.timed('compose.acquire'):
            owner = get_bridge()
        if owner and id(owner.library) not in wrapped_libraries:
            wrapped_libraries.add(id(owner.library))
            owner.library.dlss5_quality_compose = profile.wrap('compose.dll_upload_dispatch_readback',
                                                              owner.library.dlss5_quality_compose)
        return owner
    stack.enter_context(mock.patch.object(rc,'_native_bridge',bridge))

    capture_factory = fg.open_capture
    class Capture:
        def __init__(self, source):
            self.inner = capture_factory(source)
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def read(self):
            with profile.timed('source.read'):
                return self.inner.read()
    stack.enter_context(mock.patch.object(fg,'open_capture',Capture))
    stack.enter_context(mock.patch.object(gui,'open_capture',Capture))


def generate(task, frames):
    from dlss5tool.video_export import find_ffmpeg
    ffmpeg = find_ffmpeg()
    source = task/'source-960x540.mp4'
    large = task/'source-1920x1080.mp4'
    commands = [(['-f','lavfi','-i','testsrc2=size=960x540:rate=30'],source),
                (['-i',str(source),'-vf','scale=1920:1080'],large)]
    for inputs, destination in commands:
        if destination.exists():
            raise ValueError('Refusing source overwrite: '+str(destination))
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-n',*inputs,'-frames:v',str(frames),
            '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',str(destination)],
            check=True,timeout=30,creationflags=NO_WINDOW)


def run_case(args):
    import numpy as np
    from dlss5tool import dlss_engine, frame_generation as fg, gui
    from dlss5tool.residual_composition import release_native_composer
    from scripts.diagnose_composer_lifetime import memory_snapshot

    task = args.task.resolve(strict=True)
    if not (task/'TASK.md').is_file():
        raise ValueError('Task must be registered first')
    adapters = dlss_engine.available_render_adapters()
    if not adapters:
        raise RuntimeError('No usable render adapter')
    source = task/('source-1920x1080.mp4' if args.case == 'nr' else 'source-960x540.mp4')
    output = task/f'{args.case}-{args.label}.mp4'
    if output.exists():
        raise ValueError('Refusing output overwrite')
    settings = dict(host_backend='v2',host_auto_fallback=False,host_submission='merged',
        host_persistent_buffers=True,host_zero_fast_path=True,host_in_flight=1,
        render_gpu=adapters[0]['id'],guidance_mode=0,style=0,intensity=.7,
        local_tone=1.,local_struct=1.,skin_struct=.5,use_auto_mask=False,
        output_mix=1.,output_view=0,nvenc_preset='p5',quality_profile='high',rate_control='quality',
        video_bitrate_mbps=20,super_resolution_scale=1 if args.case=='nr' else 2)
    if args.case in ('gui_sr_nr','sr_nr_fg'):
        settings['nr_quality'] = {'total': .75}
    elif args.case == 'sr_fg_total_zero':
        settings['nr_quality'] = {'total': 0.}
    elif args.case == 'sr_fg_basic_zero':
        settings.update(intensity=0.,local_tone=0.,local_struct=0.,skin_struct=0.,use_auto_mask=False)
    profile = Profile()
    before = memory_snapshot()
    cancel = threading.Event()
    watchdog = threading.Timer(120,cancel.set)
    watchdog.daemon = True
    report = {'case':args.case,'label':args.label,'settings':settings,'adapters':adapters,
        'source':str(source),'output':str(output),'memory_before':before,
        'scope':'Production serial frame_generation entry; gui_sr_nr uses actual GUI SDR upscale method. No GUI/cache-layer throughput claim.'}
    def progress(message, value=0, **kwargs):
        match = re.match(r'^处理 (\d+)/',str(message))
        if match:
            profile.complete(int(match[1]))
            current = memory_snapshot()
            if current['private_bytes']-before['private_bytes'] > 2*1024**3:
                cancel.set()
        if cancel.is_set():
            raise RuntimeError('Bounded probe stopped or exceeded 120 seconds')
    started = time.perf_counter()
    watchdog.start()
    try:
        with ExitStack() as stack:
            instrument(stack,profile)
            if args.case == 'gui_sr_nr':
                def set_progress(done,total,label):
                    profile.complete(done)
                app = SimpleNamespace(video=str(source),_video_color_info={},root=SimpleNamespace(update=lambda:None),
                    _export_cancel_event=cancel,_guidance_started=lambda *a:None,logln=lambda *a:None,
                    set_progress=set_progress,_raise_if_export_cancelled=lambda:fg.check_cancel(cancel))
                app._iter_frames=lambda *a,**k:gui.App._iter_frames(app,*a,**k)
                report['result'] = gui.App._export_sdr_upscaled_video(app,str(source),{},str(output),args.frames,
                    30.,960,540,settings,settings,0,1.)
            else:
                report['result'] = fg.export_video(source,output,multiplier=1 if args.case=='nr' else 2,
                    scale=1 if args.case=='nr' else 2,enhance=args.case!='sr_fg_only',settings=settings,
                    cancel=cancel,progress=progress,log_dir=task/f'{args.case}-{args.label}-logs')
        report['status']='complete'
    except Exception as error:
        report.update(status='failed',error=str(error))
    finally:
        watchdog.cancel()
        release_native_composer()
        report['elapsed_seconds']=time.perf_counter()-started
        report['memory_after']=memory_snapshot()
        report.update(profile.summary())
    destination=task/f'{args.case}-{args.label}-profile.json'
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'case':args.case,'label':args.label,'status':report['status'],
        'error':report.get('error'),'elapsed_seconds':report['elapsed_seconds'],
        'steady_source_fps':report['steady_source_fps'],
        'stages_ms':{name:round(data['after_first_4_mean_ms'],3)
                     for name,data in report['stages'].items()},
        'report':str(destination)},ensure_ascii=False),flush=True)
    return 0 if report['status']=='complete' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--generate',action='store_true')
    parser.add_argument('--case',choices=CASES,default='nr')
    parser.add_argument('--frames',type=int,default=32)
    parser.add_argument('--label',default='r1')
    args=parser.parse_args()
    if not 8 <= args.frames <= 48:
        parser.error('frames must be 8..48')
    if args.generate:
        if not (args.task/'TASK.md').is_file():
            parser.error('Register TASK.md first')
        generate(args.task,args.frames)
    else:
        raise SystemExit(run_case(args))
