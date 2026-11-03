#!/usr/bin/env python3
"""Machine-translate one caption track into another language, keeping timing.

Used when YouTube genuinely has no caption track for the requested language
(DIRECTIVE 3.7).  The source track is the fused YouTube original; the output
keeps deduplicated display-unit timing derived from the source word boundaries,
then writes the standard interchange formats so Module 2 can fuse it like any
other track.

Provenance and the candidate score are written to ``SUBTITLE_SOURCES.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import download_youtube_bilingual_srt as captions  # noqa: E402
import subtitle_timing  # noqa: E402
import subtitle_timeline  # noqa: E402

MYMEMORY_URL = "https://api.mymemory.translated.net/get?q={text}&langpair={pair}"


def log(message: str) -> None:
    print(message, flush=True)


def format_srt(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt(seconds: float) -> str:
    return format_srt(seconds).replace(",", ".")


def write_srt(cues: list[dict], path: Path) -> None:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{format_srt(cue['start'])} --> {format_srt(cue['end'])}\n{cue['text']}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_vtt(cues: list[dict], path: Path) -> None:
    blocks = ["WEBVTT\n"]
    for cue in cues:
        blocks.append(f"{format_vtt(cue['start'])} --> {format_vtt(cue['end'])}\n{cue['text']}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_ttml(cues: list[dict], path: Path) -> None:
    body = "\n".join(
        f'      <p begin="{format_vtt(cue["start"])}" end="{format_vtt(cue["end"])}">'
        f"{escape(cue['text'])}</p>"
        for cue in cues
    )
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<tt xmlns="http://www.w3.org/ns/ttml">\n  <body>\n    <div>\n'
        f"{body}\n    </div>\n  </body>\n</tt>\n",
        encoding="utf-8",
    )


def write_json3(cues: list[dict], path: Path, language: str) -> None:
    events = [
        {
            "tStartMs": int(round(cue["start"] * 1000)),
            "dDurationMs": max(1, int(round((cue["end"] - cue["start"]) * 1000))),
            "segs": [{"utf8": cue["text"], "tOffsetMs": 0}],
        }
        for cue in cues
    ]
    path.write_text(
        json.dumps({"events": events, "wireMagic": "mb1", "lang": language}, ensure_ascii=False),
        encoding="utf-8",
    )


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def build_translation_units(cues: list[dict]) -> list[dict]:
    """Translate deduplicated display phrases instead of isolated rolling cues.

    YouTube rolling captions repeat the previous words in each new event.
    ``build_display_events`` removes those repeats using the original word
    timings, then groups the remaining words into readable, time-bounded units.
    The source cue list is not mutated.
    """
    events = subtitle_timeline.build_display_events(cues)
    units = []
    for english, _ in events:
        if not english:
            continue
        text = " ".join(token.text for token in english)
        text = re.sub(r"\s+([,.;:!?，。、；：！？…])", r"\1", text)
        text = re.sub(r"([(“‘])\s+", r"\1", text).strip()
        start = english[0].start
        end = max(token.end for token in english)
        if text and end > start:
            units.append({"start": start, "end": end, "text": text})
    return units


def translate_mymemory(texts: list[str], source: str, target: str, email: str) -> list[str]:
    pair = f"{source}|{target}"
    translated: list[str] = []
    for index, text in enumerate(texts):
        url = MYMEMORY_URL.format(text=urllib.parse.quote(text[:480]), pair=urllib.parse.quote(pair))
        if email:
            url += f"&de={urllib.parse.quote(email)}"
        last_error = ""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                    timeout=30,
                ) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
                rendered = (payload.get("responseData") or {}).get("translatedText") or ""
                if rendered:
                    translated.append(rendered)
                    break
                last_error = "empty response"
            except Exception as error:  # noqa: BLE001
                last_error = str(error)
            time.sleep(1.5 * (attempt + 1))
        else:
            raise SystemExit(f"MyMemory failed at translation unit {index}: {last_error}")
        if index % 100 == 0:
            log(f"  translated {index}/{len(texts)}")
    return translated


def translate_assemblyai(texts: list[str], source: str, target: str) -> list[str]:
    """Translate display units through the AssemblyAI LLM gateway in JSON batches."""
    key = ""
    for name in ("ASSEMBLYAI", "ASSEMBLYAI_API_KEY"):
        key = os.environ.get(name, "").strip() or key
    if not key:
        raise RuntimeError("ASSEMBLYAI is not set")

    endpoint = "https://llm-gateway.assemblyai.com/v1/chat/completions"
    translated: list[str] = []
    batch_size = 40
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = {
            "model": "gemini-2.5-flash-lite",
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate each complete subtitle display unit using its full "
                        "sentence context. Reply with a JSON object "
                        '{"lines": ["...", ...]} that has exactly one Simplified Chinese '
                        "string per input unit, in the same order. Keep each unit intact; "
                        "do not merge, split or renumber units. Do not add commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"lines": batch}, ensure_ascii=False),
                },
            ],
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"authorization": key, "content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
        content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        content = (
            content.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        try:
            rendered = json.loads(content).get("lines") or []
        except json.JSONDecodeError as error:
            raise RuntimeError(f"AssemblyAI returned non-JSON at batch {start}: {error}") from error
        if len(rendered) != len(batch):
            raise RuntimeError(
                f"AssemblyAI returned {len(rendered)} lines for {len(batch)} inputs at {start}"
            )
        translated.extend(str(line).strip() for line in rendered)
        log(f"  translated {min(start + batch_size, len(texts))}/{len(texts)}")
    return translated


def translate_argos(texts: list[str], source: str, target: str) -> list[str]:
    import argostranslate.package as package
    import argostranslate.translate as translate

    cache = Path.home() / ".local/share/argos-translate/packages"
    installed = translate.get_installed_languages()
    has_pair = any(
        lang.code == source and any(other.code == target for other in lang.translations_from)
        for lang in installed
    )
    if not has_pair:
        log("installing Argos language package...")
        package.update_package_index()
        available = package.get_available_packages()
        match = next(
            (item for item in available if item.from_code == source and item.to_code == target),
            None,
        )
        if match is None:
            raise SystemExit(f"Argos has no package for {source}->{target} (cache {cache})")
        package.install_from_path(match.download())
        installed = translate.get_installed_languages()
    source_lang = next(lang for lang in installed if lang.code == source)
    target_lang = next(lang for lang in installed if lang.code == target)
    return [source_lang.get_translation(target_lang).translate(text) for text in texts]


def score_candidate(
    *,
    bilingual: bool,
    precision: int,
    authority: int,
    coverage: float,
    reproducible: bool,
) -> dict:
    language = 40 if bilingual else 15
    precision_points = precision
    authority_points = authority
    coverage_points = round(max(0.0, min(1.0, coverage)) * 15)
    reproducible_points = 5 if reproducible else 0
    total = language + precision_points + authority_points + coverage_points + reproducible_points
    return {
        "language_coverage": language,
        "timing_precision": precision_points,
        "authority": authority_points,
        "coverage": coverage_points,
        "reproducibility": reproducible_points,
        "total": total,
        "passes_threshold": total >= 60,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Machine-translate a caption track")
    parser.add_argument("--caption-dir", required=True, help="Folder with the source track")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--source-language", default="en-orig")
    parser.add_argument("--target-language", default="zh-Hans")
    parser.add_argument("--engine", choices=("argos", "mymemory", "assemblyai"), default="argos")
    parser.add_argument("--output-dir", help="Where the translated formats are written")
    parser.add_argument("--report", help="SUBTITLE_SOURCES.json path")
    parser.add_argument("--email", default="", help="MyMemory contact email (raises quota)")
    parser.add_argument("--limit", type=int, default=0, help="Translate only the first N cues")
    parser.add_argument("--video-duration", type=float, default=0.0)
    args = parser.parse_args(argv)

    caption_dir = Path(args.caption_dir)
    output_dir = Path(args.output_dir) if args.output_dir else caption_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    tracks = subtitle_timing.build_tracks(
        caption_dir, args.video_id, [args.source_language]
    )
    track = tracks[args.source_language]
    cues = subtitle_timing.to_ass_cues(track)
    if args.limit:
        cues = cues[: args.limit]
    log(f"source cues: {len(cues)} from {track['primary_format']}")

    units = build_translation_units(cues)
    if not units:
        raise ValueError(f"No translatable subtitle units found for {args.video_id}")
    texts = [unit["text"] for unit in units]
    unique = list(dict.fromkeys(texts))
    log(f"deduplicated rolling captions into {len(texts)} display units")
    log(f"unique translation units: {len(unique)}")

    engine_used = args.engine
    if args.engine == "assemblyai":
        try:
            rendered_unique = translate_assemblyai(unique, "en", "zh")
        except Exception as error:  # noqa: BLE001 - keep the local engine as a floor
            log(f"AssemblyAI translation failed ({error}); falling back to Argos")
            engine_used = "argos"
            rendered_unique = translate_argos(unique, "en", "zh")
    elif args.engine == "argos":
        rendered_unique = translate_argos(unique, "en", "zh")
    else:
        rendered_unique = translate_mymemory(unique, "en", "zh", args.email)
    if len(rendered_unique) != len(unique):
        raise RuntimeError(
            f"Translation returned {len(rendered_unique)} results for {len(unique)} units"
        )
    mapping = dict(zip(unique, rendered_unique))
    translated = [mapping[text] for text in texts]

    out_cues = [
        {"start": unit["start"], "end": unit["end"], "text": text}
        for unit, text in zip(units, translated)
    ]

    write_srt(out_cues, output_dir / f"{args.video_id}.{args.target_language}.srt")
    write_vtt(out_cues, output_dir / f"{args.video_id}.{args.target_language}.vtt")
    write_ttml(out_cues, output_dir / f"{args.video_id}.{args.target_language}.ttml")
    write_json3(
        out_cues,
        output_dir / f"{args.video_id}.{args.target_language}.json3",
        args.target_language,
    )

    duration = args.video_duration or out_cues[-1]["end"]
    covered = out_cues[-1]["end"] - out_cues[0]["start"]
    score = score_candidate(
        bilingual=True,
        precision=18,
        authority=6,
        coverage=covered / duration if duration else 0.0,
        reproducible=True,
    )
    report_path = Path(args.report) if args.report else output_dir / "SUBTITLE_SOURCES.json"
    report = {
        "video_id": args.video_id,
        "generated_at": subtitle_timing.utc_now(),
        "target_language": args.target_language,
        "engine": engine_used,
        "requested_engine": args.engine,
        "source_track": {
            "language": args.source_language,
            "format": track["primary_format"],
            "formats_used": track["formats_used"],
            "cues": len(cues),
            "translation_units": len(units),
        },
        "candidates": [
            {
                "id": f"{args.target_language}-{engine_used}",
                "kind": "machine-translated",
                "engine": engine_used,
                "formats": ["srt", "vtt", "ttml", "json3"],
                "notes": "srv1/srv2/srv3 are YouTube-internal serializations and are not synthesized",
                "score": score,
            }
        ],
        "selected": f"{args.target_language}-{engine_used}",
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {len(out_cues)} cues; score {score['total']}/100")
    log(f"report: {report_path}")
    return 0 if score["passes_threshold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
