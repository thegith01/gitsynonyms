from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import scheme1_local_ass  # noqa: E402

VIDEO_ID = "SCHEME1TEST"


def write_srt(path: Path, cues: list[tuple[str, str, str]]) -> None:
    blocks = []
    for index, (start, end, text) in enumerate(cues, 1):
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_json3(path: Path, cues: list[tuple[int, int, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "tStartMs": start,
                        "dDurationMs": end - start,
                        "segs": [{"utf8": text}],
                    }
                    for start, end, text in cues
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def english_cues() -> list[tuple[str, str, str]]:
    return [
        ("00:00:01,000", "00:00:03,000", "Hello."),
        ("00:00:03,000", "00:00:05,000", "Goodbye."),
    ]


def chinese_cues() -> list[tuple[str, str, str]]:
    return [
        ("00:00:01,000", "00:00:03,000", "你好。"),
        ("00:00:03,000", "00:00:05,000", "再见。"),
    ]


def test_identical_source_cue_duplicates_are_removed_but_distinct_text_is_kept():
    duplicate = {
        "start_ns": 1_000_000_000,
        "end_ns": 3_000_000_000,
        "text": "It's incredible.",
        "text_source": "json3",
        "sources": ["json3"],
    }
    overlapping_distinct = {
        **duplicate,
        "text": "It's really incredible.",
        "sources": ["srt"],
    }

    cues, removed = scheme1_local_ass.deduplicate_identical_cues(
        [duplicate, {**duplicate, "sources": ["srt"]}, overlapping_distinct]
    )

    assert removed == 1
    assert [cue["text"] for cue in cues] == [
        "It's incredible.",
        "It's really incredible.",
    ]
    assert cues[0]["sources"] == ["json3", "srt"]


def build_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "ass_path": tmp_path / "result.ass",
        "srt_path": tmp_path / "result.srt",
        "report_path": tmp_path / "SCHEME_ADVANCED_SELFDEV_1.json",
        "ergonomics_path": tmp_path / "ERGONOMICS.json",
    }


def write_source_report(
    folder: Path,
    *,
    chinese_kind: str = "auto-translated",
    chinese_present: bool = True,
) -> None:
    (folder / "CAPTION_FORMATS.json").write_text(
        json.dumps(
            {
                "tracks": {
                    "en-orig": {"present": True, "kind": "auto-generated"},
                    "zh-Hans": {
                        "present": chinese_present,
                        "kind": chinese_kind,
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def test_aligned_official_chinese_is_reused_without_translation(tmp_path):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    write_srt(tmp_path / f"{VIDEO_ID}.zh-Hans.srt", chinese_cues())
    write_source_report(tmp_path)
    paths = build_paths(tmp_path)

    report = scheme1_local_ass.build(
        tmp_path, VIDEO_ID, None, **paths
    )

    assert report["cue_count"] == 2
    assert report["chinese"]["kind"] == "official-aligned"
    assert report["chinese"]["source"] == f"{VIDEO_ID}.zh-Hans.srt"
    content = paths["ass_path"].read_text(encoding="utf-8-sig")
    assert content.count("Dialogue: 1,") == 2
    assert "你好。" in content
    assert "Hello." in content


def test_official_chinese_priority_and_all_available_formats_are_reported(
    tmp_path,
):
    write_srt(
        tmp_path / f"{VIDEO_ID}.en-orig.srt",
        [("00:00:01,000", "00:00:03,000", "SRT English fallback.")],
    )
    write_json3(
        tmp_path / f"{VIDEO_ID}.en-orig.json3",
        [(1000, 3000, "Official English.")],
    )
    write_srt(
        tmp_path / f"{VIDEO_ID}.zh-Hans.srt",
        [("00:00:01,000", "00:00:03,000", "SRT 中文回退。")],
    )
    write_json3(
        tmp_path / f"{VIDEO_ID}.zh-Hans.json3",
        [(1000, 3000, "官方中文译文。")],
    )
    write_source_report(tmp_path)
    paths = build_paths(tmp_path)

    report = scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)

    assert report["english"]["primary_format"] == "srt"
    assert report["english"]["formats_used"] == ["json3", "srt"]
    assert report["english"]["format_usage"]["srt"]["matched_cues"] == 1
    assert report["chinese"]["primary_format"] == "json3"
    assert report["chinese"]["kind"] == "official-aligned"
    assert report["chinese"]["formats_used"] == ["json3", "srt"]
    assert report["chinese"]["format_usage"]["srt"]["matched_cues"] == 1
    content = paths["ass_path"].read_text(encoding="utf-8-sig")
    assert "官方中文译文。" in content
    assert "SRT " in content
    assert "fallback." in content
    assert "Official" not in content
    assert "SRT 中文回退。" not in content


def test_official_chinese_with_different_cue_grid_is_not_replaced_by_mt(
    tmp_path,
):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    write_json3(
        tmp_path / f"{VIDEO_ID}.zh-Hans.json3",
        [(1000, 5000, "来自 YouTube 的官方整句译文。")],
    )
    write_source_report(tmp_path)
    paths = build_paths(tmp_path)

    report = scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)

    assert report["chinese"]["kind"] == "official-time-aligned"
    assert report["chinese"]["alignment"] == "source-time-overlap"
    assert report["chinese"]["source"] == f"{VIDEO_ID}.zh-Hans.json3"
    content = paths["srt_path"].read_text(encoding="utf-8")
    assert content.count("来自 YouTube 的官方整句译文。") == 2


def test_unreadable_official_chinese_does_not_silently_fall_back_to_mt(
    tmp_path,
):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    (tmp_path / f"{VIDEO_ID}.zh-Hans.json3").write_text("not json", encoding="utf-8")
    write_source_report(tmp_path)
    paths = build_paths(tmp_path)

    with pytest.raises(ValueError, match="no readable Chinese caption format"):
        scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)


def test_recorded_non_translated_chinese_source_is_rejected(tmp_path):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    write_srt(tmp_path / f"{VIDEO_ID}.zh-Hans.srt", chinese_cues())
    (tmp_path / "CAPTION_FORMATS.json").write_text(
        json.dumps(
            {
                "tracks": {
                    "en-orig": {"present": True, "kind": "auto-generated"},
                    "zh-Hans": {"present": True, "kind": "manual"},
                }
            }
        ),
        encoding="utf-8",
    )
    paths = build_paths(tmp_path)

    with pytest.raises(ValueError, match="expected auto-translated"):
        scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)


def test_missing_official_chinese_fails_without_machine_translation(tmp_path):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    write_source_report(tmp_path, chinese_present=False)
    paths = build_paths(tmp_path)

    with pytest.raises(ValueError, match="requires the official YouTube auto-translated"):
        scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)


def test_overlong_official_chinese_is_rejected(tmp_path):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    write_srt(
        tmp_path / f"{VIDEO_ID}.zh-Hans.srt",
        [
            (
                "00:00:01,000",
                "00:00:03,000",
                "这是一个" + "非常" * 10 + "长的官方中文翻译。",
            ),
            ("00:00:03,000", "00:00:05,000", "再见。"),
        ],
    )
    write_source_report(tmp_path)
    paths = build_paths(tmp_path)

    with pytest.raises(ValueError, match="exceed 28 characters"):
        scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)


def test_overlong_english_is_split_at_word_boundaries():
    cues = [
        {
            "start": 0.0,
            "end": 10.0,
            "text": "word " * 20,
        }
    ]

    split = scheme1_local_ass.split_overlong_english(cues, 60)

    assert len(split) > 1
    assert all(len(cue["text"]) <= 60 for cue in split)
    assert split[0]["start"] == 0.0
    assert split[-1]["end"] == 10.0
