"""Algorithmic contract for the subtitle timeline engine (Module 2).

The burn regressed because caption handling was tuned fixture by fixture. This
module pins the *global* invariants instead, so any change to the engine is
judged on the whole 3-hour corpus, not on one hand-written example:

* a rolling caption window never renders a word twice and never loses one;
* the rendered token stream is a subsequence of the source word stream, so no
  invented or reordered text can reach the screen;
* only two deletions are legal: a closed-class ASR stutter (``I I``) and the
  repeated prefix of a rolling window (which is already on screen);
* display events are disjoint and monotonic, and every event fits two lines per
  language at the configured character budget;
* karaoke starts are the source's own word timings, not an even spread.
"""

from __future__ import annotations

import difflib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import subtitle_layout  # noqa: E402
import subtitle_timeline  # noqa: E402

ARCHIVE = (
    ROOT
    / "output"
    / "2026-10-25_LIVE-President-Trump-rallies-in-Michigan-ahead-of-state-s-November-Election_9aPyO1jfDGM"
)


def _load_youtube_script():
    spec = importlib.util.spec_from_file_location(
        "youtube_srt_timeline", SCRIPTS / "download_youtube_bilingual_srt.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


youtube_srt = _load_youtube_script()

WORD = re.compile(r"[A-Za-z0-9']+")


def words(text: str) -> list[str]:
    return [value.casefold() for value in WORD.findall(text)]


def merge_digits(values: list[str]) -> list[str]:
    """``200 000`` in two caption segments is one number on screen."""
    merged: list[str] = []
    for value in values:
        if value.isdigit() and merged and merged[-1].isdigit():
            merged[-1] += value
        else:
            merged.append(value)
    return merged


def source_words(cues: list[dict]) -> list[str]:
    values: list[str] = []
    for cue in cues:
        for timing in cue.get("word_timings") or []:
            values.extend(words(str(timing.get("text", ""))))
        if not cue.get("word_timings"):
            values.extend(words(str(cue.get("text", ""))))
    return merge_digits(values)


def rendered_words(events: list[tuple[list, list]]) -> list[str]:
    values: list[str] = []
    for english, _ in events:
        for token in english:
            values.extend(words(token.text))
    return merge_digits(values)


def unexplained_deletions(source: list[str], displayed: list[str]) -> list[list[str]]:
    """Deletions that are neither an ASR stutter nor a rolling repeat."""
    matcher = difflib.SequenceMatcher(None, source, displayed, autojunk=False)
    rendered: list[str] = []
    unexplained: list[list[str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rendered.extend(displayed[j1:j2])
            continue
        if tag == "insert":
            unexplained.append(displayed[j1:j2])
            continue
        if tag != "delete":
            # A replace means the engine changed a word; that is never allowed.
            unexplained.append([f"{source[i1:i2]} -> {displayed[j1:j2]}"])
            continue
        deleted = source[i1:i2]
        window = rendered[-40:]
        repeated = any(
            window[index : index + len(deleted)] == deleted
            for index in range(len(window))
        )
        stutter = all(value in subtitle_timeline.DEDUPE_STOPWORDS for value in deleted)
        if not (repeated or stutter):
            unexplained.append(deleted)
    return unexplained


def rolling_vtt(count: int, window: int = 3) -> tuple[list[dict], list[str]]:
    """Cues that re-show the previous ``window`` words before adding a new one."""
    sentence = [f"w{index}" for index in range(count)]
    blocks = []
    for index in range(count - 1):
        start = 1.0 + index
        end = start + 2.0
        text = " ".join(sentence[max(0, index + 1 - window) : index + 2])
        blocks.append(f"00:00:{start:06.3f} --> 00:00:{end:06.3f}\n{text}\n")
    return youtube_srt.parse_vtt("WEBVTT\n\n" + "\n".join(blocks)), sentence


def test_rolling_window_renders_every_word_exactly_once():
    cues, sentence = rolling_vtt(40)

    events = subtitle_timeline.build_display_events(cues)

    assert rendered_words(events) == sentence
    for english, _ in events:
        text = " ".join(token.text for token in english)
        assert not re.search(r"\b(\w+)\s+\1\b", text)


def test_events_are_disjoint_and_monotonic_on_rolling_cues():
    cues, _ = rolling_vtt(60)

    events = subtitle_timeline.build_display_events(cues)

    previous_end = 0.0
    for english, _ in events:
        assert english
        start = english[0].start
        end = max(token.end for token in english)
        assert start >= previous_end - 0.001, (start, previous_end)
        assert end > start
        previous_end = end


def test_asr_stutter_is_collapsed_but_real_repetition_survives():
    cues = [
        {"start": 1.0, "end": 2.0, "text": "I I came in"},
        {"start": 2.2, "end": 4.0, "text": "no no we will not"},
    ]

    events = subtitle_timeline.build_display_events(cues)

    assert rendered_words(events) == words("I came in no no we will not")


def test_latin_fragments_in_translation_stay_on_the_chinese_line():
    english = [
        {"start": 1.0, "end": 2.0, "text": "one two"},
        {"start": 2.0, "end": 3.0, "text": "three four"},
    ]
    translations = [
        {"start": 1.0, "end": 2.0, "text": "一 二"},
        {"start": 2.0, "end": 3.0, "text": "Mcronone 2019 三 四"},
    ]

    events = subtitle_timeline.build_display_events(
        english, other_cues=translations
    )

    # The translation's Latin fragments must not become the English clock and
    # push the real English words to the end of the timeline.
    assert rendered_words(events) == words("one two three four")
    assert events[0][0][0].start == 1.0
    assert events[-1][0][-1].end <= 3.0
    chinese_text = "".join(
        token.text for _, chinese in events for token in chinese
    )
    assert "Mcronone" in chinese_text
    assert "2019" in chinese_text


def test_chinese_master_falls_back_to_the_english_translation_clock():
    chinese = [
        {"start": 1.0, "end": 2.0, "text": "一 二"},
        {"start": 2.0, "end": 3.0, "text": "三 四"},
    ]
    english = [
        {"start": 1.0, "end": 2.0, "text": "one two"},
        {"start": 2.0, "end": 3.0, "text": "three four"},
    ]

    events = subtitle_timeline.build_display_events(
        chinese, other_cues=english
    )

    assert rendered_words(events) == words("one two three four")
    assert events[0][0][0].start == 1.0
    assert "".join(token.text for _, chinese in events for token in chinese) == "一二三四"


def test_chinese_source_group_is_never_split_across_events():
    translations = [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "女士们、先生们，美国总统唐纳德·特朗普",
        },
        {"start": 3.0, "end": 5.0, "text": "第一夫人梅拉尼娅·特朗普"},
    ]
    english = [
        {"start": 1.0, "end": 3.0, "text": "Ladies and gentlemen, the President"},
        {"start": 3.0, "end": 5.0, "text": "First Lady Melania Trump."},
    ]

    events = subtitle_timeline.build_display_events(english, other_cues=translations)

    seen: dict[int, int] = {}
    for index, (_, chinese) in enumerate(events):
        for token in chinese:
            assert seen.setdefault(token.group, index) == index


@pytest.fixture(scope="module")
def archived_events():
    if not ARCHIVE.exists():
        pytest.skip("archived 3-hour caption corpus is not available")
    cues = youtube_srt.parse_json3(
        (ARCHIVE / f"{ARCHIVE.name.rsplit('_', 1)[-1]}.en.en-orig.json3").read_text(
            encoding="utf-8"
        )
    )
    return cues, subtitle_timeline.build_display_events(cues)


def test_real_three_hour_track_has_no_invented_or_lost_speech(archived_events):
    cues, events = archived_events

    source = source_words(cues)
    displayed = rendered_words(events)

    assert len(source) > 20_000
    assert len(displayed) >= len(source) * 0.99
    assert unexplained_deletions(source, displayed) == []


def test_real_three_hour_events_are_disjoint_and_fit_two_lines(archived_events):
    _, events = archived_events

    previous_end = 0.0
    for english, chinese in events:
        assert english
        start = english[0].start
        end = max(token.end for token in english)
        assert start >= previous_end - 0.001, (start, previous_end)
        assert end > start
        previous_end = end

        english_text = " ".join(token.text for token in english)
        lines = subtitle_layout.wrap_caption(english_text, "en", hard_limit=True)
        assert len(lines) <= 2
        assert all(len(line) <= subtitle_layout.EN_MAX_CHARS for line in lines)

        chinese_text = "".join(token.text for token in chinese)
        if chinese_text:
            lines = subtitle_layout.wrap_caption(chinese_text, "zh-Hans", hard_limit=True)
            assert len(lines) <= 2
            assert all(len(line) <= subtitle_layout.ZH_MAX_CHARS for line in lines)


def test_real_three_hour_word_starts_are_the_source_timings(archived_events):
    cues, events = archived_events
    starts = {
        round(float(timing["start"]), 2)
        for cue in cues
        for timing in cue.get("word_timings") or []
    }

    checked = 0
    for english, _ in events:
        for token in english:
            if not token.exact:
                continue
            assert round(token.start, 2) in starts, (token.text, token.start)
            checked += 1
    assert checked > 18_000


def test_ass_dialogues_never_overlap_and_never_repeat(archived_events):
    cues, _ = archived_events
    chinese = youtube_srt.parse_srt(
        "1\n00:00:01,000 --> 00:00:02,000\n你好\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n世界\n\n"
    )

    content = youtube_srt.build_ass(chinese, cues)

    dialogues = [
        line for line in content.splitlines() if line.startswith("Dialogue: 1,")
    ]
    previous_end = 0.0
    previous_text = ""
    for line in dialogues:
        _, start, end = line.split(",", 3)[:3]
        start_seconds = _ass_seconds(start)
        end_seconds = _ass_seconds(end)
        assert start_seconds >= previous_end - 0.001, (start, previous_end)
        assert end_seconds > start_seconds
        previous_end = end_seconds
        text = re.sub(r"\{[^}]*\}", "", line.split(",", 9)[-1]).replace(r"\N", " ")
        assert text.strip()
        assert text != previous_text
        previous_text = text


def test_karaoke_absolute_starts_follow_vtt_inline_timestamps():
    english = youtube_srt.parse_vtt(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "<00:00:01.200>Hello <00:00:01.800>world!\n"
    )
    chinese = youtube_srt.parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n你好\n")

    content = youtube_srt.build_ass(chinese, english)
    line = next(
        entry for entry in content.splitlines() if entry.startswith("Dialogue: 1,")
    )

    event_start = _ass_seconds(line.split(",", 3)[1])
    offsets = [
        (event_start + int(kt) / 100, word)
        for kt, word in re.findall(r"\{\\kt(\d+)\\k\d+\}([^\\{]+)", line)
    ]

    assert ("Hello", 1.2) in [(word, round(start, 2)) for start, word in offsets]
    assert offsets[-1][1].strip() == "world!"
    assert round(offsets[-1][0], 2) == 1.8


def _ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
