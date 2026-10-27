#!/usr/bin/env python3
"""Validate the organization chart against the Directive's rank ladder.

DIRECTIVE.md 2.1 fixes the ladder ``部 → 司 → 处 → 科 → 组``: modules 1, 2 and 3
are ministry-level, every 司 belongs to a 部, and no unit may skip a level.
The chart in ``organization/chart.json`` is the machine-readable copy of that
ladder; this script is the gate that keeps the docs, workflows and registries
from drifting into a flat "everything belongs to 总控" list.

Usage::

    python scripts/org_chart.py check
    python scripts/org_chart.py tree
    python scripts/org_chart.py stats --json
    python scripts/org_chart.py path --unit sec-asr
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "organization" / "chart.json"

SCHEMA = "org-chart/1"
LEVELS = ("部", "司", "处", "科", "组")
PARENT_LEVEL = {"司": "部", "处": "司", "科": "处", "组": "科"}
REQUIRED_DEPARTMENTS = {
    "dept-module1": "模块1",
    "dept-module2": "模块2",
    "dept-module3": "模块3",
}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load(path: Path = CHART) -> dict:
    if not path.is_file():
        raise ValueError(f"org chart not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def by_id(units: list[dict]) -> dict[str, dict]:
    return {str(unit.get("id")): unit for unit in units}


def validate(data: dict) -> list[str]:
    problems: list[str] = []
    if data.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}")
    units = data.get("units")
    if not isinstance(units, list) or not units:
        return problems + ["units must be a non-empty list"]

    index = by_id(units)
    if len(index) != len(units):
        problems.append("unit ids must be unique")

    for position, unit in enumerate(units):
        where = f"units[{position}]"
        if not isinstance(unit, dict):
            problems.append(f"{where}: must be an object")
            continue
        uid = str(unit.get("id") or "")
        if not ID_PATTERN.match(uid):
            problems.append(f"{where}: id must be a lowercase slug, got {uid!r}")
        name = str(unit.get("name") or "")
        level = unit.get("level")
        if level not in LEVELS:
            problems.append(f"{uid or where}: level must be one of {list(LEVELS)}")
            continue
        if not name.endswith(level):
            problems.append(f"{uid}: name {name!r} must end with {level}")
        parent = unit.get("parent")
        if level == "部":
            if parent is not None:
                problems.append(f"{uid}: 部 must sit directly under 总控 (parent null)")
        else:
            expected = PARENT_LEVEL[level]
            parent_unit = index.get(str(parent)) if parent is not None else None
            if parent_unit is None:
                problems.append(f"{uid}: {level} needs an existing parent")
            elif parent_unit.get("level") != expected:
                problems.append(
                    f"{uid}: {level} must belong to a {expected}, parent is "
                    f"{parent_unit.get('level')}"
                )
        if "reports_to" in unit and unit.get("reports_to") != "总控":
            problems.append(f"{uid}: reports_to may only be 总控")
        if unit.get("reports_to") and level != "司":
            problems.append(f"{uid}: only a 司 may report directly to 总控")

    for uid, unit in index.items():
        seen: set[str] = set()
        cursor = unit
        while cursor and cursor.get("parent") is not None:
            if cursor.get("id") in seen:
                problems.append(f"{uid}: parent chain contains a cycle")
                break
            seen.add(str(cursor.get("id")))
            cursor = index.get(str(cursor.get("parent")))
        else:
            if cursor is not None and cursor.get("level") != "部":
                problems.append(f"{uid}: parent chain must end at a 部")

    for department_id, label in REQUIRED_DEPARTMENTS.items():
        unit = index.get(department_id)
        if unit is None:
            problems.append(f"{label}: department {department_id} is missing")
        elif unit.get("level") != "部":
            problems.append(f"{label}: {department_id} must be ministry-level (部)")

    children: dict[str, list[dict]] = {}
    for unit in units:
        if isinstance(unit, dict) and unit.get("parent") is not None:
            children.setdefault(str(unit.get("parent")), []).append(unit)

    for uid, unit in index.items():
        level = unit.get("level")
        kids = children.get(uid, [])
        if level == "部" and not any(kid.get("level") == "司" for kid in kids):
            problems.append(f"{uid}: every 部 needs at least one 司")
        if level == "司" and not any(kid.get("level") == "处" for kid in kids):
            problems.append(f"{uid}: every 司 needs at least one 处")
        if level == "处" and not any(kid.get("level") == "科" for kid in kids):
            problems.append(f"{uid}: every 常设处 needs at least one 科")

    return problems


def counts(data: dict) -> Counter:
    return Counter(
        unit.get("level") for unit in data.get("units") or [] if isinstance(unit, dict)
    )


def department_of(data: dict, unit: dict) -> str:
    index = by_id(data.get("units") or [])
    cursor = unit
    while cursor is not None and cursor.get("level") != "部":
        cursor = index.get(str(cursor.get("parent")))
    return str((cursor or {}).get("id") or "?")


def stats(data: dict) -> dict:
    units = [unit for unit in data.get("units") or [] if isinstance(unit, dict)]
    per_department = Counter(department_of(data, unit) for unit in units)
    return {
        "total": len(units),
        "by_level": {level: counts(data)[level] for level in LEVELS},
        "by_department": dict(sorted(per_department.items())),
    }


def render_tree(data: dict) -> str:
    units = [unit for unit in data.get("units") or [] if isinstance(unit, dict)]
    children: dict[str | None, list[dict]] = {}
    for unit in units:
        children.setdefault(unit.get("parent"), []).append(unit)

    lines = ["总控"]

    def walk(parent: str | None, prefix: str) -> None:
        kids = children.get(parent, [])
        for position, unit in enumerate(kids):
            last = position == len(kids) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{unit.get('name')} [{unit.get('level')}]")
            walk(str(unit.get("id")), prefix + ("    " if last else "│   "))

    walk(None, "")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the 部→司→处→科→组 organization chart.")
    parser.add_argument("command", choices=("check", "tree", "stats", "path"))
    parser.add_argument("--chart", type=Path, default=CHART)
    parser.add_argument("--unit", help="unit id for the path command")
    parser.add_argument("--json", action="store_true", help="stats: machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load(args.chart)
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
        print(f"ok: {report['total']} units {report['by_level']}")
        return 0

    if args.command == "tree":
        print(render_tree(data))
        return 0

    if args.command == "path":
        if not args.unit:
            print("--unit is required for path", file=sys.stderr)
            return 2
        index = by_id(data.get("units") or [])
        unit = index.get(args.unit)
        if unit is None:
            print(f"unknown unit: {args.unit}", file=sys.stderr)
            return 1
        chain = []
        while unit is not None:
            chain.append(f"{unit.get('name')} [{unit.get('level')}]")
            unit = index.get(str(unit.get("parent"))) if unit.get("parent") else None
        print(" -> ".join(reversed(chain)))
        return 0

    report = stats(data)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"total: {report['total']}")
        for key, value in report["by_level"].items():
            print(f"{key}: {value}")
        for key, value in report["by_department"].items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
