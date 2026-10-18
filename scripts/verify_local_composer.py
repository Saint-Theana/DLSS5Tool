"""Real optional DLL device/pixel/lifetime verification, no NGX/model required."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import time
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlss5tool import dlss_engine, residual_composition as rc
from dlss5tool.preview_jobs import LatestPreviewJob


def run(dll):
    records = dlss_engine.available_render_adapters()
    selected = records[0]
    luid = selected['luid_high'], selected['luid_low']
    report = {'adapter': selected, 'dll': str(dll), 'cases': []}
    with mock.patch.object(rc, '_native_library_path', return_value=str(dll)):
        bridge = rc._native_bridge(luid)
        assert bridge is not None and bridge.adapter_luid == luid
        assert rc._native_bridge((0x7fffffff, 0xffffffff)) is None
        report['invalid_adapter_rejected'] = True
        job = LatestPreviewJob(persistent=True, cleanup=rc.release_native_composer)
        threads, owners, durations = [], [], []
        source = np.arange(1001*1001*3, dtype=np.uint32).reshape(1001,1001,3).astype(np.uint8)
        output = np.bitwise_xor(source, 31)
        settings = {'nr_quality': {'total': .7}, '_composition_adapter': selected}
        with mock.patch.object(rc, '_native_compose', return_value=None):
            expected = rc.compose(source, output, settings)
        def compute():
            import threading
            threads.append(threading.get_ident())
            started = time.perf_counter()
            result = rc.compose(source, output, settings)
            durations.append((time.perf_counter()-started)*1000)
            owners.append(rc._native_bridge(luid).handle)
            return result
        try:
            for i in range(6):
                job.request(i, compute)
                deadline = time.monotonic()+30
                while not job.ready():
                    assert time.monotonic()<deadline
                    time.sleep(.002)
                pixels = job.request(i, None)
                error = np.abs(pixels.astype(np.int16)-expected.astype(np.int16))
                assert error.max() <= 1
            assert len(set(threads)) == len(set(owners)) == 1
            report.update(persistent_same_thread=True, persistent_same_handle=True,
                          composition_ms=durations, sdr_max_code_error=int(error.max()))
        finally:
            job.close()
            deadline=time.monotonic()+10
            while job.is_alive():
                assert time.monotonic()<deadline
                time.sleep(.002)
            rc.release_native_composer()
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,required=True)
    parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--name',default='device-worker-native.json')
    args=parser.parse_args()
    assert (args.task/'TASK.md').is_file()
    report=run(args.dll.resolve())
    with (args.task/args.name).open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2)
    print(json.dumps(report,indent=2))
