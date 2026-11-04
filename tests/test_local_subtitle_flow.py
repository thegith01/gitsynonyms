from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import assemblyai_captions  # noqa: E402
import asr_captions  # noqa: E402
import download_youtube_bilingual_srt as captions  # noqa: E402
import local_subtitle_flow as flow  # noqa: E402

VIDEO_ID = "ZG123456789"
TITLE = f"Clip [{VIDEO_ID}]"
FORMATS = ("json3", "srv3", "srv2", "srv1", "ttml", "vtt", "srt")


def make_folder(tmp_path: Path, *, with_media: bool = True) -> Path:
    folder = tmp_path / "a"
    folder.mkdir()
    if with_media:
        (folder / f"{TITLE}.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return folder


def write_track(
    folder: Path,
    language: str,
    formats: tuple[str, ...] = FORMATS,
) -> None:
    for extension in formats:
        (folder / f"{VIDEO_ID}.{language}.{extension}").write_text(
            "placeholder", encoding="utf-8"
        )


def write_caption_report(folder: Path, english: dict, chinese: dict | None = None) -> Path:
    path = folder / flow.CAPTION_REPORT
    path.write_text(
        json.dumps(
            {
                "video_id": VIDEO_ID,
                "tracks": {
                    flow.ENGLISH: english,
                    flow.CHINESE: chinese or {"present": False, "formats": []},
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def fake_ass(folder: Path, video_id: str, args) -> int:
    path = (
        args.ass_output
        or folder / flow.local_bilingual_ass.DEFAULT_ASS_NAME
    )
    Path(path).write_text("[Script Info]\n", encoding="utf-8")
    return 0


def clear_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        flow,
        "API_KEYS_FILE",
        Path(__file__).with_name(".no-api-keys-for-tests"),
    )
    for name in ("ASSEMBLYAI", "ASSEMBLYAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_run_youtube_captions_passes_sleep_subtitles_to_fetcher(tmp_path, monkeypatch):
    received: list[str] = []

    def fake_main(argv):
        received.extend(argv)
        return 0

    monkeypatch.setattr(flow.fetch_youtube_captions, "main", fake_main)
    report = tmp_path / "CAPTION_FORMATS.json"

    assert flow.run_youtube_captions(tmp_path, VIDEO_ID, 56, report) == 0
    assert received == [
        "--video-id",
        VIDEO_ID,
        "--output-dir",
        str(tmp_path),
        "--groups",
        "en,zh",
        "--sleep-subtitles",
        "56",
        "--report",
        str(report),
    ]


def test_run_translation_passes_arguments_to_translator(tmp_path, monkeypatch):
    received: list[str] = []

    def fake_main(argv):
        received.extend(argv)
        return 0

    monkeypatch.setattr(flow.machine_translate_captions, "main", fake_main)

    assert flow.run_translation(tmp_path, VIDEO_ID, "argos", 6.0) == 0
    assert received == [
        "--caption-dir",
        str(tmp_path),
        "--video-id",
        VIDEO_ID,
        "--source-language",
        flow.ENGLISH,
        "--target-language",
        flow.CHINESE,
        "--engine",
        "argos",
        "--output-dir",
        str(tmp_path),
        "--report",
        str(tmp_path / "SUBTITLE_SOURCES.json"),
        "--video-duration",
        "6.000",
    ]


def test_run_asr_passes_arguments_to_the_selected_engine(tmp_path, monkeypatch):
    media = tmp_path / "clip.mp4"
    received: list[str] = []

    def fake_main(argv):
        received.extend(argv)
        return 0

    monkeypatch.setattr(flow.assemblyai_captions, "main", fake_main)
    assert flow.run_asr(tmp_path, VIDEO_ID, media, "assemblyai", "base") == 0
    assert received == [
        "--video",
        str(media),
        "--video-id",
        VIDEO_ID,
        "--track",
        flow.ENGLISH,
        "--output-dir",
        str(tmp_path),
        "--work-dir",
        str(tmp_path / flow.ASR_WORK_DIR),
    ]

    received.clear()
    monkeypatch.setattr(flow.asr_captions, "main", fake_main)
    assert flow.run_asr(tmp_path, VIDEO_ID, media, "whisper", "small") == 0
    assert received == [
        "--video",
        str(media),
        "--video-id",
        VIDEO_ID,
        "--track",
        flow.ENGLISH,
        "--model",
        "small",
        "--output-dir",
        str(tmp_path),
    ]


def test_local_defaults_sleep_subtitles_56_seconds_and_allow_opaque_black_box():
    args = flow.build_parser().parse_args([])

    assert args.sleep_subtitles == 56
    assert args.box_style == "none"


def test_local_wait_alias_sets_ytdlp_subtitle_sleep():
    args = flow.build_parser().parse_args(["--wait", "56"])

    assert args.sleep_subtitles == 56


def test_caption_fetch_sets_yt_dlp_sleep_for_chinese_not_workflow_pause(
    tmp_path, monkeypatch
):
    fetcher = flow.fetch_youtube_captions
    waits: list[tuple[str, int]] = []
    pauses: list[int] = []
    monkeypatch.setattr(
        fetcher,
        "fetch_listing",
        lambda *_args: {
            "subtitles": {},
            "automatic_captions": {
                "en": [{"ext": "srt", "url": "https://example.test/en.srt"}],
                "zh-Hans": [{"ext": "srt", "url": "https://example.test/zh.srt"}],
            },
        },
    )

    def fake_download(_url, video_id, language, _kind, directory, wait, _formats):
        waits.append((language, wait))
        path = directory / f"{video_id}.{language}.srt"
        path.write_text("caption", encoding="utf-8")
        return [path], [], path

    monkeypatch.setattr(fetcher.captions, "download_track", fake_download)
    monkeypatch.setattr(fetcher.time, "sleep", pauses.append)

    assert fetcher.main(
        [
            "--video-id",
            VIDEO_ID,
            "--output-dir",
            str(tmp_path),
            "--groups",
            "en,zh",
            "--sleep-subtitles",
            "56",
        ]
    ) == 0

    assert waits == [("en", 0), ("zh-Hans", 56)]
    assert pauses == []


def test_run_ass_forwards_box_settings(tmp_path, monkeypatch):
    received: list[str] = []

    def fake_main(argv):
        received.extend(argv)
        return 0

    monkeypatch.setattr(flow.local_bilingual_ass, "main", fake_main)
    args = flow.build_parser().parse_args(
        [
            "--box-style",
            "solid-color",
            "--box-color",
            "#000000",
            "--box-opacity",
            "1",
            "--box-x",
            "66",
            "--box-y",
            "883",
            "--box-width",
            "1786",
            "--box-height",
            "139",
        ]
    )

    assert flow.run_ass(tmp_path, VIDEO_ID, args) == 0
    assert "--box-style" in received
    assert received[received.index("--box-style") + 1] == "solid-color"
    assert received[received.index("--box-color") + 1] == "#000000"
    assert received[received.index("--box-opacity") + 1] == "1.0"
    assert received[received.index("--box-x") + 1] == "66"
    assert received[received.index("--box-y") + 1] == "883"
    assert received[received.index("--box-width") + 1] == "1786"
    assert received[received.index("--box-height") + 1] == "139"


# ---------------------------------------------------------------------------
# Input resolution and the caption verdict
# ---------------------------------------------------------------------------


def test_resolves_every_youtube_url_shape(tmp_path):
    folder = make_folder(tmp_path, with_media=False)

    for url in (
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}",
        VIDEO_ID,
    ):
        assert flow.resolve_video_id(url, None, folder, None) == VIDEO_ID


def test_rejects_a_video_id_that_contradicts_the_url(tmp_path):
    folder = make_folder(tmp_path, with_media=False)

    try:
        flow.resolve_video_id(f"https://youtu.be/{VIDEO_ID}", "AAAAAAAAAAA", folder, None)
    except ValueError as error:
        assert "contradicts" in str(error)
    else:
        raise AssertionError("a contradictory --video-id must fail")


def test_caption_verdict_separates_absent_from_probe_error(tmp_path):
    folder = make_folder(tmp_path, with_media=False)

    present = write_caption_report(folder, {"present": True, "formats": ["json3"]})
    assert flow.caption_verdict(present) == "present"

    absent = write_caption_report(folder, {"present": False, "formats": []})
    assert flow.caption_verdict(absent) == "absent"

    failed = write_caption_report(
        folder, {"present": False, "formats": [], "error": "HTTP 429"}
    )
    assert flow.caption_verdict(failed) == "probe-error"


# ---------------------------------------------------------------------------
# Flow 1: YouTube seven formats first
# ---------------------------------------------------------------------------


def test_flow1_downloads_both_languages_and_skips_translation(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    calls: list[str] = []

    def fake_fetch(directory, video_id, wait, report):
        calls.append("fetch")
        write_track(directory, flow.ENGLISH)
        write_track(directory, flow.CHINESE)
        write_caption_report(
            directory,
            {"present": True, "formats": list(FORMATS)},
            {"present": True, "formats": list(FORMATS)},
        )
        return 0

    def fake_translate(*_args):
        raise AssertionError("translation must not run when YouTube has Chinese")

    def fake_build(directory, video_id, args):
        calls.append("ass")
        return fake_ass(directory, video_id, args)

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_build)

    assert flow.main(
        ["--url", f"https://youtu.be/{VIDEO_ID}", "--directory", str(folder)]
    ) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert report["flow"] == "youtube"
    assert report["reason"] == "youtube-english-present"
    assert report["translation"] == {"ran": False}
    assert report["formats"][flow.ENGLISH] == sorted(FORMATS)
    assert calls == ["fetch", "ass"]


def test_flow1_translates_chinese_when_youtube_has_only_english(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    clear_keys(monkeypatch)
    calls: list[tuple[str, str]] = []

    def fake_fetch(directory, video_id, wait, report):
        calls.append(("fetch", ""))
        write_track(directory, flow.ENGLISH)
        write_caption_report(
            directory,
            {"present": True, "formats": list(FORMATS)},
            {"present": False, "formats": []},
        )
        return 0

    def fake_translate(directory, video_id, engine, duration):
        calls.append(("translate", engine))
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_build(directory, video_id, args):
        calls.append(("ass", ""))
        return fake_ass(directory, video_id, args)

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_build)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["flow"] == "youtube"
    assert report["translation"] == {
        "engine": "argos",
        "requested_engine": "argos",
        "ran": True,
    }
    assert ("translate", "argos") in calls


def test_translation_fallback_is_reported_as_the_engine_that_ran(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    monkeypatch.setenv("ASSEMBLYAI", "test-key")

    def fake_fetch(directory, video_id, wait, report):
        write_track(directory, flow.ENGLISH)
        write_caption_report(directory, {"present": True, "formats": list(FORMATS)})
        return 0

    def fake_translate(directory, video_id, engine, duration):
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        (directory / "SUBTITLE_SOURCES.json").write_text(
            json.dumps({"engine": "argos", "requested_engine": engine}),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["translation"] == {
        "engine": "argos",
        "requested_engine": "assemblyai",
        "ran": True,
    }


def test_flow1_uses_assemblyai_translation_when_a_key_is_set(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    monkeypatch.setenv("ASSEMBLYAI", "test-key")
    seen: list[str] = []

    def fake_fetch(directory, video_id, wait, report):
        write_track(directory, flow.ENGLISH)
        write_caption_report(directory, {"present": True, "formats": list(FORMATS)})
        return 0

    def fake_translate(directory, video_id, engine, duration):
        seen.append(engine)
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        return 0

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 0
    assert seen == ["assemblyai"]


def test_a_probe_error_does_not_spend_money_on_asr(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)

    def fake_fetch(directory, video_id, wait, report):
        write_caption_report(
            directory,
            {"present": False, "formats": [], "error": "HTTP 429"},
        )
        return 0

    def fake_asr(*_args):
        raise AssertionError("ASR must not run on a transient probe failure")

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 1

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "failed" in report["error"]


# ---------------------------------------------------------------------------
# Flow 2: AssemblyAI word-timed ASR
# ---------------------------------------------------------------------------


def test_entry_points_accept_an_argument_list():
    # The flow calls these modules with a list instead of mutating sys.argv.
    assert "argv" in inspect.signature(assemblyai_captions.main).parameters
    assert "argv" in inspect.signature(asr_captions.main).parameters
    assert "argv" in inspect.signature(flow.machine_translate_captions.main).parameters
    assert "argv" in inspect.signature(flow.fetch_youtube_captions.main).parameters


def test_flow2_transcribes_then_translates_then_builds_ass(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    clear_keys(monkeypatch)
    calls: list[str] = []

    def fake_fetch(directory, video_id, wait, report):
        calls.append("fetch")
        write_caption_report(
            directory,
            {"present": False, "formats": []},
            {"present": False, "formats": []},
        )
        return 0

    def fake_asr(directory, video_id, media, engine, model):
        calls.append("asr")
        assert media.name == f"{TITLE}.mp4"
        write_track(directory, flow.ENGLISH, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_translate(directory, video_id, engine, duration):
        calls.append("translate")
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_build(directory, video_id, args):
        calls.append("ass")
        return fake_ass(directory, video_id, args)

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_build)

    assert flow.main(
        ["--url", f"https://www.youtube.com/watch?v={VIDEO_ID}", "--directory", str(folder)]
    ) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert report["flow"] == "asr"
    assert report["reason"] == "youtube-english-absent"
    assert report["asr"] == {"engine": "whisper", "report": "ASR.json"}
    assert calls == ["fetch", "asr", "translate", "ass"]


def test_flow2_uses_assemblyai_asr_when_a_key_is_set(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    monkeypatch.setenv("ASSEMBLYAI", "test-key")
    seen: list[str] = []

    def fake_fetch(directory, video_id, wait, report):
        write_caption_report(directory, {"present": False, "formats": []})
        return 0

    def fake_asr(directory, video_id, media, engine, model):
        seen.append(engine)
        write_track(directory, flow.ENGLISH, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_translate(directory, video_id, engine, duration):
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        return 0

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 0
    assert seen == ["assemblyai"]


def test_flow2_refuses_to_guess_without_a_local_media_file(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, with_media=False)

    def fake_fetch(directory, video_id, wait, report):
        write_caption_report(directory, {"present": False, "formats": []})
        return 0

    def fake_asr(*_args):
        raise AssertionError("ASR needs the local audio")

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 1

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert "local media" in report["error"]


def test_force_asr_skips_the_probe_even_when_youtube_has_captions(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    clear_keys(monkeypatch)
    calls: list[str] = []

    def fake_fetch(*_args):
        raise AssertionError("force-asr must not probe YouTube")

    def fake_asr(directory, video_id, media, engine, model):
        calls.append("asr")
        write_track(directory, flow.ENGLISH, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_translate(directory, video_id, engine, duration):
        calls.append("translate")
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_build(directory, video_id, args):
        calls.append("ass")
        return fake_ass(directory, video_id, args)

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_build)

    assert flow.main(
        ["--directory", str(folder), "--video-id", VIDEO_ID, "--force-asr"]
    ) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["reason"] == "force-asr"
    assert calls == ["asr", "translate", "ass"]


# ---------------------------------------------------------------------------
# Reuse of an existing local set
# ---------------------------------------------------------------------------


def test_complete_local_pair_skips_the_probe(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    write_track(folder, flow.ENGLISH)
    write_track(folder, flow.CHINESE)

    def fake_fetch(*_args):
        raise AssertionError("a complete local pair must not re-probe YouTube")

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(["--directory", str(folder), "--video-id", VIDEO_ID]) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["reason"] == "local-captions"


def test_refresh_forces_the_probe_even_with_a_complete_local_pair(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    write_track(folder, flow.ENGLISH)
    write_track(folder, flow.CHINESE)
    called: list[str] = []

    def fake_fetch(directory, video_id, wait, report):
        called.append("fetch")
        write_caption_report(
            directory,
            {"present": True, "formats": list(FORMATS)},
            {"present": True, "formats": list(FORMATS)},
        )
        return 0

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(
        ["--directory", str(folder), "--video-id", VIDEO_ID, "--refresh"]
    ) == 0
    assert called == ["fetch"]


def test_skip_youtube_uses_the_existing_captions_without_a_probe(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    write_track(folder, flow.ENGLISH)
    write_track(folder, flow.CHINESE)

    def fake_fetch(*_args):
        raise AssertionError("--skip-youtube must not touch the network")

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(
        ["--directory", str(folder), "--video-id", VIDEO_ID, "--skip-youtube"]
    ) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["reason"] == "offline-local"


# ---------------------------------------------------------------------------
# ASR json3 must keep the spaces the fused ASS reads back
# ---------------------------------------------------------------------------


def asr_cue() -> list[dict]:
    return [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "Hello world",
            "words": [
                {"word": "Hello", "start": 1.0, "end": 1.5},
                {"word": "world", "start": 1.5, "end": 2.0},
            ],
        }
    ]


def test_assemblyai_json3_keeps_spaces_between_words(tmp_path):
    assemblyai_captions.write_outputs(asr_cue(), tmp_path, "clip", "en-orig")

    parsed = captions.parse_json3(
        (tmp_path / "clip.json3").read_text(encoding="utf-8")
    )

    assert parsed[0]["text"] == "Hello world"
    assert [word["text"] for word in parsed[0]["word_timings"]] == ["Hello", "world"]


def test_faster_whisper_json3_keeps_spaces_between_words(tmp_path):
    asr_captions.write_json3(asr_cue(), tmp_path / "clip.json3", "en-orig")

    parsed = captions.parse_json3(
        (tmp_path / "clip.json3").read_text(encoding="utf-8")
    )

    assert parsed[0]["text"] == "Hello world"


# ---------------------------------------------------------------------------
# Explicit source dimensions (local/url/offline x YouTube/ASR x official/MT)
# ---------------------------------------------------------------------------


def test_presets_cover_the_explicit_source_dimensions():
    expected = {
        "local-youtube-official": ("youtube", "youtube", False),
        "local-youtube-mt": ("youtube", "mt", False),
        "local-asr-mt": ("asr", "mt", False),
        "local-asr-official": ("asr", "youtube", False),
        "url-youtube-official": ("youtube", "youtube", False),
        "url-youtube-mt": ("youtube", "mt", False),
        "offline-official": ("youtube", "youtube", True),
        "offline-mt": ("youtube", "mt", True),
    }
    for name, (english, chinese, offline) in expected.items():
        preset = flow.PRESETS[name]
        assert preset["english"] == english
        assert preset["chinese"] == chinese
        assert bool(preset["skip_youtube"]) is offline


def test_preset_local_asr_mt_forces_asr_and_translation(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    clear_keys(monkeypatch)
    calls: list[tuple[str, str]] = []

    def fake_fetch(*_args):
        raise AssertionError("local-asr-mt must not probe YouTube")

    def fake_asr(directory, video_id, media, engine, model):
        calls.append(("asr", engine))
        write_track(directory, flow.ENGLISH)
        return 0

    def fake_translate(directory, video_id, engine, duration):
        calls.append(("translate", engine))
        write_track(directory, flow.CHINESE, ("json3", "srt", "vtt", "ttml"))
        return 0

    def fake_build(directory, video_id, args):
        calls.append(("ass", ""))
        return fake_ass(directory, video_id, args)

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)
    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_build)

    assert flow.main(
        [
            "--directory",
            str(folder),
            "--video-id",
            VIDEO_ID,
            "--preset",
            "local-asr-mt",
        ]
    ) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["flow"] == "asr"
    assert report["selection"] == {
        "preset": "local-asr-mt",
        "english_source": "asr",
        "chinese_source": "mt",
    }
    assert calls == [("asr", "whisper"), ("translate", "argos"), ("ass", "")]


def test_forced_youtube_english_refuses_asr_when_absent(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)

    def fake_fetch(directory, video_id, wait, report):
        write_caption_report(directory, {"present": False, "formats": []})
        return 0

    def fake_asr(*_args):
        raise AssertionError("--english-source youtube must not fall back to ASR")

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_asr", fake_asr)

    assert flow.main(
        [
            "--directory",
            str(folder),
            "--video-id",
            VIDEO_ID,
            "--english-source",
            "youtube",
        ]
    ) == 1

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "--english-source youtube" in report["error"]


def test_forced_mt_replaces_an_existing_chinese_track(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    clear_keys(monkeypatch)
    write_track(folder, flow.ENGLISH)
    write_track(folder, flow.CHINESE)
    write_caption_report(
        folder,
        {"present": True, "formats": list(FORMATS)},
        {"present": True, "formats": list(FORMATS)},
    )
    translated: list[str] = []

    def fake_translate(directory, video_id, engine, duration):
        translated.append(engine)
        return 0

    monkeypatch.setattr(flow, "run_translation", fake_translate)
    monkeypatch.setattr(flow, "run_ass", fake_ass)

    assert flow.main(
        [
            "--directory",
            str(folder),
            "--video-id",
            VIDEO_ID,
            "--preset",
            "local-youtube-mt",
        ]
    ) == 0

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["selection"]["chinese_source"] == "mt"
    assert report["translation"]["ran"] is True
    assert translated == ["argos"]


def test_forced_official_chinese_errors_when_absent(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)

    def fake_fetch(directory, video_id, wait, report):
        write_track(directory, flow.ENGLISH)
        write_caption_report(
            directory,
            {"present": True, "formats": list(FORMATS)},
            {"present": False, "formats": []},
        )
        return 0

    def fake_translate(*_args):
        raise AssertionError("--chinese-source youtube must not translate")

    monkeypatch.setattr(flow, "run_youtube_captions", fake_fetch)
    monkeypatch.setattr(flow, "run_translation", fake_translate)

    assert flow.main(
        [
            "--directory",
            str(folder),
            "--video-id",
            VIDEO_ID,
            "--chinese-source",
            "youtube",
        ]
    ) == 1

    report = json.loads((folder / flow.FLOW_REPORT).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "--chinese-source mt" in report["error"]
