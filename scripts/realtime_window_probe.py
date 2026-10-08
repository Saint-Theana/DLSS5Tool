"""Exercise our own animated window; never selects/captures another application."""
from __future__ import annotations

import argparse
import hashlib
from copy import deepcopy
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import sys
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool.realtime import DEFAULT_CONFIG, RealtimeClient, NR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--effect', default='Bilinear')
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
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
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
    client = RealtimeClient({'realtime_runtime_directory': args.runtime_directory} if args.runtime_directory else {})
    start = time.monotonic()
    events = []
    clicks = []
    canvas.bind('<Button-1>', lambda e: clicks.append({'x': e.x, 'y': e.y, 'time': time.monotonic()-start}))
    screenshot_sent = False
    last_status = 0
    closing = False
    changed_quality = False
    protocol_checked = False
    parameter_test = None

    def finish():
        nonlocal closing
        if closing:
            return
        closing = True
        client.close()
        while not client.events.empty():
            events.append(client.events.get_nowait())
        statuses = [e for e in events if e.get('event') == 'status']
        report = {'effect': args.effect, 'config': config, 'events': events, 'source_clicks': clicks,
                  'rendered': any(e.get('metrics', {}).get('real', 0) > 0 for e in statuses),
                  'native_failures': [e for e in events if e.get('event') in ('error', 'fatal') or e.get('event') == 'ack' and not e.get('ok')],
                  'exit_ok': any(e.get('event') == 'exited' and e.get('returncode') == 0 for e in events)}
        report['quality_confirmed'] = any(e.get('quality_revision', 0) >= 2 and e.get('quality_revision') == e.get('quality_applied_revision') for e in statuses)
        report['parameter_test'] = parameter_test
        report['parameter_confirmed'] = bool(parameter_test and any(
            e.get('run_id') == parameter_test['run_id'] and e.get('effects') and
            abs(e['effects'][0].get('parameters', {}).get(parameter_test['name'], float('inf')) - parameter_test['value']) < 1e-5
            for e in statuses))
        report['command_arguments'] = vars(args)
        with (ROOT / 'runtime/realtime/dlss5_realtime_host.exe').open('rb') as stream:
            report['host_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        folder = ROOT / 'tmp/realtime-integration-20261003'
        folder.mkdir(exist_ok=True)
        label = args.case or hashlib.sha256(json.dumps(vars(args), sort_keys=True).encode()).hexdigest()[:12]
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in label):
            raise ValueError('Unsafe case name')
        path = folder / ('probe-' + label + '.json')
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(path), 'rendered': report['rendered'], 'exit_ok': report['exit_ok'], 'failures': len(report['native_failures']), 'quality_confirmed': report['quality_confirmed']}, ensure_ascii=False), flush=True)
        root.destroy()

    def tick():
        nonlocal screenshot_sent, last_status, changed_quality, protocol_checked, parameter_test
        elapsed = time.monotonic() - start
        if elapsed > args.seconds:
            finish()
            return
        if not (args.static_quality and elapsed > 5):
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
        if elapsed > 8 and not screenshot_sent:
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
    root.after(800, lambda: client.start(hwnd, config))
    if args.lifecycle:
        root.after(10000, lambda: root.geometry('960x540'))
        root.after(14000, root.iconify)
        root.after(16000, root.deiconify)
    tick()
    root.mainloop()


if __name__ == '__main__':
    main()
