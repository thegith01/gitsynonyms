#!/usr/bin/env python3
"""Score acquired footage on the five Module 1 material criteria.

The 素材获取处 must answer, before Module 2 burns anything: is this clip clean,
trustworthy, multi-angle, long enough, and is it actually moving instead of a
frozen or unrelated still?  This script measures the parts that can be measured
from the file itself by sampling the video, and reuses the source ranking for
trust and angle count.

It does NOT judge whether the content is *relevant* - that needs a human or an
event brief.  A pass here only means "not static, not black, long enough, from a
trusted upload with other candidates available".

Usage::

    python scripts/footage_quality.py --video work/abc.source.mp4 \
        --sources work/SOURCES.json --report work/FOOTAGE.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FREEZE_LIMIT = 0.35
BLACK_LIMIT = 0.20
PASS_MARK = 60
TARGET_SECONDS = 90 * 60


def log(message: str) -> None:
    print(message, flush=True)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_footage(
    duration: float,
    freeze_ratio: float,
    black_ratio: float,
    trust: float,
    angles: int,
    target_seconds: float = TARGET_SECONDS,
) -> dict:
    """Return a 100-point breakdown for the five material criteria.

    Weights: duration 20, motion 25, clean 20, trust 20, angles 15.
    The pass mark is 60 **and** both freeze and black ratios must be inside
    their limits; a static or black clip must never pass on length alone.
    """
    duration_points = round(clamp(duration / target_seconds, 0, 1) * 20)
    if freeze_ratio > FREEZE_LIMIT:
        motion_points = 0
    else:
        motion_points = round((1 - freeze_ratio / FREEZE_LIMIT) * 25)
    if black_ratio > BLACK_LIMIT:
        clean_points = 0
    else:
        clean_points = round((1 - black_ratio / BLACK_LIMIT) * 20)
    trust_points = round(clamp(trust, 0, 20))
    if angles >= 3:
        angle_points = 15
    elif angles == 2:
        angle_points = 12
    elif angles == 1:
        angle_points = 6
    else:
        angle_points = 0

    total = duration_points + motion_points + clean_points + trust_points + angle_points
    return {
        "total": min(100, total),
        "duration": duration_points,
        "motion": motion_points,
        "clean": clean_points,
        "trust": trust_points,
        "angles": angle_points,
        "freeze_ratio": round(freeze_ratio, 4),
        "black_ratio": round(black_ratio, 4),
        "passes_threshold": bool(
            total >= PASS_MARK and freeze_ratio <= FREEZE_LIMIT and black_ratio <= BLACK_LIMIT
        ),
    }


def parse_durations(log_text: str, key: str) -> float:
    """Sum every ``<key>: 12.3`` value in ffmpeg's report."""
    total = 0.0
    for match in re.finditer(rf"{key}:\s*([0-9]+(?:\.[0-9]+)?)", log_text):
        total += float(match.group(1))
    return total


def parse_scene_count(stdout: str) -> int:
    """Count scene metadata blocks emitted by ``metadata=print``."""
    return len(re.findall(r"pts_time:", stdout))


def probe_duration(video: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    try:
        return float((result.stdout or "").strip().splitlines()[0])
    except (IndexError, ValueError):
        raise SystemExit(f"could not read duration from {video}")


def windows(duration: float, samples: int, seconds: float) -> list[tuple[float, float]]:
    if duration <= seconds:
        return [(0.0, duration)]
    samples = max(1, samples)
    step = (duration - seconds) / max(1, samples - 1)
    return [(index * step, seconds) for index in range(samples)]


def analyse_window(video: Path, start: float, length: float) -> dict:
    base = ["ffmpeg", "-nostdin", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(video), "-an"]
    frozen = subprocess.run(
        [*base, "-vf", "freezedetect=n=0.003:d=1.0,blackdetect=d=0.4:pix_th=0.10",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=900,
    )
    scene = subprocess.run(
        [*base, "-vf", "select='gt(scene,0.35)',metadata=print", "-f", "null", "-"],
        capture_output=True, text=True, timeout=900,
    )
    return {
        "start": round(start, 3),
        "length": round(length, 3),
        "freeze_seconds": parse_durations(frozen.stderr, "freeze_duration"),
        "black_seconds": parse_durations(frozen.stderr, "black_duration"),
        "scene_changes": parse_scene_count(scene.stdout),
    }


def source_context(path: Path | None) -> tuple[float, int]:
    """Read trust of the selected candidate and the number of distinct channels."""
    if not path or not path.is_file():
        return 12.0, 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 12.0, 1
    candidates = data.get("candidates") or []
    selected_id = data.get("selected")
    selected = next((row for row in candidates if row.get("id") == selected_id), None)
    trust = float(((selected or {}).get("score") or {}).get("trust") or 12)
    channels = {
        (row.get("channel") or row.get("uploader") or "").strip().lower()
        for row in candidates
        if float(((row.get("score") or {}).get("total") or 0)) >= 60
    }
    channels.discard("")
    return trust, max(1, len(channels))


def build_report(video: Path, samples: int, seconds: float, sources: Path | None) -> dict:
    duration = probe_duration(video)
    windows_ = windows(duration, samples, seconds)
    results = [analyse_window(video, start, length) for start, length in windows_]
    sampled = sum(item["length"] for item in results) or 1.0
    freeze_ratio = sum(item["freeze_seconds"] for item in results) / sampled
    black_ratio = sum(item["black_seconds"] for item in results) / sampled
    scenes = sum(item["scene_changes"] for item in results)
    trust, angles = source_context(sources)
    score = score_footage(duration, freeze_ratio, black_ratio, trust, angles)

    return {
        "schema": "module1-footage/1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "video": str(video),
        "duration": round(duration, 3),
        "sampled_seconds": round(sampled, 3),
        "metrics": {
            "freeze_ratio": round(freeze_ratio, 4),
            "black_ratio": round(black_ratio, 4),
            "scene_changes": scenes,
            "scene_changes_per_minute": round(scenes / (sampled / 60), 2),
            "trust": trust,
            "angles": angles,
        },
        "windows": results,
        "score": score,
        "passes_threshold": score["passes_threshold"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score footage on clean / motion / length / trust / angles.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=None, help="SOURCES.json for trust and angle count")
    parser.add_argument("--report", type=Path, default=Path("work/FOOTAGE.json"))
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--sample-seconds", type=float, default=20.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.video.is_file():
        print(f"error: video not found: {args.video}", file=sys.stderr)
        return 2
    try:
        report = build_report(args.video, args.samples, args.sample_seconds, args.sources)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    metrics = report["metrics"]
    log(
        f"freeze={metrics['freeze_ratio']:.1%} black={metrics['black_ratio']:.1%} "
        f"scenes/min={metrics['scene_changes_per_minute']} "
        f"trust={metrics['trust']} angles={metrics['angles']}"
    )
    log(f"score {report['score']['total']}/100 -> {'pass' if report['passes_threshold'] else 'fail'}")
    log(f"report: {args.report}")
    return 0 if report["passes_threshold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
