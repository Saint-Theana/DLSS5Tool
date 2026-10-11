"""Read-only installed dependency inventory; hash candidates, never delete them."""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(roots, *, min_bytes=1024**2, pe_imports=False):
    """Logical bytes, not allocated disk usage; separate editions are not savings.

    Never follow directory junctions/symlinks. Missing roots fail explicitly so a
    mistyped package cannot appear as a zero-byte successful optimization.
    """
    roots = [Path(root).absolute() for root in roots]
    if len(set(roots)) != len(roots) or any(a in b.parents for a in roots for b in roots if a != b):
        raise ValueError('Audit roots must be distinct and non-overlapping')
    sizes, buckets, skipped, executables = {}, defaultdict(list), [], []
    for root in roots:
        if not root.is_dir() or root.is_symlink() or root.is_junction():
            raise ValueError(f'Expected a real existing directory: {root}')
        total = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in list(dirs):
                path = Path(directory)/name
                if path.is_symlink() or path.is_junction():
                    dirs.remove(name)
                    skipped.append(str(path))
            for name in files:
                path = Path(directory)/name
                if path.is_symlink():
                    skipped.append(str(path))
                    continue
                size = path.stat().st_size
                total += size
                if size >= min_bytes:
                    buckets[size].append(path)
                if pe_imports and path.suffix.lower() in ('.exe', '.dll', '.pyd'):
                    executables.append(path)
        sizes[str(root)] = total
    duplicates = []
    for size, files in buckets.items():
        if len(files) < 2:
            continue
        hashes = defaultdict(list)
        for path in files:
            with path.open('rb') as stream:
                hashes[hashlib.file_digest(stream, 'sha256').hexdigest()].append(str(path))
        duplicates += [dict(bytes=size, sha256=digest, paths=sorted(paths),
                            copies=len(paths), action='audit-only; dependency use must be checked')
                       for digest, paths in hashes.items() if len(paths) > 1]
    imports = []
    if pe_imports:
        import pefile
        for path in executables:
            record = {'path': str(path)}
            try:
                with pefile.PE(str(path), fast_load=True) as pe:
                    pe.parse_data_directories(directories=[1, 13])
                    record['imports'] = sorted({entry.dll.decode('ascii', errors='replace')
                        for table in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                        for entry in getattr(pe, table, [])})
            except pefile.PEFormatError as error:
                record['error'] = str(error)
            imports.append(record)
    return {'schema': 2, 'directory_bytes': sizes,
            'identical_file_candidates': sorted(duplicates, key=lambda item: (-item['bytes'], item['sha256'])),
            'skipped_links': skipped, 'pe_imports': imports, 'min_duplicate_bytes': min_bytes,
            'measurement': 'logical installed bytes; separate editions are alternatives, not additive savings',
            'safe_removal_bytes': 0,
            'note': 'Separate dependency search roots may require identical files. No removal authorized.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, action='append', help='Repeat for actual lite/full/addon or runtime roots')
    parser.add_argument('--min-bytes', type=int, default=1024**2)
    parser.add_argument('--pe-imports', action='store_true', help='Inspect static and delay PE imports; dynamic loaders still need testing')
    args = parser.parse_args()
    if args.min_bytes < 0:
        parser.error('--min-bytes must be non-negative')
    result = inventory(args.root or [ROOT/'runtime/realtime', ROOT/'runtime/gpu-export', ROOT/'mods/enhancement'],
                       min_bytes=args.min_bytes, pe_imports=args.pe_imports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
