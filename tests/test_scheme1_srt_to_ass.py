from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "scheme1_srt_to_ass.py"
SPEC = importlib.util.spec_from_file_location("scheme1_srt_to_ass", SCRIPT)
scheme1 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scheme1
SPEC.loader.exec_module(scheme1)


def test_converts_scheme1_bilingual_srt_with_scheme1_style(tmp_path):
    source = tmp_path / "source.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n你好。\nHello.\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\n再见。\nGoodbye.\n",
        encoding="utf-8",
    )
    destination = tmp_path / "result.ass"

    scheme1.convert_srt_to_ass(source, destination)

    content = destination.read_text(encoding="utf-8-sig")
    assert "Style: Chinese,Microsoft YaHei,57.6," in content
    assert "Style: English,Segoe UI,48,&H00D1CB9B,&HECF1F2," in content
    assert "WrapStyle: 0" in content
    assert "CaptionBox" not in content
    dialogues = [
        line for line in content.splitlines() if line.startswith("Dialogue: 1,")
    ]
    assert len(dialogues) == 2
    assert dialogues[0].startswith("Dialogue: 1,0:00:01.00,0:00:02.00,")
    assert dialogues[1].startswith("Dialogue: 1,0:00:02.00,0:00:03.00,")
    assert all(dialogue.split(",", 9)[-1].count(r"\N") == 2 for dialogue in dialogues)
    assert "Hello." in content
    assert "你好。" in content


def test_attaches_standalone_closing_punctuation_to_complete_ass_cue(tmp_path):
    source = tmp_path / "source.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n她应该留下吗\nShould she stay\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\n？\nor go?\n",
        encoding="utf-8",
    )
    destination = tmp_path / "result.ass"

    scheme1.convert_srt_to_ass(source, destination)

    dialogues = [
        line
        for line in destination.read_text(encoding="utf-8-sig").splitlines()
        if line.startswith("Dialogue: 1,")
    ]
    assert len(dialogues) == 1
    assert dialogues[0].startswith("Dialogue: 1,0:00:01.00,0:00:03.00,")
    assert "她应该留下吗？" in dialogues[0]
    assert "Should she stay or go?" in dialogues[0]


@pytest.mark.parametrize(
    "text",
    [
        "1\n00:00:01,000 --> 00:00:02,000\nEnglish only\n",
        "1\n00:00:01,000 --> 00:00:02,000\n中文\nEnglish\nExtra\n",
        "1\n00:00:01,000 --> 00:00:02,000\n中文\n也有中文\n",
    ],
)
def test_rejects_non_bilingual_or_malformed_cues(tmp_path, text):
    source = tmp_path / "invalid.srt"
    source.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError):
        scheme1.split_bilingual_tracks(source)
