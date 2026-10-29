"""Ergonomic subtitle wrapping (Module 2, 人体工学司).

The burn regressed repeatedly because the ASS writer measured a whole cue with
optimistic widths and never inserted hard line breaks. These tests pin the
layout rules that keep every rendered line inside the 5% safe area:

* Chinese: at most 28 full-width characters per line.
* English: at most 60 characters per line.
* One line per language is the target; the two-line path is only an overflow
  guard. Closing punctuation never starts a line.
* The font shrinks before text can leave the frame, but never below the floor.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import subtitle_layout  # noqa: E402


def _load_youtube_script():
    spec = importlib.util.spec_from_file_location(
        "youtube_srt_layout", SCRIPTS / "download_youtube_bilingual_srt.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_chinese_lines_never_exceed_twenty_eight_characters():
    text = "总统在密歇根州的集会上谈到了经济、移民和即将到来的选举"

    lines = subtitle_layout.wrap_caption(text, "zh-Hans")

    assert "".join(lines) == text
    assert all(len(line) <= subtitle_layout.ZH_MAX_CHARS for line in lines)
    assert all(line for line in lines)


def test_chinese_never_leaves_closing_punctuation_at_the_start_of_a_line():
    text = "我们今晚要说的事情很多，包括经济、边境和能源价格，以及接下来几周的安排。"

    lines = subtitle_layout.wrap_caption(text, "zh-Hans")

    assert not any(line[0] in subtitle_layout.NO_LINE_START for line in lines)


def test_short_chinese_stays_on_one_line():
    assert subtitle_layout.wrap_caption("谢谢你", "zh-Hans") == ["谢谢你"]


def test_two_line_chinese_is_balanced_without_dropping_text():
    text = "我们今晚要说的事情很多，包括经济、边境和能源价格，以及接下来几周的安排。"

    lines = subtitle_layout.wrap_caption(text, "zh-Hans")

    assert len(lines) == 2
    assert "".join(lines) == text
    assert abs(len(lines[0]) - len(lines[1])) <= 6


def test_english_wraps_at_word_boundaries_within_sixty_characters():
    text = (
        "The President is speaking tonight about the economy, the border, "
        "and the election that is only a few weeks away."
    )

    lines = subtitle_layout.wrap_caption(text, "en")

    assert all(len(line) <= subtitle_layout.EN_MAX_CHARS for line in lines)
    assert " ".join(lines) == text
    assert " ".join(lines).split() == text.split()


def test_english_two_line_split_prefers_balanced_lines():
    text = "We are going to keep talking about the border and the economy tonight"

    lines = subtitle_layout.wrap_caption(text, "en")

    assert len(lines) == 2
    assert abs(len(lines[0]) - len(lines[1])) <= 4


def test_overlong_single_word_is_split_instead_of_overflowing():
    lines = subtitle_layout.wrap_caption("A" * 70, "en")

    assert all(len(line) <= subtitle_layout.EN_MAX_CHARS for line in lines)
    assert "".join(lines) == "A" * 70


def test_long_text_returns_extra_lines_instead_of_silently_dropping_words():
    text = "word " * 40

    lines = subtitle_layout.wrap_caption(text.strip(), "en", max_lines=2)

    assert len(lines) > 2
    assert " ".join(lines).split() == text.split()


def test_line_units_measure_cjk_as_full_width_and_latin_as_conservative():
    assert subtitle_layout.line_units("你好") == 2.0
    assert subtitle_layout.line_units("Hi") == 2 * subtitle_layout.LATIN_EM
    assert subtitle_layout.LATIN_EM > 0.5


def test_fit_font_size_shrinks_only_when_the_widest_line_overflows():
    size = subtitle_layout.fit_font_size(["短句"], 57.6, 1728)
    assert size == 57.6

    small = subtitle_layout.fit_font_size(["这是一行非常宽的中文字幕"], 57.6, 400)
    assert small < 57.6
    assert small >= 28.0


def test_fit_font_size_never_goes_below_the_legibility_floor():
    size = subtitle_layout.fit_font_size(["这是一行特别特别宽的中文字幕"], 57.6, 5)
    assert size == 28.0


def test_generated_ass_keeps_long_chinese_on_one_line_per_event():
    youtube_srt = _load_youtube_script()
    text = "我们今晚要说的事情很多，包括经济、边境和能源价格，以及接下来几周的安排。"
    cues = youtube_srt.parse_srt(f"1\n00:00:01,000 --> 00:00:04,000\n{text}\n\n")

    result = youtube_srt.build_ass(cues, cues)

    assert "WrapStyle: 0" in result
    dialogues = [line for line in result.splitlines() if ",Chinese," in line]
    assert dialogues
    rendered: list[str] = []
    for dialogue in dialogues:
        body = re.sub(r"\{[^}]*\}", "", dialogue.split(",,0,0,0,,", 1)[1])
        lines = [line for line in body.split(r"\N") if line]
        assert len(lines) == 1
        assert len(lines[0]) <= subtitle_layout.ZH_MAX_CHARS
        rendered.append(lines[0])
    assert "".join(rendered) == text


def test_generated_ass_anchors_text_above_the_bottom_margin():
    youtube_srt = _load_youtube_script()
    cues = youtube_srt.parse_srt("1\n00:00:01,000 --> 00:00:02,000\n你好\n\n")

    result = youtube_srt.build_ass(cues, cues)

    assert r"{\an2\pos(960,1000)}" in result
    assert r"{\an1" not in result and r"{\an5" not in result
