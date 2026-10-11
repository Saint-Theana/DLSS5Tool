"""Exercise our own animated window; never selects/captures another application."""
from __future__ import annotations

import argparse
import hashlib
from copy import deepcopy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool.realtime import DEFAULT_CONFIG, RealtimeClient, NR, validate_config, sample_gpu_load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--effect', default='Bilinear')
    parser.add_argument('--output', type=Path, required=True, help='New, isolated case directory (never reused)')
    parser.add_argument('--host', type=Path, default=ROOT / 'runtime/realtime/dlss5_realtime_host.exe')
    parser.add_argument('--config', type=Path, help='Validated control-only config, overrides effect options')
    parser.add_argument('--screenshot', action='store_true', help='Opt in to an owned-source screenshot')
    parser.add_argument('--gpu-sampling', action='store_true')
    parser.add_argument('--source-exe', type=Path, help='Owned realtime_test_source executable')
    parser.add_argument('--source-position', nargs=2, type=int, default=[80, 80])
    parser.add_argument('--source-hdr', action='store_true')
    parser.add_argument('--move-source', nargs=2, type=int, help='Move only our source halfway through the test')
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--capture', type=int, default=0)
    parser.add_argument('--flow', type=int, default=0)
    parser.add_argument('--windowed', action='store_true')
    parser.add_argument('--lifecycle', action='store_true')
    parser.add_argument('--resolution', type=int, default=100)
    parser.add_argument('--protect', action='store_true')
    parser.add_argument('--runtime-directory')
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--anti-flicker', type=int, default=0)
    parser.add_argument('--case', help='Unique evidence label (letters/digits/hyphens)')
    parser.add_argument('--chain', action='store_true', help='NR + SR + FG combined chain')
    parser.add_argument('--static-quality', action='store_true')
    parser.add_argument('--hdr', action='store_true')
    parser.add_argument('--gpu', type=int, default=-1)
    parser.add_argument('--game-mode', action='store_true')
    parser.add_argument('--no-topmost', action='store_true')
    parser.add_argument('--sync-mode', type=int, default=0)
    parser.add_argument('--frame-rate', type=float, default=60)
    parser.add_argument('--protocol-test', action='store_true')
    parser.add_argument('--residual-test', action='store_true', help='Owned NR first-pass five-control live receipts')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    if (args.source_hdr or args.move_source) and not args.source_exe:
        parser.error('HDR/moving source requires --source-exe')
    if not 5 <= args.seconds <= 1800:
        parser.error('--seconds must be between 5 and 1800')
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    if args.source_exe:
        # Monitor rectangles from the native host are physical pixels. Set this
        # before Tk creates any HWND, otherwise SetWindowPos/GetWindowRect use
        # virtualized coordinates at 150% and a "cross-screen" test can lie.
        dpi_user = ctypes.WinDLL('user32', use_last_error=True)
        dpi_user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if not dpi_user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise ctypes.WinError(ctypes.get_last_error())
    root = tk.Tk()
    root.title('DLSS5Tool realtime synthetic acceptance')
    root.geometry('800x450+80+80')
    canvas = tk.Canvas(root, bg='#122033', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    root.update()
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    hwnd = int(user.GetAncestor(root.winfo_id(), 2))
    source = None
    source_metadata = None
    source_moves = []
    if args.source_exe:
        root.withdraw()
        source = subprocess.Popen([str(args.source_exe.resolve()), str(int(args.seconds + 10)),
            *map(str, args.source_position), str(int(args.source_hdr))], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
        incoming = queue.Queue()
        threading.Thread(target=lambda: incoming.put(source.stdout.readline()), daemon=True).start()
        try:
            source_metadata = json.loads(incoming.get(timeout=8))
            if source_metadata.get('pid') != source.pid or not source_metadata.get('hwnd'):
                raise ValueError('Owned source identity mismatch')
            hwnd = source_metadata['hwnd']
        except Exception:
            source.terminate()
            source.wait(timeout=3)
            root.destroy()
            raise
    config = deepcopy(DEFAULT_CONFIG)
    config['effects'] = [{'name': NR if args.effect == 'NR' else args.effect, 'parameters': {}, 'scale': [args.scale, args.scale]}]
    if args.chain:
        config['effects'] = [{'name': NR, 'parameters': {}, 'scale': [1, 1]},
                             {'name': r'DLSS\DLSS_SR', 'parameters': {}, 'scale': [args.scale, args.scale]},
                             {'name': r'DLSSFG\DLSS_FrameGeneration', 'parameters': {}, 'scale': [1, 1]}]
    if args.effect == 'NR' or args.chain:
        config['effects'][0]['parameters']['opticalFlowMethod'] = args.flow
        config['effects'][0]['parameters']['antiFlicker'] = args.anti_flicker
        if args.resolution != 100:
            config['effects'][0]['parameters'].update(enableInputResolutionScaling=1, inputResolutionPercent=args.resolution)
        if args.protect:
            config['quality'].update(protection=True, regions=[[0, 0, 1, .22]])
    config.update(windowed=args.windowed, capture_method=args.capture, hdr=args.hdr, gpu_index=args.gpu)
    config.update(game_mode=args.game_mode, disable_topmost=args.no_topmost, sync_mode=args.sync_mode, frame_rate=args.frame_rate)
    if args.config:
        config = validate_config(json.loads(args.config.read_text(encoding='utf-8')))
    residual_values = dict(residualMultiplier=1.4, shadowStructureMultiplier=.6,
                           reflectionGlowMultiplier=1.3, residualSaturation=.7, residualLightness=1.2)
    if args.residual_test:
        if config['effects'][0]['name'] != NR:
            raise ValueError('Residual probe requires NR as the first effect')
        config['effects'][0]['parameters']['enableResidualControls'] = 1
    client = RealtimeClient({'realtime_runtime_directory': args.runtime_directory} if args.runtime_directory else {},
                            host=args.host, state_root=folder / 'state')
    start = time.monotonic()
    events = []
    clicks = []
    canvas.bind('<Button-1>', lambda e: clicks.append({'x': e.x, 'y': e.y, 'time': time.monotonic()-start}))
    screenshot_sent = False
    last_status = 0
    closing = False
    changed_quality = False
    moved = False
    protocol_checked = False
    parameter_test = None
    residual_run = None
    sampling_stop = threading.Event()
    gpu_samples = queue.Queue(maxsize=1024)
    sampler = None
    def sample():
        while not sampling_stop.is_set():
            item = dict(time=time.monotonic() - start, **sample_gpu_load())
            try:
                gpu_samples.put_nowait(item)
            except queue.Full:
                break
            sampling_stop.wait(2)
    if args.gpu_sampling:
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
    # Independent of Tk callbacks; only terminates the exact child we created.
    def deadline():
        process = client.process
        if process and process.poll() is None:
            process.terminate()
    guard = threading.Timer(args.seconds + 10, deadline)
    guard.daemon = True
    guard.start()

    def finish():
        nonlocal closing
        if closing:
            return
        closing = True
        client.close()
        if source:
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            if source.poll() is None:
                user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE, owned source only
                try:
                    source.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    source.terminate()
                    source.wait(timeout=3)
        sampling_stop.set()
        if sampler:
            sampler.join(timeout=4)
        guard.cancel()
        while not client.events.empty():
            events.append(client.events.get_nowait())
        statuses = [e for e in events if e.get('event') == 'status']
        report = {'effect': args.effect, 'config': config, 'events': events, 'source_clicks': clicks,
                  'rendered': any(e.get('metrics', {}).get('real', 0) > 0 for e in statuses),
                  'native_failures': [e for e in events if e.get('event') in ('error', 'fatal') or e.get('event') == 'ack' and not e.get('ok')],
                  'exit_ok': any(e.get('event') == 'exited' and e.get('returncode') == 0 for e in events)}
        report['quality_confirmed'] = any(e.get('quality_revision', 0) >= 2 and e.get('quality_revision') == e.get('quality_applied_revision') for e in statuses)
        report['parameter_test'] = parameter_test
        report['residual_values'] = residual_values if args.residual_test else None
        report['residual_run'] = residual_run
        report['residual_confirmed'] = bool(residual_run is not None and any(
            e.get('run_id') == residual_run and e.get('effects') and
            all(abs(e['effects'][0].get('parameters', {}).get(k, float('inf')) - v) < 1e-5
                for k, v in residual_values.items()) for e in statuses))
        report['parameter_confirmed'] = bool(parameter_test and any(
            e.get('run_id') == parameter_test['run_id'] and e.get('effects') and
            abs(e['effects'][0].get('parameters', {}).get(parameter_test['name'], float('inf')) - parameter_test['value']) < 1e-5
            for e in statuses))
        report['command_arguments'] = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
        report['duration_seconds'] = time.monotonic() - start
        report['gpu_samples'] = list(gpu_samples.queue)
        report['runtime_selection'] = client.runtime_selection
        report['source_metadata'] = source_metadata
        report['source_moves'] = source_moves
        report['source_exit_code'] = source.returncode if source else None
        with client.host.open('rb') as stream:
            report['host_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        path = folder / 'report.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(path), 'rendered': report['rendered'], 'exit_ok': report['exit_ok'], 'failures': len(report['native_failures']), 'quality_confirmed': report['quality_confirmed']}, ensure_ascii=False), flush=True)
        root.destroy()

    def tick():
        nonlocal screenshot_sent, last_status, changed_quality, protocol_checked, parameter_test, moved, residual_run
        elapsed = time.monotonic() - start
        if elapsed > args.seconds:
            finish()
            return
        if args.move_source and not moved and elapsed > args.seconds / 2:
            moved = True
            user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user.GetDpiForWindow.argtypes = [wintypes.HWND]
            before = user.GetDpiForWindow(hwnd)
            ok = user.SetWindowPos(hwnd, None, *args.move_source, 0, 0, 0x0015)  # no size/z-order/activation
            user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            rect = wintypes.RECT()
            rect_ok = user.GetWindowRect(hwnd, ctypes.byref(rect))
            source_moves.append(dict(time=elapsed, ok=bool(ok), before_dpi=before,
                                     after_dpi=user.GetDpiForWindow(hwnd), position=args.move_source,
                                     actual_rect=[rect.left, rect.top, rect.right, rect.bottom] if rect_ok else None))
        if not source and not (args.static_quality and elapsed > 5):
            animate(elapsed)
        if args.static_quality and elapsed > 7 and not changed_quality:
            changed_quality = True
            value = deepcopy(config['quality']); value['total'] = 0
            client.send('quality', quality=value)
        while True:
            try:
                event = client.events.get_nowait()
            except queue.Empty:
                break
            events.append(event)
            event['probe_time'] = elapsed
            if args.residual_test and residual_run is None and event.get('event') == 'status' and event.get('metrics', {}).get('submitted', 0) > 0:
                live = {p['name'] for p in event.get('parameter_modes', []) if p['mode'] == 1}
                if residual_values.keys() <= live:
                    residual_run = event['run_id']
                    for name, value in residual_values.items():
                        client.send('set_parameter', effect=0, name=name, value=value, run_id=residual_run)
            if args.protocol_test and not protocol_checked and event.get('event') == 'status' and event.get('metrics', {}).get('submitted', 0) > 0:
                protocol_checked = True
                client.send('quality', quality=config['quality'], run_id=event['run_id'] + 100)
                if (args.effect == 'NR' or args.chain) and any(p['name'] == 'intensity' and p['mode'] == 1 for p in event.get('parameter_modes', [])):
                    parameter_test = {'name': 'intensity', 'value': .65, 'run_id': event['run_id']}
                    client.send('set_parameter', effect=0, **parameter_test)
                client.send('compare', run_id=event['run_id'])
                root.after(800, lambda: client.send('compare'))
            if not args.quiet:
                print(json.dumps({k:v for k,v in event.items() if k not in ('parameter_modes','effects','desired_effects')}, ensure_ascii=False), flush=True)
        if args.screenshot and elapsed > 8 and not screenshot_sent:
            screenshot_sent = True
            if client.process and client.process.poll() is None:
                client.send('screenshot')
        if elapsed - last_status >= 1:
            last_status = elapsed
            if client.process and client.process.poll() is None:
                client.send('status')
        root.after(16, tick)

    def animate(elapsed):
        canvas.delete('all')
        w, h = canvas.winfo_width(), canvas.winfo_height()
        for x in range(0, w, 16):
            canvas.create_line(x, 0, x, h, fill='#28415b')
        canvas.create_rectangle((elapsed * 100) % max(1, w-120), 100,
                                (elapsed * 100) % max(1, w-120) + 120, 240, fill='#e8ad3b')
        canvas.create_text(25, 35, anchor='nw', text=f'DLSS5Tool · synthetic moving target\n{elapsed:.2f}s  |  HUD / 细线 / motion | clicks: {len(clicks)}',
                           fill='white', font=('Microsoft YaHei UI', 20))

    root.protocol('WM_DELETE_WINDOW', finish)
    def begin():
        try:
            client.start(hwnd, config, source.pid if source else os.getpid())
        except Exception as error:
            events.append({'event': 'fatal', 'message': str(error)})
            finish()
    root.after(800, begin)
    if args.lifecycle:
        root.after(10000, lambda: root.geometry('960x540'))
        root.after(14000, root.iconify)
        root.after(16000, root.deiconify)
    try:
        tick()
        root.mainloop()
    finally:
        client.close()
        if source and source.poll() is None:
            source.terminate()
            source.wait(timeout=3)
        sampling_stop.set()
        guard.cancel()


if __name__ == '__main__':
    main()
