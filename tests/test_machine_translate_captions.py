from __future__ import annotations

import json
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


def test_report_names_the_engine_that_actually_ran(tmp_path, monkeypatch):
    video_id = "TESTVIDEOID"
    caption = {
        "events": [
            {
                "tStartMs": 1000,
                "dDurationMs": 2000,
                "segs": [{"utf8": "Hello"}, {"utf8": " world", "tOffsetMs": 500}],
            }
        ]
    }
    (tmp_path / f"{video_id}.en-orig.json3").write_text(
        json.dumps(caption), encoding="utf-8"
    )

    def unavailable(*_args):
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(machine_translate_captions, "translate_assemblyai", unavailable)
    monkeypatch.setattr(
        machine_translate_captions,
        "translate_argos",
        lambda texts, *_args: ["你好"] * len(texts),
    )

    assert machine_translate_captions.main(
        [
            "--caption-dir",
            str(tmp_path),
            "--video-id",
            video_id,
            "--engine",
            "assemblyai",
            "--report",
            str(tmp_path / "SUBTITLE_SOURCES.json"),
        ]
    ) == 0

    report = json.loads(
        (tmp_path / "SUBTITLE_SOURCES.json").read_text(encoding="utf-8")
    )
    assert report["engine"] == "argos"
    assert report["requested_engine"] == "assemblyai"
    assert report["candidates"][0]["engine"] == "argos"
    assert report["selected"] == "zh-Hans-argos"


def test_assemblyai_falls_back_when_the_default_model_is_unavailable(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI", "test-key")
    seen: list[str] = []

    def fake_completion(payload, _key):
        seen.append(payload["model"])
        if payload["model"] == machine_translate_captions.ASSEMBLYAI_DEFAULT_MODEL:
            raise machine_translate_captions.ModelUnavailable("no access")
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"lines": ["你好", "再见"]}, ensure_ascii=False
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        machine_translate_captions, "_assemblyai_completion", fake_completion
    )

    assert machine_translate_captions.translate_assemblyai(
        ["Hello", "Bye"], "en", "zh"
    ) == ["你好", "再见"]
    assert seen == [
        machine_translate_captions.ASSEMBLYAI_DEFAULT_MODEL,
        machine_translate_captions.ASSEMBLYAI_FALLBACK_MODELS[0],
    ]


def test_assemblyai_bisects_a_batch_that_merges_lines(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI", "test-key")
    calls: list[int] = []

    def fake_completion(payload, _key):
        batch = json.loads(payload["messages"][1]["content"])["lines"]
        calls.append(len(batch))
        lines = ["合并"] if len(batch) > 1 else [f"译{batch[0]}"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"lines": lines}, ensure_ascii=False)
                    }
                }
            ]
        }

    monkeypatch.setattr(
        machine_translate_captions, "_assemblyai_completion", fake_completion
    )

    assert machine_translate_captions.translate_assemblyai(
        ["a", "b", "c", "d"], "en", "zh"
    ) == ["译a", "译b", "译c", "译d"]
    assert max(calls) == 4


def test_assemblyai_joins_one_input_that_the_model_splits(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI", "test-key")

    def fake_completion(_payload, _key):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"lines": ["你", "好"]}, ensure_ascii=False
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        machine_translate_captions, "_assemblyai_completion", fake_completion
    )

    assert machine_translate_captions.translate_assemblyai(
        ["Hello"], "en", "zh"
    ) == ["你好"]
