import builtins
from pathlib import Path
import unittest
from unittest import mock
import numpy as np
from dlss5tool import nvofa, app_settings
from dlss5tool.optical_flow_contract import descriptor, output_shape, S10_5_SCALE
from dlss5tool.guidance_worker import Models

ROOT = Path(__file__).resolve().parents[1]


class OpticalFlowContractTests(unittest.TestCase):
    def test_native_d3d11_and_local_cuda_agree_on_grid_math(self):
        # Verify the pinned native shader still uses the reference semantics.
        native = (ROOT/'third_party/realtime/magpie/src/Magpie.Core/NvidiaOpticalFlowProvider.cpp').read_text(encoding='utf-8')
        self.assertIn('return float2(field.Load(int3(p, 0))) / 32.0;', native)
        self.assertIn('sourcePixel / float(GridSize) - 0.5', native)
        self.assertIn('float2 p = float2(tid.xy) + 0.5;', native)
        for grid in (1, 2, 4):
            h, w = 32, 48
            gh, gw = output_shape(w, h, grid)
            values = np.random.default_rng(grid).integers(-1000, 1000, (gh, gw, 2), dtype=np.int16)
            expected = np.empty((h, w, 2), np.float32)
            for y in range(h):
                for x in range(w):
                    gx, gy = (x+.5)/grid-.5, (y+.5)/grid-.5
                    ix, iy = int(np.floor(gx)), int(np.floor(gy))
                    ax, ay = gx-ix, gy-iy
                    sample = lambda xx, yy: values[min(max(yy, 0), gh-1), min(max(xx, 0), gw-1)].astype(np.float32)/S10_5_SCALE
                    expected[y, x] = (sample(ix, iy)*(1-ax)+sample(ix+1, iy)*ax)*(1-ay) + (sample(ix, iy+1)*(1-ax)+sample(ix+1, iy+1)*ax)*ay
            np.testing.assert_allclose(nvofa.decode_flow(values, w, h), expected, atol=1e-6)

    def test_quality_namespaces_remain_distinct(self):
        cuda, d3d = descriptor('cuda'), descriptor('d3d11')
        self.assertEqual(cuda['vector_units'], d3d['vector_units'])
        self.assertNotEqual(cuda['quality_namespace'], d3d['quality_namespace'])
        self.assertFalse(cuda['session_sharing'])
        with self.assertRaises(ValueError):
            output_shape(0, 8)

    def test_native_model_initialization_never_imports_torch(self):
        original_import = builtins.__import__
        attempted = []
        def guarded(name, *args, **kwargs):
            if name.split('.')[0] in ('torch', 'torchvision', 'depth_anything_v2'):
                attempted.append(name)
                raise AssertionError('Pure NVOFA imported a model runtime')
            return original_import(name, *args, **kwargs)
        settings = {**app_settings.DEFAULTS, 'guidance_mode': 1, 'guidance_flow_backend': 'nvofa',
                    'guidance_execution': 'serial', 'guidance_cache_mb': 0}
        with mock.patch('builtins.__import__', side_effect=guarded), \
                mock.patch.object(Models, '_infer_flow'):
            model = Models(settings)
            try:
                self.assertIsNone(model.torch)
            finally:
                model.close()
        self.assertEqual(attempted, [])
