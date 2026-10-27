#!/usr/bin/env python3
"""Registry of the platforms Module 3 may publish to.

The 资源上传司 must be able to name every platform it targets, not just the one
it happens to use today. The registry keeps one record per platform, grouped by
kind (video / social / paper), and `check` enforces the standing requirement of
**more than 100 platforms** plus the field rules.

What a record does NOT claim: that an upload adapter exists. `api` and `status`
say what is known; only `scripts/publishing_registry.py check` passing means the
bookkeeping is complete, not that every platform can be uploaded to.

Usage::

    python scripts/publishing_registry.py check
    python scripts/publishing_registry.py stats
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "publishing" / "registry.json"

KINDS = {"video", "social", "paper"}
REGIONS = {"global", "us", "cn", "eu", "jp", "kr", "ru", "in", "sea", "latam", "africa", "mideast"}
APIS = {"official", "partner", "none", "unknown"}
AUTHS = {"oauth", "api-key", "session", "manual", "none", "unknown"}
STATUSES = {"registered", "planned", "blocked"}
MIN_PLATFORMS = 100
MIN_PER_KIND = 20


def load(path: Path = REGISTRY) -> dict:
    if not path.is_file():
        raise ValueError(f"publishing registry not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def validate(data: dict, min_platforms: int = MIN_PLATFORMS) -> list[str]:
    problems: list[str] = []
    platforms = data.get("platforms")
    if not isinstance(platforms, list):
        return ["platforms must be a list"]

    seen_ids: set[str] = set()
    seen_urls: set[tuple[str, str]] = set()
    for index, row in enumerate(platforms):
        where = f"platforms[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{where}: must be an object")
            continue
        pid = str(row.get("id") or "")
        if not pid:
            problems.append(f"{where}: id is required")
        elif pid in seen_ids:
            problems.append(f"{where}: duplicate id {pid}")
        seen_ids.add(pid)

        if row.get("kind") not in KINDS:
            problems.append(f"{pid or where}: kind must be one of {sorted(KINDS)}")
        if row.get("region") not in REGIONS:
            problems.append(f"{pid or where}: region must be one of {sorted(REGIONS)}")
        if row.get("api") not in APIS:
            problems.append(f"{pid or where}: api must be one of {sorted(APIS)}")
        if row.get("auth") not in AUTHS:
            problems.append(f"{pid or where}: auth must be one of {sorted(AUTHS)}")
        if row.get("status") not in STATUSES:
            problems.append(f"{pid or where}: status must be one of {sorted(STATUSES)}")
        if not str(row.get("name") or "").strip():
            problems.append(f"{pid or where}: name is required")

        url = str(row.get("url") or "")
        if not url.startswith("https://"):
            problems.append(f"{pid or where}: url must be https")
        key = (str(row.get("kind")), url.rstrip("/"))
        if key in seen_urls:
            problems.append(f"{pid or where}: duplicate {key[0]} url {url}")
        seen_urls.add(key)

    if len(platforms) < min_platforms:
        problems.append(f"need at least {min_platforms} platforms, found {len(platforms)}")

    counts = Counter(row.get("kind") for row in platforms if isinstance(row, dict))
    for kind in sorted(KINDS):
        if counts[kind] < MIN_PER_KIND:
            problems.append(f"kind {kind} has {counts[kind]} platforms, need at least {MIN_PER_KIND}")

    return problems


def stats(data: dict) -> dict:
    platforms = [row for row in data.get("platforms") or [] if isinstance(row, dict)]
    by_kind = Counter(row.get("kind") for row in platforms)
    by_region = Counter(row.get("region") for row in platforms)
    by_status = Counter(row.get("status") for row in platforms)
    by_api = Counter(row.get("api") for row in platforms)
    return {
        "total": len(platforms),
        "by_kind": dict(sorted(by_kind.items())),
        "by_region": dict(sorted(by_region.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_api": dict(sorted(by_api.items())),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the Module 3 publishing platform registry.")
    parser.add_argument("command", choices=("check", "stats", "json"))
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load(args.registry)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.command == "check":
        problems = validate(data)
        if problems:
            for problem in problems:
                print(f"FAIL {problem}", file=sys.stderr)
            return 1
        report = stats(data)
        print(f"ok: {report['total']} platforms {report['by_kind']}")
        return 0

    report = stats(data)
    if args.command == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"total: {report['total']}")
        for key, value in report.items():
            if key != "total":
                print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
