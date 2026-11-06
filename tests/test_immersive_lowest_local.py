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


def test_source_anchored_events_follow_each_english_cue():
    english = [
        {"start": 1.0, "end": 3.0, "text": "First."},
        {"start": 2.0, "end": 4.0, "text": "Second."},
    ]
    chinese = [{"start": 1.0, "end": 4.0, "text": "第一第二。"}]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert unpaired == []
    assert [(event["start"], event["end"]) for event in events] == [
        (1.0, 2.0),
        (2.0, 4.0),
    ]
    assert [event["english"] for event in events] == ["First.", "Second."]
    assert [event["chinese"] for event in events] == ["第一第二。", "第一第二。"]
    assert [event["source_trimmed"] for event in events] == [True, False]
    assert [event["active_chinese_cues"] for event in events] == [1, 1]


def test_latest_active_chinese_target_is_selected_at_source_midpoint():
    english = [{"start": 1.0, "end": 3.0, "text": "Hello."}]
    chinese = [
        {"start": 0.5, "end": 4.0, "text": "旧翻译。"},
        {"start": 2.0, "end": 3.5, "text": "新翻译。"},
    ]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert unpaired == []
    assert len(events) == 1
    assert events[0]["chinese"] == "新翻译。"
    assert events[0]["active_chinese_cues"] == 2
    assert events[0]["target_cue_start"] == 2.0


def test_unpaired_source_cues_are_skipped_and_recorded():
    english = [
        {"start": 1.0, "end": 2.0, "text": "Hello."},
        {"start": 2.5, "end": 3.5, "text": "World."},
    ]
    chinese = [{"start": 2.0, "end": 4.0, "text": "你好。"}]

    events, unpaired = baseline.build_source_anchored_events(chinese, english)

    assert [(event["start"], event["end"]) for event in events] == [(2.5, 3.5)]
    assert events[0]["english"] == "World."
    assert events[0]["chinese"] == "你好。"
    assert [item["reason"] for item in unpaired] == ["missing-chinese"]
    assert [item["missing"] for item in unpaired] == ["Chinese"]
    assert [item["active"] for item in unpaired] == ["English"]

    ass = baseline.render_ass(events)
    assert ass.count("Dialogue: 1,") == 1
    assert "Style: English" in ass
    assert "Style: Chinese" in ass
    assert "World." in ass
    assert "你好。" in ass

    with pytest.raises(ValueError, match="only accepts bilingual snapshots"):
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
    assert report["baseline"]["observed_model"].startswith("source-anchored")
    assert report["baseline"]["source_anchored"] is True
    assert report["baseline"]["active_cues_joined"] is False
    assert report["baseline"]["target_persistence"] is True
    assert report["synchronization"]["event_count"] == 1
    assert report["synchronization"]["bilingual_event_count"] == 1
    assert report["synchronization"]["events_are_bilingual"] is True
    assert report["synchronization"]["source_anchored"] is True
    assert report["synchronization"]["source_cue_count"] == 1
    assert report["synchronization"]["source_cues_skipped"] == 0
    assert report["synchronization"]["unpaired_intervals"] == 0
    assert report["synchronization"]["unpaired_intervals_skipped"] is True
    assert report["synchronization"]["monolingual_events"] == 0
    assert report["synchronization"]["target_persistence_events"] == 0
    assert report["synchronization"]["max_active_chinese_cues"] == 1
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


def test_immersive_lowest_skips_unpaired_source_cues_in_outputs(tmp_path):
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
    assert report["synchronization"]["source_cue_count"] == 2
    assert report["synchronization"]["source_cues_skipped"] == 1
    assert report["synchronization"]["unpaired_intervals"] == 1
    assert report["synchronization"]["unpaired_details"][0]["reason"] == (
        "missing-chinese"
    )
    srt = (tmp_path / baseline.DEFAULT_SRT_NAME).read_text(encoding="utf-8")
    assert srt.count("-->") == 1
    assert "World." in srt
    ass = (tmp_path / baseline.DEFAULT_ASS_NAME).read_text(encoding="utf-8-sig")
    assert ass.count("Dialogue: 1,") == 1


def test_immersive_lowest_refuses_unverified_local_sources(tmp_path):
    cues_file(tmp_path, "en-orig", [("00:00:01,000", "00:00:03,000", "Hello.")])
    cues_file(tmp_path, "zh-Hans", [("00:00:01,000", "00:00:03,000", "你好。")])

    with pytest.raises(ValueError, match="requires CAPTION_FORMATS.json"):
        baseline.build(tmp_path, VIDEO_ID)
