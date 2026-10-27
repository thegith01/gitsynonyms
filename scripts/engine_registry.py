#!/usr/bin/env python3
"""Engine registry for the Module 2 research offices.

Four offices research and rank engines across the web:

* ``asr``          - 语音转写处 (speech -> English transcript)
* ``translation``  - 翻译处 (English -> Chinese subtitles)
* ``voice-burn``   - 语音刻录处 (TTS dub aligned to the subtitle timeline)
* ``voice-clone``  - 语音克隆处 (zero-shot voice cloning)

Each office keeps a versioned record in ``docs/engines/data/<office>.json``:
a 100-point rubric, one scored row per candidate, citations for every score,
and a selection. Totals are *recomputed from the rubric* so a hand-edited total
cannot survive `check`; a candidate below the pass mark may not be used for a
deliverable.

Usage::

    python scripts/engine_registry.py check
    python scripts/engine_registry.py rank --office asr
    python scripts/engine_registry.py markdown --office asr --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "engines" / "data"
DOC_DIR = ROOT / "docs" / "engines"

OFFICES = ("asr", "translation", "voice-burn", "voice-clone")

STATUSES = {"measured", "vendor-claimed", "estimated"}
PASS_MARK = 60

REQUIRED_TOP = ("schema", "office", "title", "updated_at", "rubric", "candidates", "selection")


def record_path(office: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"{office}.json"


def load(office: str, data_dir: Path = DATA_DIR) -> dict:
    path = record_path(office, data_dir)
    if not path.is_file():
        raise ValueError(f"engine record not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def dimensions(record: dict) -> list[dict]:
    return list((record.get("rubric") or {}).get("dimensions") or [])


def weights(record: dict) -> dict[str, int]:
    return {item["id"]: int(item["weight"]) for item in dimensions(record)}


def total(record: dict, candidate: dict) -> int:
    """Recompute a candidate total from the rubric, never from a stored number."""
    limit = weights(record)
    scores = candidate.get("scores") or {}
    return int(round(sum(min(float(scores.get(key, 0)), limit[key]) for key in limit)))


def rank(record: dict) -> list[dict]:
    dims = [item["id"] for item in dimensions(record)]
    first = dims[0] if dims else ""
    rows = []
    for candidate in record.get("candidates") or []:
        rows.append({**candidate, "total": total(record, candidate)})
    rows.sort(key=lambda row: (-row["total"], -(row.get("scores") or {}).get(first, 0), row["id"]))
    for index, row in enumerate(rows, 1):
        row["rank"] = index
        row["passes"] = row["total"] >= int(record.get("threshold", PASS_MARK))
    return rows


def validate(record: dict) -> list[str]:
    """Return a list of human-readable problems; empty means the record is valid."""
    problems: list[str] = []
    for key in REQUIRED_TOP:
        if key not in record:
            problems.append(f"missing top-level key: {key}")
    if problems:
        return problems

    dims = dimensions(record)
    if not dims:
        problems.append("rubric.dimensions is empty")
        return problems

    seen: set[str] = set()
    for item in dims:
        key = item.get("id")
        if not key:
            problems.append("rubric dimension without id")
            continue
        if key in seen:
            problems.append(f"duplicate rubric dimension: {key}")
        seen.add(key)
        weight = item.get("weight")
        if not isinstance(weight, int) or weight <= 0:
            problems.append(f"rubric {key}: weight must be a positive integer")
        if not item.get("label"):
            problems.append(f"rubric {key}: label is required")

    if seen and sum(int(item.get("weight", 0)) for item in dims) != 100:
        problems.append("rubric weights must add up to 100")

    ids = set()
    candidates = record.get("candidates") or []
    if not candidates:
        problems.append("no candidates")
    for candidate in candidates:
        cid = candidate.get("id")
        if not cid:
            problems.append("candidate without id")
            continue
        if cid in ids:
            problems.append(f"duplicate candidate id: {cid}")
        ids.add(cid)
        if candidate.get("status") not in STATUSES:
            problems.append(f"{cid}: status must be one of {sorted(STATUSES)}")
        scores = candidate.get("scores") or {}
        for key in seen:
            if key not in scores:
                problems.append(f"{cid}: missing score for {key}")
                continue
            value = scores[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"{cid}: score for {key} must be numeric")
            elif value < 0 or value > int(next(i["weight"] for i in dims if i["id"] == key)):
                problems.append(f"{cid}: score for {key} is outside 0..{next(i['weight'] for i in dims if i['id'] == key)}")
        extra = set(scores) - seen
        if extra:
            problems.append(f"{cid}: scores for unknown dimensions {sorted(extra)}")
        evidence = candidate.get("evidence") or []
        if not evidence:
            problems.append(f"{cid}: at least one evidence entry is required")
        for item in evidence:
            url = str(item.get("url") or "")
            if not url.startswith("https://"):
                problems.append(f"{cid}: evidence url must be https: {url or '<empty>'}")
            if not item.get("observed_at"):
                problems.append(f"{cid}: evidence needs observed_at: {url or '<empty>'}")

    selection = record.get("selection") or {}
    primary = selection.get("primary")
    if primary and primary not in ids:
        problems.append(f"selection.primary is not a candidate: {primary}")
    for key in ("fallback", "upgrade", "offline"):
        for name in selection.get(key) or []:
            if name not in ids:
                problems.append(f"selection.{key} is not a candidate: {name}")

    ranked = rank(record)
    chosen = next((row for row in ranked if row["id"] == primary), None)
    if chosen and not chosen["passes"]:
        problems.append(
            f"selection.primary {primary} scores {chosen['total']}, below the "
            f"{record.get('threshold', PASS_MARK)} pass mark"
        )
    return problems


def check_all(data_dir: Path = DATA_DIR) -> list[str]:
    problems: list[str] = []
    for office in OFFICES:
        try:
            record = load(office, data_dir)
        except (OSError, ValueError) as error:
            problems.append(str(error))
            continue
        if record.get("office") != office:
            problems.append(f"{office}: record says office={record.get('office')!r}")
        problems.extend(f"{office}: {item}" for item in validate(record))
    return problems


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def render(record: dict) -> str:
    dims = dimensions(record)
    ranked = rank(record)
    threshold = int(record.get("threshold", PASS_MARK))
    lines = [
        f"# {record['title']}",
        "",
        f"> 评分口径 v{(record.get('rubric') or {}).get('version', '1.0')}　"
        f"数据更新 {record['updated_at']}　及格线 {threshold}/100",
        "",
        "本页由 `scripts/engine_registry.py markdown` 从 "
        f"`docs/engines/data/{record['office']}.json` 生成；总分由评分表重算，"
        "不接受手填。每个分数都必须有可复核链接。",
        "",
        "## 评分维度",
        "",
        "| 维度 | 权重 | 计分口径 |",
        "|---|---:|---|",
    ]
    for item in dims:
        lines.append(f"| {_cell(item['label'])} | {item['weight']} | {_cell(item.get('rule', ''))} |")

    lines += [
        "",
        "## 排名",
        "",
        "| 名次 | 引擎 | 类型 | 总分 | 结论 | 数据性质 | 成本 |",
        "|---:|---|---|---:|---|---|---|",
    ]
    for row in ranked:
        verdict = "可用" if row["passes"] else "不及格"
        lines.append(
            f"| {row['rank']} | `{row['id']}` {_cell(row.get('name', ''))} | "
            f"{_cell(row.get('kind', ''))} | {row['total']} | {verdict} | "
            f"{_cell(row.get('status', ''))} | {_cell(row.get('cost', '—'))} |"
        )

    selection = record.get("selection") or {}
    lines += ["", "## 选型", ""]
    for key, label in (
        ("primary", "当前主用"),
        ("upgrade", "达到条件后升级"),
        ("fallback", "回退"),
        ("offline", "离线兜底"),
    ):
        names = selection.get(key)
        if isinstance(names, str):
            names = [names]
        if names:
            lines.append(f"- **{label}**：{', '.join(f'`{name}`' for name in names)}")
    if selection.get("reason"):
        lines += ["", selection["reason"]]

    lines += [
        "",
        "## 逐维度得分",
        "",
        "| 引擎 | " + " | ".join(_cell(item["label"]) for item in dims) + " | 总分 |",
        "|---|" + "---:|" * len(dims) + "---:|",
    ]
    for row in ranked:
        values = " | ".join(str(row["scores"].get(item["id"], 0)) for item in dims)
        lines.append(f"| `{row['id']}` | {values} | {row['total']} |")

    lines += ["", "## 证据", ""]
    for row in ranked:
        lines.append(f"### `{row['id']}`")
        if row.get("notes"):
            lines.append("")
            lines.append(row["notes"])
        lines.append("")
        for item in row.get("evidence") or []:
            note = item.get("note") or item.get("url")
            lines.append(f"- {item['observed_at']}　{note}　<{item['url']}>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_markdown(office: str, data_dir: Path = DATA_DIR, doc_dir: Path = DOC_DIR) -> Path:
    record = load(office, data_dir)
    target = doc_dir / f"{office}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(record), encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and rank Module 2 engine research.")
    parser.add_argument("command", choices=("check", "rank", "markdown", "json", "select"))
    parser.add_argument("--office", choices=OFFICES)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--doc-dir", type=Path, default=DOC_DIR)
    parser.add_argument("--write", action="store_true", help="markdown: write docs/engines/<office>.md")
    parser.add_argument("--top", type=int, default=0, help="rank: limit rows")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "check":
        problems = check_all(args.data_dir)
        if problems:
            for problem in problems:
                print(f"FAIL {problem}", file=sys.stderr)
            return 1
        print(f"ok: {len(OFFICES)} offices valid")
        return 0

    office = args.office
    if not office:
        print("--office is required for this command", file=sys.stderr)
        return 2
    try:
        record = load(office, args.data_dir)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.command == "rank":
        rows = rank(record)[: args.top or None]
        for row in rows:
            flag = "pass" if row["passes"] else "fail"
            print(f"{row['rank']:>3}  {row['id']:38} {row['total']:>3}/100  {flag}  {row.get('cost', '-')}")
        return 0

    if args.command == "json":
        print(json.dumps(rank(record), indent=2, ensure_ascii=False))
        return 0

    if args.command == "select":
        selection = record.get("selection") or {}
        print(selection.get("primary", ""))
        return 0

    record = load(office, args.data_dir)
    problems = validate(record)
    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    if args.write:
        print(write_markdown(office, args.data_dir, args.doc_dir))
    else:
        print(render(record), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
