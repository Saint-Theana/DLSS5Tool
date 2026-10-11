"""Read-only verification of a documentation-only edition refresh.

Compare manifests and actual ZIP bytes to the accepted package, verify upload
volumes and all incremental payloads without extracting another environment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.package_editions import inventory, sha
from scripts.release_updates import plan_updates, verify_upload_updates


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(before, after):
    old_report = read(before / 'package-report.json')
    report = read(after / 'package-report.json')
    version = report['version']
    require(version == old_report['version'], 'Version changed')
    require(not report['published'], 'Refresh must remain unpublished')
    manifests, changes = {}, {}
    for kind in ('lite', 'addon', 'full'):
        old = read(before / f'verification/{kind}-files.json')
        new = read(after / f'verification/{kind}-files.json')
        changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
        require(changed == ([] if kind == 'addon' else ['CHANGELOG.md']),
                f'Unexpected content changes: {kind}: {changed}')
        require(inventory(after / f'DLSS5Tool-{version}-win64-{kind}') == new,
                f'Staged files differ: {kind}')
        record = report['editions'][kind]
        archive = after / record['name']
        require(archive.stat().st_size == record['size'] and sha(archive) == record['sha256'],
                f'ZIP digest differs: {kind}')
        with zipfile.ZipFile(archive) as z:
            require(len(z.infolist()) == len(new) and set(z.namelist()) == set(new),
                    f'ZIP members differ: {kind}')
            for item in z.infolist():
                with z.open(item) as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                require(new[item.filename] == {'size': item.file_size, 'sha256': digest},
                        f'ZIP content differs: {kind}/{item.filename}')
        combined = hashlib.sha256()
        for part in record['volumes']:
            path = after / 'github-assets' / part['name']
            require(path.stat().st_size == part['size'] and sha(path) == part['sha256'],
                    f'Volume mismatch: {path.name}')
            with path.open('rb') as source:
                for block in iter(lambda: source.read(8 * 1024**2), b''):
                    combined.update(block)
        if record['volumes']:
            require(combined.hexdigest() == record['sha256'], 'Volume assembly mismatch')
        manifests[kind], changes[kind] = new, changed
        print(f'Verified {kind}: ZIP bytes, staged files, volumes; changes={changed}', flush=True)
    require(manifests['full'] == {**manifests['lite'], **manifests['addon']}, 'Overlay differs')
    canonical = after / 'github-assets' / report['github_portable_asset']
    require(sha(canonical) == report['editions']['lite']['sha256'], 'Canonical ZIP differs')
    notes = ROOT / 'docs/release' / f'RELEASE_NOTES_{version}.md'
    for path in (after / notes.name, after / 'github-assets' / notes.name):
        require(path.read_bytes() == notes.read_bytes(), 'Release notes differ')
    expected_log = {'size': (ROOT / 'CHANGELOG.md').stat().st_size, 'sha256': sha(ROOT / 'CHANGELOG.md')}
    require(manifests['lite']['CHANGELOG.md'] == expected_log, 'Source changelog differs')
    plan = plan_updates(version)
    baselines = {b['version']: b for b in plan['baselines']}
    updates = []
    for record in report['incremental_updates']['assets']:
        kind, old_version = record['edition'], record['from']
        with zipfile.ZipFile(after / 'github-assets' / record['name']) as z:
            manifest = json.loads(z.read('manifest.json'))
            require(manifest['before'] == baselines[old_version]['inventories'][kind], 'Before mismatch')
            require(manifest['after'] == manifests[kind], 'After mismatch')
            changed = {name for name, value in manifest['after'].items()
                       if manifest['before'].get(name) != value}
            require(set(z.namelist()) == {'manifest.json'} | {'payload/' + n for n in changed},
                    'Unexpected payload entries')
            for name, value in manifest['after'].items():
                if name in changed:
                    with z.open('payload/' + name) as source:
                        actual = {'size': z.getinfo('payload/' + name).file_size,
                                  'sha256': hashlib.file_digest(source, 'sha256').hexdigest()}
                else:
                    actual = baselines[old_version]['inventories'][kind][name]
                require(actual == value, f'Incremental reconstruction differs: {name}')
        updates.append({'from': old_version, 'edition': kind, 'files': len(manifest['after'])})
        print(f'Verified incremental overlay: {old_version} -> {version} {kind}', flush=True)
    verify_upload_updates(after / 'github-assets')
    return {'version': version, 'changes': changes, 'updates': updates,
            'changelog': expected_log, 'archives_and_volumes_verified': True,
            'release_notes_identical': True, 'upload_check_passed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.before.resolve(), args.after.resolve())
    with args.report.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print('Documentation-only refresh verified.', flush=True)
