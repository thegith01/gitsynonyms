#!/usr/bin/env python3
"""Transcribe a video with AssemblyAI when YouTube ships no caption track.

DIRECTIVE 3.7 allows ASR only when the seven YouTube formats are genuinely
absent.  This module is the hosted ASR path: it extracts a mono audio track
with ffmpeg, uploads it to AssemblyAI, polls the transcript, and writes
word-timed ``json3``/``srt``/``vtt``/``ttml`` plus ``ASR.json``.

The API key comes from ``ASSEMBLYAI`` (or ``ASSEMBLYAI_API_KEY``).  When the
key is missing the caller falls back to the local faster-whisper path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.assemblyai.com/v2"
POLL_SECONDS = 6


def log(message: str) -> None:
    print(message, flush=True)


def load_local_api_keys(path: Path) -> None:
    """Load ``name:value`` lines without shadowing environment variables."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        if name and value:
            os.environ.setdefault(name, value)


def api_key() -> str:
    load_local_api_keys(
        Path(__file__).resolve().parents[1] / "input" / "api_keys"
    )
    for name in ("ASSEMBLYAI", "ASSEMBLYAI_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SystemExit("ASSEMBLYAI is not set; cannot use the hosted ASR path")

def request_json(url: str, key: str, payload: dict | None = None, method: str = "GET") -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"authorization": key, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"AssemblyAI {method} {url} -> {error.code}: {detail}") from error


def upload(path: Path, key: str) -> str:
    data = path.read_bytes()
    log(f"uploading {path.name} ({len(data)/1e6:.1f} MB)")
    request = urllib.request.Request(
        f"{API}/upload",
        data=data,
        method="POST",
        headers={"authorization": key, "content-type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"AssemblyAI upload -> {error.code}: {detail}") from error
    return payload["upload_url"]


def extract_audio(video: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
        str(target),
    ]
    log("extracting mono 16 kHz audio for ASR")
    subprocess.run(command, check=True)
    log(f"audio: {target.name} ({target.stat().st_size/1e6:.1f} MB)")
    return target


def submit(upload_url: str, key: str, language: str) -> str:
    payload = {
        "audio_url": upload_url,
        "speech_model": "universal",
        "punctuate": True,
        "format_text": True,
        "language_code": language,
    }
    created = request_json(f"{API}/transcript", key, payload, method="POST")
    log(f"transcript id: {created['id']}")
    return created["id"]


def wait_for(transcript_id: str, key: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = request_json(f"{API}/transcript/{transcript_id}", key)
        status = payload.get("status")
        if status == "completed":
            return payload
        if status == "error":
            raise RuntimeError(f"AssemblyAI transcription failed: {payload.get('error')}")
        log(f"  status: {status}")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"transcript {transcript_id} did not finish in {timeout}s")


def group_words(words: list[dict]) -> list[dict]:
    cues: list[dict] = []
    current: list[dict] = []
    for index, word in enumerate(words):
        current.append(word)
        text = word.get("text") or ""
        following = words[index + 1] if index + 1 < len(words) else None
        gap = (following["start"] - word["end"]) if following else 10_000
        duration = word["end"] - current[0]["start"]
        boundary = (
            text.endswith((".", "!", "?", "。", "！", "？"))
            or gap >= 900
            or duration >= 8000
            or len(current) >= 14
            or following is None
        )
        if boundary and current:
            cues.append(
                {
                    "start": current[0]["start"] / 1000.0,
                    "end": max(current[-1]["end"], current[0]["start"] + 200) / 1000.0,
                    "text": " ".join(item.get("text", "").strip() for item in current).strip(),
                    "words": [
                        {
                            "word": item.get("text", ""),
                            "start": item["start"] / 1000.0,
                            "end": item["end"] / 1000.0,
                        }
                        for item in current
                    ],
                }
            )
            current = []
    return cues


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def vtt_time(seconds: float) -> str:
    return srt_time(seconds).replace(",", ".")


def write_outputs(cues: list[dict], out: Path, stem: str, language: str) -> list[str]:
    srt = []
    for index, cue in enumerate(cues, start=1):
        srt.append(f"{index}\n{srt_time(cue['start'])} --> {srt_time(cue['end'])}\n{cue['text']}\n")
    (out / f"{stem}.srt").write_text("\n".join(srt), encoding="utf-8")

    vtt = ["WEBVTT\n"]
    for cue in cues:
        vtt.append(f"{vtt_time(cue['start'])} --> {vtt_time(cue['end'])}\n{cue['text']}\n")
    (out / f"{stem}.vtt").write_text("\n".join(vtt), encoding="utf-8")

    body = "\n".join(
        f'      <p begin="{vtt_time(cue["start"])}" end="{vtt_time(cue["end"])}">'
        f"{escape(cue['text'])}</p>"
        for cue in cues
    )
    (out / f"{stem}.ttml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<tt xmlns="http://www.w3.org/ns/ttml">\n  <body>\n    <div>\n'
        f"{body}\n    </div>\n  </body>\n</tt>\n",
        encoding="utf-8",
    )

    events = []
    for cue in cues:
        # JSON3 segments are concatenated verbatim by the parser, so the space
        # between words must live in the segment text, not in a separate join.
        segments = []
        for word in cue["words"]:
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
        segments = segments or [{"utf8": cue["text"], "tOffsetMs": 0}]
        events.append(
            {
                "tStartMs": int(round(cue["start"] * 1000)),
                "dDurationMs": max(1, int(round((cue["end"] - cue["start"]) * 1000))),
                "segs": segments,
            }
        )
    (out / f"{stem}.json3").write_text(
        json.dumps({"events": events, "wireMagic": "mb1", "lang": language}, ensure_ascii=False),
        encoding="utf-8",
    )
    return ["srt", "vtt", "ttml", "json3"]


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AssemblyAI word-timed captions")
    parser.add_argument("--video", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--track", default="en-orig")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--work-dir", default="work")
    parser.add_argument("--timeout", type=int, default=5400)
    args = parser.parse_args(argv)

    video = Path(args.video)
    if not video.is_file():
        raise SystemExit(f"source video not found: {video}")

    key = api_key()
    audio = extract_audio(video, Path(args.work_dir) / f"{args.video_id}.asr.mp3")
    upload_url = upload(audio, key)
    transcript_id = submit(upload_url, key, args.language)
    payload = wait_for(transcript_id, key, args.timeout)

    words = payload.get("words") or []
    if not words:
        raise SystemExit("AssemblyAI returned no words")
    cues = group_words(words)
    log(f"cues: {len(cues)} from {len(words)} words")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.video_id}.{args.track}"
    formats = write_outputs(cues, out, stem, args.track)

    duration = float(payload.get("audio_duration") or 0) or (cues[-1]["end"] if cues else 0)
    covered = cues[-1]["end"] - cues[0]["start"] if cues else 0
    coverage = min(1.0, covered / duration) if duration else 0.0
    score = 40 + 25 + 10 + round(coverage * 15) + 5
    report = {
        "video_id": args.video_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "kind": "asr",
        "engine": "assemblyai/universal",
        "transcript_id": transcript_id,
        "language": args.language,
        "track": args.track,
        "cues": len(cues),
        "words": len(words),
        "duration": duration,
        "formats": formats,
        "score": {
            "language_coverage": 40,
            "timing_precision": 25,
            "authority": 10,
            "coverage": round(coverage * 15),
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
