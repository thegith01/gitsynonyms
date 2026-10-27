#!/usr/bin/env python3
"""Add a TTS dub track to a video, aligned to subtitle cue timings.

Speaks the chosen language line of an SRT/VTT file with a catalogue TTS
voice (edge-tts) and mixes it over the original audio.

This module deliberately does NOT clone a real person's voice. Voice
cloning requires the speaker's written consent and a locally licensed
model; point --voice at a catalogue voice instead.

Usage:
  python3 scripts/tts_dub.py --video in.mp4 --subtitle zh.srt \\
      --output out.mp4 --voice zh-CN-XiaoxiaoNeural --original-gain 0.25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BATCH_SIZE = 25


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def probe_duration(path: Path) -> float:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]).stdout
    return float(json.loads(out)["format"]["duration"])


def ts_to_seconds(value: str) -> float:
    h, m, rest = value.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_subtitles(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    blocks = [b for b in text.split("\n\n") if "-->" in b]
    cues: list[dict] = []
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_raw, end_raw = lines[timing_index].split("-->")
        body = " ".join(lines[timing_index + 1:]).strip()
        if not body:
            continue
        start = ts_to_seconds(start_raw.strip().split(" ")[0])
        end = ts_to_seconds(end_raw.strip().split(" ")[0])
        if end <= start:
            continue
        cues.append({"start": start, "end": end, "text": body})
    cues.sort(key=lambda c: c["start"])
    return cues


def pick_line(text: str, mode: str) -> str:
    """Bilingual SRT puts one language per line; pick by script."""
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        return ""
    if mode == "first":
        return parts[0]
    if mode == "second":
        return parts[-1]
    for part in parts:
        if any("\u4e00" <= ch <= "\u9fff" for ch in part):
            return part
    return parts[0]


async def synth_cues(cues: list[dict], voice: str, rate: str, work: Path) -> list[Path]:
    import edge_tts  # imported lazily so the module can be linted without it

    paths: list[Path] = []
    semaphore = asyncio.Semaphore(4)

    async def one(index: int, text: str) -> Path:
        target = work / f"cue_{index:05d}.mp3"
        async with semaphore:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(target))
        return target

    tasks = [one(i, cue["text"]) for i, cue in enumerate(cues)]
    paths = await asyncio.gather(*tasks)
    return list(paths)


def build_dub_track(cues: list[dict], clips: list[Path], total: float, work: Path) -> Path:
    """Lay each clip at its cue start over silence, in bounded batches."""
    batch_files: list[Path] = []
    for batch_index, offset in enumerate(range(0, len(cues), BATCH_SIZE)):
        batch = cues[offset:offset + BATCH_SIZE]
        batch_clips = clips[offset:offset + BATCH_SIZE]
        start = batch[0]["start"]
        end = max(c["end"] for c in batch) + 0.5
        span = max(end - start, 0.5)
        inputs: list[str] = ["-f", "lavfi", "-t", f"{span:.3f}", "-i", "anullsrc=r=24000:cl=mono"]
        filters: list[str] = []
        for i, (cue, clip) in enumerate(zip(batch, batch_clips), start=1):
            inputs += ["-i", str(clip)]
            delay = max(int((cue["start"] - start) * 1000), 0)
            filters.append(f"[{i}:a]adelay={delay}|{delay}[a{i}]")
        mix_inputs = "".join(f"[a{i}]" for i in range(1, len(batch) + 1))
        filters.append(f"[0:a]{mix_inputs}amix=inputs={len(batch) + 1}:normalize=0:dropout_transition=0[mix]")
        out = work / f"batch_{batch_index:04d}.wav"
        run([
            "ffmpeg", "-y", "-v", "error", *inputs,
            "-filter_complex", ";".join(filters), "-map", "[mix]",
            "-c:a", "pcm_s16le", str(out),
        ])
        batch_files.append(out)

    if not batch_files:
        raise RuntimeError("no subtitle cues were usable for dubbing")

    concat_list = work / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in batch_files) + "\n",
        encoding="utf-8",
    )
    track = work / "dub.wav"
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-t", f"{total:.3f}",
        "-c:a", "pcm_s16le", str(track),
    ])
    return track


def mux(video: Path, dub: Path, output: Path, original_gain: float) -> None:
    if original_gain <= 0:
        run([
            "ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(dub),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-shortest", str(output),
        ])
        return
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(dub),
        "-filter_complex",
        f"[0:a]volume={original_gain}[bg];[bg][1:a]amix=inputs=2:normalize=0:duration=longest[aout]",
        "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", str(output),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="TTS dub a video from its subtitles")
    parser.add_argument("--video", required=True)
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--line", choices=["auto", "first", "second"], default="auto")
    parser.add_argument("--original-gain", type=float, default=0.25,
                        help="0 keeps dub only; 1 keeps original at full level")
    args = parser.parse_args()

    video = Path(args.video)
    subtitle = Path(args.subtitle)
    output = Path(args.output)
    for path in (video, subtitle):
        if not path.is_file():
            print(f"missing input: {path}", file=sys.stderr)
            return 1
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ffmpeg/ffprobe not on PATH", file=sys.stderr)
        return 1
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("edge-tts is required: pip install edge-tts", file=sys.stderr)
        return 1

    cues = parse_subtitles(subtitle)
    if not cues:
        print("no cues parsed from subtitle", file=sys.stderr)
        return 1
    for cue in cues:
        cue["text"] = pick_line(cue["text"], args.line)
    cues = [c for c in cues if c["text"]]
    total = probe_duration(video)

    print(f"cues: {len(cues)}, voice: {args.voice}, video: {total:.1f}s", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        clips = asyncio.run(synth_cues(cues, args.voice, args.rate, work))
        print(f"synthesised {len(clips)} clips", flush=True)
        dub = build_dub_track(cues, clips, total, work)
        output.parent.mkdir(parents=True, exist_ok=True)
        mux(video, dub, output, args.original_gain)
    print(f"wrote {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
