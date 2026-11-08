from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import scheme_local_immersive_lowest as baseline  # noqa: E402

VIDEO_ID = "BASELINE1234"


def cues_file(folder: Path, language: str, cues: list[tuple[str, str, str]]) -> None:
    blocks = [
        f"{index}\n{start} --> {end}\n{text}"
        for index, (start, end, text) in enumerate(cues, 1)
    ]
    (folder / f"{VIDEO_ID}.{language}.srt").write_text(
        "\n\n".join(blocks) + "\n", encoding="utf-8"
    )


def source_report(folder: Path) -> None:
    (folder / "CAPTION_FORMATS.json").write_text(
        json.dumps(
            {
                "video_id": VIDEO_ID,
                "tracks": {
                    "en-orig": {
                        "present": True,
                        "kind": "auto-generated",
                        "youtube_code": "en-orig",
                        "formats": ["srt"],
                    },
                    "zh-Hans": {
                        "present": True,
                        "kind": "auto-translated",
                        "youtube_code": "zh-Hans",
                        "formats": ["srt"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_ambient_markers_are_filtered_and_phrase_cues_merge_into_one_unit():
    english = [
        {"start": 0.0, "end": 2.0, "text": ">> [music] Hello,"},
        {"start": 1.5, "end": 3.0, "text": "world."},
    ]
    chinese = [{"start": 0.0, "end": 3.0, "text": "[掌声] 你好，世界。"}]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert unpaired == []
    assert len(events) == 1
    assert events[0]["english"] == "Hello, world."
    assert events[0]["chinese"] == "你好，世界。"
    assert events[0]["target_selection"] == "cue-aligned"
    assert events[0]["english_word_timings"]
    assert all(
        "[" not in event["english"] and ">>" not in event["english"]
        for event in events
    )


def test_clause_units_split_at_punctuation_and_reading_budget():
    import subtitle_timeline

    english = [
        {
            "start": 0.0,
            "end": 12.0,
            "text": (
                "Alpha beta gamma, delta epsilon zeta, eta theta iota, "
                "kappa lambda mu, nu xi omicron, pi rho sigma, tau upsilon "
                "phi, chi psi omega."
            ),
        }
    ]

    tokens = subtitle_timeline.build_timeline(english)
    units = baseline._split_clause_tokens(tokens)

    assert len(units) > 1
    for unit in units:
        assert subtitle_timeline._char_count(unit) <= 60
        assert unit[-1].text.rstrip().endswith((",", ";", ":", "."))
    assert units[-1][-1].text.endswith(".")


def test_phrase_cues_merge_into_one_bilingual_unit():
    english = [
        {"start": 0.0, "end": 2.0, "text": ">> And when people ask"},
        {"start": 1.5, "end": 3.0, "text": "me what exactly"},
        {"start": 2.5, "end": 4.0, "text": "we're trying to do."},
    ]
    chinese = [
        {"start": 0.0, "end": 2.0, "text": "当人们问我"},
        {"start": 1.5, "end": 3.0, "text": "究竟"},
        {"start": 2.5, "end": 4.0, "text": "想做什么。"},
    ]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert unpaired == []
    assert len(events) == 1
    assert events[0]["english"] == "And when people ask me what exactly we're trying to do."
    assert events[0]["chinese"] == "当人们问我究竟想做什么。"
    assert events[0]["target_selection"] == "unit-overlap"


def test_unpaired_units_are_merged_and_recorded():
    english = [
        {"start": 0.0, "end": 1.0, "text": "Hello."},
        {"start": 2.0, "end": 3.0, "text": "World."},
    ]
    chinese = [{"start": 2.0, "end": 3.0, "text": "世界。"}]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert [(event["start"], event["end"]) for event in events] == [(0.0, 3.0)]
    assert events[0]["english"] == "Hello. World."
    assert events[0]["chinese"] == "世界。"
    assert events[0]["merged_source_units"] == 1
    assert [item["reason"] for item in unpaired] == ["missing-chinese"]
    assert [item["missing"] for item in unpaired] == ["Chinese"]
    assert [item["english"] for item in unpaired] == ["Hello."]
    assert [item["disposition"] for item in unpaired] == [
        "merged-into-neighbor"
    ]

    ass = baseline.render_ass(events)
    assert ass.count("Dialogue: 1,") == 1
    assert "Style: English" in ass
    assert "Style: Chinese" in ass
    assert "Hello." in ass
    assert "World." in ass
    assert "世界。" in ass

    with pytest.raises(ValueError, match="only accepts bilingual events"):
        baseline.render_ass(
            [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "chinese": "",
                    "english": "Hello.",
                    "english_word_timings": [],
                }
            ]
        )


def test_nearby_chinese_is_attached_with_the_nearest_fallback():
    english = [{"start": 1.0, "end": 2.0, "text": "Hello."}]
    chinese = [{"start": 2.2, "end": 2.8, "text": "你好。"}]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert unpaired == []
    assert len(events) == 1
    assert events[0]["chinese"] == "你好。"
    assert events[0]["target_selection"] == "nearest-fallback"
    assert events[0]["end"] >= 2.8


def test_immersive_lowest_requires_verified_official_youtube_track_kinds(
    tmp_path, monkeypatch
):
    cues_file(tmp_path, "en-orig", [("00:00:01,000", "00:00:03,000", "Hello.")])
    cues_file(tmp_path, "zh-Hans", [("00:00:01,000", "00:00:03,000", "你好。")])
    source_report(tmp_path)
    monkeypatch.setattr(
        baseline.local_bilingual_ass, "probe_duration", lambda media: 10.0
    )

    report = baseline.build(tmp_path, VIDEO_ID)

    assert report["scheme_id"] == "scheme_local__immersive_lowest"
    assert report["scheme"] == "scheme_低级_沉浸翻译（最低 / LOWEST 标准）"
    assert report["baseline"]["observed_model"].startswith(
        "short timed-text phrase units"
    )
    assert report["baseline"]["source_anchored"] is True
    assert report["baseline"]["active_cues_joined"] is True
    assert report["baseline"]["clause_units"] is True
    assert report["baseline"]["target_persistence"] is False
    assert report["baseline"]["cross_cue_deduplication"] is True
    assert report["synchronization"]["event_count"] == 1
    assert report["synchronization"]["rendered_event_count"] == 1
    assert report["synchronization"]["overwide_event_splits"] == 0
    assert report["synchronization"]["bilingual_event_count"] == 1
    assert report["synchronization"]["events_are_bilingual"] is True
    assert report["synchronization"]["source_anchored"] is True
    assert report["synchronization"]["clause_units"] is True
    assert report["synchronization"]["source_cue_count"] == 1
    assert report["synchronization"]["source_unit_count"] == 1
    assert report["synchronization"]["source_cues_skipped"] == 0
    assert report["synchronization"]["source_units_merged"] == 0
    assert report["synchronization"]["unpaired_intervals"] == 0
    assert report["synchronization"]["unpaired_intervals_skipped"] is False
    assert report["synchronization"]["unpaired_intervals_merged"] is True
    assert report["synchronization"]["monolingual_events"] == 0
    assert report["synchronization"]["target_persistence_events"] == 0
    assert report["synchronization"]["max_active_chinese_cues"] == 1
    assert report["synchronization"]["target_selection_counts"] == {
        "cue-aligned": 1
    }
    assert report["sources"]["en-orig"]["youtube"]["kind"] == "auto-generated"
    assert report["sources"]["zh-Hans"]["youtube"]["kind"] == "auto-translated"
    assert report["style"]["box_style"] == "presidential-blue"
    assert report["style"]["box_color"] == "#0F1647"
    assert report["style"]["box_opacity"] == 0.99
    assert "你好。" in (tmp_path / baseline.DEFAULT_SRT_NAME).read_text(
        encoding="utf-8"
    )
    ass = (tmp_path / baseline.DEFAULT_ASS_NAME).read_text(encoding="utf-8-sig")
    assert "Microsoft YaHei" in ass
    assert "Segoe UI" in ass
    assert "CaptionBox" in ass
    assert "Style: Chinese,Microsoft YaHei,57.6,&H00A8FFFF" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:10.00,CaptionBox" in ass
    assert "Dialogue: 1," in ass
    assert "你好。" in ass
    assert "Hello." in ass
    assert r"\k" in ass


def test_immersive_lowest_merges_unpaired_units_in_outputs(tmp_path):
    cues_file(
        tmp_path,
        "en-orig",
        [
            ("00:00:01,000", "00:00:02,000", "Hello."),
            ("00:00:02,500", "00:00:03,500", "World."),
        ],
    )
    cues_file(tmp_path, "zh-Hans", [("00:00:02,000", "00:00:04,000", "你好。")])
    source_report(tmp_path)

    report = baseline.build(tmp_path, VIDEO_ID, box_style="none")

    assert report["synchronization"]["event_count"] == 1
    assert report["synchronization"]["rendered_event_count"] == 1
    assert report["synchronization"]["source_cue_count"] == 2
    assert report["synchronization"]["source_unit_count"] == 2
    assert report["synchronization"]["source_cues_skipped"] == 0
    assert report["synchronization"]["source_units_merged"] == 1
    assert report["synchronization"]["unpaired_intervals"] == 1
    assert report["synchronization"]["unpaired_details"][0]["reason"] == (
        "missing-chinese"
    )
    assert report["synchronization"]["unpaired_details"][0]["disposition"] == (
        "merged-into-neighbor"
    )
    srt = (tmp_path / baseline.DEFAULT_SRT_NAME).read_text(encoding="utf-8")
    assert srt.count("-->") == 1
    assert "Hello." in srt
    assert "World." in srt
    ass = (tmp_path / baseline.DEFAULT_ASS_NAME).read_text(encoding="utf-8-sig")
    assert ass.count("Dialogue: 1,") == 1


def test_immersive_lowest_refuses_unverified_local_sources(tmp_path):
    cues_file(tmp_path, "en-orig", [("00:00:01,000", "00:00:03,000", "Hello.")])
    cues_file(tmp_path, "zh-Hans", [("00:00:01,000", "00:00:03,000", "你好。")])

    with pytest.raises(ValueError, match="requires CAPTION_FORMATS.json"):
        baseline.build(tmp_path, VIDEO_ID)
