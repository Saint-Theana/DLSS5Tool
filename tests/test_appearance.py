"""Stage, compatibility and portable look contracts without GPU inference."""
from copy import deepcopy
import unittest
import numpy as np
from dlss5tool import appearance, app_settings
from dlss5tool.residual_composition import compose, protection_mask, fine_controls, _hsl, _rgb
from dlss5tool.video_export import compose_output_frame, compose_hdr_frame
from dlss5tool.parameter_transfer import portable_preset, read_portable, from_realtime, to_realtime
from dlss5tool.render_cache import render_identity
from tests.test_parameter_unification import catalog, config
from unittest import mock


class AppearanceTests(unittest.TestCase):
    def test_neutral_identity_old_defaults_and_source_alpha(self):
        base = np.full((7, 9, 4), 90, np.uint8)
        output = base+20
        self.assertIs(compose(base, output, {}), output)
        self.assertIs(compose(base, output, appearance.DEFAULTS), output)
        self.assertEqual(app_settings.validate({})['nr_quality'], appearance.DEFAULT_QUALITY)
        result = compose(base, output, {'nr_quality': {'total': 0}})
        np.testing.assert_array_equal(result, base)
        q = {'nr_quality': {'protection': True, 'feather': 0, 'regions': [[0, 0, .5, 1]]}}
        result = compose(base, output, q)
        np.testing.assert_array_equal(result[:, :5], base[:, :5])
        np.testing.assert_array_equal(result[:, 5:, :3], output[:, 5:, :3])
        np.testing.assert_array_equal(result[..., 3], base[..., 3])

    def test_quality_ranges_mutation_and_cache_stage(self):
        for value in (float('nan'), float('inf'), -1, 2.1, True):
            with self.assertRaises(ValueError):
                appearance.quality({'total': value})
        for regions in ([[0, 0, 0, 1]], [[0, 0, 2, 1]], [[0, 0, 1, 1]]*5):
            with self.assertRaises(ValueError):
                appearance.quality({'regions': regions})
        q = appearance.quality()
        q['regions'].append([0, 0, 1, 1])
        self.assertFalse(appearance.quality()['regions'])
        a, b = {}, {'nr_quality': {'total': .5}}
        self.assertNotEqual(render_identity('example.mp4', a), render_identity('example.mp4', b))
        self.assertEqual(render_identity('example.mp4', appearance.raw_settings(a)),
                         render_identity('example.mp4', appearance.raw_settings(b)))

    def test_hsl_and_directional_controls(self):
        rgb = np.random.default_rng(12).random((15, 17, 3), dtype=np.float32)
        np.testing.assert_allclose(_rgb(_hsl(rgb)), rgb, atol=5e-7)
        base = np.full((2, 3, 3), .5, np.float32)
        for delta, field in ((-.2, 'shadowStructureMultiplier'), (.2, 'reflectionGlowMultiplier')):
            result = fine_controls(base, base+delta, appearance.residual({field: 0}))
            np.testing.assert_array_equal(result, base)

    def test_hdr_linear_global_and_fine_controls(self):
        base, output = np.full((3, 5, 4), .4, np.float16), np.full((3, 5, 4), .6, np.float16)
        for profile in ('hdr10_pq', 'hdr10_hlg'):
            result = compose_hdr_frame(base, output, profile=profile, settings={'nr_quality': {'total': 0}})
            np.testing.assert_array_equal(result, base)
            result = compose_hdr_frame(base, output, profile=profile, settings={'nr_residual': {'residualMultiplier': 2}})
            self.assertTrue(np.isfinite(result).all())
            self.assertTrue((result[..., :3] > output[..., :3]).all())
        self.assertIs(compose(base, output, {}), output)

    def test_legacy_mix_remains_separate_and_view_applied_after_quality(self):
        a, b = np.full((3, 5, 3), 80, np.uint8), np.full((3, 5, 3), 160, np.uint8)
        q = {'nr_quality': {'total': .5}}
        np.testing.assert_array_equal(compose_output_frame(a, b, mix=.5, settings=q), np.full_like(a, 100))
        view = compose_output_frame(a, b, view=2, settings={'nr_quality': {'total': 0}})
        np.testing.assert_array_equal(view[:, 3:], a[:, 3:])

    def test_portable_groups_are_explicit_and_lossless(self):
        c, meta = config(), catalog()
        meta = deepcopy(meta)
        from dlss5tool.realtime import NR
        meta[NR]['parameters'] += [dict(name=k, default=1, min=0, max=2) for k in appearance.RESIDUAL_FIELDS]
        c['quality'].update(total=.35, regions=[[0, 0, .5, 1]], protection=True)
        values = from_realtime(c, meta, 5, appearance.GROUPS)
        saved = portable_preset(values, ('quality',))
        self.assertNotIn('_regions', saved['values'])
        self.assertEqual(read_portable(saved), saved)
        _, changed = to_realtime(saved['values'], config(), meta, saved['groups'])
        self.assertEqual(changed['quality']['total'], .35)
        self.assertFalse(changed['quality']['regions'])
        self.assertEqual(from_realtime(to_realtime(values, config(), meta, appearance.GROUPS)[1], meta, 5, appearance.GROUPS), values)
        bad = deepcopy(saved)
        bad['values']['executable'] = ['bad.exe', None]
        with self.assertRaises(ValueError):
            read_portable(bad)

    def test_feather_uses_pixel_centers_and_union(self):
        q = appearance.quality({'protection': True, 'regions': [[0, 0, 1, 1]], 'feather': 2})
        mask = protection_mask((5, 7), q)
        self.assertAlmostEqual(mask[0, 0], .15625)
        self.assertEqual(mask[2, 3], 1)

    def test_malformed_portable_presets_and_unknown_metadata_fail_closed(self):
        saved = portable_preset(from_realtime(config(), catalog(), 1), ('basic',))
        for groups in ([{}], ['basic', 'basic'], [], ['device']):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                read_portable(dict(saved, groups=groups))
        for pair in (None, '12', [1], [1, True, False]):
            bad = deepcopy(saved)
            bad['values']['intensity'] = pair
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                read_portable(bad)
        with self.assertRaises(ValueError):
            from_realtime(config(), catalog(), 1, ('residual',))

    def test_nvofa_worker_does_not_require_addon_or_import_torch(self):
        import builtins
        from dlss5tool import guidance_worker, mod_paths, guidance_client
        settings = {'guidance_mode': 1, 'guidance_flow_backend': 'nvofa',
                    'guidance_device': 'cuda', 'guidance_flow_edge': 128,
                    'mods_directory': 'not-installed'}
        self.assertTrue(guidance_client.validate(settings)['builtin_nvofa'])
        self.assertEqual(set(mod_paths.guidance_candidates(settings)), {'worker'})
        importer = builtins.__import__
        def guarded(name, *a, **kw):
            if name.split('.')[0] in ('torch', 'torchvision'):
                raise AssertionError('NVOFA imported Torch')
            return importer(name, *a, **kw)
        fake = mock.Mock(w=128, h=128, grid=4)
        fake.calculate.return_value = np.zeros((128, 128, 2), np.float32)
        with mock.patch('builtins.__import__', side_effect=guarded), mock.patch('dlss5tool.nvofa.OpticalFlow', return_value=fake):
            model = guidance_worker.Models(settings)
            try:
                self.assertIsNone(model.torch)
                frame = np.zeros((128, 128, 4), np.uint8)
                model.process(frame, True)
                model.process(frame, False)
                self.assertEqual(model.last_metrics['model_runtime'], 'driver-only')
            finally:
                model.close()

    def test_active_composition_keeps_raw_nr_cache(self):
        from dlss5tool import render_cache as rc
        from tests.test_render_cache import renderer
        import threading
        cache = rc.RenderCache(100000)
        with mock.patch.object(rc, 'export_video', side_effect=renderer):
            try:
                first = cache.session('source', {'nr_quality': {'total': .4}})
                first.wait(0, threading.Event())
                raw = cache.base
                second = cache.session('source', {'nr_quality': {'total': .8}})
                self.assertIs(cache.base, raw)
                self.assertIsNot(first, second)
            finally:
                cache.close()

    def test_session_copies_nested_appearance_snapshot(self):
        from dlss5tool.render_cache import RenderSession
        values = {'nr_quality': {'regions': [[0, 0, .5, 1]], 'protection': True}}
        session = RenderSession('source', values, 1024)
        values['nr_quality']['regions'][0][2] = 1
        self.assertEqual(session.settings['nr_quality']['regions'][0][2], .5)

    def test_active_appearance_does_not_use_gpu_direct_nr_output(self):
        from dlss5tool import frame_generation as fg
        from fractions import Fraction
        import tempfile
        from pathlib import Path
        import cv2
        class Writer:
            def __init__(self, path, *args, **kwargs):
                self.path = path
            def write(self, frame):
                np.testing.assert_array_equal(frame, np.full((128, 128, 3), 70, np.uint8))
            def finish(self):
                self.path.touch()
            def abort(self):
                pass
        nr = mock.Mock()
        nr.process.side_effect = lambda rgba, **kw: cv2.cvtColor(np.full((128, 128, 3), 120, np.uint8), cv2.COLOR_BGR2RGBA)
        capture = mock.Mock()
        capture.read.side_effect = [(True, np.full((128, 128, 3), 20, np.uint8)), (False, None)]
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp)/'in.avi', Path(tmp)/'out.mp4'
            source.touch()
            with mock.patch.object(fg, 'open_capture', return_value=capture), \
                 mock.patch('dlss5tool.super_resolution.query_gpu_memory', return_value=None), \
                 mock.patch('dlss5tool.dlss_host_process.ProcessLive', return_value=nr) as factory, \
                 mock.patch('dlss5tool.gpu_export_process.ProcessGpuVideoWriter', Writer):
                fg.export_video(source, target, multiplier=1, enhance=True,
                    settings={'nr_quality': {'total': .5}}, log_dir=Path(tmp)/'logs',
                    source_inspector=lambda *a, **k: ({'is_hdr': False, 'profile': 'srgb', 'color_primaries': 'bt709'}, Fraction(24), 128, 128, 1),
                    gpu_export={'host_library': 'host', 'native_library': 'nvenc', 'sdr_ptx': 'ptx'})
            self.assertNotIn('_gpu_export_host', factory.call_args.args[2])
            nr.gpu_output_create.assert_not_called()
            nr.process_device.assert_not_called()
            nr.process.assert_called_once()
