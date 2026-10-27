#!/usr/bin/env python3
"""Cut a small, web-playable preview and poster from a burned film.

GitHub Release download URLs redirect with ``Content-Disposition: attachment``
and do not reliably answer Range requests, so the 1080p asset (often ~2 GB)
cannot be used as a ``<video src>``: the browser downloads the whole thing and
then usually refuses to play it. The Pages site therefore streams a short
720p montage kept in ``site/media/`` and shows a poster frame from the same
film, both taken from the burned deliverable so the picture is the real one.

Usage::

    python scripts/make_web_preview.py --video work/burned.mp4 --video-id 9aPyO1jfDGM

The workflow downloads the 1.8 GB release asset on a cloud runner, runs this
script, and commits only the small preview, poster and JSON summary.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "site" / "media"

# A single 90 s excerpt from a three-hour rally can land on an empty stage, so
# the preview is assembled from a few spread-out segments instead.
DEFAULT_SEGMENTS = 3
DEFAULT_SECONDS = 30
DEFAULT_HEIGHT = 720
DEFAULT_CRF = 30
SEGMENT_FRACTIONS = (0.12, 0.50, 0.85)
POSTER_WIDTH = 1280


def probe_duration(ffprobe: str, video: Path) -> float:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def has_audio(ffprobe: str, video: Path) -> bool:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def pick_segments(
    duration: float,
    *,
    count: int = DEFAULT_SEGMENTS,
    seconds: int = DEFAULT_SECONDS,
) -> list[float]:
    """Return non-overlapping segment starts, spread across the film.

    Very short films collapse to a single segment so the preview never repeats
    the same footage or runs past the end of the source.
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    length = min(float(seconds), duration)
    if duration < length * 1.6:
        return [0.0]
    starts: list[float] = []
    for fraction in SEGMENT_FRACTIONS[: max(1, count)]:
        start = min(max(0.0, duration * fraction), duration - length)
        if all(abs(start - other) >= length for other in starts):
            starts.append(round(start, 3))
    return starts or [0.0]


def build_preview_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    starts: list[float],
    *,
    seconds: int = DEFAULT_SECONDS,
    height: int = DEFAULT_HEIGHT,
    crf: int = DEFAULT_CRF,
    audio: bool = True,
) -> list[str]:
    filters: list[str] = []
    labels: list[str] = []
    for index, start in enumerate(starts):
        filters.append(
            f"[0:v]trim=start={start}:duration={seconds},setpts=PTS-STARTPTS,"
            f"scale=-2:{height}:flags=lanczos,setsar=1[v{index}]"
        )
        if audio:
            filters.append(
                f"[0:a]atrim=start={start}:duration={seconds},asetpts=PTS-STARTPTS[a{index}]"
            )
            labels.append(f"[v{index}][a{index}]")
        else:
            labels.append(f"[v{index}]")
    joined = "".join(labels)
    if audio:
        filters.append(f"{joined}concat=n={len(starts)}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    else:
        filters.append(f"{joined}concat=n={len(starts)}:v=1:a=0[v]")
        maps = ["-map", "[v]", "-an"]
    return [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        ";".join(filters),
        *maps,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]


def build_poster_command(
    ffmpeg: str,
    source: Path,
    poster: Path,
    *,
    at_seconds: float,
    width: int = POSTER_WIDTH,
) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2:flags=lanczos",
        "-q:v",
        "3",
        str(poster),
    ]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make a web preview and poster from a burned film.")
    parser.add_argument("--video", required=True, type=Path, help="burned MP4 to sample")
    parser.add_argument("--video-id", required=True, help="video id used in the output file names")
    parser.add_argument("--output-dir", type=Path, default=MEDIA)
    parser.add_argument("--segments", type=int, default=DEFAULT_SEGMENTS)
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--crf", type=int, default=DEFAULT_CRF)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe") or "ffprobe")
    args = parser.parse_args(argv)

    video = args.video.expanduser().resolve()
    if not video.is_file():
        print(f"error: no such video: {video}", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(args.ffprobe, video)
    audio = has_audio(args.ffprobe, video)
    starts = pick_segments(duration, count=args.segments, seconds=args.seconds)
    preview = args.output_dir / f"{args.video_id}-preview.mp4"
    poster = args.output_dir / f"{args.video_id}-poster.jpg"

    run(
        build_preview_command(
            args.ffmpeg,
            video,
            preview,
            starts,
            seconds=args.seconds,
            height=args.height,
            crf=args.crf,
            audio=audio,
        )
    )
    run(
        build_poster_command(
            args.ffmpeg,
            video,
            poster,
            at_seconds=min(starts[0] + args.seconds / 2, max(duration - 1, 0)),
        )
    )
    summary = {
        "video_id": args.video_id,
        "source_duration": round(duration, 3),
        "segment_starts": starts,
        "segment_seconds": args.seconds,
        "height": args.height,
        "preview_bytes": preview.stat().st_size,
        "poster_bytes": poster.stat().st_size,
    }
    (args.output_dir / f"{args.video_id}-preview.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
