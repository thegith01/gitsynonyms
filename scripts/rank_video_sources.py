#!/usr/bin/env python3
"""Rank candidate uploads of one event by duration, resolution, trust and fit.

Stage "select source" of the autonomous pipeline.  Searches YouTube through
``yt-dlp``, enriches the best candidates with format metadata and writes
``SOURCES.json`` with a transparent 100-point score.

Occlusion (banner over the caption area) is not judged here: it needs real
frames, so Module 2 decides it at burn time from the downloaded source.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TRUSTED_CHANNELS = {
    "white house": 20,
    "the white house": 20,
    "c-span": 20,
    "reuters": 18,
    "associated press": 18,
    "ap": 18,
    "bbc news": 16,
    "nbc news": 14,
    "abc news": 14,
    "cbs news": 14,
    "fox news": 12,
    "cnn": 12,
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "will", "into",
    "ahead", "after", "before", "over", "under", "live", "video", "full",
}


def log(message: str) -> None:
    print(message, flush=True)


def keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", text.lower())
    return {word for word in words if word not in STOPWORDS}


def ytdlp_json(args: list[str], timeout: int) -> list[dict]:
    command = ["yt-dlp", "--no-warnings", "--ignore-errors", *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    payloads = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payloads.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not payloads and result.returncode != 0:
        log(f"  yt-dlp failed: {(result.stderr or '').strip().splitlines()[-1:]}")
    return payloads


def search(query: str, limit: int, proxy: str | None, timeout: int) -> list[dict]:
    args = [f"ytsearch{limit}:{query}", "--flat-playlist", "--dump-json", "--skip-download"]
    if proxy:
        args += ["--proxy", proxy]
    return ytdlp_json(args, timeout)


def enrich(video_id: str, proxy: str | None, timeout: int) -> dict:
    args = [f"https://www.youtube.com/watch?v={video_id}", "-J", "--skip-download"]
    if proxy:
        args += ["--proxy", proxy]
    payloads = ytdlp_json(args, timeout)
    return payloads[0] if payloads else {}


def trust_score(channel: str) -> int:
    lowered = (channel or "").lower()
    for name, points in TRUSTED_CHANNELS.items():
        if name in lowered:
            return points
    return 5


def score_candidate(item: dict, wanted: set[str], expected_duration: float | None) -> dict:
    duration = float(item.get("duration") or 0)
    if expected_duration and duration:
        ratio = min(duration, expected_duration) / max(duration, expected_duration)
        duration_points = round(ratio * 30)
    else:
        duration_points = 12 if duration else 0

    height = 0
    for fmt in item.get("formats") or []:
        if fmt.get("vcodec") not in (None, "none"):
            height = max(height, int(fmt.get("height") or 0))
    height_points = 25 if height >= 1080 else 15 if height >= 720 else 5 if height else 0

    overlap = len(wanted & keywords(item.get("title") or ""))
    title_points = min(15, overlap * 3)

    views = int(item.get("view_count") or 0)
    view_points = min(10, round(math.log10(views + 1) * 3)) if views else 0

    trust = trust_score(item.get("channel") or item.get("uploader") or "")

    total = duration_points + height_points + title_points + view_points + trust
    return {
        "total": min(total, 100),
        "duration": duration_points,
        "height": height_points,
        "title": title_points,
        "views": view_points,
        "trust": trust,
        "max_height": height,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank candidate uploads of one event")
    parser.add_argument("--title", required=True)
    parser.add_argument("--video-id", default="")
    parser.add_argument("--expected-duration", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--enrich", type=int, default=6)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--report", default="")
    parser.add_argument("--min-score", type=int, default=60)
    args = parser.parse_args()

    wanted = keywords(args.title)
    query = " ".join(sorted(wanted)[:12]) or args.title
    log(f"query: {query}")
    candidates = search(query, args.limit, args.proxy or None, args.timeout)
    log(f"search hits: {len(candidates)}")

    seen: set[str] = set()
    ranked = []
    for item in candidates:
        video_id = item.get("id")
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        if args.video_id and video_id == args.video_id:
            continue
        ranked.append({"id": video_id, "title": item.get("title") or "",
                       "channel": item.get("channel") or item.get("uploader") or "",
                       "duration": item.get("duration") or 0,
                       "view_count": item.get("view_count") or 0})

    ranked.sort(key=lambda row: score_candidate(row, wanted, args.expected_duration)["total"],
                reverse=True)

    for row in ranked[: args.enrich]:
        detail = enrich(row["id"], args.proxy or None, args.timeout)
        if detail:
            row["formats_checked"] = True
            row["duration"] = detail.get("duration") or row["duration"]
            row["channel"] = detail.get("channel") or row["channel"]
            row["view_count"] = detail.get("view_count") or row["view_count"]
            row["formats"] = [
                {"format_id": fmt.get("format_id"), "height": fmt.get("height"),
                 "ext": fmt.get("ext"), "vcodec": fmt.get("vcodec")}
                for fmt in detail.get("formats") or []
                if fmt.get("vcodec") not in (None, "none")
            ]
        row["score"] = score_candidate(row, wanted, args.expected_duration)
        log(f"  {row['id']} {row['score']['total']:>3} {row['channel'][:30]} {row['title'][:60]}")

    for row in ranked[args.enrich:]:
        row["score"] = score_candidate(row, wanted, args.expected_duration)

    ranked.sort(key=lambda row: row["score"]["total"], reverse=True)
    best = ranked[0] if ranked else None
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "query": query,
        "source_video_id": args.video_id or None,
        "expected_duration": args.expected_duration or None,
        "candidates": ranked,
        "selected": best["id"] if best else None,
        "selected_score": best["score"]["total"] if best else 0,
        "passes_threshold": bool(best and best["score"]["total"] >= args.min_score),
    }
    target = Path(args.report) if args.report else Path("work/SOURCES.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"selected: {report['selected']} score={report['selected_score']}")
    log(f"report: {target}")
    return 0 if report["passes_threshold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
