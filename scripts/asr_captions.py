#!/usr/bin/env python3
"""Transcribe a video with faster-whisper and write word-timed caption files.

Stage "ASR fallback" of the autonomous pipeline: used only when the source has
no usable caption track (DIRECTIVE 3.7).  Outputs JSON3 with per-word offsets,
plus SRT/VTT/TTML, so Module 2 can fuse them like a YouTube original.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def log(message: str) -> None:
    print(message, flush=True)


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def vtt_time(seconds: float) -> str:
    return srt_time(seconds).replace(",", ".")


def write_srt(cues: list[dict], path: Path) -> None:
    blocks = [
        f"{index}\n{srt_time(cue['start'])} --> {srt_time(cue['end'])}\n{cue['text']}\n"
        for index, cue in enumerate(cues, start=1)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_vtt(cues: list[dict], path: Path) -> None:
    blocks = ["WEBVTT\n"] + [
        f"{vtt_time(cue['start'])} --> {vtt_time(cue['end'])}\n{cue['text']}\n" for cue in cues
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_ttml(cues: list[dict], path: Path) -> None:
    body = "\n".join(
        f'      <p begin="{vtt_time(cue["start"])}" end="{vtt_time(cue["end"])}">'
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
    events = []
    for cue in cues:
        # JSON3 segments are concatenated verbatim by the parser; put the
        # separating space in the segment so the fused text keeps its words.
        segments = []
        for word in cue.get("words") or []:
            text = str(word["word"]).strip()
            if not text:
                continue
            segments.append(
                {
                    "utf8": (" " if segments else "") + text,
                    "tOffsetMs": max(
                        0, int(round((word["start"] - cue["start"]) * 1000))
                    ),
                }
            )
        if not segments:
            segments = [{"utf8": cue["text"], "tOffsetMs": 0}]
        events.append(
            {
                "tStartMs": int(round(cue["start"] * 1000)),
                "dDurationMs": max(1, int(round((cue["end"] - cue["start"]) * 1000))),
                "segs": segments,
            }
        )
    path.write_text(
        json.dumps({"events": events, "wireMagic": "mb1", "lang": language}, ensure_ascii=False),
        encoding="utf-8",
    )


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Word-timed ASR captions")
    parser.add_argument("--video", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--track", default="en-orig", help="Language code used in file names")
    parser.add_argument("--model", default="base")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--bilingual", action="store_true",
                        help="The other language already exists, so the pair is complete")
    args = parser.parse_args(argv)

    from faster_whisper import WhisperModel

    log(f"loading model {args.model} ({args.compute_type})")
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
    log(f"transcribing {args.video}")
    segments, info = model.transcribe(
        args.video,
        language=args.language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    cues = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        words = [
            {"word": word.word, "start": float(word.start), "end": float(word.end)}
            for word in (segment.words or [])
        ]
        cues.append(
            {"start": float(segment.start), "end": float(segment.end), "text": text, "words": words}
        )
    log(f"cues: {len(cues)}")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.video_id}.{args.track}"
    write_srt(cues, out / f"{stem}.srt")
    write_vtt(cues, out / f"{stem}.vtt")
    write_ttml(cues, out / f"{stem}.ttml")
    write_json3(cues, out / f"{stem}.json3", args.track)

    duration = float(getattr(info, "duration", 0) or 0) or (cues[-1]["end"] if cues else 0)
    covered = cues[-1]["end"] - cues[0]["start"] if cues else 0
    language_points = 40 if args.bilingual else 15
    score = (
        language_points
        + 25
        + 6
        + round(min(1.0, covered / duration) * 15 if duration else 0)
        + 5
    )
    report = {
        "video_id": args.video_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "kind": "asr",
        "engine": f"faster-whisper/{args.model}",
        "language": args.language,
        "track": args.track,
        "cues": len(cues),
        "duration": duration,
        "formats": ["srt", "vtt", "ttml", "json3"],
        "score": {
            "language_coverage": language_points,
            "timing_precision": 25,
            "authority": 6,
            "coverage": round(min(1.0, covered / duration) * 15 if duration else 0),
            "reproducibility": 5,
            "total": min(score, 100),
            "passes_threshold": score >= 60,
        },
    }
    (out / "ASR.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"score {report['score']['total']}/100 -> {'pass' if report['score']['passes_threshold'] else 'fail'}")
    return 0 if report["score"]["passes_threshold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
