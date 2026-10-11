"""Screenshot P0/P2 contract: actual adapters, HDR math and cache boundaries."""
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import tempfile
import unittest
import numpy as np
from dlss5tool import appearance, parameter_contract as contract, app_settings
from dlss5tool.residual_composition import compose, hdr_fine_controls
from dlss5tool.video_export import compose_hdr_frame, _pq_eotf, _pq_oetf, _hlg_eotf, _hlg_oetf
from dlss5tool.parameter_transfer import from_realtime, to_realtime, portable_preset, read_portable


class ContractTests(unittest.TestCase):
    def test_composition_revision_invalidates_derived_not_raw_nr(self):
        from dlss5tool import render_cache as cache
        raw = appearance.raw_settings({'intensity': .7, 'output_mix': 1})
        look = dict(raw, nr_residual={'residualMultiplier': 1.5})
        a, b = cache.render_identity('synthetic', raw), cache.render_identity('synthetic', look)
        with mock.patch.object(cache, 'COMPOSITION_VERSION', 999):
            self.assertEqual(a, cache.render_identity('synthetic', raw))
            self.assertNotEqual(b, cache.render_identity('synthetic', look))

    def test_hdr_nr_only_preview_uses_full_precision_pipeline(self):
        from dlss5tool.shared_render_preview import SharedRenderPreview
        from dlss5tool.preview_feedback import PreviewFeedback
        config = dict(hdr_mode=True, super_resolution_scale=1, frame_generation_multiplier=1)
        app = SimpleNamespace(video='synthetic.mkv', _export_settings={},
            _video_color_info={'is_hdr': True}, _preview_effect_settings=lambda: config,
            _local_adjustments=mock.Mock())
        self.assertTrue(SharedRenderPreview._uses_shared_render(app))
        PreviewFeedback._set_parameter_status(app, 'pending')
        app._local_adjustments.set_operation_state.assert_called_with('pending', hdr=True)
        config['hdr_mode'] = False
        self.assertFalse(SharedRenderPreview._uses_shared_render(app))
        PreviewFeedback._set_parameter_status(app, 'pending')
        app._local_adjustments.set_operation_state.assert_called_with('pending', hdr=False)
        config['super_resolution_scale'] = 2
        self.assertTrue(SharedRenderPreview._uses_shared_render(app))

    def test_copy_honors_narrower_installed_backend_without_partial_write(self):
        from copy import deepcopy
        from tests.test_parameter_unification import config, catalog
        from dlss5tool.realtime import NR
        meta = catalog()
        meta[NR]['parameters'] += [contract.PARAMETERS['nr_residual.' + k].descriptor(name=k) for k in contract.RESIDUAL]
        source = config()
        values = from_realtime(source, meta, 5, ('residual',))
        values['nr_residual.residualMultiplier'] = ('1.8', None)
        next(p for p in meta[NR]['parameters'] if p['name'] == 'residualMultiplier')['max'] = 1.5
        before = deepcopy(source)
        with self.assertRaises(ValueError):
            to_realtime(values, source, meta, ('residual',))
        self.assertEqual(source, before)

    def test_single_source_defaults_ranges_and_backend_metadata(self):
        for p in contract.BASIC:
            self.assertEqual(app_settings.DEFAULTS[p.key], p.default)
        for name in contract.RESIDUAL:
            p = contract.PARAMETERS['nr_residual.' + name]
            self.assertEqual(appearance.residual()[name], p.default)
            for value in (p.minimum-.01, p.maximum+.01, float('nan'), True):
                with self.assertRaises(ValueError):
                    appearance.residual({name: value})
        native = dict(name='pass2_skinStructureStrength', default=0, min=0, max=3, integer=False, step=.1)
        mapped = contract.native_descriptor(native)
        self.assertEqual(mapped['contract_key'], 'skin_struct')
        self.assertEqual((mapped['default'], mapped['max']), (0, 3))
        self.assertNotIn('label', native)
        unknown = dict(name='vendor-private', min=3)
        self.assertEqual(contract.native_descriptor(unknown), unknown)

    def test_mode_support_update_and_receipts(self):
        self.assertEqual(contract.update_policy('residual', mode='local'), 'compose')
        self.assertEqual(contract.update_policy('basic', mode='local'), 'recompute')
        for mode in (None, 0, 2, 99):
            self.assertEqual(contract.update_policy('residual', mode='realtime', native_mode=mode), 'restart')
        self.assertEqual(contract.update_policy('residual', mode='realtime', native_mode=1), 'live')
        self.assertFalse(contract.capabilities(mode='realtime', hdr=True)['residual'])
        self.assertTrue(contract.capabilities(mode='realtime', hdr=True, ready={'appearance_hdr_residual_version': 1})['residual'])
        self.assertTrue(contract.capabilities(mode='local', hdr=True)['residual'])
        for mode in ('local', 'realtime'):
            self.assertFalse(contract.capabilities(mode=mode, nr=False)['quality'])
        self.assertEqual(contract.feedback_state(pending=True, unapplied=True, restart=True), 'pending')
        self.assertEqual(contract.feedback_state(unapplied=True, restart=True), 'restart')
        self.assertEqual(contract.feedback_state(reason='HDR unsupported', pending=True), 'unsupported')

    def test_diagnostics_share_fields_not_gpu_ownership(self):
        a = contract.diagnostic(mode='local', state='pending', generation=2)
        b = contract.diagnostic(mode='realtime', state='pending', generation=7)
        self.assertEqual(a.keys(), b.keys())
        self.assertEqual(a['invalidation_rules'], b['invalidation_rules'])
        self.assertNotIn('nr', a['invalidation_rules']['residual'])
        self.assertIn('nr', a['invalidation_rules']['basic'])
        for name in ('original', 'processed', 'compare'):
            self.assertEqual(contract.comparison_command(name), name)
        with self.assertRaises(ValueError):
            contract.comparison_command('arbitrary native command')

    def test_portable_partial_roundtrip_and_legacy_neutral(self):
        from tests.test_parameter_unification import config, catalog
        from dlss5tool.realtime import NR, validate_config
        meta = catalog()
        meta[NR]['parameters'] += [contract.PARAMETERS['nr_residual.' + k].descriptor(name=k) for k in contract.RESIDUAL]
        source = config()
        source['quality'].update(total=.3, regions=[[0, 0, .5, .5]], protection=True)
        values = from_realtime(source, meta, 5, appearance.GROUPS)
        for group in appearance.GROUPS:
            preset = read_portable(portable_preset(values, [group]))
            before = config()
            before['hdr'] = True
            _, result = to_realtime(preset['values'], before, meta, preset['groups'])
            self.assertTrue(result['hdr'])
            if group != 'regions':
                self.assertEqual(result['quality']['regions'], [])
        self.assertEqual(validate_config({})['quality'], appearance.DEFAULT_QUALITY)
        self.assertEqual(appearance.settings({}), appearance.DEFAULTS)


class HDRFineTests(unittest.TestCase):
    def test_each_control_exact_linear_reference_and_zero_residual(self):
        base = np.array([[[2., 2., 2.], [-.2, -.2, -.2], [0., 0., 0.]]], np.float32)
        output = base + np.array([[[1., 1., 1.], [-.1, -.1, -.1], [.1, .2, .3]]], np.float32)
        for field, value in (('residualMultiplier', 2), ('shadowStructureMultiplier', 0),
                             ('reflectionGlowMultiplier', 0), ('residualSaturation', 0), ('residualLightness', 0)):
            r = appearance.residual({field: value})
            result = hdr_fine_controls(base, output, r)
            delta = (output-base)*r['residualMultiplier']
            weights = np.array([.2126, .7152, .0722], np.float32)
            for x in range(3):
                luminance = float(delta[0, x] @ weights)
                scale = r['shadowStructureMultiplier'] if luminance < 0 else r['reflectionGlowMultiplier'] if luminance > 0 else 1
                d = delta[0, x]*scale
                y = float(d @ weights)
                expected = base[0, x] + y*r['residualLightness'] + (d-y)*r['residualSaturation']
                np.testing.assert_allclose(result[0, x], expected, atol=1e-6)
            np.testing.assert_array_equal(hdr_fine_controls(base, base, r), base)

    def test_pq_hlg_scrgb_alpha_protection_and_legacy_mix(self):
        for profile, decode, encode in (('hdr10_pq', _pq_eotf, _pq_oetf), ('hdr10_hlg', _hlg_eotf, _hlg_oetf),
                                        ('scrgb', lambda x: x, lambda x: x)):
            base = np.ones((3, 5, 4), np.float32)
            base[..., :3] = encode(np.array([.05, .1, .2], np.float32) if profile != 'scrgb' else np.array([-.2, 2, 3]))
            base[..., 3] = .7
            out = base.copy()
            out[..., :3] = encode(decode(base[..., :3]) + .1)
            out[..., 3] = .4
            base, out = base.astype(np.float16), out.astype(np.float16)
            look = {'nr_residual': {'residualMultiplier': 2}}
            result = compose_hdr_frame(base, out, profile=profile, settings=look)
            linear_base, linear_out = decode(base[..., :3].astype(np.float32)), decode(out[..., :3].astype(np.float32))
            expected = encode(linear_base + (linear_out-linear_base)*2).astype(np.float16)
            np.testing.assert_allclose(result[..., :3], expected, atol=.001)
            np.testing.assert_array_equal(result[..., 3], base[..., 3])
            protected = dict(look, nr_quality={'protection': True, 'feather': 0, 'regions': [[0, 0, 1, 1]]})
            np.testing.assert_allclose(compose(base, out, protected, profile=profile), base, atol=.001)
            if profile == 'scrgb':
                mixed = compose_hdr_frame(base, out, profile=profile, mix=.5, settings=look)
                np.testing.assert_allclose(mixed[..., :3], out[..., :3], atol=.002)
                self.assertLess(mixed[0, 0, 0], 0)
                self.assertGreater(mixed[0, 0, 2], 1)

    def test_neutral_sdr_and_hdr_leave_original_result_untouched(self):
        for dtype, profile in ((np.uint8, 'srgb'), (np.float16, 'hdr10_pq'), (np.float32, 'scrgb')):
            a = np.ones((3, 5, 4), dtype=dtype)
            b = a.copy()
            self.assertIs(compose(a, b, appearance.DEFAULTS, profile=profile), b)

    def test_generated_native_hdr_path_and_live_rules(self):
        from scripts.prepare_realtime_build import generate
        with tempfile.TemporaryDirectory() as tmp:
            generate(Path(tmp))
            source = (Path(tmp)/'DLSSNRFilter.cpp').read_text(encoding='utf-8')
        self.assertIn('ApplyHdrResidualControls(original, residual', source)
        self.assertIn('.padding0 = impl.experimentalHdrPath ? 1u : 0u', source)
        self.assertIn('experimentalHdrPath ? 100u : settings.inputResolutionPercent', source)
        rules = source[source.index('EffectParameterApplyMode DLSSNRFilter::GetParameterApplyMode'):]
        rules = rules[:rules.index('EffectParameterRestartReason DLSSNRFilter')]
        self.assertNotIn('parameterName == "residualMultiplier" || parameterName == "residualSaturation" ||', rules)


if __name__ == '__main__':
    unittest.main()
