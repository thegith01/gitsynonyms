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


def test_active_snapshots_use_latest_cue_at_each_boundary():
    english = [
        {"start": 1.0, "end": 3.0, "text": "First."},
        {"start": 2.0, "end": 4.0, "text": "Second."},
    ]
    chinese = [
        {"start": 1.0, "end": 3.0, "text": "第一句。"},
        {"start": 2.0, "end": 4.0, "text": "第二句。"},
    ]

    events, unpaired = baseline.build_active_snapshots(chinese, english)

    assert unpaired == []
    assert [(event["start"], event["end"]) for event in events] == [
        (1.0, 2.0),
        (2.0, 3.0),
        (3.0, 4.0),
    ]
    assert events[0]["english"] == "First."
    assert events[1]["english"] == "Second."
    assert events[1]["chinese"] == "第二句。"
    assert events[2]["english"] == "Second."
    assert events[2]["chinese"] == "第二句。"


def test_unpaired_active_windows_emit_source_language_events():
    english = [{"start": 1.0, "end": 3.0, "text": "Hello."}]
    chinese = [{"start": 2.0, "end": 4.0, "text": "你好。"}]

    events, unpaired = baseline.build_active_snapshots(chinese, english)

    assert [(event["start"], event["end"]) for event in events] == [
        (1.0, 2.0),
        (2.0, 3.0),
        (3.0, 4.0),
    ]
    assert events[0]["english"] == "Hello."
    assert events[0]["chinese"] == ""
    assert events[2]["english"] == ""
    assert events[2]["chinese"] == "你好。"
    assert [item["missing"] for item in unpaired] == ["Chinese", "English"]

    ass = baseline.render_ass(events)
    assert ass.count("Dialogue: 1,") == 3
    assert "Style: English" in ass
    assert "Style: Chinese" in ass
    assert "Hello." in ass
    assert "你好。" in ass


def test_immersive_lowest_requires_verified_official_youtube_track_kinds(tmp_path):
    cues_file(tmp_path, "en-orig", [("00:00:01,000", "00:00:03,000", "Hello.")])
    cues_file(tmp_path, "zh-Hans", [("00:00:01,000", "00:00:03,000", "你好。")])
    source_report(tmp_path)

    report = baseline.build(tmp_path, VIDEO_ID)

    assert report["scheme_id"] == "scheme_local__immersive_lowest"
    assert report["scheme"] == "scheme_低级_沉浸翻译（最低 / LOWEST 标准）"
    assert report["baseline"]["observed_model"] == (
        "latest active cue per language at cuechange boundaries"
    )
    assert report["synchronization"]["event_count"] == 1
    assert report["sources"]["en-orig"]["youtube"]["kind"] == "auto-generated"
    assert report["sources"]["zh-Hans"]["youtube"]["kind"] == "auto-translated"
    assert "你好。" in (tmp_path / baseline.DEFAULT_SRT_NAME).read_text(
        encoding="utf-8"
    )
    ass = (tmp_path / baseline.DEFAULT_ASS_NAME).read_text(encoding="utf-8-sig")
    assert "Microsoft YaHei" in ass
    assert "Segoe UI" in ass
    assert "Dialogue: 1," in ass
    assert "你好。" in ass
    assert "Hello." in ass
    assert r"\k" in ass


def test_immersive_lowest_refuses_unverified_local_sources(tmp_path):
    cues_file(tmp_path, "en-orig", [("00:00:01,000", "00:00:03,000", "Hello.")])
    cues_file(tmp_path, "zh-Hans", [("00:00:01,000", "00:00:03,000", "你好。")])

    with pytest.raises(ValueError, match="requires CAPTION_FORMATS.json"):
        baseline.build(tmp_path, VIDEO_ID)
