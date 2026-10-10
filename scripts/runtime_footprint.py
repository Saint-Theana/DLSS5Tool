"""Read-only installed dependency inventory; hash candidates, never delete them."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(roots):
    sizes, buckets = {}, defaultdict(list)
    for root in roots:
        total = 0
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            size = path.stat().st_size
            total += size
            if size >= 1024**2 and path.suffix.lower() in ('.exe', '.dll', '.pyd', '.pth'):
                buckets[size].append(path)
        sizes[str(root)] = total
    duplicates = []
    for size, files in buckets.items():
        if len(files) < 2:
            continue
        hashes = defaultdict(list)
        for path in files:
            with path.open('rb') as stream:
                hashes[hashlib.file_digest(stream, 'sha256').hexdigest()].append(str(path))
        duplicates += [dict(bytes=size, sha256=digest, paths=paths, action='audit-only; dependency use must be checked')
                       for digest, paths in hashes.items() if len(paths) > 1]
    return {'directory_bytes': sizes, 'identical_file_candidates': duplicates,
            'note': 'Separate dependency search roots may require identical files. No removal authorized.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory([ROOT/'runtime/realtime', ROOT/'runtime/gpu-export', ROOT/'mods/enhancement'])
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
