"""Project-scoped Windows release paths; never write to the shared dist root."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path, PureWindowsPath
import re

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'packaging/release-output.json'


def release_paths(version, *, policy_path=POLICY, day=None):
    data = json.loads(Path(policy_path).read_text(encoding='utf-8'))
    if data.get('schema') != 1:
        raise ValueError('Unsupported release output policy')
    root = PureWindowsPath(data['release_root'])
    project = data['project_folder']
    if not root.is_absolute() or root == PureWindowsPath(root.anchor):
        raise ValueError('Release root must be a named absolute Windows directory')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', project):
        raise ValueError('One project folder is required under the shared release root')
    if not re.fullmatch(r'v\d+\.\d+\.\d+', version):
        raise ValueError('Release version must be vX.Y.Z')
    day = day or datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    if not re.fullmatch(r'\d{8}', day):
        raise ValueError('Task date must be YYYYMMDD')
    project_root = root / project
    release = project_root / version
    return {key: value.as_posix() for key, value in {
        'project': project_root, 'release': release,
        'base': release / 'base', 'editions': release / 'editions',
        'work': project_root / 'tmp' / f'release-{version}-{day}',
    }.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    print(json.dumps(release_paths(args.version)))
