from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import machine_translate_captions  # noqa: E402


def rolling_cues() -> list[dict]:
    return [
        {
            "start": 1.0,
            "end": 3.2,
            "text": "I think we should",
            "word_timings": [
                {"start": 1.0, "end": 1.3, "text": "I"},
                {"start": 1.3, "end": 1.8, "text": "think"},
                {"start": 1.8, "end": 2.1, "text": "we"},
                {"start": 2.1, "end": 2.5, "text": "should"},
            ],
        },
        {
            "start": 2.0,
            "end": 4.4,
            "text": "we should go home",
            "word_timings": [
                {"start": 2.0, "end": 2.3, "text": "we"},
                {"start": 2.3, "end": 2.7, "text": "should"},
                {"start": 2.7, "end": 3.0, "text": "go"},
                {"start": 3.0, "end": 3.5, "text": "home"},
            ],
        },
        {
            "start": 3.0,
            "end": 5.0,
            "text": "go home now.",
            "word_timings": [
                {"start": 3.0, "end": 3.3, "text": "go"},
                {"start": 3.3, "end": 3.7, "text": "home"},
                {"start": 3.7, "end": 4.2, "text": "now."},
            ],
        },
    ]


def test_rolling_cues_become_one_contextual_translation_unit():
    units = machine_translate_captions.build_translation_units(rolling_cues())

    assert units == [
        {"start": 1.0, "end": 4.2, "text": "I think we should go home now."}
    ]


def test_translation_units_keep_source_order_across_a_real_pause():
    cues = rolling_cues()
    cues.append(
        {
            "start": 8.0,
            "end": 9.0,
            "text": "Thank you.",
            "word_timings": [
                {"start": 8.0, "end": 8.5, "text": "Thank"},
                {"start": 8.5, "end": 9.0, "text": "you."},
            ],
        }
    )

    units = machine_translate_captions.build_translation_units(cues)

    assert [unit["text"] for unit in units] == [
        "I think we should go home now.",
        "Thank you.",
    ]
    assert [(unit["start"], unit["end"]) for unit in units] == [
        (1.0, 4.2),
        (8.0, 9.0),
    ]


def test_translation_unit_generation_does_not_mutate_source_cues():
    cues = rolling_cues()
    original = [
        (cue["text"], [word.copy() for word in cue["word_timings"]])
        for cue in cues
    ]

    machine_translate_captions.build_translation_units(cues)

    assert [
        (cue["text"], cue["word_timings"])
        for cue in cues
    ] == original


def test_overlapping_source_words_are_not_sent_twice_for_translation():
    units = machine_translate_captions.build_translation_units(rolling_cues())
    words = " ".join(unit["text"] for unit in units).split()

    assert words == ["I", "think", "we", "should", "go", "home", "now."]
