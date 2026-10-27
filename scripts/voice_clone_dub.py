#!/usr/bin/env python3
"""Consent-gated few-shot voice cloning dub.

Clone ONLY a speaker who has given written authorisation: yourself, or a
voice actor you hired. The module refuses to run without a consent file and
prepends an audible synthetic-speech disclosure by default.

It does not bundle or download model weights. Point --backend-command at a
local zero-shot TTS CLI (GPT-SoVITS, CosyVoice 2, F5-TTS, OpenVoice V2 ...):

  --backend-command 'python /opt/GPT-SoVITS/api_v2.py --ref {ref} --text {text} --out {out}'

Placeholders: {ref} {text} {out} {language}.

Consent file (JSON), required:
  {
    "speaker_name": "Zhang San",
    "relationship": "self" | "hired_voice_actor" | "written_permission",
    "authorised": true,
    "evidence": "signed-release-2026-10-27.pdf",
    "valid_until": "2027-10-27"
  }
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts_dub import build_dub_track, mux, parse_subtitles, pick_line, probe_duration  # noqa: E402

DISCLOSURE_TEXT = "\u4ee5\u4e0b\u97f3\u9891\u4e3a\u4eba\u5de5\u5408\u6210\u8bed\u97f3\uff0c\u4ec5\u7528\u4e8e\u6f14\u793a\u3002"
REQUIRED_KEYS = {"speaker_name", "relationship", "authorised", "evidence"}
ALLOWED_RELATIONSHIPS = {"self", "hired_voice_actor", "written_permission"}


def load_consent(path: Path, speaker: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"consent file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise SystemExit(f"consent file missing keys: {sorted(missing)}")
    if data["authorised"] is not True:
        raise SystemExit("consent file says authorised != true; refusing to clone")
    if data["relationship"] not in ALLOWED_RELATIONSHIPS:
        raise SystemExit(
            f"relationship must be one of {sorted(ALLOWED_RELATIONSHIPS)}, "
            f"got {data['relationship']!r}"
        )
    if speaker and data["speaker_name"].strip().casefold() != speaker.strip().casefold():
        raise SystemExit(
            f"--speaker {speaker!r} does not match consent speaker_name "
            f"{data['speaker_name']!r}"
        )
    if not str(data.get("evidence", "")).strip():
        raise SystemExit("consent file must name the signed evidence document")
    valid_until = data.get("valid_until")
    if valid_until:
        try:
            expiry = date.fromisoformat(valid_until)
        except ValueError as error:
            raise SystemExit(f"valid_until is not ISO date: {valid_until!r}") from error
        if expiry < date.today():
            raise SystemExit(f"consent expired on {valid_until}; obtain fresh authorisation")
    return data


def synth(text: str, ref: Path, out: Path, template: str, language: str) -> None:
    command = template.format(ref=shlex.quote(str(ref)), text=shlex.quote(text),
                              out=shlex.quote(str(out)), language=language)
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        raise SystemExit(
            f"backend failed (exit {result.returncode}): {(result.stderr or result.stdout)[:400]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Consent-gated 8s voice-clone dub")
    parser.add_argument("--video", required=True)
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--reference", required=True, help="6-10s clean speech of the AUTHORISED speaker")
    parser.add_argument("--consent", required=True, help="JSON consent file")
    parser.add_argument("--speaker", default="", help="must equal consent speaker_name")
    parser.add_argument("--backend-command", required=True,
                        help="local zero-shot TTS command with {ref} {text} {out} {language}")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--output", required=True)
    parser.add_argument("--original-gain", type=float, default=0.2)
    parser.add_argument("--no-disclosure", action="store_true",
                        help="NOT recommended; removes the audible synthetic-speech notice")
    args = parser.parse_args()

    consent = load_consent(Path(args.consent), args.speaker)
    print(f"consent ok: {consent['speaker_name']} ({consent['relationship']}), "
          f"evidence={consent['evidence']}", flush=True)

    video = Path(args.video)
    subtitle = Path(args.subtitle)
    reference = Path(args.reference)
    for path in (video, subtitle, reference):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")

    ref_seconds = probe_duration(reference)
    if ref_seconds < 3:
        raise SystemExit(f"reference audio is {ref_seconds:.1f}s; provide at least 3s")
    print(f"reference: {ref_seconds:.1f}s", flush=True)

    cues = parse_subtitles(subtitle)
    for cue in cues:
        cue["text"] = pick_line(cue["text"], "auto")
    cues = [c for c in cues if c["text"]]
    if not cues:
        raise SystemExit("no usable subtitle cues")

    total = probe_duration(video)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        clips: list[Path] = []
        shift = 0.0
        if not args.no_disclosure:
            notice = work / "disclosure.wav"
            synth(DISCLOSURE_TEXT, reference, notice, args.backend_command, args.language)
            shift = min(probe_duration(notice), max(total - 1.0, 0.5))
            clips.append(notice)
            schedule = [{"start": 0.0, "end": shift, "text": DISCLOSURE_TEXT}]
            for cue in cues:
                start_at = cue["start"] + shift
                if start_at >= total:
                    continue
                schedule.append({
                    "start": start_at,
                    "end": min(cue["end"] + shift, total),
                    "text": cue["text"],
                })
            cues = schedule
        for index, cue in enumerate(cues[len(clips):], start=len(clips)):
            out = work / f"cue_{index:05d}.wav"
            synth(cue["text"], reference, out, args.backend_command, args.language)
            clips.append(out)
        print(f"synthesised {len(clips)} clips (disclosure shift {shift:.1f}s)", flush=True)
        dub = build_dub_track(cues, clips, total, work)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        mux(video, dub, Path(args.output), args.original_gain)
    print(f"wrote {args.output}", flush=True)
    print("REMINDER: keep the synthetic-speech disclosure; labelling is mandatory in CN/EU.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
