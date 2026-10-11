"""Real local GPU teardown through the production Tk resource guard, no capture.

Repeatedly render synthetic frames and prove the exact owned host process exits
before realtime admission. This does not measure global VRAM or game performance.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(DLSS5TOOL_SETTINGS_PATH=str(output/'settings.json'),
                      DLSS5TOOL_QUEUE_PATH=str(output/'queue.json'), DLSS5TOOL_DISABLE_UPDATE_CHECK='1')
    import tkinter as tk
    import numpy as np
    from dlss5tool import gui, app_settings
    from dlss5tool.dlss_host_process import ProcessLive
    settings = {**app_settings.DEFAULTS, 'guidance_mode': 1, 'guidance_flow_backend': 'nvofa',
                'guidance_device': 'cuda', 'guidance_flow_fallback': False,
                'guidance_flow_edge': 128, 'mods_directory': str(output/'absent-addon'),
                'host_backend': 'v2', 'dlss_runtime': '__bundled__', 'intensity': .5}
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    root = tk.Tk()
    root.withdraw()
    errors, cycles = [], []
    root.report_callback_exception = lambda *error: errors.append(str(error))
    app = gui.App(root)
    try:
        for index in range(3):
            live = app._live = ProcessLive(128, 128, settings)
            pixels = np.random.default_rng(index).integers(0, 255, (128, 128, 4), dtype=np.uint8)
            pixels[..., 3] = 255
            assert live.process(pixels, reset=True) is not None
            assert live.process(np.roll(pixels, 2, axis=1)) is not None
            pid = live._session._process.pid
            handle = kernel.OpenProcess(0x00100000, False, pid)
            assert handle
            try:
                assert app._gpu_conflict('realtime').owner == 'preview'
                tick = time.perf_counter()
                app._release_preview_for_realtime()
                callback_ms = (time.perf_counter()-tick)*1000
                ticks = 0
                while app._gpu_release_thread.is_alive():
                    root.update()
                    ticks += 1
                    if time.perf_counter()-tick > 45:
                        raise TimeoutError('GPU release did not finish')
                    time.sleep(.005)
                root.update()
                assert not app._gpu_release_error
                assert app._live is None and app._gpu_conflict('realtime') is None
                assert kernel.WaitForSingleObject(handle, 0) == 0, 'Host still alive after admission'
                cycles.append({'cycle': index, 'host_pid': pid, 'host_exited': True,
                               'release_callback_ms': callback_ms, 'event_pumps': ticks,
                               'release_total_ms': (time.perf_counter()-tick)*1000})
            finally:
                kernel.CloseHandle(handle)
        assert not errors, errors
        report = {'status': 'passed', 'cycles': cycles, 'tk_errors': errors,
                  'scope': 'actual NVOFA/NR hosts, production local release guard; no global VRAM claim'}
        (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        app._on_close()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
