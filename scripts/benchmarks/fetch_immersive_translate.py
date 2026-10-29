#!/usr/bin/env python3
"""Fetch, verify and unpack the Immersive Translate CRX baseline.

The repository never stores the binary: the third-party CRX is reproduced from
the pinned Chrome Web Store URL and checked against the SHA-256 recorded in
``benchmarks/immersive-translate/baseline.json``. That keeps the subtitle
quality floor auditable without adding a 13 MB binary to git.

Usage::

    python scripts/benchmarks/fetch_immersive_translate.py
    python scripts/benchmarks/fetch_immersive_translate.py --verify
    python scripts/benchmarks/fetch_immersive_translate.py --refresh-hashes

Exit codes: ``0`` verified, ``1`` download/verification failure, ``2`` usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "benchmarks" / "immersive-translate" / "baseline.json"
CHECKED_FILES = (
    "manifest.json",
    "content_main.js",
    "video-subtitle/inject.js",
    "default_config.json",
    "styles/inject.css",
)
CRX_MAGIC = b"Cr24"
DOWNLOAD_TIMEOUT = 180


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_baseline() -> dict:
    with BASELINE.open(encoding="utf-8") as handle:
        return json.load(handle)


def default_out_dir(baseline: dict) -> Path:
    version = baseline["artifact"].get("version") or baseline["version"]
    return Path(tempfile.gettempdir()) / "gitsynonyms-immersive-translate" / version


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {url}")
        payload = response.read()
    if not payload.startswith(CRX_MAGIC):
        raise RuntimeError(
            "response is not a CRX (missing Cr24 magic); the store may have "
            "returned an interstitial page"
        )
    destination.write_bytes(payload)


def unpack_crx(crx_path: Path, destination: Path) -> int:
    """Strip the CRX header and extract the inner ZIP. Returns the CRX version."""
    raw = crx_path.read_bytes()
    if raw[:4] != CRX_MAGIC:
        raise RuntimeError("not a CRX: missing Cr24 magic")
    version = struct.unpack("<I", raw[4:8])[0]
    if version == 3:
        header_len = struct.unpack("<I", raw[8:12])[0]
        zip_start = 12 + header_len
    elif version == 2:
        pubkey_len, signature_len = struct.unpack("<II", raw[8:16])
        zip_start = 16 + pubkey_len + signature_len
    else:
        raise RuntimeError(f"unsupported CRX version {version}")

    payload = raw[zip_start:]
    if payload[:2] != b"PK":
        raise RuntimeError("CRX payload does not start with a ZIP signature")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    archive = destination.parent / "payload.zip"
    archive.write_bytes(payload)
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
    finally:
        archive.unlink(missing_ok=True)
    return version


def verify_files(ext_dir: Path, expected: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for relative, digest in expected.items():
        target = ext_dir / relative
        if not target.exists():
            problems.append(f"missing {relative}")
            continue
        actual = sha256_file(target)
        if actual != digest:
            problems.append(f"hash mismatch {relative}: {actual} != {digest}")
    return problems


def collect_hashes(ext_dir: Path) -> dict[str, str]:
    return {relative: sha256_file(ext_dir / relative) for relative in CHECKED_FILES}


def refresh_hashes(baseline: dict, crx_path: Path, ext_dir: Path) -> dict:
    raw = crx_path.read_bytes()
    baseline["artifact"]["crx_sha256"] = sha256_bytes(raw)
    baseline["artifact"]["crx_bytes"] = len(raw)
    baseline["artifact"]["unpacked_files"] = sum(
        1 for path in ext_dir.rglob("*") if path.is_file()
    )
    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    baseline["version"] = manifest["version"]
    baseline["artifact"]["version"] = manifest["version"]
    baseline["artifact"]["manifest_version"] = manifest["manifest_version"]
    baseline["artifact"]["file_sha256"] = collect_hashes(ext_dir)
    return baseline


def write_baseline(baseline: dict) -> None:
    BASELINE.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        help="working directory (default: the system temp directory)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify an existing local copy instead of downloading",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even when a local CRX is present",
    )
    parser.add_argument(
        "--refresh-hashes",
        action="store_true",
        help="re-pin baseline.json to the downloaded artifact (version bump only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    baseline = load_baseline()
    artifact = baseline["artifact"]
    out_dir = (args.out or default_out_dir(baseline)).expanduser().resolve()
    crx_path = out_dir / "immersive-translate.crx"
    ext_dir = out_dir / "ext"

    if args.verify and not crx_path.exists():
        print(f"error: no local CRX at {crx_path}", file=sys.stderr)
        return 2

    if not args.verify and (args.force or not crx_path.exists()):
        print(f"downloading {artifact['extension_id']} -> {crx_path}")
        try:
            download(artifact["crx_url"], crx_path)
        except Exception as error:  # noqa: BLE001 - report, do not traceback
            print(f"error: download failed: {error}", file=sys.stderr)
            return 1

    raw = crx_path.read_bytes()
    problems: list[str] = []
    if artifact.get("crx_bytes") and len(raw) != artifact["crx_bytes"]:
        problems.append(f"size {len(raw)} != pinned {artifact['crx_bytes']}")
    actual_digest = sha256_bytes(raw)
    if actual_digest != artifact.get("crx_sha256"):
        problems.append(f"crx sha256 {actual_digest} != pinned {artifact['crx_sha256']}")
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(
            "hint: if the store published a new build, review the diff and run "
            "--refresh-hashes",
            file=sys.stderr,
        )
        return 1

    try:
        crx_version = unpack_crx(crx_path, ext_dir)
    except Exception as error:  # noqa: BLE001
        print(f"error: unpack failed: {error}", file=sys.stderr)
        return 1

    if args.refresh_hashes:
        baseline = refresh_hashes(baseline, crx_path, ext_dir)
        write_baseline(baseline)
        print(f"baseline re-pinned to version {baseline['version']}")

    file_problems = verify_files(ext_dir, baseline["artifact"]["file_sha256"])
    if file_problems:
        for problem in file_problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    print(f"crx version     {crx_version}")
    print(f"extension       {manifest['name']} {manifest['version']}")
    print(f"crx sha256      {actual_digest}")
    print(f"unpacked files  {sum(1 for p in ext_dir.rglob('*') if p.is_file())}")
    print(f"directory       {ext_dir}")
    print("status          verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
