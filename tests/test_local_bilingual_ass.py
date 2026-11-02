import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import local_bilingual_ass
import subtitle_ergonomics


VIDEO_ID = "ZG123456789"
TITLE = "President Trump Gaggles with Press [ZG123456789]"

JSON3_EN = {
    "events": [
        {
            "tStartMs": 1000,
            "dDurationMs": 2000,
            "segs": [{"utf8": "Hello"}, {"utf8": " world", "tOffsetMs": 500}],
        },
        {
            "tStartMs": 4000,
            "dDurationMs": 2000,
            "segs": [{"utf8": "Second"}, {"utf8": " line", "tOffsetMs": 600}],
        },
    ]
}

SRT_EN = (
    "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\nSecond line\n"
)

JSON3_ZH = {
    "events": [
        {
            "tStartMs": 1000,
            "dDurationMs": 2000,
            "segs": [{"utf8": "你好"}, {"utf8": "世界", "tOffsetMs": 500}],
        },
        {
            "tStartMs": 4000,
            "dDurationMs": 2000,
            "segs": [{"utf8": "第二"}, {"utf8": "行", "tOffsetMs": 600}],
        },
    ]
}

SRT_ZH = (
    "1\n00:00:01,000 --> 00:00:03,000\n你好世界\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\n第二行\n"
)


def make_folder(tmp_path: Path, *, with_media: bool = True) -> Path:
    folder = tmp_path / "a"
    folder.mkdir()
    if with_media:
        (folder / f"{TITLE}.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (folder / f"{TITLE}.en-orig.json3").write_text(json.dumps(JSON3_EN), encoding="utf-8")
    (folder / f"{TITLE}.en-orig.srt").write_text(SRT_EN, encoding="utf-8")
    (folder / f"{TITLE}.zh-Hans.json3").write_text(json.dumps(JSON3_ZH), encoding="utf-8")
    (folder / f"{TITLE}.zh-Hans.srt").write_text(SRT_ZH, encoding="utf-8")
    return folder


def test_derives_the_video_id_and_reads_title_based_caption_names(tmp_path):
    folder = make_folder(tmp_path)

    exit_code = local_bilingual_ass.main(["--directory", str(folder)])

    assert exit_code == 0
    ass = folder / local_bilingual_ass.DEFAULT_ASS_NAME
    assert ass.is_file()
    timing = json.loads((folder / local_bilingual_ass.DEFAULT_TIMING_NAME).read_text(encoding="utf-8"))
    assert timing["video_id"] == VIDEO_ID
    assert timing["tracks"]["en-orig"]["formats_used"] == ["json3", "srt"]
    assert timing["tracks"]["zh-Hans"]["formats_used"] == ["json3", "srt"]
    assert timing["tracks"]["en-orig"]["cue_count"] == 2


def test_keeps_one_line_per_language_and_word_karaoke(tmp_path):
    folder = make_folder(tmp_path)

    assert local_bilingual_ass.main(["--directory", str(folder)]) == 0

    content = (folder / local_bilingual_ass.DEFAULT_ASS_NAME).read_text(encoding="utf-8-sig")
    assert "你好世界" in content
    assert "Hello" in content and "world" in content
    assert "Style: Chinese" in content and "Style: English" in content
    assert "\\kt" in content and "\\k" in content
    assert "CaptionBox" not in content
    assert "PlayResX: 1920" in content and "PlayResY: 1080" in content

    dialogues = [line for line in content.splitlines() if line.startswith("Dialogue: ")]
    assert dialogues

    for line in dialogues:
        text = line.split(",", 9)[-1]
        assert len(subtitle_ergonomics.visible_lines(text)) <= 2


def test_accepts_an_explicit_video_id_without_media(tmp_path):
    folder = make_folder(tmp_path, with_media=False)

    exit_code = local_bilingual_ass.main(
        ["--directory", str(folder), "--video-id", VIDEO_ID]
    )

    assert exit_code == 0
    assert (folder / local_bilingual_ass.DEFAULT_ASS_NAME).is_file()


def test_missing_chinese_track_fails_loudly(tmp_path):
    folder = make_folder(tmp_path)
    for path in folder.glob("*.zh-Hans.*"):
        path.unlink()

    assert local_bilingual_ass.main(["--directory", str(folder)]) == 1


def test_strict_mode_reports_ergonomics_errors(tmp_path):
    folder = make_folder(tmp_path)
    # Two 20-character English cues in two seconds read at 10 CPS, far above
    # the 20 CPS adult limit only when the text is long enough; this fixture is
    # deliberately comfortable, so strict must succeed.
    assert local_bilingual_ass.main(["--directory", str(folder), "--strict"]) == 0
    report = json.loads(
        (folder / local_bilingual_ass.DEFAULT_ERGONOMICS_NAME).read_text(encoding="utf-8")
    )
    assert report["format"] == "ass"
    assert report["summary"]["cues"] >= 1
