#!/usr/bin/env python3
"""Build the lowest-standard local Immersive Translate bilingual subtitle pair.

The REA-observed cue model snapshots every active source cue on each
``cuechange``. This local baseline mirrors that behavior with the official
YouTube English ASR and its official auto-translated Chinese track. It does
not deduplicate rolling cues or invent a translation when the active windows
do not overlap.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Sequence

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_youtube_bilingual_srt as captions  # noqa: E402
import local_bilingual_ass  # noqa: E402
import subtitle_ergonomics  # noqa: E402
import subtitle_timing  # noqa: E402

ENGLISH = "en-orig"
CHINESE = "zh-Hans"
DEFAULT_SRT_NAME = "bilingual_immersive_lowest_Chinese-English.srt"
DEFAULT_ASS_NAME = "bilingual_immersive_lowest_Chinese-English.ass"
DEFAULT_REPORT_NAME = "IMMERSIVE_LOWEST.json"
DEFAULT_ERGONOMICS_NAME = "IMMERSIVE_LOWEST_ERGONOMICS.json"
SCHEME_NAME = "scheme_local__immersive_lowest"
SCHEME_LABEL = "scheme_低级_沉浸翻译（最低 / LOWEST 标准）"
BASELINE_ID = "immersive-translate"
BASELINE_VERSION = "1.34.4"
REA_EVIDENCE_ID = "ev_8afad77784dc3350625bc01599d2ddd910cc811cc08b8f6054508c3d7a25855f"
REA_COVERAGE = (
    "partial: 53 inventoried files, 1 analyzed source; semantic graph truncated"
)
LOWEST_FORMAT_PRIORITY = (
    "json3",
    "srv3",
    "srv2",
    "srv1",
    "ttml",
    "vtt",
    "srt",
)


def _read_source_report(folder: Path) -> dict:
    path = folder / "CAPTION_FORMATS.json"
    if not path.is_file():
        raise ValueError(
            f"{SCHEME_LABEL} requires CAPTION_FORMATS.json to verify that "
            "English is YouTube auto-generated and Chinese is its auto-translation."
        )
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {path.name}: {error}") from error
    if not isinstance(report, dict) or not isinstance(report.get("tracks"), dict):
        raise ValueError(f"{path.name} has no caption track records")
    return report


def _verify_source_kind(report: dict, language: str, expected_kind: str) -> dict:
    track = report["tracks"].get(language)
    if not isinstance(track, dict) or not track.get("present"):
        raise ValueError(
            f"{report.get('video_id', 'source')} has no verified {language} track"
        )
    actual = track.get("kind")
    if actual != expected_kind:
        raise ValueError(
            f"{language} source is {actual or 'unknown'}, expected {expected_kind}; "
            "refresh the YouTube caption set before building this scheme"
        )
    return {
        "verified": True,
        "kind": actual,
        "youtube_code": track.get("youtube_code"),
        "formats": track.get("formats", []),
        "missing_formats": track.get("missing_formats", []),
    }


def load_source_tracks(folder: Path, video_id: str, media_stem: str | None) -> tuple[dict, dict]:
    source_report = _read_source_report(folder)

    provenance = {}
    tracks = {}
    for language, expected_kind in (
        (ENGLISH, "auto-generated"),
        (CHINESE, "auto-translated"),
    ):
        provenance[language] = _verify_source_kind(
            source_report, language, expected_kind
        )
        files = local_bilingual_ass.discover_reported_formats(
            folder,
            video_id,
            language,
            media_stem,
            source_report["tracks"].get(language, {}),
        )
        if not files:
            raise ValueError(
                f"no official {language} caption formats for {video_id} in {folder}"
            )
        parsed: dict[str, list[dict]] = {}
        failures = {}
        for extension in LOWEST_FORMAT_PRIORITY:
            path = files.get(extension)
            if path is None:
                continue
            try:
                parser = captions.CAPTION_PARSERS[extension]
                cues = parser(
                    path.read_text(encoding="utf-8-sig", errors="replace")
                )
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
            raise ValueError(
                f"no readable {language} caption format: "
                + "; ".join(
                    f"{extension}: {error}"
                    for extension, error in failures.items()
                )
            )
        primary_format = next(
            extension
            for extension in LOWEST_FORMAT_PRIORITY
            if extension in parsed
        )
        tracks[language] = {
            "cues": parsed[primary_format],
            "primary_format": primary_format,
            "formats_parsed": [
                extension
                for extension in LOWEST_FORMAT_PRIORITY
                if extension in parsed
            ],
            "formats_used": [primary_format],
            "formats_found": [
                extension
                for extension in LOWEST_FORMAT_PRIORITY
                if extension in files
            ],
            "format_failures": failures,
            "format_sources": {
            extension: files[extension].name
            for extension in LOWEST_FORMAT_PRIORITY
            if extension in files
            },
        }
    return tracks, provenance


def _active_cues(cues: Sequence[dict], instant: float) -> list[dict]:
    active = [
        cue
        for cue in cues
        if float(cue["start"]) <= instant < float(cue["end"])
        and str(cue.get("text", "")).strip()
    ]
    active.sort(key=lambda cue: (float(cue["start"]), float(cue["end"])))
    return active


def build_active_snapshots(
    chinese: Sequence[dict], english: Sequence[dict]
) -> tuple[list[dict], list[dict]]:
    """Create full active-cue snapshots at every source or translation boundary."""
    for language, cues in ((CHINESE, chinese), (ENGLISH, english)):
        if not cues:
            raise ValueError(f"{language} track contains no usable cues")
        for cue in cues:
            start, end = float(cue["start"]), float(cue["end"])
            if (
                not math.isfinite(start)
                or not math.isfinite(end)
                or start < 0
                or end <= start
                or not str(cue.get("text", "")).strip()
            ):
                raise ValueError(
                    f"{language} track contains an empty or invalid source cue"
                )

    boundaries = sorted(
        {
            round(float(cue[key]), 3)
            for cue in (*chinese, *english)
            for key in ("start", "end")
        }
    )
    snapshots = []
    unpaired = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        midpoint = (start + end) / 2
        active_chinese = _active_cues(chinese, midpoint)
        active_english = _active_cues(english, midpoint)
        active_chinese = active_chinese[-1:]
        active_english = active_english[-1:]
        chinese_text = captions._single_caption_line(
            "\n".join(str(cue["text"]).strip() for cue in active_chinese)
        ).strip()
        english_text = captions._single_caption_line(
            "\n".join(str(cue["text"]).strip() for cue in active_english)
        ).strip()
        if not chinese_text and not english_text:
            continue
        if not chinese_text or not english_text:
            unpaired.append(
                {
                    "start": start,
                    "end": end,
                    "missing": "Chinese" if not chinese_text else "English",
                    "active": "English" if not english_text else "Chinese",
                }
            )
        snapshot = {
            "start": start,
            "end": end,
            "chinese": chinese_text,
            "english": english_text,
            "english_word_timings": [
                timing
                for cue in active_english
                for timing in captions._word_timings_for_text(
                    str(cue.get("text", "")), [cue]
                )
            ],
        }
        snapshots.append(snapshot)

    if not any(item["chinese"] and item["english"] for item in snapshots):
        raise ValueError(
            "the official tracks have no bilingual active interval"
        )
    return snapshots, unpaired


def render_ass(
    snapshots: Sequence[dict],
    *,
    video_duration: float | None = None,
    box_style: str = "none",
    box_color: str = "#000000",
    box_opacity: float = 0.99,
    caption_order: str = "chinese-first",
) -> str:
    """Render active-cue snapshots with the shared bilingual ASS styling."""
    bilingual_snapshots = [
        item for item in snapshots if item["chinese"] and item["english"]
    ]
    chinese = [
        {"start": item["start"], "end": item["end"], "text": item["chinese"]}
        for item in bilingual_snapshots
    ]
    english = [
        {
            "start": item["start"],
            "end": item["end"],
            "text": item["english"],
            "word_timings": item.get("english_word_timings", []),
        }
        for item in bilingual_snapshots
    ]
    content = captions.build_ass(
        chinese,
        english,
        first_font="Microsoft YaHei",
        second_font="Segoe UI",
        second_font_size=48,
        first_font_scale=1.2,
        first_color="#FFC928",
        second_color="#F2F1EC",
        english_highlight_color="#9BCBD1",
        cue_aligned=True,
        box_style=box_style,
        box_color=box_color,
        box_opacity=box_opacity,
        caption_order=caption_order,
        video_duration=video_duration,
        max_english_lines=1,
        max_chinese_lines=1,
    )
    lines = content.splitlines()
    dialogue_indexes = [
        index
        for index, line in enumerate(lines)
        if line.startswith("Dialogue: 1,")
    ]
    if len(dialogue_indexes) == len(bilingual_snapshots):
        for dialogue_index, snapshot in zip(
            dialogue_indexes, bilingual_snapshots
        ):
            fields = lines[dialogue_index].split(",", 9)
            if len(fields) != 10:
                raise ValueError("Generated lowest-standard ASS has a malformed dialogue.")
            hours, minutes, seconds = fields[1].split(":")
            whole_seconds, fraction = seconds.split(".")
            original_start = (
                int(hours) * 3600
                + int(minutes) * 60
                + int(whole_seconds)
                + int(fraction) / 100
            )
            shift = round((original_start - float(snapshot["start"])) * 100)
            fields[1] = captions.ass_timestamp(float(snapshot["start"]))
            fields[2] = captions.ass_timestamp(float(snapshot["end"]))
            fields[9] = re.sub(
                r"\\kt(\d+)",
                lambda match: f"\\kt{max(0, int(match.group(1)) + shift)}",
                fields[9],
            )
            lines[dialogue_index] = ",".join(fields)

    left = captions.CAPTION_AREA[0]
    right = captions.CAPTION_AREA[2]
    bottom = captions.CAPTION_AREA[3]
    center_x = (left + right) // 2
    baseline_y = bottom - 8
    chinese_size = 48 * 1.2
    english_size = 48
    line_gap = 10
    for snapshot in snapshots:
        chinese_text = str(snapshot["chinese"]).strip()
        english_text = str(snapshot["english"]).strip()
        if chinese_text and english_text:
            continue
        if english_text:
            language = "English"
            font_size = english_size
            text = english_text
            lower_language = (
                "Chinese" if caption_order == "english-first" else "English"
            )
            word_timings = snapshot.get("english_word_timings", [])
        else:
            language = "Chinese"
            font_size = chinese_size
            text = chinese_text
            lower_language = (
                "Chinese" if caption_order == "english-first" else "English"
            )
            word_timings = []
        lower_size = english_size if lower_language == "English" else chinese_size
        y = (
            baseline_y - line_gap - lower_size
            if language != lower_language
            else baseline_y
        )
        body = (
            f"{{\\an2\\pos({center_x},{y:g})}}"
            f"{{\\r{language}\\fs{font_size:g}}}"
        )
        if language == "English":
            body += captions.ass_karaoke_text(
                text,
                float(snapshot["end"]) - float(snapshot["start"]),
                start=float(snapshot["start"]),
                word_timings=word_timings,
            )
        else:
            body += captions.ass_escape_text(text)
        lines.append(
            f"Dialogue: 1,{captions.ass_timestamp(float(snapshot['start']))},"
            f"{captions.ass_timestamp(float(snapshot['end']))},"
            f"{language},,0,0,0,,{body}"
        )

    events = [
        line for line in lines if line.startswith("Dialogue: 1,")
    ]
    other_lines = [
        line for line in lines if not line.startswith("Dialogue: 1,")
    ]

    def timestamp_seconds(value: str) -> float:
        hours, minutes, seconds = value.split(":")
        whole_seconds, fraction = seconds.split(".")
        return (
            int(hours) * 3600
            + int(minutes) * 60
            + int(whole_seconds)
            + int(fraction) / 100
        )

    events.sort(
        key=lambda line: timestamp_seconds(line.split(",", 9)[1])
    )
    for index, line in enumerate(events):
        fields = line.split(",", 9)
        if len(fields) != 10:
            raise ValueError("Generated lowest-standard ASS has a malformed dialogue.")
        start = timestamp_seconds(fields[1])
        end = timestamp_seconds(fields[2])
        if index + 1 < len(events):
            next_start = timestamp_seconds(events[index + 1].split(",", 9)[1])
            if end > next_start:
                if next_start <= start:
                    raise ValueError(
                        "Generated lowest-standard ASS contains simultaneous "
                        "display events that cannot be separated."
                    )
                fields[2] = captions.ass_timestamp(next_start)
        if timestamp_seconds(fields[2]) <= start:
            raise ValueError(
                "Generated lowest-standard ASS contains a zero-duration event "
                "after overlap correction."
            )
        events[index] = ",".join(fields)
    return "\n".join([*other_lines, *events]) + "\n"


def build(
    folder: Path,
    video_id: str,
    media: Path | None = None,
    *,
    srt_path: Path | None = None,
    ass_path: Path | None = None,
    report_path: Path | None = None,
    ergonomics_path: Path | None = None,
    fps: float = 24.0,
    strict: bool = False,
    box_style: str = "none",
    box_color: str = "#000000",
    box_opacity: float = 0.99,
    caption_order: str = "chinese-first",
) -> dict:
    folder = Path(folder)
    tracks, provenance = load_source_tracks(
        folder, video_id, media.stem if media else None
    )
    snapshots, unpaired = build_active_snapshots(
        tracks[CHINESE]["cues"], tracks[ENGLISH]["cues"]
    )
    raw_video_duration = local_bilingual_ass.probe_duration(media)
    video_duration = local_bilingual_ass.ass_coverage_duration(
        raw_video_duration
    )
    if box_style != "none" and video_duration is None:
        raise ValueError(
            "a readable local video duration is required for full-video caption-box coverage"
        )

    srt_file = (srt_path or folder / DEFAULT_SRT_NAME).expanduser().resolve()
    ass_file = (ass_path or folder / DEFAULT_ASS_NAME).expanduser().resolve()
    report_file = (
        report_path or folder / DEFAULT_REPORT_NAME
    ).expanduser().resolve()
    ergonomics_file = (
        ergonomics_path or folder / DEFAULT_ERGONOMICS_NAME
    ).expanduser().resolve()
    for destination in (srt_file, ass_file, report_file, ergonomics_file):
        destination.parent.mkdir(parents=True, exist_ok=True)

    blocks = [
        f"{index}\n{captions.format_timestamp(event['start'])} --> "
        f"{captions.format_timestamp(event['end'])}\n"
        f"{event['chinese']}\n{event['english']}"
        for index, event in enumerate(snapshots, 1)
    ]
    srt_file.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    ass_file.write_text(
        render_ass(
            snapshots,
            video_duration=video_duration,
            box_style=box_style,
            box_color=box_color,
            box_opacity=box_opacity,
            caption_order=caption_order,
        ),
        encoding="utf-8-sig",
    )
    ergonomics = subtitle_ergonomics.analyze_subtitle(ass_file, fps=fps)
    subtitle_ergonomics.write_report(ergonomics_file, ergonomics)

    report = {
        "generated_at": subtitle_timing.utc_now(),
        "video_id": video_id,
        "scheme": SCHEME_LABEL,
        "scheme_id": SCHEME_NAME,
        "baseline": {
            "id": BASELINE_ID,
            "version": BASELINE_VERSION,
            "rea_evidence_id": REA_EVIDENCE_ID,
            "rea_coverage": REA_COVERAGE,
            "observed_model": "latest active cue per language at cuechange boundaries",
            "cross_cue_deduplication": False,
            "stale_active_cues_reemitted": False,
            "word_karaoke": True,
        },
        "sources": {
            language: {
                "youtube": provenance[language],
                "primary_format": tracks[language]["primary_format"],
                "formats_found": tracks[language]["formats_found"],
                "formats_parsed": tracks[language]["formats_parsed"],
                "formats_used": tracks[language]["formats_used"],
                "format_sources": tracks[language]["format_sources"],
                "format_failures": tracks[language]["format_failures"],
                "cue_count": len(tracks[language]["cues"]),
            }
            for language in (ENGLISH, CHINESE)
        },
        "style": {
            "caption_order": caption_order,
            "box_style": box_style,
            "box_color": box_color,
            "box_opacity": box_opacity,
            "video_duration": raw_video_duration,
            "background_end": video_duration,
        },
        "synchronization": {
            "method": "union of official cue boundaries; snapshot all active cues",
            "event_count": len(snapshots),
            "bilingual_event_count": len(snapshots) - len(unpaired),
            "events_are_bilingual": not unpaired,
            "unpaired_intervals": len(unpaired),
            "unpaired_details": unpaired,
        },
        "outputs": {
            "srt": srt_file.name,
            "ass": ass_file.name,
            "ergonomics": ergonomics_file.name,
        },
        "ergonomics_summary": ergonomics["summary"],
    }
    report_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if strict and ergonomics["summary"]["errors"]:
        raise ValueError(
            f"ergonomics found {ergonomics['summary']['errors']} errors; "
            f"see {ergonomics_file.name}"
        )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Build {SCHEME_LABEL} bilingual subtitles."
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--srt-output", type=Path)
    parser.add_argument("--ass-output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ergonomics-report", type=Path)
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument(
        "--box-style",
        choices=(*captions.BOX_STYLES, "none"),
        default="none",
    )
    parser.add_argument("--box-color", default="#000000")
    parser.add_argument("--box-opacity", type=float, default=0.99)
    parser.add_argument(
        "--caption-order",
        choices=("chinese-first", "english-first"),
        default="chinese-first",
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build(
            args.directory,
            args.video_id,
            args.media,
            srt_path=args.srt_output,
            ass_path=args.ass_output,
            report_path=args.report,
            ergonomics_path=args.ergonomics_report,
            fps=args.fps,
            strict=args.strict,
            box_style=args.box_style,
            box_color=args.box_color,
            box_opacity=args.box_opacity,
            caption_order=args.caption_order,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"{SCHEME_LABEL} failed: {error}", file=sys.stderr)
        return 1
    print(
        f"{report['scheme']}: {report['synchronization']['event_count']} "
        f"bilingual active-cue snapshots"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
