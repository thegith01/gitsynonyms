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
    # A possessive apostrophe sits on the cue text but not on the word timing
    # ("parents'" versus "parents"); trimming both sides keeps the comparison
    # about speech, not punctuation.
    return [
        value.casefold()
        for value in (match.strip("'") for match in WORD.findall(text))
        if value
    ]


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
    unexplained: list[list[str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "insert"):
            continue
        if tag != "delete":
            # A replace means the engine changed a word; that is never allowed.
            unexplained.append([f"{source[i1:i2]} -> {displayed[j1:j2]}"])
            continue
        deleted = source[i1:i2]
        # A rolling cue repeats the previous cue's tail, so the engine keeps
        # one copy. difflib may align that copy to either occurrence, so a
        # deletion is legal when the phrase occurs at least twice in the source
        # and at least once in the rendered stream.
        occurrences = sum(
            1
            for index in range(len(source) - len(deleted) + 1)
            if source[index : index + len(deleted)] == deleted
        )
        rendered_once = any(
            displayed[index : index + len(deleted)] == deleted
            for index in range(len(displayed) - len(deleted) + 1)
        )
        stutter = all(value in subtitle_timeline.DEDUPE_STOPWORDS for value in deleted)
        if not (stutter or (occurrences >= 2 and rendered_once)):
            unexplained.append(deleted)
    return unexplained


def _vtt_clock(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:06.3f}"


def rolling_vtt(count: int, window: int = 3) -> tuple[list[dict], list[str]]:
    """Cues that re-show the previous ``window`` words before adding a new one."""
    sentence = [f"w{index}" for index in range(count)]
    blocks = []
    for index in range(count - 1):
        start = 1.0 + index
        end = start + 2.0
        text = " ".join(sentence[max(0, index + 1 - window) : index + 2])
        blocks.append(f"{_vtt_clock(start)} --> {_vtt_clock(end)}\n{text}\n")
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


def test_bilingual_sentence_events_keep_sentence_starts_and_both_languages():
    english = [
        {"start": 1.0, "end": 2.0, "text": "We have news,"},
        {"start": 2.0, "end": 3.0, "text": "and it changes everything."},
        {"start": 4.0, "end": 5.0, "text": "They will act."},
    ]
    chinese = [
        {"start": 1.1, "end": 2.1, "text": "有个消息，"},
        {"start": 2.1, "end": 3.1, "text": "这改变了一切。"},
        {"start": 4.1, "end": 5.1, "text": "他们会行动。"},
    ]

    events = subtitle_timeline.build_bilingual_sentence_events(
        english, other_cues=chinese
    )

    assert len(events) == 2
    assert all(
        english_tokens and chinese_tokens
        for english_tokens, chinese_tokens in events
    )
    assert " ".join(token.text for token in events[0][0]) == (
        "We have news, and it changes everything."
    )
    assert "".join(token.text for token in events[0][1]) == "有个消息，这改变了一切。"
    assert events[0][0][0].start == 1.0
    assert events[0][0][-1].text.endswith(".")
    assert events[0][1][-1].text.endswith("。")
    assert events[1][0][0].text == "They"


def test_bilingual_sentence_events_merge_adjacent_translation_sentences():
    english = [{"start": 1.0, "end": 3.0, "text": "Mr. President, welcome."}]
    chinese = [
        {"start": 1.0, "end": 2.0, "text": "总统先生。"},
        {"start": 2.0, "end": 3.0, "text": "欢迎。"},
    ]

    events = subtitle_timeline.build_bilingual_sentence_events(
        english, other_cues=chinese
    )

    assert len(events) == 1
    english_tokens, chinese_tokens = events[0]
    assert english_tokens and chinese_tokens
    assert " ".join(token.text for token in english_tokens) == "Mr. President, welcome."
    assert "".join(token.text for token in chinese_tokens) == "总统先生。欢迎。"


def test_bilingual_sentence_events_reject_a_missing_translation_track():
    with pytest.raises(ValueError, match="requires timed English and Chinese"):
        subtitle_timeline.build_bilingual_sentence_events(
            [{"start": 1.0, "end": 2.0, "text": "No translation."}]
        )


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


def test_real_three_hour_events_begin_on_source_word_boundaries(archived_events):
    import bisect

    cues, events = archived_events
    spans = sorted(
        (float(timing["start"]), float(timing["end"]))
        for cue in cues
        for timing in cue.get("word_timings") or []
    )
    span_starts = [start for start, _ in spans]
    starts = {round(start, 2) for start, _ in spans}
    cue_starts = {round(float(cue["start"]), 2) for cue in cues}

    anchored = 0
    for english, _ in events:
        start = english[0].start
        if english[0].exact:
            if round(start, 2) in starts:
                anchored += 1
                continue
            # A word split out of a multi-word timing entry ("Donald J.")
            # starts inside that entry rather than on its first millisecond.
            index = bisect.bisect_right(span_starts, start) - 1
            neighbours = [spans[i] for i in (index, index + 1) if 0 <= i < len(spans)]
            assert any(low <= start <= high for low, high in neighbours), (
                english[0].text,
                start,
            )
            continue
        # A cue whose text and word timings disagree ("1,000%" versus the
        # timings "1" + "000") has no exact token. Its interpolated word still
        # starts on a source cue boundary, not on an invented clock position.
        assert round(start, 2) in cue_starts, (english[0].text, start)
    assert len(events) > 2_000
    assert anchored >= len(events) * 0.95


def test_ass_dialogues_never_overlap(archived_events):
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
    for line in dialogues:
        _, start, end = line.split(",", 3)[:3]
        start_seconds = _ass_seconds(start)
        end_seconds = _ass_seconds(end)
        assert start_seconds >= previous_end - 0.001, (start, previous_end)
        assert end_seconds > start_seconds
        text = re.sub(r"\{[^}]*\}", "", line.split(",", 9)[-1]).replace(r"\N", " ")
        assert text.strip()
        previous_end = end_seconds
    # Identical adjacent text is not a defect on its own: the rally chants
    # "We love Trump." three times in a row. Re-emission is already excluded by
    # the every-word-once and non-overlap invariants above.


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
        (round(event_start + int(kt) / 100, 2), word.strip())
        for kt, word in re.findall(r"\{\\kt(\d+)\\k\d+\}([^\\{]+)", line)
    ]

    assert (1.2, "Hello") in offsets
    assert offsets[-1][1] == "world!"
    assert offsets[-1][0] == 1.8


def _ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


C7_ARCHIVE = (
    ROOT
    / "output"
    / "2026-10-28_president-trump-gaggles-with-press-upon-arrival-at-joint-base-andrews-oct-28-2026_C7OR400n_mc"
)


@pytest.fixture(scope="module")
def c7_events():
    if not C7_ARCHIVE.exists():
        pytest.skip("archived C7 bilingual caption pair is not available")
    english = youtube_srt.parse_json3(
        (C7_ARCHIVE / "C7OR400n_mc.en.en-orig.json3").read_text(encoding="utf-8")
    )
    chinese = youtube_srt.parse_srt(
        (C7_ARCHIVE / "C7OR400n_mc.zh-Hans.srt").read_text(encoding="utf-8")
    )
    return subtitle_timeline.build_display_events(english, other_cues=chinese)


def test_cue_alignment_keeps_one_line_in_each_language(c7_events):
    assert len(c7_events) > 190
    for english, chinese in c7_events:
        assert english and chinese
        english_text = " ".join(token.text for token in english)
        chinese_text = "".join(token.text for token in chinese)
        assert ">>" not in english_text and ">>" not in chinese_text
        assert len(subtitle_layout.wrap_caption(english_text, "en")) == 1
        assert len(subtitle_layout.wrap_caption(chinese_text, "zh-Hans")) == 1
        assert len(english_text) <= subtitle_layout.EN_MAX_CHARS
        assert len(chinese_text) <= subtitle_layout.ZH_MAX_CHARS


def test_the_31_second_mark_has_both_languages(c7_events):
    active = [
        (english, chinese)
        for english, chinese in c7_events
        if min(token.start for token in [*english, *chinese])
        <= 31.0
        <= max(token.end for token in [*english, *chinese])
    ]

    assert active
    assert all(english and chinese for english, chinese in active)
    assert any(
        "exciting" in " ".join(token.text for token in english)
        for english, _ in active
    )
