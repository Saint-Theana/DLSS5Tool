"""Validate explicit realtime artifacts; never silently prune the feature."""
import hashlib
import json
from pathlib import Path


def validate_feature_runtimes(directory):
    """Required bundled realtime chain; never fall back to a developer DLL."""
    directory = Path(directory)
    for name in ('nvngx_dlssnr.dll', 'nvngx_dlss.dll', 'nvngx_dlssg.dll'):
        path = directory / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing realtime feature runtime: {path}')


def validate_runtime(directory, *, local_candidate=False):
    directory = Path(directory)
    manifest = json.loads((directory / 'build-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Invalid realtime manifest')
    if not manifest.get('packaging_license_review_complete') and not local_candidate:
        raise ValueError('Realtime GPL/NVIDIA distribution review pending: only an explicitly local candidate is permitted')
    files = manifest['files']
    if not {'dlss5_realtime_host.exe', 'licenses/DLSS5Tool-GPLv3.txt', 'REALTIME-NOTICE.txt', 'sources.lock.json'}.issubset(files):
        raise ValueError('Missing realtime host/notices')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() and p.name != 'build-manifest.json'}
    if actual != set(files):
        raise ValueError('Realtime inventory changed; rebuild its manifest')
    for name, record in files.items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Unsafe realtime path')
        if path.suffix.lower() == '.dll':
            raise ValueError('Unexpected runtime DLL inside realtime module')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != record['sha256'] or path.stat().st_size != record['size']:
            raise ValueError(f'Realtime artifact changed: {name}')
    return manifest
