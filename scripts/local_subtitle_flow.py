#!/usr/bin/env python3
"""Run the two local caption flows behind one command.

Flow 1 (YouTube first, DIRECTIVE 3.7)
    When YouTube publishes an English track -- manual or auto-generated --
    download every published serialization for English and Chinese
    (``json3``/``srv3``/``srv2``/``srv1``/``ttml``/``vtt``/``srt``).  If the
    Chinese track is missing, machine-translate the English display units
    (AssemblyAI LLM gateway first, Argos as the keyless floor).  Then render
    the bilingual ASS with the same layout the pipeline burns.

Flow 2 (ASR fallback)
    Only when the caption report *proves* that YouTube has no English track:
    extract mono audio from the local media file, send it to AssemblyAI for a
    word-timed English transcript (faster-whisper when no key is configured),
    translate the display units to Chinese, then render the same ASS.

A failed probe is not proof that a track is absent.  The flow aborts on a
probe error instead of paying for ASR, exactly like ``auto-pipeline.yml``.
Every decision, engine and score is written to ``LOCAL_FLOW.json`` beside the
captions so the choice can be audited later (DIRECTIVE 3.7.4).

Usage::

    python scripts/local_subtitle_flow.py \
        --url "https://youtu.be/<video-id>" --directory "D:\\MyDownload\\a"

    # the folder already holds the seven formats for both languages
    python scripts/local_subtitle_flow.py --directory "D:\\MyDownload\\a" --offline

Exit codes: 0 on success, 1 when a stage fails or the input is incomplete.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import assemblyai_captions  # noqa: E402
import asr_captions  # noqa: E402
import download_youtube_bilingual_srt as captions  # noqa: E402
import fetch_youtube_captions  # noqa: E402
import local_bilingual_ass  # noqa: E402
import machine_translate_captions  # noqa: E402
import subtitle_timing  # noqa: E402

ENGLISH = "en-orig"
CHINESE = "zh-Hans"
FLOW_REPORT = "LOCAL_FLOW.json"
CAPTION_REPORT = "CAPTION_FORMATS.json"
ASR_WORK_DIR = "work"

YOUTUBE = "youtube"
ASR = "asr"
MT = "mt"

# Explicit paths the operator can request with --preset.  Each entry maps to
# the English source, the Chinese source, and whether YouTube may be probed.
# ``auto`` keeps the historical behavior (YouTube first, ASR only when the
# report proves English is absent).
PRESETS: dict[str, dict[str, object]] = {
    # Local media, official YouTube English, official YouTube Chinese.
    "local-youtube-official": {
        "english": YOUTUBE,
        "chinese": YOUTUBE,
        "skip_youtube": False,
    },
    # Local media, official YouTube English, machine-translated Chinese.
    "local-youtube-mt": {
        "english": YOUTUBE,
        "chinese": MT,
        "skip_youtube": False,
    },
    # Local media, ASR English, machine-translated Chinese.
    "local-asr-mt": {
        "english": ASR,
        "chinese": MT,
        "skip_youtube": False,
    },
    # Local media, ASR English, official YouTube Chinese.
    "local-asr-official": {
        "english": ASR,
        "chinese": YOUTUBE,
        "skip_youtube": False,
    },
    # URL only (no local media), official YouTube English and Chinese.
    "url-youtube-official": {
        "english": YOUTUBE,
        "chinese": YOUTUBE,
        "skip_youtube": False,
    },
    # URL only, official YouTube English, machine-translated Chinese.
    "url-youtube-mt": {
        "english": YOUTUBE,
        "chinese": MT,
        "skip_youtube": False,
    },
    # Offline: reuse the local English and Chinese caption files.
    "offline-official": {
        "english": YOUTUBE,
        "chinese": YOUTUBE,
        "skip_youtube": True,
    },
    # Offline: reuse the local English captions and translate Chinese.
    "offline-mt": {
        "english": YOUTUBE,
        "chinese": MT,
        "skip_youtube": True,
    },
}



def log(message: str) -> None:
    print(message, flush=True)


API_KEYS_FILE = Path(__file__).resolve().parents[1] / "input" / "api_keys"


def load_local_api_keys(path: Path | None = None) -> None:
    """Load ``name:value`` lines from the gitignored local key file.

    Environment variables always win, so GitHub Actions secrets and explicit
    shell exports are not shadowed by a stale developer-machine key file.
    """
    path = path or API_KEYS_FILE
    if not path.is_file():
        return
    for number, raw in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        if name and value:
            os.environ.setdefault(name, value)


def assemblyai_key(path: Path | None = None) -> str:
    load_local_api_keys(path)
    for name in ("ASSEMBLYAI", "ASSEMBLYAI_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def has_key() -> bool:
    return bool(assemblyai_key())


def has_track(folder: Path, video_id: str, language: str) -> bool:
    return bool(subtitle_timing.discover_tracks(folder, video_id, language))


def translation_report(folder: Path) -> dict:
    """Return the translation report, or an empty mapping when unreadable."""
    path = folder / "SUBTITLE_SOURCES.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def complete_youtube_pair(folder: Path, video_id: str) -> bool:
    """True when this flow already wrote a full English set and some Chinese.

    Only id-based names are considered: that is what ``fetch_youtube_captions``
    writes.  Title-based folders stay the job of ``local_bilingual_ass.py``.
    Pass ``--refresh`` to probe YouTube again anyway.
    """
    english = subtitle_timing.discover_tracks(folder, video_id, ENGLISH)
    chinese = subtitle_timing.discover_tracks(folder, video_id, CHINESE)
    if not english or not chinese:
        return False
    report = folder / CAPTION_REPORT
    if report.is_file():
        try:
            track = (
                json.loads(report.read_text(encoding="utf-8")).get("tracks", {})
                .get(ENGLISH, {})
            )
        except (OSError, ValueError, AttributeError):
            return False
        published = set(track.get("source_formats") or [])
        written = set(track.get("formats") or [])
        return bool(track.get("present")) and published <= written
    return len(english) == len(subtitle_timing.FORMAT_PRIORITY)


def caption_verdict(report_path: Path) -> str:
    """Classify the caption probe: present, absent, or a transient failure."""
    data = json.loads(report_path.read_text(encoding="utf-8"))
    track = (data.get("tracks") or {}).get(ENGLISH) or {}
    if track.get("present"):
        return "present"
    if track.get("error"):
        return "probe-error"
    return "absent"


def resolve_video_id(
    url: str | None,
    explicit: str | None,
    folder: Path,
    media: Path | None,
) -> str:
    if url:
        resolved = captions.video_id_from_url(url)
        if explicit and explicit != resolved:
            raise ValueError(
                f"--video-id {explicit!r} contradicts the URL id {resolved!r}"
            )
        return resolved
    return local_bilingual_ass.derive_video_id(folder, media, explicit)


def translation_engine(requested: str) -> str:
    if requested != "auto":
        return requested
    return "assemblyai" if has_key() else "argos"


def asr_engine(requested: str) -> str:
    if requested != "auto":
        return requested
    return "assemblyai" if has_key() else "whisper"


def stage(name: str, function, *args) -> None:
    """Run one stage, turning its exit code into an exception."""
    log(f"== {name} ==")
    try:
        code = function(*args)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    except Exception as error:  # noqa: BLE001 - report the stage that failed
        raise RuntimeError(f"{name} failed: {error}") from error
    if code:
        raise RuntimeError(f"{name} failed (exit {code})")


# --------------------------------------------------------------------------
# Stage wrappers.  Tests replace these instead of hitting the network.
# --------------------------------------------------------------------------


def run_youtube_captions(
    folder: Path,
    video_id: str,
    sleep_subtitles: int,
    report: Path,
) -> int:
    return fetch_youtube_captions.main(
        [
            "--video-id",
            video_id,
            "--output-dir",
            str(folder),
            "--groups",
            "en,zh",
            "--sleep-subtitles",
            str(sleep_subtitles),
            "--report",
            str(report),
        ]
    )


def run_translation(
    folder: Path,
    video_id: str,
    engine: str,
    duration: float,
) -> int:
    command = [
        "--caption-dir",
        str(folder),
        "--video-id",
        video_id,
        "--source-language",
        ENGLISH,
        "--target-language",
        CHINESE,
        "--engine",
        engine,
        "--output-dir",
        str(folder),
        "--report",
        str(folder / "SUBTITLE_SOURCES.json"),
    ]
    if duration > 0:
        command += ["--video-duration", f"{duration:.3f}"]
    return machine_translate_captions.main(command)


def run_asr(
    folder: Path,
    video_id: str,
    media: Path,
    engine: str,
    model: str,
) -> int:
    if engine == "assemblyai":
        return assemblyai_captions.main(
            [
                "--video",
                str(media),
                "--video-id",
                video_id,
                "--track",
                ENGLISH,
                "--output-dir",
                str(folder),
                "--work-dir",
                str(folder / ASR_WORK_DIR),
            ]
        )
    return asr_captions.main(
        [
            "--video",
            str(media),
            "--video-id",
            video_id,
            "--track",
            ENGLISH,
            "--model",
            model,
            "--output-dir",
            str(folder),
        ]
    )


def run_ass(folder: Path, video_id: str, args: argparse.Namespace) -> int:
    ass_path = (
        args.ass_output or folder / local_bilingual_ass.DEFAULT_ASS_NAME
    ).expanduser().resolve()
    timing_path = (
        args.timing_report or folder / local_bilingual_ass.DEFAULT_TIMING_NAME
    ).expanduser().resolve()
    command = [
        "--directory",
        str(folder),
        "--video-id",
        video_id,
        "--ass-output",
        str(ass_path),
        "--timing-report",
        str(timing_path),
        "--caption-order",
        args.caption_order,
        "--max-lines",
        str(args.max_lines),
        "--fps",
        str(args.fps),
        "--box-style",
        args.box_style,
    ]
    if args.box_opacity is not None:
        command += ["--box-opacity", str(args.box_opacity)]
    if args.box_color:
        command += ["--box-color", args.box_color]
    command += [
        "--box-x",
        str(args.box_x),
        "--box-y",
        str(args.box_y),
        "--box-width",
        str(args.box_width),
        "--box-height",
        str(args.box_height),
    ]
    if args.strict:
        command.append("--strict")
    return local_bilingual_ass.main(command)


# --------------------------------------------------------------------------
# Flow selection
# --------------------------------------------------------------------------


def apply_preset(args: argparse.Namespace) -> None:
    """Fill the source choices from --preset, keeping explicit flags on top."""
    preset = PRESETS.get(args.preset or "")
    if preset:
        if args.english_source is None:
            args.english_source = str(preset["english"])
        if args.chinese_source is None:
            args.chinese_source = str(preset["chinese"])
        if preset.get("skip_youtube"):
            args.skip_youtube = True
    if args.english_source is None:
        args.english_source = "auto"
    if args.chinese_source is None:
        args.chinese_source = "auto"
    if args.force_asr:
        if args.english_source == YOUTUBE:
            raise ValueError(
                "--force-asr contradicts --english-source youtube"
            )
        # Leave english_source as auto; choose_flow keeps the historical
        # "force-asr" reason for this explicit switch.
    if args.english_source == ASR and args.skip_youtube:
        raise ValueError(
            "--skip-youtube/--offline cannot be combined with --english-source asr"
        )
    if args.english_source == ASR and args.refresh:
        log("warning: --refresh has no effect when --english-source is asr")


def choose_flow(
    folder: Path,
    video_id: str,
    args: argparse.Namespace,
) -> tuple[str, str]:
    """Return ``(flow, reason)`` and make sure flow 1 has its tracks."""
    if args.english_source == ASR:
        log("english-source=asr: skipping the YouTube probe")
        return ASR, "forced-asr"

    if args.force_asr:
        log("force-asr: skipping the YouTube probe")
        return ASR, "force-asr"

    if args.skip_youtube:
        if not has_track(folder, video_id, ENGLISH):
            raise RuntimeError(
                "--skip-youtube needs an existing English caption track; "
                f"none found for {video_id} in {folder}"
            )
        log("skip-youtube: using the captions already in the folder")
        return YOUTUBE, "offline-local"

    if not args.refresh and complete_youtube_pair(folder, video_id):
        log("local captions are complete; skipping the YouTube probe (use --refresh to re-probe)")
        return YOUTUBE, "local-captions"

    report = folder / CAPTION_REPORT
    try:
        run_youtube_captions(folder, video_id, args.sleep_subtitles, report)
    except (Exception, SystemExit) as error:  # noqa: BLE001 - a probe failure is not "absent"
        if has_track(folder, video_id, ENGLISH):
            log(f"warning: caption probe failed ({error}); keeping local captions")
            return YOUTUBE, "local-captions"
        raise RuntimeError(
            "caption probe failed; refusing to guess with ASR "
            f"({error})"
        ) from error

    if not report.is_file():
        if has_track(folder, video_id, ENGLISH):
            log("warning: caption probe wrote no report; keeping local captions")
            return YOUTUBE, "local-captions"
        raise RuntimeError(
            f"caption probe wrote no report at {report}; refusing to guess with ASR"
        )

    verdict = caption_verdict(report)
    if verdict == "present":
        return YOUTUBE, "youtube-english-present"
    if verdict == "probe-error":
        if has_track(folder, video_id, ENGLISH):
            log("warning: English caption download failed; keeping local captions")
            return YOUTUBE, "local-captions"
        raise RuntimeError(
            f"the English caption download failed (see {report}); "
            "treating it as transient instead of paying for ASR"
        )
    if has_track(folder, video_id, ENGLISH):
        log("warning: YouTube no longer lists English captions; reusing the local set")
        return YOUTUBE, "local-captions"
    if args.english_source == YOUTUBE:
        raise RuntimeError(
            "YouTube publishes no English track and --english-source youtube "
            "was requested; rerun with --english-source asr to transcribe "
            "the local media"
        )
    log("YouTube publishes no English track; falling back to ASR")
    return ASR, "youtube-english-absent"


def execute_flow(
    flow: str,
    folder: Path,
    video_id: str,
    media: Path | None,
    args: argparse.Namespace,
    state: dict,
) -> None:
    if args.chinese_source == YOUTUBE and not has_track(
        folder, video_id, CHINESE
    ):
        raise RuntimeError(
            f"no Chinese caption track for {video_id} in {folder}; "
            "rerun with --chinese-source mt to machine-translate the "
            "English track"
        )
    if flow == ASR:
        if media is None:
            raise RuntimeError(
                "flow 2 needs the local media file for ASR; pass --media "
                "or put the video in --directory"
            )
        engine = asr_engine(args.asr_engine)
        if engine == "assemblyai" and not has_key():
            raise RuntimeError(
                "ASSEMBLYAI is not set; pass --asr-engine whisper for the local fallback"
            )
        log(f"ASR engine: {engine}")
        stage("ASR", run_asr, folder, video_id, media, engine, args.asr_model)
        state["asr"] = {"engine": engine, "report": "ASR.json"}
        if not has_track(folder, video_id, ENGLISH):
            raise RuntimeError("ASR produced no English caption track")
    elif not has_track(folder, video_id, ENGLISH):
        raise RuntimeError(
            f"no English caption track for {video_id} in {folder}"
        )

    chinese_present = has_track(folder, video_id, CHINESE)
    needs_translation = args.chinese_source == MT or not chinese_present
    if needs_translation:
        if chinese_present:
            log(
                "chinese-source=mt: replacing the existing Chinese track "
                "with machine translation"
            )
        engine = translation_engine(args.translation_engine)
        log(f"translation engine: {engine}")
        duration = local_bilingual_ass.probe_duration(media) or 0.0
        stage("translation", run_translation, folder, video_id, engine, duration)
        # The translator may fall back (AssemblyAI -> Argos); report what ran.
        actual = str(translation_report(folder).get("engine") or engine)
        state["translation"] = {
            "engine": actual,
            "requested_engine": engine,
            "ran": True,
        }
        if actual != engine:
            log(f"translation fell back to {actual}")
        if not has_track(folder, video_id, CHINESE):
            raise RuntimeError("translation produced no Chinese caption track")
    else:
        log("Chinese track present; skipping translation")
        state["translation"] = {"ran": False}

    stage("ASS", run_ass, folder, video_id, args)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local bilingual caption flow: YouTube seven formats first, "
            "AssemblyAI word-timed ASR only when YouTube has no English track. "
            "Use --preset or --english-source/--chinese-source to force one of "
            "the explicit source dimensions."
        )
    )
    parser.add_argument(
        "--url",
        help="YouTube URL or 11-character id (optional when the file names carry it).",
    )
    parser.add_argument("--video-id", help="YouTube id when --url is omitted.")
    parser.add_argument(
        "--directory",
        default=".",
        type=Path,
        help="Folder with the media file and captions (default: .).",
    )
    parser.add_argument("--media", type=Path, help="Explicit local media file for flow 2.")
    parser.add_argument(
        "--skip-youtube",
        "--offline",
        dest="skip_youtube",
        action="store_true",
        help="Never touch YouTube; use the caption files already in the folder.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Probe YouTube even when the local seven-format set looks complete.",
    )
    parser.add_argument(
        "--preset",
        choices=tuple(PRESETS),
        help=(
            "Explicit source dimension: local/url/offline x YouTube/ASR English "
            "x official/machine Chinese. See docs/LOCAL_FLOW_MATRIX.md."
        ),
    )
    parser.add_argument(
        "--english-source",
        choices=("auto", YOUTUBE, ASR),
        default=None,
        help=(
            "English source: youtube = official track only, asr = transcribe "
            "the local media, auto = current behavior (default: auto)."
        ),
    )
    parser.add_argument(
        "--chinese-source",
        choices=("auto", YOUTUBE, MT),
        default=None,
        help=(
            "Chinese source: youtube = official track only, mt = machine "
            "translation (replaces an existing Chinese track), auto = use "
            "YouTube when present (default: auto)."
        ),
    )
    parser.add_argument(
        "--force-asr",
        action="store_true",
        help="Skip the YouTube probe and transcribe the local media with ASR.",
    )
    parser.add_argument(
        "--asr-engine",
        choices=("auto", "assemblyai", "whisper"),
        default="auto",
        help="ASR backend (default: assemblyai when a key is set, else whisper).",
    )
    parser.add_argument(
        "--asr-model",
        default="base",
        help="faster-whisper model for the keyless fallback (default: base).",
    )
    parser.add_argument(
        "--translation-engine",
        choices=("auto", "assemblyai", "argos", "mymemory"),
        default="auto",
        help="Chinese translation backend (default: assemblyai with a key, else argos).",
    )
    parser.add_argument(
        "--sleep-subtitles",
        "--wait",
        dest="sleep_subtitles",
        type=int,
        default=56,
        help=(
            "Pass the interval to yt-dlp as --sleep-subtitles for Chinese "
            "caption requests; English requests use 0 (default: 56 seconds)."
        ),
    )
    parser.add_argument(
        "--box-style",
        choices=(*captions.BOX_STYLES, "none"),
        default="none",
        help="Caption box behind the text (default: none).",
    )
    parser.add_argument(
        "--box-opacity",
        type=float,
        help="Caption-box opacity from 0 to 1 (default: style setting).",
    )
    parser.add_argument(
        "--box-color",
        help="Solid caption-box color in #RRGGBB form (default: style color).",
    )
    parser.add_argument("--box-x", type=int, default=captions.CAPTION_BOX_AREA[0])
    parser.add_argument("--box-y", type=int, default=captions.CAPTION_BOX_AREA[1])
    parser.add_argument(
        "--box-width",
        type=int,
        default=captions.CAPTION_BOX_AREA[2] - captions.CAPTION_BOX_AREA[0],
    )
    parser.add_argument(
        "--box-height",
        type=int,
        default=captions.CAPTION_BOX_AREA[3] - captions.CAPTION_BOX_AREA[1],
    )
    parser.add_argument(
        "--caption-order",
        choices=("chinese-first", "english-first"),
        default="chinese-first",
        help="Which language sits on the upper ASS line (default: chinese-first).",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        choices=(1, 2),
        default=1,
        help="Lines per language in the ASS (default: 1).",
    )
    parser.add_argument(
        "--fps", type=float, default=24.0, help="Ergonomics frame rate (default: 24)."
    )
    parser.add_argument(
        "--ass-output",
        type=Path,
        help=f"ASS path (default: <folder>/{local_bilingual_ass.DEFAULT_ASS_NAME}).",
    )
    parser.add_argument(
        "--timing-report",
        type=Path,
        help=(
            "Nanosecond sidecar path "
            f"(default: <folder>/{local_bilingual_ass.DEFAULT_TIMING_NAME})."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when the ergonomics report finds an error.",
    )
    return parser


def write_report(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_local_api_keys()
    folder = args.directory.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)

    state: dict = {
        "generated_at": subtitle_timing.utc_now(),
        "status": "failed",
        "source": {"url": args.url, "directory": str(folder)},
    }
    report_path = folder / FLOW_REPORT

    try:
        apply_preset(args)
        media = (
            args.media.expanduser().resolve()
            if args.media
            else local_bilingual_ass.media_file(folder, args.video_id)
        )
        if media is not None and not media.is_file():
            raise RuntimeError(f"media file not found: {media}")
        video_id = resolve_video_id(args.url, args.video_id, folder, media)
        state["video_id"] = video_id
        state["source"]["media"] = media.name if media else None
        log(f"video id: {video_id}")
        log(f"media   : {media.name if media else '(none)'}")

        flow, reason = choose_flow(folder, video_id, args)
        state["flow"] = flow
        state["reason"] = reason
        state["selection"] = {
            "preset": args.preset,
            "english_source": args.english_source,
            "chinese_source": args.chinese_source,
        }
        execute_flow(flow, folder, video_id, media, args, state)

        formats = {
            language: sorted(subtitle_timing.discover_tracks(folder, video_id, language))
            for language in (ENGLISH, CHINESE)
        }
        ass_path = (
            args.ass_output or folder / local_bilingual_ass.DEFAULT_ASS_NAME
        ).expanduser().resolve()
        state.update(
            {
                "status": "ok",
                "formats": formats,
                "caption_report": (
                    CAPTION_REPORT if (folder / CAPTION_REPORT).is_file() else None
                ),
                "outputs": {
                    "ass": ass_path.name,
                    "timing": (
                        args.timing_report
                        or folder / local_bilingual_ass.DEFAULT_TIMING_NAME
                    ).name,
                    "ergonomics": local_bilingual_ass.DEFAULT_ERGONOMICS_NAME,
                    "precision_vtt": [
                        f"{ass_path.stem}.{language}.precision.vtt"
                        for language in (ENGLISH, CHINESE)
                    ],
                },
            }
        )
        write_report(report_path, state)
        log(f"flow    : {flow} ({reason})")
        log(f"report  : {report_path}")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        state["error"] = str(error)
        write_report(report_path, state)
        log(f"error: {error}")
        return 1
    except SystemExit as error:
        state["error"] = f"stage exited with code {error.code}"
        write_report(report_path, state)
        log(f"error: {state['error']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
