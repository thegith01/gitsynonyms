#!/usr/bin/env python3
"""Convert a Scheme 1 bilingual SRT to the styled ASS subtitle format."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_youtube_bilingual_srt as captions  # noqa: E402

SCHEME1_ASS_STYLE = {
    "first_font": "Microsoft YaHei",
    "second_font": "Segoe UI",
    "second_font_size": 48,
    "first_font_scale": 1.2,
    "first_color": "#FFC928",
    "second_color": "#F2F1EC",
    "english_highlight_color": "#9BCBD1",
    "box_style": "none",
    "max_english_lines": 1,
    "max_chinese_lines": 1,
}


def split_bilingual_tracks(source: Path) -> tuple[list[dict], list[dict]]:
    """Validate Scheme 1 cue shape and split each Chinese/English pair."""
    cues = captions.parse_srt(source.read_text(encoding="utf-8-sig"))
    chinese: list[dict] = []
    english: list[dict] = []
    previous_start = -1.0
    previous_end = -1.0

    for cue in cues:
        start, end = cue["start"], cue["end"]
        if start < previous_start or start < previous_end:
            raise ValueError(
                f"Scheme 1 SRT cues must be ordered and non-overlapping near {start:.3f}s."
            )
        lines = [line.strip() for line in cue["text"].splitlines() if line.strip()]
        if len(lines) == 1:
            plain = captions.html.unescape(re.sub(r"<[^>]*>", "", lines[0]))
            if captions.CJK.search(plain):
                raise ValueError(
                    f"Scheme 1 cue at {start:.3f}s has Chinese text without an "
                    "English source cue."
                )
            english.append({**cue, "text": lines[0], "unpaired": True})
            previous_start, previous_end = start, end
            continue
        if len(lines) != 2:
            raise ValueError(
                f"Scheme 1 cue at {start:.3f}s must contain exactly two non-empty language lines."
            )

        by_language: dict[str, list[str]] = {"zh": [], "en": []}
        for line in lines:
            plain = captions.html.unescape(re.sub(r"<[^>]*>", "", line))
            language = "zh" if captions.CJK.search(plain) else "en"
            by_language[language].append(line)
        if any(len(by_language[language]) != 1 for language in ("zh", "en")):
            raise ValueError(
                f"Scheme 1 cue at {start:.3f}s must contain one Chinese and one English line."
            )

        chinese_text = by_language["zh"][0]
        english_text = by_language["en"][0]
        punctuation_only = all(
            character in captions.subtitle_layout.NO_LINE_START
            for character in chinese_text
        )
        if punctuation_only:
            if not chinese or abs(chinese[-1]["end"] - start) > 0.001:
                raise ValueError(
                    f"Closing punctuation at {start:.3f}s has no preceding bilingual cue."
                )
            chinese[-1]["text"] += chinese_text
            chinese[-1]["end"] = end
            english[-1]["text"] += " " + english_text
            english[-1]["end"] = end
        else:
            chinese.append({**cue, "text": chinese_text})
            english.append({**cue, "text": english_text})
        previous_start, previous_end = start, end

    return chinese, english


def ass_timestamp_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    whole_seconds, fraction = seconds.split(".")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(whole_seconds)
        + int(fraction) / 100
    )


def convert_srt_to_ass(
    source: Path,
    destination: Path,
    *,
    english_word_timings: list[list[dict | None]] | None = None,
    video_duration: float | None = None,
    box_style: str | None = None,
    box_color: str | None = None,
    box_opacity: float | None = None,
    caption_order: str | None = None,
) -> Path:
    chinese, english = split_bilingual_tracks(source)
    if english_word_timings is not None:
        if len(english_word_timings) != len(english):
            raise ValueError(
                "Scheme 1 word timings do not match the bilingual SRT cue count."
            )
        for cue, timings in zip(english, english_word_timings):
            cue["word_timings"] = timings
    style = dict(SCHEME1_ASS_STYLE)
    if box_style is not None:
        style["box_style"] = box_style
    if box_color is not None:
        style["box_color"] = box_color
    if box_opacity is not None:
        style["box_opacity"] = box_opacity
    if caption_order is not None:
        style["caption_order"] = caption_order
    if video_duration is not None:
        style["video_duration"] = video_duration
    unpaired_english = [cue for cue in english if cue.get("unpaired")]
    bilingual_english = [
        cue for cue in english if not cue.get("unpaired")
    ]
    if not chinese or not bilingual_english:
        raise ValueError(
            "Scheme 1 needs at least one bilingual cue to render the styled timeline."
        )
    content = captions.build_ass(
        chinese, bilingual_english, cue_aligned=True, **style
    )
    lines = content.splitlines()
    dialogues = [line for line in lines if line.startswith("Dialogue: 1,")]
    cue_events: list[list[tuple[int, list[str], float, float]]] = [
        [] for _ in bilingual_english
    ]
    for line_index, line in enumerate(lines):
        if not line.startswith("Dialogue: 1,"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            raise ValueError("Generated ASS contains a malformed Scheme 1 event.")
        actual_start = ass_timestamp_seconds(fields[1])
        actual_end = ass_timestamp_seconds(fields[2])
        matching_cues = [
            index
            for index, cue in enumerate(bilingual_english)
            if cue["start"] - 0.02 <= actual_start < cue["end"] + 0.02
        ]
        if not matching_cues:
            raise ValueError(
                f"Generated ASS event at {actual_start:.3f}s does not map to a "
                "Scheme 1 SRT cue."
            )
        cue_index = max(
                matching_cues, key=lambda index: bilingual_english[index]["start"]
        )
        cue_events[cue_index].append(
            (line_index, fields, actual_start, actual_end)
        )

    if not dialogues or any(not events for events in cue_events):
        raise ValueError("Generated ASS does not preserve every Scheme 1 cue.")

    for cue, events in zip(bilingual_english, cue_events):
        events.sort(key=lambda event: event[2])
        for event_index, (line_index, fields, actual_start, actual_end) in enumerate(
            events
        ):
            if len(events) == 1:
                target_start = cue["start"]
                target_end = cue["end"]
            else:
                if (
                    actual_start < cue["start"] - 0.02
                    or actual_end > cue["end"] + 0.02
                ):
                    raise ValueError(
                        f"Split ASS events exceed the Scheme 1 cue at "
                        f"{cue['start']:.3f}s."
                    )
                target_start = max(actual_start, cue["start"])
                target_end = min(actual_end, cue["end"])
                if event_index + 1 < len(events):
                    target_end = min(target_end, events[event_index + 1][2])
                if target_end <= target_start:
                    raise ValueError(
                        f"Split ASS event has no positive duration at "
                        f"{cue['start']:.3f}s."
                    )
            shift = round((actual_start - target_start) * 100)
            fields[1] = captions.ass_timestamp(target_start)
            fields[2] = captions.ass_timestamp(target_end)
            fields[9] = re.sub(
                r"\\kt(\d+)",
                lambda match: f"\\kt{max(0, int(match.group(1)) + shift)}",
                fields[9],
            )
            if fields[9].count(r"\N") != 2:
                raise ValueError(
                    f"Generated ASS changed cue timing or wrapped a language "
                    f"line at {cue['start']:.3f}s."
                )
            lines[line_index] = ",".join(fields)

    left = captions.CAPTION_AREA[0]
    right = captions.CAPTION_AREA[2]
    bottom = captions.CAPTION_AREA[3]
    center_x = (left + right) // 2
    baseline_y = bottom - 8
    caption_order = str(style.get("caption_order", "chinese-first"))
    english_size = int(style.get("second_font_size", 48))
    chinese_size = english_size * float(style.get("first_font_scale", 1.2))
    line_gap = int(style.get("line_gap", 10))
    lower_language = (
        "English" if caption_order == "chinese-first" else "Chinese"
    )
    for cue in unpaired_english:
        font_size = english_size
        y = (
            baseline_y
            if lower_language == "English"
            else baseline_y - line_gap - english_size
        )
        body = (
            f"{{\\an2\\pos({center_x},{y:g})}}"
            f"{{\\rEnglish\\fs{font_size:g}}}"
            + captions.ass_karaoke_text(
                cue["text"],
                float(cue["end"]) - float(cue["start"]),
                start=float(cue["start"]),
                word_timings=cue.get("word_timings", []),
            )
        )
        lines.append(
            f"Dialogue: 1,{captions.ass_timestamp(cue['start'])},"
            f"{captions.ass_timestamp(cue['end'])},English,,0,0,0,,{body}"
        )

    dialogue_lines = [
        line for line in lines if line.startswith("Dialogue: 1,")
    ]
    non_dialogue_lines = [
        line for line in lines if not line.startswith("Dialogue: 1,")
    ]
    dialogue_lines.sort(
        key=lambda line: ass_timestamp_seconds(line.split(",", 9)[1])
    )
    lines = [*non_dialogue_lines, *dialogue_lines]
    content = "\n".join(lines) + "\n"
    captions.write_ass(destination, content)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Scheme 1 bilingual SRT to styled ASS."
    )
    parser.add_argument("srt", type=Path, help="Scheme 1 bilingual SRT input.")
    parser.add_argument(
        "--output",
        type=Path,
        help="ASS output path (default: beside the SRT with an .ass extension).",
    )
    args = parser.parse_args(argv)
    destination = args.output or args.srt.with_suffix(".ass")
    try:
        result = convert_srt_to_ass(args.srt, destination)
    except (OSError, ValueError) as error:
        print(f"Scheme 1 SRT-to-ASS failed: {error}", file=sys.stderr)
        return 1
    print(f"Generated {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
