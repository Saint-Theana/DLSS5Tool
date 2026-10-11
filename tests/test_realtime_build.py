import json
from pathlib import Path
import unittest
import zipfile
from scripts.fetch_realtime_sources import SOURCES, validate_archive
from scripts.realtime_packaging import validate_runtime, validate_feature_runtimes
from scripts.prepare_realtime_build import generate
import tempfile

ROOT = Path(__file__).resolve().parents[1]


class RealtimeBuildTests(unittest.TestCase):
    def test_bundled_chain_requires_sr_as_well_as_nr_and_fg(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            for name in ('nvngx_dlssnr.dll', 'nvngx_dlssg.dll'):
                (runtime / name).write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'nvngx_dlss.dll'):
                validate_feature_runtimes(runtime)
            (runtime / 'nvngx_dlss.dll').touch()
            with self.assertRaisesRegex(ValueError, 'nvngx_dlss.dll'):
                validate_feature_runtimes(runtime)
            (runtime / 'nvngx_dlss.dll').write_bytes(b'fixture')
            validate_feature_runtimes(runtime)

    def test_standalone_parameter_localization_never_uses_packaged_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            generate(output)
            localization = (output / 'standalone_parameter_localization.h').read_text(encoding='utf-8')
            self.assertNotIn('ResourceContext::', localization)
            self.assertNotIn('ResourceLoader::', localization)
            self.assertIn('StandaloneString(key, false)', localization)
            rules = (output / 'standalone_parameter_rules.h').read_text(encoding='utf-8')
            self.assertIn('parameter != "inputResolutionPercent" && getValue("enableResidualControls", 0.0f)', rules)
            overlay = (output / 'OverlayDrawer.cpp').read_text(encoding='utf-8')
            self.assertIn('#include "standalone_parameter_localization.h"', overlay)
            self.assertIn('#include "standalone_parameter_rules.h"', overlay)
            self.assertNotIn('#include "EffectParameterLocalization.h"', overlay)
            self.assertIn('Realtime::StopHint()', overlay)
            self.assertIn('Realtime::IntroAlpha()', overlay)
            self.assertIn('int(255 * stopAlpha)', overlay)
            self.assertIn('_isToolbarItemActive || IsEditingParameters()', overlay)
            self.assertNotIn('Standalone stop guidance remains visible', overlay)
            renderer = (output / 'Renderer.cpp').read_text(encoding='utf-8')
            self.assertIn('if (submitted && contentFrame)', renderer)
            self.assertIn('Realtime::GuidancePresented', renderer)
            self.assertIn('!options.Is3DGameMode() || options.isParameterFocusSwitchingEnabled', renderer)
            self.assertIn('action == OverlayAction::EffectParameters || _overlayDrawer.IsEditingParameters()', renderer)
            self.assertIn('Options().Is3DGameMode()) return Realtime::IntroAlpha()', overlay)
            resources = (output / 'standalone_resources.h').read_text(encoding='utf-8')
            self.assertIn('L"Home_FrameSync_Mode/Header", L"同步模式"', resources)
            parameter_input = (output / 'ParameterInputHost.cpp').read_text(encoding='utf-8')
            self.assertIn('ParameterPanelState::Preview && !ScalingWindow::Get().Options().Is3DGameMode()', parameter_input)

    def test_all_pins_match_tracked_lock(self):
        lock = json.loads((ROOT / 'native/realtime/sources.lock.json').read_text(encoding='utf-8'))['sources']
        self.assertEqual(set(lock), set(SOURCES))
        for name, (repo, sha) in SOURCES.items():
            self.assertEqual((repo, sha), (lock[name]['repository'], lock[name]['commit']))
            self.assertEqual(len(sha), 40)

    def test_archive_rejects_traversal_duplicates_and_multiple_roots(self):
        for names in (['root/../evil'], ['/absolute'], ['root/A', 'root/a'], ['root/a', 'other/b'], ['root/C:evil'], ['root/a.']):
            with self.subTest(names=names), self.assertRaises(RuntimeError):
                validate_archive([zipfile.ZipInfo(n) for n in names])
        link = zipfile.ZipInfo('root/link'); link.external_attr = 0o120777 << 16
        with self.assertRaises(RuntimeError): validate_archive([link])
        validate_archive([zipfile.ZipInfo('root/'), zipfile.ZipInfo('root/good.cpp')])

    def test_public_runtime_guard_is_closed(self):
        path = ROOT / 'runtime/realtime'
        if not (path / 'build-manifest.json').is_file(): self.skipTest('native build not present')
        with self.assertRaisesRegex(ValueError, 'distribution review'):
            validate_runtime(path)
        validate_runtime(path, local_candidate=True)


if __name__ == '__main__': unittest.main()
