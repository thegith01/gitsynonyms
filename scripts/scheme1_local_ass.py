#!/usr/bin/env python3
"""Build the Scheme 1 cue-aligned bilingual ASS from a local caption folder.

Scheme 1 is deliberately smaller than the fused seven-format timeline:

* the English SRT cue is the display unit, and its end is trimmed to the next
  cue's start (the rolling-caption correction);
* every English cue carries exactly one Chinese line, so each ASS event is one
  bilingual cue with no merging and no re-timing;
* the bilingual SRT is rendered by ``scheme1_srt_to_ass`` with one line per
  language.

When YouTube publishes a Chinese track with the *same* cue boundaries as the
English SRT (the reference example), it is used as-is.  A rolling Chinese track
has its own sentence boundaries and cannot be paired one-to-one; in that case
the English cues are translated individually through the configured engine so
the Scheme 1 shape is preserved.  ``SCHEME1.json`` records which path ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Sequence

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_youtube_bilingual_srt as captions  # noqa: E402
import local_bilingual_ass  # noqa: E402
import machine_translate_captions  # noqa: E402
import scheme1_srt_to_ass  # noqa: E402
import subtitle_ergonomics  # noqa: E402
import subtitle_layout  # noqa: E402
import subtitle_timing  # noqa: E402

ENGLISH = "en-orig"
CHINESE = "zh-Hans"
DEFAULT_ASS_NAME = "bilingual_scheme1_Chinese-English.ass"
DEFAULT_SRT_NAME = "bilingual_scheme1_Chinese-English.srt"
DEFAULT_REPORT_NAME = "SCHEME1.json"
DEFAULT_ERGONOMICS_NAME = "ASS_ERGONOMICS.json"
DEFAULT_CACHE_NAME = "SCHEME1_TRANSLATIONS.json"
API_KEYS_FILE = Path(__file__).resolve().parents[1] / "input" / "api_keys"

# English SRT is the reference display transcript.  The other formats are
# fallbacks for folders where the SRT was not published.
ENGLISH_ORDER = ("srt", "vtt", "ttml", "json3", "srv3", "srv2", "srv1")
# Chinese SRT is what the reference example pairs with English.  If it is not
# cue-aligned, the rolling formats are equally unusable for Scheme 1, so the
# order only decides which candidate is inspected first.
CHINESE_ORDER = ("srt", "vtt", "ttml", "json3", "srv3", "srv2", "srv1")


def log(message: str) -> None:
    print(message, flush=True)


def load_local_api_keys(path: Path | None = None) -> None:
    """Load ``name:value`` lines without shadowing an explicit environment."""
    path = path or API_KEYS_FILE
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        if name and value:
            os.environ.setdefault(name, value)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\r", " ").replace("\n", " ")).strip()


def parse_cues(files: dict[str, Path], order: Sequence[str], label: str) -> tuple[list[dict], Path]:
    """Parse the first readable format and trim rolling-cue overlaps."""
    for extension in order:
        path = files.get(extension)
        if path is None:
            continue
        try:
            cues = captions.parse_caption_file(path)
        except (OSError, ValueError):
            continue
        cues = [
            {**cue, "text": clean_text(cue.get("text", ""))}
            for cue in captions._without_rolling_cues(cues)
            if clean_text(cue.get("text", ""))
        ]
        if cues:
            return cues, path
    raise ValueError(
        f"no readable {label} caption format in {', '.join(files)}"
    )


def same_timeline(left: Sequence[dict], right: Sequence[dict], tolerance: float = 0.002) -> bool:
    if len(left) != len(right):
        return False
    return all(
        abs(float(a["start"]) - float(b["start"])) <= tolerance
        and abs(float(a["end"]) - float(b["end"])) <= tolerance
        for a, b in zip(left, right)
    )


def find_aligned_chinese(
    files: dict[str, Path],
    english: Sequence[dict],
) -> tuple[list[dict] | None, Path | None]:
    """Return a Chinese track only when it matches the English cue grid."""
    for extension in CHINESE_ORDER:
        path = files.get(extension)
        if path is None:
            continue
        try:
            cues = captions.parse_caption_file(path)
        except (OSError, ValueError):
            continue
        cues = [
            {**cue, "text": clean_text(cue.get("text", ""))}
            for cue in captions._without_rolling_cues(cues)
            if clean_text(cue.get("text", ""))
        ]
        if cues and same_timeline(cues, english):
            return cues, path
    return None, None


def load_cache(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(key): str(value)
        for key, value in (data.get("lines") or {}).items()
        if str(key).strip() and str(value).strip()
    }


def write_cache(path: Path, lines: dict[str, str]) -> None:
    path.write_text(
        json.dumps({"lines": lines}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def translate_missing(
    texts: Sequence[str],
    cache: dict[str, str],
    *,
    engine: str,
    model: str | None,
    max_chars: int,
) -> tuple[dict[str, str], str]:
    """Translate the texts not already in the cache; return the engine used."""
    missing = [text for text in dict.fromkeys(texts) if text not in cache]
    if not missing:
        return cache, "cache"
    log(f"translating {len(missing)} unique English cues ({engine})")
    if engine == "assemblyai":
        try:
            rendered = machine_translate_captions.translate_assemblyai(
                missing, "en", "zh", model=model, max_chars=max_chars
            )
            used = "assemblyai"
        except Exception as error:  # noqa: BLE001 - keep the local engine as a floor
            log(f"AssemblyAI translation failed ({error}); falling back to Argos")
            try:
                rendered = machine_translate_captions.translate_argos(
                    missing, "en", "zh"
                )
            except Exception as argos_error:  # noqa: BLE001
                raise RuntimeError(
                    f"AssemblyAI failed ({error}) and Argos is unavailable "
                    f"({argos_error}); install argostranslate or fix the gateway"
                ) from argos_error
            used = "argos"
    elif engine == "argos":
        rendered = machine_translate_captions.translate_argos(missing, "en", "zh")
        used = "argos"
    elif engine == "mymemory":
        rendered = machine_translate_captions.translate_mymemory(
            missing, "en", "zh", ""
        )
        used = "mymemory"
    else:
        raise ValueError(f"unsupported translation engine: {engine!r}")
    if len(rendered) != len(missing):
        raise RuntimeError(
            f"translation returned {len(rendered)} lines for {len(missing)} cues"
        )
    for text, translated in zip(missing, rendered):
        value = clean_text(translated)
        if not value:
            raise ValueError(f"translation produced an empty line for {text!r}")
        cache[text] = value
    return cache, used


def split_overlong_english(cues: Sequence[dict], max_chars: int) -> list[dict]:
    """Split an overlong English cue at a word boundary, preserving order."""
    result: list[dict] = []
    for cue in cues:
        text = clean_text(cue["text"])
        if len(text) <= max_chars:
            result.append({**cue, "text": text})
            continue
        lines = subtitle_layout.wrap_caption(
            text, "en", max_chars=max_chars, max_lines=1
        )
        if len(lines) < 2:
            result.append({**cue, "text": text})
            continue
        total = sum(len(line) for line in lines)
        cursor = float(cue["start"])
        duration = float(cue["end"]) - cursor
        for index, line in enumerate(lines):
            end = float(cue["end"]) if index == len(lines) - 1 else cursor + duration * len(line) / total
            result.append({**cue, "start": cursor, "end": end, "text": line})
            cursor = end
    return result


def build(
    folder: Path,
    video_id: str,
    media: Path | None,
    *,
    ass_path: Path | None = None,
    srt_path: Path | None = None,
    report_path: Path | None = None,
    ergonomics_path: Path | None = None,
    cache_path: Path | None = None,
    engine: str = "assemblyai",
    model: str | None = None,
    force_mt: bool = False,
    box_style: str = "none",
    box_color: str | None = None,
    box_opacity: float | None = None,
    caption_order: str = "chinese-first",
    fps: float = 24.0,
    strict: bool = False,
    limit: int = 0,
) -> dict:
    """Build the Scheme 1 ASS and return the audit report."""
    folder = Path(folder)
    media_stem = media.stem if media else None
    english_files = local_bilingual_ass.discover_formats(
        folder, video_id, ENGLISH, media_stem
    )
    if not english_files:
        raise ValueError(f"no English caption formats for {video_id} in {folder}")
    english, english_source = parse_cues(english_files, ENGLISH_ORDER, "English")
    english = split_overlong_english(
        english, subtitle_layout.max_chars_for("en")
    )
    if limit:
        english = english[:limit]
        force_mt = True

    chinese_files = local_bilingual_ass.discover_formats(
        folder, video_id, CHINESE, media_stem
    )
    chinese: list[dict] | None = None
    chinese_source: Path | None = None
    if chinese_files and not force_mt:
        chinese, chinese_source = find_aligned_chinese(chinese_files, english)

    max_chinese = subtitle_layout.max_chars_for("zh-Hans")
    translation_engine = "official"
    cache: dict[str, str] = {}
    if chinese is None:
        cache_file = cache_path or folder / DEFAULT_CACHE_NAME
        cache = load_cache(cache_file)
        texts = [cue["text"] for cue in english]
        cache, translation_engine = translate_missing(
            texts,
            cache,
            engine=engine,
            model=model,
            max_chars=max_chinese,
        )
        write_cache(cache_file, cache)
        chinese = [
            {**cue, "text": cache[cue["text"]]}
            for cue in english
        ]
        chinese_source = cache_file

    overlong = [
        cue for cue in chinese if len(clean_text(cue["text"])) > max_chinese
    ]
    if overlong:
        preview = ", ".join(
            f"{cue['start']:.2f}s:{len(clean_text(cue['text']))}c"
            for cue in overlong[:6]
        )
        raise ValueError(
            f"{len(overlong)} Chinese cues exceed {max_chinese} characters "
            f"({preview}); shorten the translation before rendering"
        )

    bilingual_srt = captions.build_scheme1_bilingual_srt(chinese, english)
    destination_srt = (srt_path or folder / DEFAULT_SRT_NAME).expanduser().resolve()
    destination_srt.parent.mkdir(parents=True, exist_ok=True)
    destination_srt.write_text(bilingual_srt, encoding="utf-8")

    destination_ass = (ass_path or folder / DEFAULT_ASS_NAME).expanduser().resolve()
    style = {"box_style": box_style, "caption_order": caption_order}
    if box_color:
        style["box_color"] = box_color
    if box_opacity is not None:
        style["box_opacity"] = box_opacity
    scheme1_srt_to_ass.convert_srt_to_ass(
        destination_srt, destination_ass, **style
    )

    ergonomics_file = (
        ergonomics_path or folder / DEFAULT_ERGONOMICS_NAME
    ).expanduser().resolve()
    ergonomics = subtitle_ergonomics.analyze_subtitle(destination_ass, fps=fps)
    subtitle_ergonomics.write_report(ergonomics_file, ergonomics)
    summary = ergonomics["summary"]
    log(
        "ergonomics: "
        f"{subtitle_ergonomics.summary_line(ergonomics)} "
        f"(report: {ergonomics_file.name})"
    )
    for issue in ergonomics["issues"][:8]:
        log(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")

    report = {
        "generated_at": subtitle_timing.utc_now(),
        "video_id": video_id,
        "ass": destination_ass.name,
        "bilingual_srt": destination_srt.name,
        "ergonomics": ergonomics_file.name,
        "english": {
            "source": english_source.name,
            "cues": len(english),
        },
        "chinese": {
            "source": chinese_source.name if chinese_source else None,
            "kind": "official-aligned" if translation_engine == "official" else "machine-translated",
            "engine": translation_engine,
            "cues": len(chinese),
        },
        "cue_count": len(english),
        "translation_cache": (
            None if translation_engine == "official" else (cache_path or folder / DEFAULT_CACHE_NAME).name
        ),
        "style": {
            "box_style": box_style,
            "caption_order": caption_order,
            "max_english_lines": 1,
            "max_chinese_lines": 1,
        },
        "ergonomics_summary": summary,
    }
    report_file = (report_path or folder / DEFAULT_REPORT_NAME).expanduser().resolve()
    report_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log(f"scheme1: {len(english)} bilingual cues -> {destination_ass}")
    log(f"report : {report_file}")
    if strict and summary["errors"]:
        raise ValueError(
            f"ergonomics found {summary['errors']} errors; see {ergonomics_file.name}"
        )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Scheme 1 cue-aligned bilingual ASS."
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--ass-output", type=Path)
    parser.add_argument("--srt-output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ergonomics-report", type=Path)
    parser.add_argument("--translation-cache", type=Path)
    parser.add_argument(
        "--engine",
        choices=("assemblyai", "argos", "mymemory"),
        default="assemblyai",
    )
    parser.add_argument("--model", help="AssemblyAI LLM Gateway model.")
    parser.add_argument(
        "--force-mt",
        action="store_true",
        help="Ignore an aligned official Chinese track and translate instead.",
    )
    parser.add_argument(
        "--box-style",
        choices=(*captions.BOX_STYLES, "none"),
        default="none",
    )
    parser.add_argument("--box-color")
    parser.add_argument("--box-opacity", type=float)
    parser.add_argument(
        "--caption-order",
        choices=("chinese-first", "english-first"),
        default="chinese-first",
    )
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Translate and render only the first N English cues (smoke test).",
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_local_api_keys()
    try:
        build(
            args.directory,
            args.video_id,
            args.media,
            ass_path=args.ass_output,
            srt_path=args.srt_output,
            report_path=args.report,
            ergonomics_path=args.ergonomics_report,
            cache_path=args.translation_cache,
            engine=args.engine,
            model=args.model,
            force_mt=args.force_mt,
            box_style=args.box_style,
            box_color=args.box_color,
            box_opacity=args.box_opacity,
            caption_order=args.caption_order,
            fps=args.fps,
            strict=args.strict,
            limit=args.limit,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Scheme 1 ASS failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
