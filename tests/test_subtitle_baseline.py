"""Executable subtitle quality floor: scheme_local__immersive_lowest /
Immersive Translate v1.34.4.

``benchmarks/immersive-translate/baseline.json`` records what the shipped
extension actually does. This module turns that record into obligations: every
``requirements[].test`` name must exist here, and every test must hold on the
real 3-hour corpus or on synthetic rolling captions.

The baseline is a *floor*, not a target. Several assertions below are stricter
than the extension can satisfy (word-level karaoke, cross-cue de-duplication,
a fixed typographic budget); that is deliberate, because a burned ASS cannot
delegate layout or timing to a browser at playback time.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import subtitle_layout  # noqa: E402
import subtitle_timeline  # noqa: E402

BASELINE_PATH = ROOT / "benchmarks" / "immersive-translate" / "baseline.json"
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

ARCHIVE = (
    ROOT
    / "output"
    / "2026-10-25_LIVE-President-Trump-rallies-in-Michigan-ahead-of-state-s-November-Election_9aPyO1jfDGM"
)

WORD = re.compile(r"[A-Za-z0-9']+")


def _load_youtube_script():
    spec = importlib.util.spec_from_file_location(
        "youtube_srt_baseline", SCRIPTS / "download_youtube_bilingual_srt.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


youtube_srt = _load_youtube_script()


def words(text: str) -> list[str]:
    # Cue text may carry a possessive apostrophe that the word timing does not.
    return [
        value.casefold()
        for value in (match.strip("'") for match in WORD.findall(text))
        if value
    ]


def merge_digits(values: list[str]) -> list[str]:
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
        timings = cue.get("word_timings") or []
        if timings:
            for timing in timings:
                values.extend(words(str(timing.get("text", ""))))
        else:
            values.extend(words(str(cue.get("text", ""))))
    return merge_digits(values)


def rendered_words(events: list[tuple[list, list]]) -> list[str]:
    values: list[str] = []
    for english, _ in events:
        for token in english:
            values.extend(words(token.text))
    return merge_digits(values)


def unexplained_deletions(source: list[str], displayed: list[str]) -> list[list[str]]:
    matcher = difflib.SequenceMatcher(None, source, displayed, autojunk=False)
    unexplained: list[list[str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "insert"):
            continue
        if tag != "delete":
            unexplained.append([f"{source[i1:i2]} -> {displayed[j1:j2]}"])
            continue
        deleted = source[i1:i2]
        # Rolling cues repeat the previous tail; one copy is rendered and the
        # other is legally dropped. difflib may align to either occurrence.
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


def rolling_vtt(count: int, window: int = 3) -> tuple[list[dict], list[str]]:
    sentence = [f"w{index}" for index in range(count)]
    blocks = []
    for index in range(count - 1):
        start = 1.0 + index
        end = start + 2.0
        text = " ".join(sentence[max(0, index + 1 - window) : index + 2])
        blocks.append(f"00:00:{start:06.3f} --> 00:00:{end:06.3f}\n{text}\n")
    return youtube_srt.parse_vtt("WEBVTT\n\n" + "\n".join(blocks)), sentence


def _ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


@pytest.fixture(scope="module")
def archived_events():
    if not ARCHIVE.exists():
        pytest.skip("archived 3-hour caption corpus is not available")
    video_id = ARCHIVE.name.rsplit("_", 1)[-1]
    cues = youtube_srt.parse_json3(
        (ARCHIVE / f"{video_id}.en.en-orig.json3").read_text(encoding="utf-8")
    )
    return cues, subtitle_timeline.build_display_events(cues)


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def test_baseline_artifact_is_pinned():
    artifact = BASELINE["artifact"]
    assert BASELINE["id"] == "immersive-translate"
    assert BASELINE["role"] == "minimum"
    assert BASELINE["version"] == "1.34.4"
    assert artifact["extension_id"] == "bpoadfkcbjbfhfodiogcnhhhpibjhbnh"
    assert re.fullmatch(r"[0-9a-f]{64}", artifact["crx_sha256"])
    assert artifact["crx_bytes"] > 1_000_000
    assert artifact["file_sha256"], "pinned file hashes must not be empty"
    for relative, digest in artifact["file_sha256"].items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest), relative


def test_baseline_binary_is_not_committed():
    stray = [
        path
        for pattern in ("*.crx", "*.zip")
        for path in (ROOT / "benchmarks").rglob(pattern)
    ]
    assert stray == [], f"baseline binaries must stay out of git: {stray}"


def test_every_requirement_has_an_executable_test():
    missing = [
        requirement["id"]
        for requirement in BASELINE["requirements"]
        if not callable(globals().get(requirement["test"]))
    ]
    assert missing == [], f"requirements without a test: {missing}"


# --------------------------------------------------------------------------
# requirements
# --------------------------------------------------------------------------


def test_baseline_dual_language():
    english = youtube_srt.parse_srt(
        "1\n00:00:01,000 --> 00:00:03,000\nLadies and gentlemen,\n\n"
        "2\n00:00:03,000 --> 00:00:06,000\nThe President of the United States.\n\n"
    )
    chinese = youtube_srt.parse_srt(
        "1\n00:00:01,000 --> 00:00:03,000\n女士们先生们，\n\n"
        "2\n00:00:03,000 --> 00:00:06,000\n美国总统。\n\n"
    )

    events = subtitle_timeline.build_display_events(english, other_cues=chinese)

    assert events
    for index, (english_tokens, chinese_tokens) in enumerate(events):
        assert english_tokens, f"event {index} lost the English line"
        assert chinese_tokens, f"event {index} lost the Chinese line"


def test_baseline_cue_aligned_timing(archived_events):
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
    previous_start = 0.0
    for english, _ in events:
        start = english[0].start
        assert start >= previous_start - 0.001, (start, previous_start)
        previous_start = start

        if english[0].exact:
            if round(start, 2) in starts:
                anchored += 1
                continue
            # A word split out of a multi-word timing entry ("Donald J.")
            # starts inside its source span rather than on the span's own
            # start. It still may not invent a clock position.
            index = bisect.bisect_right(span_starts, start) - 1
            neighbours = [spans[i] for i in (index, index + 1) if 0 <= i < len(spans)]
            assert any(low <= start <= high for low, high in neighbours), (
                english[0].text,
                start,
            )
            continue
        # "1,000%" has cue text but split word timings ("1" + "000"), so the
        # engine interpolates it across the cue. The interpolation begins on
        # the source cue boundary, which is still cue-aligned.
        assert round(start, 2) in cue_starts, (english[0].text, start)

    assert len(events) > 2000
    assert anchored >= len(events) * 0.95


def test_baseline_no_source_loss(archived_events):
    cues, events = archived_events

    source = source_words(cues)
    displayed = rendered_words(events)

    assert len(source) > 20_000
    assert len(displayed) >= len(source) * 0.99
    assert unexplained_deletions(source, displayed) == []


def test_baseline_single_render():
    cues, sentence = rolling_vtt(40)

    events = subtitle_timeline.build_display_events(cues)

    assert rendered_words(events) == sentence
    texts: list[str] = []
    for english, _ in events:
        text = " ".join(token.text for token in english)
        assert not re.search(r"\b(\w+)\s+\1\b", text)
        texts.append(text)
    assert len(texts) == len(set(texts)), "adjacent events repeated a whole caption"


def test_baseline_typographic_budget():
    assert subtitle_layout.MAX_LINES == 2
    # Ratchet: the budget may be tightened, never widened.
    assert 0 < subtitle_layout.EN_MAX_CHARS <= 60
    assert 0 < subtitle_layout.ZH_MAX_CHARS <= 28

    english = " ".join(["word"] * 20)
    lines = subtitle_layout.wrap_caption(english, "en")
    assert len(lines) <= subtitle_layout.MAX_LINES
    assert all(len(line) <= subtitle_layout.EN_MAX_CHARS for line in lines)

    chinese = "美" * 40
    lines = subtitle_layout.wrap_caption(chinese, "zh-Hans")
    assert len(lines) <= subtitle_layout.MAX_LINES
    assert all(len(line) <= subtitle_layout.ZH_MAX_CHARS for line in lines)

    # Beyond two lines the wrapper must say so instead of overflowing the frame.
    overflow = " ".join(["word"] * 60)
    assert len(subtitle_layout.wrap_caption(overflow, "en")) > subtitle_layout.MAX_LINES


def test_baseline_word_karaoke():
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

    assert ("1.2", "Hello") == (f"{offsets[0][0]:.1f}", offsets[0][1])
    assert ("1.8", "world!") == (f"{offsets[-1][0]:.1f}", offsets[-1][1])
