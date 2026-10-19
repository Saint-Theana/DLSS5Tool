"""Shared release storage always namespaces project and version."""
import json
from pathlib import Path

import pytest

from scripts.release_paths import release_paths


def test_default_is_the_user_requested_project_folder():
    paths=release_paths('v3.0.2',day='20261019')
    assert paths['base']=='E:/dist/DLSS5Tool/v3.0.2/base'
    assert paths['editions']=='E:/dist/DLSS5Tool/v3.0.2/editions'
    assert paths['work']=='E:/dist/DLSS5Tool/tmp/release-v3.0.2-20261019'


@pytest.mark.parametrize('version',['3.0.2','v3.0.2/../other','v3.0','v3.0.2-beta'])
def test_version_cannot_escape_project(version):
    with pytest.raises(ValueError):release_paths(version,day='20261019')


@pytest.mark.parametrize('root,project',[('E:/','DLSS5Tool'),('relative','DLSS5Tool'),
    ('E:/dist','../OtherProject'),('E:/dist',''),('E:/dist','Other/Project')])
def test_policy_rejects_shared_root_or_project_escape(tmp_path,root,project):
    policy=tmp_path/'policy.json'
    policy.write_text(json.dumps(dict(schema=1,release_root=root,project_folder=project)),encoding='utf-8')
    with pytest.raises(ValueError):release_paths('v3.0.2',policy_path=policy,day='20261019')


def test_packaging_default_reads_policy_and_preserves_explicit_override():
    root=Path(__file__).resolve().parents[1]
    build=(root/'scripts/build_release.ps1').read_text(encoding='utf-8')
    editions=(root/'scripts/package_editions.py').read_text(encoding='utf-8')
    assert 'release_paths.py' in build and '$releasePaths.base' in build
    assert '$releasePaths.work' in build and 'if ($OutputDirectory)' in build
    assert 'managed_output' in editions and 'args.allow_external_output' in editions
