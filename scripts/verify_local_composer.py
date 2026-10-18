"""Real optional DLL device/pixel/lifetime verification, no NGX/model required."""
import argparse
import ctypes
import hashlib
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
    report = {'adapter': selected, 'dll': str(dll), 'dll_sha256': hashlib.sha256(dll.read_bytes()).hexdigest(), 'cases': []}
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
        rng = np.random.default_rng(20261019)
        # Signed/over-white colors, non-neutral luma/chroma and direction,
        # full-frame mask coordinates, odd extents and preserved source alpha.
        for profile in ('srgb', 'hdr10_pq', 'hdr10_hlg', 'scrgb'):
            for dtype in ((np.uint8,) if profile == 'srgb' else (np.float16, np.float32, np.uint16)):
                if profile == 'scrgb' and dtype == np.uint16:
                    continue
                x = rng.uniform(-.3 if profile == 'scrgb' else .002,
                                4.0 if profile == 'scrgb' else .95, (129, 133, 4)).astype(np.float32)
                y = x + rng.uniform(-.12, .12, x.shape).astype(np.float32)
                if profile != 'scrgb': y = np.clip(y, .00001, 1)
                scale = np.iinfo(dtype).max if np.dtype(dtype).kind == 'u' else 1
                x, y = (np.rint(x*scale).astype(dtype), np.rint(y*scale).astype(dtype)) if scale != 1 else (x.astype(dtype), y.astype(dtype))
                for order in ('rgb', 'bgr'):
                    settings = dict(_composition_adapter=selected,
                        nr_quality=dict(total=1.7, darken=.8, brighten=1.3, color=.4, luminance=1.2,
                                        protection=True, regions=[[.1,.15,.7,.8]], feather=6),
                        nr_residual=dict(residualMultiplier=1.3, residualSaturation=.6,
                            residualLightness=1.4, shadowStructureMultiplier=.7, reflectionGlowMultiplier=1.5))
                    with mock.patch.object(rc, '_native_compose', return_value=None):
                        expected = rc.compose(x,y,settings,order=order,profile=profile)
                    with mock.patch.object(rc,'NATIVE_COMPOSITION_MIN_PIXELS',1):
                        values = rc.appearance.preflight(settings,hdr=profile!='srgb')
                        actual = rc._native_compose(x,y,values,order=order,profile=profile,adapter_luid=luid)
                        assert actual is not None, profile
                    difference=np.abs(actual[...,:3].astype(np.float32)-expected[...,:3].astype(np.float32))
                    # <=3/65535 is <0.05 of one 10-bit code. Float32 GPU
                    # arithmetic differs by a few ulps before CPU OETF.
                    limit = (1 if dtype == np.uint8 else 3) if scale != 1 else .004 if dtype == np.float16 and profile == 'scrgb' else .0005 if dtype == np.float16 else .00005
                    assert difference.max() <= limit, (profile,str(dtype),float(difference.max()))
                    assert np.array_equal(actual[...,3],x[...,3])
                    report['cases'].append(dict(profile=profile,dtype=np.dtype(dtype).name,order=order,
                        max_error=float(difference.max()),limit=limit,alpha_exact=True))
        for weights, rec2100 in (((.2126,.7152,.0722),False),((.2627,.6780,.0593),True)):
            x=rng.uniform(-.5,4,(43,47,4)).astype(np.float32)
            y=x+rng.uniform(-.3,.3,x.shape).astype(np.float32)
            values=rc.appearance.preflight(settings,hdr=True)
            payload=rc._native_quality_values(values,'scrgb')
            payload[30]=float(rec2100)
            expected=rc.global_controls(x[...,:3],rc.hdr_fine_controls(x[...,:3],y[...,:3],values['nr_residual'],weights),values['nr_quality'],weights)
            result=np.empty_like(x)
            bridge=rc._native_bridge(luid)
            ok=bridge.library.dlss5_quality_compose(bridge.handle,
                ctypes.c_void_p(x.ctypes.data),ctypes.c_void_p(y.ctypes.data),ctypes.c_void_p(result.ctypes.data),
                47,43,2,(ctypes.c_float*32)(*payload),32)
            assert ok
            error=float(np.max(np.abs(result[...,:3]-expected)))
            assert error<1e-5,error
            report['cases'].append(dict(linear_weights=weights,max_error=error,limit=1e-5))
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
