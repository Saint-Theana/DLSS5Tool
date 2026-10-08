"""Verify all icon frames embedded in Windows executables against an ICO."""
import argparse
import json
from pathlib import Path
import struct

import pefile


def verify(executable, icon):
    source = Path(icon).read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', source)
    if reserved or kind != 1:
        raise ValueError('Expected an ICO file')
    frames = {}
    for index in range(count):
        width, height, _, _, _, _, size, offset = struct.unpack_from('<BBBBHHII', source, 6 + index * 16)
        frames[width or 256, height or 256] = source[offset:offset + size]
    with pefile.PE(str(executable)) as image:
        resources = {entry.id: entry for entry in image.DIRECTORY_ENTRY_RESOURCE.entries}
        raw_icons = {}
        for entry in resources[3].directory.entries:
            for language in entry.directory.entries:
                record = language.data.struct
                raw_icons[entry.id, language.id] = image.get_data(record.OffsetToData, record.Size)
        checked = 0
        for group in resources[14].directory.entries:
            for language in group.directory.entries:
                record = language.data.struct
                data = image.get_data(record.OffsetToData, record.Size)
                seen = set()
                for index in range(struct.unpack_from('<H', data, 4)[0]):
                    width, height, _, _, _, _, size, ident = struct.unpack_from('<BBBBHHIH', data, 6 + index * 14)
                    key = width or 256, height or 256
                    frame = raw_icons[ident, language.id]
                    if key not in frames or frame != frames[key] or len(frame) != size:
                        raise ValueError(f'{executable}: embedded icon differs at {key}')
                    seen.add(key)
                if seen != set(frames):
                    raise ValueError(f'{executable}: incomplete embedded icon sizes')
                checked += 1
    if not checked:
        raise ValueError(f'{executable}: no application icon')
    return dict(executable=str(executable), groups=checked, frames=len(frames), matches=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executables', nargs='+', type=Path)
    parser.add_argument('--icon', type=Path, default=Path(__file__).resolve().parents[1] / 'assets/app.ico')
    args = parser.parse_args()
    print(json.dumps([verify(path, args.icon) for path in args.executables], ensure_ascii=False))
