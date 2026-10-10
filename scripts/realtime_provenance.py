"""Stage notices and exact hashes for the local realtime build, never GPU DLLs."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / 'third_party/realtime'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage(output=None):
    output = Path(output) if output is not None else ROOT / 'runtime/realtime'
    # Do not modify pinned upstream sources. Stage the additive local metadata
    # alongside the host built with prepare_realtime_build's explicit opt-in.
    effect = DEPS / 'magpie/src/Effects/DLSSNR/DLSSNR_AI_Filter.hlsl'
    text = effect.read_text(encoding='utf-8')
    marker = '//!PARAMETER\n//!GROUP Detail Control\n'
    descriptor = ('//!PARAMETER\n//!GROUP Detail Control\n'
                  '//!LABEL Enable Residual Controls (Full Resolution)\n'
                  '//!DEFAULT 0\n//!MIN 0\n//!MAX 1\n//!STEP 1\nint enableResidualControls;\n\n')
    if marker not in text:
        raise ValueError('NR effect metadata changed')
    target = output / 'effects/DLSSNR/DLSSNR_AI_Filter.hlsl'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(marker, descriptor+marker, 1), encoding='utf-8')
    lock = json.loads((ROOT / 'native/realtime/sources.lock.json').read_text(encoding='utf-8'))
    for name, info in lock['sources'].items():
        receipt = json.loads((DEPS / name / '.dlss5tool-source.json').read_text(encoding='utf-8'))
        if any(receipt[key] != info[key] for key in ('repository', 'commit', 'archive_sha256')):
            raise ValueError(f'Source receipt mismatch: {name}')
    notices = output / 'licenses'
    notices.mkdir(parents=True, exist_ok=True)
    files = {
        'DLSS5Tool-GPLv3.txt': ROOT / 'LICENSE',
        'DLSS5Tool-original-MIT.txt': ROOT / 'licenses/DLSS5Tool-original-MIT.txt',
        'NVIDIA-DLSS-SDK.txt': ROOT / 'third_party/NVIDIA-DLSS/LICENSE.txt',
    }
    for name, filename in {'magpie':'LICENSE', 'veyra':'LICENSE', 'fmt':'LICENSE',
                           'spdlog':'LICENSE', 'phmap':'LICENSE', 'imgui':'LICENSE.txt',
                           'muparser':'LICENSE', 'rapidhash':'LICENSE', 'wil':'LICENSE',
                           'nvapi':'License.txt', 'json':'LICENSE.MIT'}.items():
        files[f'{name}-LICENSE.txt'] = DEPS / name / filename
    files['WIL-ThirdPartyNotices.txt'] = DEPS / 'wil/ThirdPartyNotices.txt'
    for name, source in files.items():
        shutil.copyfile(source, notices / name)
    # Retain the actual file-level notices, not the mirror's unrelated root license.
    for name in ('nvOpticalFlowCommon.h', 'nvOpticalFlowD3D11.h'):
        text = (DEPS / 'nvof_headers' / name).read_text(encoding='utf-8')
        (notices / (name + '-LICENSE.txt')).write_text(text[:text.index('*/')+2] + '\n', encoding='utf-8')
    text = (DEPS / 'yas/include/yas/detail/config/config.hpp').read_text(encoding='utf-8')
    (notices / 'yas-Boost-1.0.txt').write_text(text[:text.index('#ifndef')], encoding='utf-8')
    shutil.copyfile(ROOT / 'native/realtime/NOTICE.md', output / 'REALTIME-NOTICE.txt')
    shutil.copyfile(ROOT / 'native/realtime/sources.lock.json', output / 'sources.lock.json')
    # Runtime source inventory includes inherited file-level notices even when
    # upstream has no separate notice file for a small dependency.
    input_files = set((ROOT / 'native/realtime').rglob('*'))
    input_files.add(ROOT / 'assets/app.ico')
    input_files.update((DEPS / 'magpie/src/Magpie.Core').rglob('*'))
    input_files.update((DEPS / 'magpie/src/Shared').rglob('*'))
    input_files.update((DEPS / 'magpie/src/Effects').rglob('*'))
    for pattern in ('include/*', 'lib/Windows_x86_64/x64/nvsdk_ngx_s.lib', 'LICENSE.txt'):
        input_files.update((ROOT / 'third_party/NVIDIA-DLSS').glob(pattern))
    input_files.update(ROOT / 'scripts' / name for name in ('prepare_realtime_build.py', 'build_realtime.ps1', 'fetch_realtime_sources.py', 'realtime_provenance.py'))
    input_files.update(DEPS / 'veyra/shaders' / name for name in ('NrResidualComposite.hlsl', 'NrProtection.hlsli'))
    inputs = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(input_files) if p.is_file()}
    outputs = {p.relative_to(output).as_posix(): {'sha256': digest(p), 'size': p.stat().st_size}
               for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'build-manifest.json'}
    manifest = {'version': 1, 'packaging_license_review_complete': False,
                'distribution_status': 'local-validation-only', 'sources': lock['sources'],
                'features': ['WGC', 'DD', 'GDI', 'DWM', 'DLSSNR', 'DLSSSR', 'DLSSFG', 'NVOF', 'VeyraResidual'],
                'source_sha256': inputs, 'files': outputs}
    (output / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Realtime provenance: {len(inputs)} source inputs, {len(outputs)} outputs; public distribution NOT cleared')


if __name__ == '__main__': stage()
