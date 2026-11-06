#!/usr/bin/env python3
"""Build the Scheme 1 cue-aligned bilingual ASS from a local caption folder.

Scheme 1 is deliberately smaller than the fused seven-format timeline:

* the English SRT cue is the display unit, and its end is trimmed to the next
  cue's start (the rolling-caption correction);
* every English cue carries exactly one Chinese line, so each ASS event is one
  bilingual cue with no merging and no re-timing;
* the bilingual SRT is rendered by ``scheme1_srt_to_ass`` with one line per
  language.

Every available YouTube format is fused independently for each language.
English SRT remains the display transcript when available; Chinese uses the
highest-priority non-empty official format. All other usable formats
corroborate timing. Official Chinese is required; machine translation is not a fallback.
``scheme_高级_自研_1`` accepts only the official YouTube English auto-ASR
track and its corresponding official auto-translated Chinese track.
``SCHEME_ADVANCED_SELFDEV_1.json`` records format and cue provenance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_youtube_bilingual_srt as captions  # noqa: E402
import local_bilingual_ass  # noqa: E402
import scheme1_srt_to_ass  # noqa: E402
import subtitle_ergonomics  # noqa: E402
import subtitle_layout  # noqa: E402
import subtitle_timeline  # noqa: E402
import subtitle_timing  # noqa: E402

ENGLISH = "en-orig"
CHINESE = "zh-Hans"
SCHEME_ID = "scheme_local__advanced_selfdev_1"
SCHEME_LABEL = "scheme_高级_自研_1"
DEFAULT_ASS_NAME = "bilingual_scheme_advanced_selfdev_1_Chinese-English.ass"
DEFAULT_SRT_NAME = "bilingual_scheme_advanced_selfdev_1_Chinese-English.srt"
DEFAULT_REPORT_NAME = "SCHEME_ADVANCED_SELFDEV_1.json"
DEFAULT_ERGONOMICS_NAME = "SCHEME_ADVANCED_SELFDEV_1_ERGONOMICS.json"

def log(message: str) -> None:
    print(message, flush=True)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\r", " ").replace("\n", " ")).strip()


def deduplicate_identical_cues(cues: Sequence[dict]) -> tuple[list[dict], int]:
    """Collapse serialization duplicates with identical times and text."""
    unique: dict[tuple[int, int, str], dict] = {}
    duplicates = 0
    for cue in cues:
        key = (
            int(cue["start_ns"]),
            int(cue["end_ns"]),
            clean_text(cue["text"]),
        )
        existing = unique.get(key)
        if existing is None:
            unique[key] = cue
            continue
        duplicates += 1
        existing["sources"] = sorted(
            set(existing.get("sources", [])) | set(cue.get("sources", []))
        )
    return list(unique.values()), duplicates


def load_fused_track(
    files: dict[str, Path],
    language: str,
    label: str,
    *,
    primary_format: str | None = None,
) -> tuple[list[dict], dict]:
    """Fuse all readable source formats and apply Scheme 1 overlap correction."""
    parsed: dict[str, list[dict]] = {}
    failures: dict[str, str] = {}
    for extension in subtitle_timing.FORMAT_PRIORITY:
        path = files.get(extension)
        if path is None:
            continue
        try:
            cues = captions.parse_caption_file(path)
            if extension == "vtt":
                cues = captions._without_rolling_cues(cues)
        except captions.SubtitleOverlapError:
            raise
        except (OSError, ValueError) as error:
            failures[extension] = str(error)
            continue
        if cues:
            parsed[extension] = cues
        else:
            failures[extension] = "no usable cues"

    if not parsed:
        details = "; ".join(
            f"{extension}: {reason}" for extension, reason in failures.items()
        )
        raise ValueError(
            f"no readable {label} caption format"
            + (f" ({details})" if details else "")
        )

    track = subtitle_timing.fuse_track(
        language, parsed, files, primary_format=primary_format
    )
    fused_cues, identical_cues_removed = deduplicate_identical_cues(
        track["cues"]
    )
    cues = [
        {
            "start": subtitle_timing.to_seconds(cue["start_ns"]),
            "end": subtitle_timing.to_seconds(cue["end_ns"]),
            "text": clean_text(cue["text"]),
            "format_sources": cue["sources"],
            "text_source": cue["text_source"],
            "word_timings": captions._word_timings_for_text(
                clean_text(cue["text"]),
                [
                    {
                        "text": cue["text"],
                        "word_timings": [
                            {
                                "text": word["text"],
                                "start": subtitle_timing.to_seconds(
                                    word["start_ns"]
                                ),
                                "end": subtitle_timing.to_seconds(
                                    word["end_ns"]
                                ),
                            }
                            for word in cue.get("word_timings", [])
                        ],
                    }
                ],
            ),
        }
        for cue in fused_cues
    ]
    track["cues"] = captions._without_rolling_cues(cues)
    track["format_failures"] = failures
    track["identical_cues_removed"] = identical_cues_removed
    track["format_usage"] = {
        extension: {
            "source": path.name,
            "parsed": extension in parsed,
            "matched_cues": sum(
                extension in cue["format_sources"] for cue in track["cues"]
            ),
            "text_cues": sum(
                cue["text_source"] == extension for cue in track["cues"]
            ),
            **(
                {"error": failures[extension]}
                if extension in failures
                else {}
            ),
        }
        for extension, path in files.items()
    }
    return track["cues"], track


def same_timeline(left: Sequence[dict], right: Sequence[dict], tolerance: float = 0.002) -> bool:
    if len(left) != len(right):
        return False
    return all(
        abs(float(a["start"]) - float(b["start"])) <= tolerance
        and abs(float(a["end"]) - float(b["end"])) <= tolerance
        for a, b in zip(left, right)
    )


def load_official_chinese(files: dict[str, Path]) -> tuple[list[dict], dict]:
    """Load official Chinese even when its cue grid differs from English."""
    if not files:
        return [], {}
    return load_fused_track(files, CHINESE, "Chinese")


def track_source(track: dict) -> Path | None:
    """Return the file supplying the fused track's primary cue text."""
    source = track.get("source_files", {}).get(track.get("primary_format"))
    return Path(source) if source else None


def load_caption_source_report(folder: Path) -> dict | None:
    """Load downloader provenance when this folder was populated by the local flow."""
    path = folder / "CAPTION_FORMATS.json"
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read caption source report {path.name}: {error}") from error
    if not isinstance(report, dict) or not isinstance(report.get("tracks"), dict):
        raise ValueError(f"caption source report {path.name} has no track records")
    return report


def verify_caption_kind(
    report: dict | None, language: str, expected_kind: str
) -> dict:
    """Reject a downloaded track whose recorded origin differs from the scheme."""
    if report is None:
        raise ValueError(
            "CAPTION_FORMATS.json is required to verify the official YouTube "
            f"{language} source for {SCHEME_LABEL}"
        )
    track = report["tracks"].get(language)
    if not isinstance(track, dict) or not track.get("present"):
        raise ValueError(
            f"CAPTION_FORMATS.json does not confirm a present {language} source track"
        )
    actual_kind = track.get("kind")
    if actual_kind != expected_kind:
        raise ValueError(
            f"{language} source is {actual_kind or 'unknown'}, expected "
            f"{expected_kind}; refresh the YouTube caption set before building Scheme 1"
        )
    return {
        "verified": True,
        "kind": actual_kind,
        "youtube_code": track.get("youtube_code"),
        "formats": track.get("formats", []),
        "missing_formats": track.get("missing_formats", []),
    }


def split_overlong_english(cues: Sequence[dict], max_chars: int) -> list[dict]:
    """Split an overlong English cue at a word boundary, preserving order."""
    result: list[dict] = []
    for cue in cues:
        text = clean_text(cue["text"])
        if len(text) <= max_chars:
            result.append({**cue, "text": text})
            continue
        lines = subtitle_layout.wrap_caption(
            text, "en", max_chars=max_chars, max_lines=1
        )
        if len(lines) < 2:
            result.append({**cue, "text": text})
            continue
        words = re.findall(r"\S+", subtitle_timeline._clean(text))
        line_word_counts = [
            len(re.findall(r"\S+", subtitle_timeline._clean(line)))
            for line in lines
        ]
        source_timings = cue.get("word_timings") or []
        if source_timings and len(source_timings) != len(words):
            raise ValueError(
                "English word timings do not align with the overlong SRT cue."
            )
        timing_groups = []
        timing_cursor = 0
        for count in line_word_counts:
            timing_groups.append(source_timings[timing_cursor : timing_cursor + count])
            timing_cursor += count
        boundaries = [float(cue["start"])]
        if source_timings:
            boundaries.extend(
                (
                    float(left[-1]["end"]) + float(right[0]["start"])
                )
                / 2
                for left, right in zip(timing_groups, timing_groups[1:])
            )
        else:
            total = sum(len(line) for line in lines)
            cursor = float(cue["start"])
            duration = float(cue["end"]) - cursor
            boundaries.extend(
                cursor
                + duration * sum(len(line) for line in lines[:index]) / total
                for index in range(1, len(lines))
            )
        boundaries.append(float(cue["end"]))
        for index, line in enumerate(lines):
            start, end = boundaries[index], boundaries[index + 1]
            if end <= start:
                raise ValueError(
                    "Timed Scheme 1 text splitting produced an empty cue interval."
                )
            result.append(
                {
                    **cue,
                    "start": start,
                    "end": end,
                    "text": line,
                    **(
                        {"word_timings": timing_groups[index]}
                        if source_timings
                        else {}
                    ),
                }
            )
    return result


def build(
    folder: Path,
    video_id: str,
    media: Path | None,
    *,
    ass_path: Path | None = None,
    srt_path: Path | None = None,
    report_path: Path | None = None,
    ergonomics_path: Path | None = None,
    box_style: str = "none",
    box_color: str | None = None,
    box_opacity: float | None = None,
    caption_order: str = "chinese-first",
    fps: float = 24.0,
    strict: bool = False,
    limit: int = 0,
) -> dict:
    """Build the higher-tier self-developed Scheme 1 ASS and its audit report."""
    folder = Path(folder)
    media_stem = media.stem if media else None
    caption_source_report = load_caption_source_report(folder)
    english_provenance = verify_caption_kind(
        caption_source_report, ENGLISH, "auto-generated"
    )
    english_source_report = caption_source_report["tracks"].get(ENGLISH, {})
    english_files = local_bilingual_ass.discover_reported_formats(
        folder, video_id, ENGLISH, media_stem, english_source_report
    )
    if not english_files:
        raise ValueError(f"no English caption formats for {video_id} in {folder}")
    english, english_track = load_fused_track(
        english_files,
        ENGLISH,
        "English",
        primary_format="srt" if "srt" in english_files else None,
    )
    english = split_overlong_english(
        english, subtitle_layout.max_chars_for("en")
    )
    if limit:
        english = english[:limit]

    chinese_source_report = caption_source_report["tracks"].get(CHINESE, {})
    chinese_files = local_bilingual_ass.discover_reported_formats(
        folder, video_id, CHINESE, media_stem, chinese_source_report
    )
    chinese: list[dict] | None = None
    chinese_track: dict = {}
    if chinese_files:
        chinese_provenance = verify_caption_kind(
            caption_source_report, CHINESE, "auto-translated"
        )
        chinese, chinese_track = load_official_chinese(chinese_files)
        if limit and english:
            chinese = [
                cue
                for cue in chinese
                if cue["start"] <= english[-1]["end"] + 0.001
                and cue["end"] > english[0]["start"]
            ]
    else:
        raise ValueError(
            f"{SCHEME_LABEL} requires the official YouTube auto-translated "
            "Chinese track; no matching local files were found."
        )

    max_chinese = subtitle_layout.max_chars_for("zh-Hans")
    if chinese is None or not chinese:
        raise ValueError(
            f"{SCHEME_LABEL} requires a readable official YouTube "
            "auto-translated Chinese track; it will not substitute machine "
            "translation or an empty cue set."
        )

    overwide_chinese = [
        {
            "start": cue["start"],
            "characters": len(clean_text(cue["text"])),
            "width_units": subtitle_layout.line_units(clean_text(cue["text"])),
        }
        for cue in chinese
        if subtitle_layout.line_units(clean_text(cue["text"])) > max_chinese
    ]

    bilingual_srt = captions.build_scheme1_bilingual_srt(chinese, english)
    raw_video_duration = local_bilingual_ass.probe_duration(media)
    video_duration = local_bilingual_ass.ass_coverage_duration(
        raw_video_duration
    )
    if box_style != "none" and video_duration is None:
        raise ValueError(
            "a readable local video duration is required for full-video caption-box coverage"
        )
    destination_srt = (srt_path or folder / DEFAULT_SRT_NAME).expanduser().resolve()
    destination_srt.parent.mkdir(parents=True, exist_ok=True)
    destination_srt.write_text(bilingual_srt, encoding="utf-8")
    _, srt_english = scheme1_srt_to_ass.split_bilingual_tracks(destination_srt)
    english_word_timings = [
        captions._word_timings_for_text(cue["text"], english)
        for cue in srt_english
    ]

    destination_ass = (ass_path or folder / DEFAULT_ASS_NAME).expanduser().resolve()
    scheme1_srt_to_ass.convert_srt_to_ass(
        destination_srt,
        destination_ass,
        english_word_timings=english_word_timings,
        video_duration=video_duration,
        box_style=box_style,
        box_color=box_color,
        box_opacity=box_opacity,
        caption_order=caption_order,
    )

    ergonomics_file = (
        ergonomics_path or folder / DEFAULT_ERGONOMICS_NAME
    ).expanduser().resolve()
    ergonomics = subtitle_ergonomics.analyze_subtitle(destination_ass, fps=fps)
    subtitle_ergonomics.write_report(ergonomics_file, ergonomics)
    summary = ergonomics["summary"]
    log(
        "ergonomics: "
        f"{subtitle_ergonomics.summary_line(ergonomics)} "
        f"(report: {ergonomics_file.name})"
    )
    for issue in ergonomics["issues"][:8]:
        log(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")

    english_source = track_source(english_track)
    chinese_source = track_source(chinese_track)
    chinese_official_aligned = same_timeline(chinese, english)
    report = {
        "generated_at": subtitle_timing.utc_now(),
        "video_id": video_id,
        "scheme": SCHEME_LABEL,
        "scheme_id": SCHEME_ID,
        "ass": destination_ass.name,
        "bilingual_srt": destination_srt.name,
        "ergonomics": ergonomics_file.name,
        "english": {
            "source": english_source.name if english_source else None,
            "cues": len(english),
            "youtube_source": english_provenance,
            "primary_format": english_track["primary_format"],
            "formats_used": english_track["formats_used"],
            "format_usage": english_track["format_usage"],
            "format_failures": english_track["format_failures"],
            "identical_cues_removed": english_track["identical_cues_removed"],
        },
        "chinese": {
            "source": chinese_source.name if chinese_source else None,
            "youtube_source": chinese_provenance,
            "kind": (
                "official-aligned"
                if chinese_official_aligned
                else "official-time-aligned"
            ),
            "engine": "youtube-auto-translation",
            "cues": len(chinese),
            "primary_format": chinese_track.get("primary_format"),
            "formats_used": chinese_track.get("formats_used", []),
            "format_usage": chinese_track.get("format_usage", {}),
            "format_failures": chinese_track.get("format_failures", {}),
            "identical_cues_removed": chinese_track.get(
                "identical_cues_removed", 0
            ),
            "overwide_cues": overwide_chinese,
            "alignment": (
                "same-cue-grid"
                if chinese_official_aligned
                else "source-time-overlap"
            ),
        },
        "cue_count": len(srt_english),
        "bilingual_cue_count": len(srt_english)
        - sum(bool(cue.get("unpaired")) for cue in srt_english),
        "unpaired_english_cues": [
            {
                "start": cue["start"],
                "end": cue["end"],
                "text": cue["text"],
            }
            for cue in srt_english
            if cue.get("unpaired")
        ],
        "style": {
            "box_style": box_style,
            "box_color": box_color or "#000000",
            "box_opacity": box_opacity,
            "video_duration": raw_video_duration,
            "background_end": video_duration,
            "caption_order": caption_order,
            "max_english_lines": 1,
            "max_chinese_lines": 1,
        },
        "ergonomics_summary": summary,
    }
    report_file = (report_path or folder / DEFAULT_REPORT_NAME).expanduser().resolve()
    report_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log(f"{SCHEME_LABEL}: {len(english)} bilingual cues -> {destination_ass}")
    log(f"report : {report_file}")
    if strict and summary["errors"]:
        raise ValueError(
            f"ergonomics found {summary['errors']} errors; see {ergonomics_file.name}"
        )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Scheme 1 cue-aligned bilingual ASS."
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--ass-output", type=Path)
    parser.add_argument("--srt-output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ergonomics-report", type=Path)
    parser.add_argument(
        "--box-style",
        choices=(*captions.BOX_STYLES, "none"),
        default="none",
    )
    parser.add_argument("--box-color")
    parser.add_argument("--box-opacity", type=float)
    parser.add_argument(
        "--caption-order",
        choices=("chinese-first", "english-first"),
        default="chinese-first",
    )
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Translate and render only the first N English cues (smoke test).",
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        build(
            args.directory,
            args.video_id,
            args.media,
            ass_path=args.ass_output,
            srt_path=args.srt_output,
            report_path=args.report,
            ergonomics_path=args.ergonomics_report,
            box_style=args.box_style,
            box_color=args.box_color,
            box_opacity=args.box_opacity,
            caption_order=args.caption_order,
            fps=args.fps,
            strict=args.strict,
            limit=args.limit,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Scheme 1 ASS failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
