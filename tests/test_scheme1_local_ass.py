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


def build_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "ass_path": tmp_path / "result.ass",
        "srt_path": tmp_path / "result.srt",
        "report_path": tmp_path / "SCHEME1.json",
        "ergonomics_path": tmp_path / "ERGONOMICS.json",
        "cache_path": tmp_path / "TRANSLATIONS.json",
    }


def test_aligned_official_chinese_is_reused_without_translation(tmp_path, monkeypatch):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    write_srt(tmp_path / f"{VIDEO_ID}.zh-Hans.srt", chinese_cues())
    paths = build_paths(tmp_path)

    def fail(*_args, **_kwargs):
        raise AssertionError("an aligned Chinese track must not be translated")

    monkeypatch.setattr(
        scheme1_local_ass.machine_translate_captions,
        "translate_assemblyai",
        fail,
    )

    report = scheme1_local_ass.build(
        tmp_path, VIDEO_ID, None, **paths
    )

    assert report["cue_count"] == 2
    assert report["chinese"]["kind"] == "official-aligned"
    assert report["chinese"]["source"] == f"{VIDEO_ID}.zh-Hans.srt"
    assert not paths["cache_path"].exists()
    content = paths["ass_path"].read_text(encoding="utf-8-sig")
    assert content.count("Dialogue: 1,") == 2
    assert "你好。" in content
    assert "Hello." in content


def test_missing_chinese_is_translated_per_cue_and_cached(tmp_path, monkeypatch):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    paths = build_paths(tmp_path)
    seen: list[str] = []

    def fake_translate(texts, _source, _target, *, model=None, max_chars=None):
        seen.extend(texts)
        return ["你好。", "再见。"][: len(texts)]

    monkeypatch.setattr(
        scheme1_local_ass.machine_translate_captions,
        "translate_assemblyai",
        fake_translate,
    )

    report = scheme1_local_ass.build(tmp_path, VIDEO_ID, None, **paths)

    assert seen == ["Hello.", "Goodbye."]
    assert report["cue_count"] == 2
    assert report["chinese"]["kind"] == "machine-translated"
    assert report["chinese"]["engine"] == "assemblyai"
    cache = json.loads(paths["cache_path"].read_text(encoding="utf-8"))
    assert cache["lines"] == {"Hello.": "你好。", "Goodbye.": "再见。"}
    content = paths["ass_path"].read_text(encoding="utf-8-sig")
    assert content.count("Dialogue: 1,") == 2


def test_overlong_chinese_translation_is_rejected(tmp_path, monkeypatch):
    write_srt(tmp_path / f"{VIDEO_ID}.en-orig.srt", english_cues())
    paths = build_paths(tmp_path)

    def fake_translate(texts, _source, _target, *, model=None, max_chars=None):
        return ["这是一个" + "非常" * 10 + "长的中文翻译。"] * len(texts)

    monkeypatch.setattr(
        scheme1_local_ass.machine_translate_captions,
        "translate_assemblyai",
        fake_translate,
    )

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
