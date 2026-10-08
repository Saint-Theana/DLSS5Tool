"""Fetch pinned source archives only; never download proprietary GPU runtimes.

Run from the repository root. Existing source trees are not overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import urllib.request
import zipfile
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "third_party" / "realtime"
WORK = ROOT / "tmp" / "realtime-integration-20261003"
SOURCES = {
    "magpie": ("SAOG0721/Magpie", "2c017d4be8311fac8584e2ff6187b1f03383bde1"),
    "veyra": ("Likely7/Veyra-NRVideo", "6851c2775c978b999e263a9c427ff43461688aa0"),
    "fmt": ("fmtlib/fmt", "407c905e45ad75fc29bf0f9bb7c5c2fd3475976f"),
    "spdlog": ("gabime/spdlog", "79524ddd08a4ec981b7fea76afd08ee05f83755d"),
    "phmap": ("greg7mdp/parallel-hashmap", "2ec799017610ef831f4dc29c21fb3cce7e4a19b9"),
    "yas": ("niXman/yas", "e70a6e31d32571238a73450304405670f40a4860"),
    "imgui": ("ocornut/imgui", "dbb5eeaadffb6a3ba6a60de1290312e5802dba5a"),
    "muparser": ("beltoforion/muparser", "fbafd7f8774af2b53f4d2de07c57353fcfc09216"),
    "rapidhash": ("Nicoshev/rapidhash", "588978411df8683777429f729be5213eb1bfd5f3"),
    "wil": ("microsoft/wil", "cbf677fb0a942557d08fd129f4c106a76247b2ec"),
    "nvapi": ("NVIDIA/nvapi", "87dca625e83fd89a983e19b904e5f3a580da90d2"),
    "json": ("nlohmann/json", "55f93686c01528224f448c19128836e7df245f72"),
    # Mirror of NVIDIA's individually MIT-licensed interface headers, not an SDK/runtime license.
    "nvof_headers": ("SlimRG/NvidiaOF5", "99e8d8eb8f269591e5e4bd5a7f3c248bbbc3a3b9"),
}


def validate_archive(entries):
    if not entries or sum(entry.file_size for entry in entries) > 512 * 1024**2:
        raise RuntimeError('Invalid archive size')
    roots = set()
    names = set()
    for entry in entries:
        parts = PurePosixPath(entry.filename).parts
        if (not parts or PurePosixPath(entry.filename).is_absolute()
                or any(p in ('..', '') or ':' in p or '\\' in p or p.rstrip(' .') != p for p in parts)
                or (entry.external_attr >> 16) & 0o170000 == 0o120000):
            raise RuntimeError(f'Unsafe archive entry: {entry.filename}')
        roots.add(parts[0])
        name = '/'.join(parts).casefold()
        if name in names:
            raise RuntimeError('Duplicate archive entry')
        names.add(name)
    if len(roots) != 1:
        raise RuntimeError('Archive must contain exactly one source root')


def request(url):
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "DLSS5Tool-source-build"}), timeout=60)


def fetch(name, repo, revision):
    target = DEST / name
    receipt = target / ".dlss5tool-source.json"
    if target.exists():
        if not receipt.is_file():
            raise RuntimeError(f"Refusing to overwrite unowned source directory: {target}")
        info = json.loads(receipt.read_text(encoding="utf-8"))
        if info["repository"] != repo or info["commit"] != revision:
            raise RuntimeError(f"Existing source revision mismatch: {target}")
        print(f"Reuse {name}: {info['commit']}", flush=True)
        return
    if shutil.disk_usage(ROOT).free < 16 * 1024**3:
        raise RuntimeError("Source fetch requires 15 GiB reserve plus 1 GiB headroom")
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('Sources must be locked to a full commit SHA')
    commit = revision
    archive = WORK / f"{name}-{commit}.zip"
    WORK.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print(f"Download source {repo}@{commit}", flush=True)
        pending = archive.with_suffix('.zip.pending')
        with request(f"https://codeload.github.com/{repo}/zip/{commit}") as response:
            with pending.open("wb") as output:
                shutil.copyfileobj(response, output)
        with zipfile.ZipFile(pending) as check:
            if check.testzip() is not None:
                raise RuntimeError('Corrupt source archive')
        pending.replace(archive)
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    lock = json.loads((ROOT / 'native/realtime/sources.lock.json').read_text(encoding='utf-8'))['sources'][name]
    if lock['commit'] != commit or lock['repository'] != repo or lock['archive_sha256'] != digest:
        raise RuntimeError(f'Source archive identity mismatch: {name}')
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        validate_archive(entries)
        # Partial extraction cannot poison the persistent source path. Retain a
        # failed small stage for explicit task cleanup; never overwrite a tree.
        stage = Path(tempfile.mkdtemp(prefix=f'extract-{name}-', dir=WORK))
        for entry in entries:
            relative = PurePosixPath(entry.filename).parts[1:]
            if not relative:
                continue
            path = stage.joinpath(*relative)
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, path.open("xb") as output:
                    shutil.copyfileobj(source, output)
    info = {"repository": repo, "requested_revision": revision,
            "commit": commit, "archive_sha256": digest}
    (stage / receipt.name).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage.rename(target)
    print(json.dumps(info), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+", choices=tuple(SOURCES))
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda name: fetch(name, *SOURCES[name]), args.names))


if __name__ == "__main__":
    main()
