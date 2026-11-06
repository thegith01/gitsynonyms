#!/usr/bin/env python3
"""Build the ergonomic bilingual ASS from a local download folder.

This is the offline counterpart of the Module 2 caption stage.  Point it at a
folder that holds one video plus YouTube's seven caption formats for both
languages and it produces the same styled ASS the pipeline burns:

    President ... [zgHIpU0pAAk].mp4
    President ... [zgHIpU0pAAk].en-orig.json3|srv3|srv2|srv1|vtt|ttml|srt
    President ... [zgHIpU0pAAk].zh-Hans.json3|srv3|srv2|srv1|vtt|ttml|srt

The ergonomics are not re-invented here.  ``subtitle_timing`` fuses the seven
formats on a nanosecond timebase, ``subtitle_layout`` enforces the 5% side
margins and the 28-character Chinese / 60-character English lines, and
``build_ass`` renders the Chinese line as a steady gold translation above the
English line whose words light up one by one from the real ``json3`` offsets.
The script adds only local-file discovery, the nanosecond sidecar, the
millisecond WebVTT sidecars and an ergonomics report so the result can be
checked before it is burned.

Usage::

    python scripts/local_bilingual_ass.py --directory "D:\\MyDownload\\a"

Exit codes: 0 on success, 1 on a missing or unreadable caption set (and on
ergonomics errors when ``--strict`` is set).
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_youtube_bilingual_srt as captions  # noqa: E402
import subtitle_ergonomics  # noqa: E402
import subtitle_timing  # noqa: E402

BRACKET_ID = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
MEDIA_SUFFIXES = (".mp4", ".mkv", ".webm", ".mov")

DEFAULT_ASS_NAME = "bilingual_precise_Chinese-English.ass"
DEFAULT_TIMING_NAME = "TIMING.json"
DEFAULT_ERGONOMICS_NAME = "ASS_ERGONOMICS.json"


def log(message: str) -> None:
    print(message, flush=True)


def media_file(folder: Path, video_id: str | None) -> Path | None:
    """Pick the local media file, preferring the one that names the video id."""
    candidates = sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if not candidates:
        return None
    if video_id:
        named = [path for path in candidates if video_id in path.stem]
        if named:
            return named[0]
    if len(candidates) > 1:
        log(
            "warning: several media files found, using the largest: "
            + candidates[0].name
        )
    return candidates[0]


def derive_video_id(folder: Path, media: Path | None, explicit: str | None) -> str:
    if explicit:
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", explicit):
            raise ValueError(
                f"--video-id must be an 11-character YouTube id, not {explicit!r}"
            )
        return explicit
    names = [media.name] if media else []
    names.extend(path.name for path in sorted(folder.iterdir()) if path.is_file())
    for name in names:
        match = BRACKET_ID.search(name)
        if match:
            return match.group(1)
    if media:
        tokens = re.findall(r"[A-Za-z0-9_-]{11}", media.stem)
        if len(tokens) == 1:
            return tokens[0]
    raise ValueError(
        "could not derive the video id from the file names; pass --video-id"
    )


def caption_prefix(path: Path, language: str) -> str:
    """Everything before ``.<language>.`` in a caption file name."""
    marker = f".{language}."
    index = path.name.find(marker)
    return path.name[:index] if index >= 0 else path.stem


def discover_formats(
    folder: Path,
    video_id: str,
    language: str,
    media_stem: str | None = None,
) -> dict[str, Path]:
    """Find the seven serializations for one language in a hand-made folder.

    The pipeline archives them as ``<id>.<language>.<ext>``; a manual download
    keeps the full title and often drops the ``[id]`` suffix entirely, as in
    ``President ... 2026.zh-Hans.json3``.  Both shapes are accepted: files are
    grouped by their title prefix, and the group that matches the local media
    file (or names the video id, or carries the most formats) wins.  That way
    two clips in one folder can never be mixed.
    """
    groups: dict[str, dict[str, Path]] = {}
    for extension in subtitle_timing.FORMAT_PRIORITY:
        for path in folder.glob(f"*.{language}.{extension}"):
            if not path.is_file():
                continue
            group = groups.setdefault(caption_prefix(path, language), {})
            current = group.get(extension)
            if current is None or len(path.name) < len(current.name):
                group[extension] = path
    if not groups:
        return {}

    stripped = None
    if media_stem:
        stripped = BRACKET_ID.sub("", media_stem).strip()

    def rank(item: tuple[str, dict[str, Path]]) -> tuple[int, int, int, int]:
        prefix, group = item
        return (
            int(bool(media_stem) and prefix == media_stem),
            int(bool(stripped) and prefix == stripped),
            int(video_id in prefix),
            len(group),
        )

    prefix, chosen = max(groups.items(), key=rank)
    if video_id not in prefix and prefix not in {media_stem, stripped}:
        log(
            f"warning: {language} captions come from {prefix!r}, "
            f"which does not name {video_id}"
        )
    return {
        extension: chosen[extension]
        for extension in subtitle_timing.FORMAT_PRIORITY
        if extension in chosen
    }


def discover_reported_formats(
    folder: Path,
    video_id: str,
    language: str,
    media_stem: str | None,
    track_report: dict,
) -> dict[str, Path]:
    """Prefer the exact files recorded by the YouTube caption fetch report."""
    names = track_report.get("files")
    if not names:
        return discover_formats(folder, video_id, language, media_stem)

    files: dict[str, Path] = {}
    for name in names:
        path = folder / str(name)
        extension = path.suffix.lstrip(".").lower()
        if extension not in subtitle_timing.FORMAT_PRIORITY:
            continue
        if not path.is_file():
            raise ValueError(
                f"CAPTION_FORMATS.json names a missing {language} caption file: "
                f"{path.name}"
            )
        files[extension] = path
    return {
        extension: files[extension]
        for extension in subtitle_timing.FORMAT_PRIORITY
        if extension in files
    }


def probe_duration(media: Path | None) -> float | None:
    """Read the container duration with ffprobe, if it is installed."""
    if media is None:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        value = float(result.stdout.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def ass_coverage_duration(duration: float | None) -> float | None:
    """Round up so centisecond ASS timing never ends before the media."""
    if duration is None:
        return None
    return math.ceil(duration * 100 - 1e-9) / 100


def build_track(folder: Path, video_id: str, language: str, media_stem: str | None = None) -> dict:
    files = discover_formats(folder, video_id, language, media_stem)
    if not files:
        raise ValueError(
            f"no {language} caption formats for {video_id} in {folder}"
        )
    if len(files) < len(subtitle_timing.FORMAT_PRIORITY):
        missing = [
            extension
            for extension in subtitle_timing.FORMAT_PRIORITY
            if extension not in files
        ]
        log(f"warning: {language} is missing {', '.join(missing)}")
    parsed = subtitle_timing.parse_formats(files)
    if not parsed:
        raise ValueError(
            f"the {language} caption files could not be parsed: "
            + ", ".join(path.name for path in files.values())
        )
    return subtitle_timing.fuse_track(language, parsed, files)


def write_sidecars(
    ass_path: Path,
    tracks: dict[str, dict],
    video_id: str,
    media: Path | None,
    timing_path: Path,
) -> dict[str, dict]:
    subtitle_timing.write_timing_report(
        timing_path,
        tracks,
        video_id=video_id,
        video=media or Path(f"{video_id}.mp4"),
    )
    sidecars: dict[str, dict] = {}
    for language, track in tracks.items():
        path = ass_path.with_name(f"{ass_path.stem}.{language}.precision.vtt")
        sidecars[language] = subtitle_timing.write_precision_vtt(track, path)
    return sidecars


def report_ergonomics(ass_path: Path, report_path: Path, fps: float, strict: bool) -> dict:
    result = subtitle_ergonomics.analyze_subtitle(ass_path, fps=fps)
    subtitle_ergonomics.write_report(report_path, result)
    summary = result["summary"]
    log(
        "ergonomics: "
        f"{subtitle_ergonomics.summary_line(result)} "
        f"(report: {report_path.name})"
    )
    for issue in result["issues"][:8]:
        log(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
    if strict and summary["errors"]:
        raise SystemExit(1)
    return result


def describe(language: str, track: dict) -> str:
    words = sum(len(cue.get("word_timings") or []) for cue in track["cues"])
    return (
        f"{language}: {'+'.join(track['formats_used'])} "
        f"({len(track['formats_used'])} formats, {track['cue_count']} cues, "
        f"{words} word timings)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the ergonomic bilingual ASS from a local caption folder."
    )
    parser.add_argument(
        "--directory",
        default=".",
        type=Path,
        help="Folder with the media file and the seven caption formats (default: .).",
    )
    parser.add_argument("--video-id", help="YouTube id when the file names omit it.")
    parser.add_argument(
        "--languages",
        default="zh-Hans,en-orig",
        help="Caption languages, upper line first (default: zh-Hans,en-orig).",
    )
    parser.add_argument(
        "--ass-output",
        type=Path,
        help=f"ASS path (default: <folder>/{DEFAULT_ASS_NAME}).",
    )
    parser.add_argument(
        "--timing-report",
        type=Path,
        help=f"Nanosecond sidecar path (default: <folder>/{DEFAULT_TIMING_NAME}).",
    )
    parser.add_argument(
        "--caption-order",
        choices=("chinese-first", "english-first"),
        default="chinese-first",
        help="Which language sits on the upper line (default: chinese-first).",
    )
    parser.add_argument(
        "--box-style",
        choices=(*captions.BOX_STYLES, "none"),
        default="none",
        help="Caption box behind the text (default: none, the cleanest reading).",
    )
    parser.add_argument(
        "--box-opacity",
        type=float,
        help="Box opacity 0-1 (default: the style's own opacity).",
    )
    parser.add_argument(
        "--box-color",
        help="Solid subtitle-box color in #RRGGBB form (default: the selected style's color).",
    )
    parser.add_argument(
        "--box-x",
        type=int,
        default=captions.CAPTION_BOX_AREA[0],
        help="Caption-box left coordinate on the 1920x1080 canvas.",
    )
    parser.add_argument(
        "--box-y",
        type=int,
        default=captions.CAPTION_BOX_AREA[1],
        help="Caption-box top coordinate on the 1920x1080 canvas.",
    )
    parser.add_argument(
        "--box-width",
        type=int,
        default=captions.CAPTION_BOX_AREA[2] - captions.CAPTION_BOX_AREA[0],
        help="Caption-box width on the 1920x1080 canvas.",
    )
    parser.add_argument(
        "--box-height",
        type=int,
        default=captions.CAPTION_BOX_AREA[3] - captions.CAPTION_BOX_AREA[1],
        help="Caption-box height on the 1920x1080 canvas.",
    )
    parser.add_argument("--first-font", default="Microsoft YaHei")
    parser.add_argument("--second-font", default="Arial")
    parser.add_argument("--second-font-size", type=int, default=48)
    parser.add_argument("--first-font-scale", type=float, default=1.2)
    parser.add_argument("--first-color", default="#FFC928")
    parser.add_argument("--second-color", default="#FFFFFF")
    parser.add_argument("--fps", type=float, default=24.0, help="Ergonomics frame rate (default: 24).")
    parser.add_argument(
        "--event-max-chars",
        type=int,
        default=60,
        help=(
            "English characters per display event (default: 60, the pipeline "
            "budget). Lower values split more often but give each event less "
            "screen time; raise the line budget first."
        ),
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        choices=(1, 2),
        default=1,
        help=(
            "Lines per language (default: 1). The local viewing default keeps "
            "one Chinese and one English line; overwide bilingual events are "
            "split at timed token boundaries to keep font sizes consistent."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when the ergonomics report finds an error.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = args.directory.expanduser().resolve()
    if not folder.is_dir():
        log(f"error: not a folder: {folder}")
        return 1

    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    if len(languages) != 2 or languages[0] == languages[1]:
        log("error: --languages must name two different languages")
        return 1

    try:
        media = media_file(folder, args.video_id)
        video_id = derive_video_id(folder, media, args.video_id)
        first_language, second_language = languages
        first = build_track(folder, video_id, first_language, media.stem if media else None)
        second = build_track(folder, video_id, second_language, media.stem if media else None)
    except (OSError, ValueError) as error:
        log(f"error: {error}")
        return 1

    duration = probe_duration(media)
    if duration is None:
        duration = max(
            track["cues"][-1]["end_ns"] for track in (first, second)
        ) / subtitle_timing.NS_PER_SECOND
        log("warning: ffprobe unavailable, using the last caption cue as the duration")

    box_style = args.box_style
    box_opacity = args.box_opacity
    if box_opacity is None:
        box_opacity = (
            captions.BOX_STYLES[box_style]["opacity"]
            if box_style in captions.BOX_STYLES
            else 0.85
        )

    content, stats = subtitle_timing.build_precise_ass(
        first,
        second,
        box_style=box_style,
        box_opacity=box_opacity,
        box_color=args.box_color,
        first_font=args.first_font,
        second_font=args.second_font,
        second_font_size=args.second_font_size,
        first_font_scale=args.first_font_scale,
        box_area=(
            args.box_x,
            args.box_y,
            args.box_x + args.box_width,
            args.box_y + args.box_height,
        ),
        caption_order=args.caption_order,
        first_color=args.first_color,
        second_color=args.second_color,
        video_duration=duration,
        event_max_chars=args.event_max_chars,
        max_english_lines=args.max_lines,
        max_chinese_lines=args.max_lines,
    )

    ass_path = (args.ass_output or folder / DEFAULT_ASS_NAME).expanduser().resolve()
    timing_path = (
        args.timing_report or folder / DEFAULT_TIMING_NAME
    ).expanduser().resolve()
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    captions.write_ass(ass_path, content)
    sidecars = write_sidecars(ass_path, {first_language: first, second_language: second}, video_id, media, timing_path)

    log(f"folder      : {folder}")
    log(f"video id    : {video_id}")
    log(f"media       : {media.name if media else '(no local media file)'} ({duration:.3f} s)")
    log(f"  {describe(first_language, first)}")
    log(f"  {describe(second_language, second)}")
    log(f"ass         : {ass_path}")
    log(f"timing      : {timing_path} (max error {stats['measured_max_quantization_error_ms']:.3f} ms)")
    log(
        "precision   : "
        + ", ".join(
            f"{language} {record['cues']} cues / {record['resolution']}"
            for language, record in sidecars.items()
        )
    )
    report_ergonomics(
        ass_path,
        folder / DEFAULT_ERGONOMICS_NAME,
        args.fps,
        args.strict,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
