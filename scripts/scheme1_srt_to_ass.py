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


def convert_srt_to_ass(
    source: Path,
    destination: Path,
    *,
    box_style: str | None = None,
    box_color: str | None = None,
    box_opacity: float | None = None,
    caption_order: str | None = None,
) -> Path:
    chinese, english = split_bilingual_tracks(source)
    style = dict(SCHEME1_ASS_STYLE)
    if box_style is not None:
        style["box_style"] = box_style
    if box_color is not None:
        style["box_color"] = box_color
    if box_opacity is not None:
        style["box_opacity"] = box_opacity
    if caption_order is not None:
        style["caption_order"] = caption_order
    content = captions.build_ass(
        chinese, english, cue_aligned=True, **style
    )
    dialogues = [
        line for line in content.splitlines() if line.startswith("Dialogue: 1,")
    ]
    if len(dialogues) != len(english):
        raise ValueError("Generated ASS does not preserve every Scheme 1 cue.")
    for cue, dialogue in zip(english, dialogues):
        fields = dialogue.split(",", 3)
        if (
            fields[1] != captions.ass_timestamp(cue["start"])
            or fields[2] != captions.ass_timestamp(cue["end"])
            or dialogue.split(",", 9)[-1].count(r"\N") != 2
        ):
            raise ValueError(
                f"Generated ASS changed cue timing or wrapped a language line at "
                f"{cue['start']:.3f}s."
            )
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
