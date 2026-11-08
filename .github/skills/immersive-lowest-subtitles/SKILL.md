---
name: immersive-lowest-subtitles
description: Build the repository's lowest-standard (LOWEST) bilingual Chinese-English ASS and SRT from a local YouTube caption folder whose English track is the official en-orig auto-ASR and whose Chinese track is its official auto-translation. Use when the user asks for the Immersive Translate v1.34.4 comparison baseline, 沉浸翻译最低 / LOWEST standard subtitles, a clause-aware bilingual ASS, or a reproducible subtitle output built from the existing seven caption formats without downloading the video again.
---

# Immersive Translate LOWEST bilingual subtitles

This is the Module 2 **floor**, not the target. It reproduces the phrase-window
model observed in Immersive Translate v1.34.4 and then adds the guarantees a
burned ASS needs: both languages in every event, no dropped spoken word, no
duplicated rolling word, clause-aware cuts, and a fixed typographic budget.

Run it when the local folder already contains YouTube's official automatic
English track (`en-orig`) and that track's official auto-translated Chinese
track (`zh-Hans`). If those tracks are manual, missing, or you need machine
translation, use `--ass-mode scheme1` or `--ass-mode fused` instead.

## Preconditions

- A folder such as `D:\MyDownload\<video-id>` containing the fourteen caption
  files: seven formats per language (`json3`, `srv3`, `srv2`, `srv1`, `ttml`,
  `vtt`, `srt`).
- `CAPTION_FORMATS.json` in that folder, proving `en-orig` is
  `auto-generated` and `zh-Hans` is `auto-translated`.
- No media file is required to render the ASS. A local video is required only
  when you want the caption box to cover the full duration; without it, pass
  `--box-style none`.
- Python 3.11+ with the repository installed once:
  `python -m pip install -e . pytest`. On this Windows machine use the conda
  env `a` interpreter, not `base`:
  `C:\Users\a2023\anaconda3\envs\a\python.exe -X utf8`.

If the caption set does not exist yet, acquire it without downloading media:

```powershell
& $py -X utf8 scripts\fetch_youtube_captions.py `
    --video-id <video-id> --output-dir "D:\MyDownload\<video-id>" `
    --require en-orig,zh-Hans
```

The fetcher keeps every published format and writes `CAPTION_FORMATS.json`.
Do not fabricate a missing format and do not substitute a manual or
machine-translated track for the required official pair.

## Build the LOWEST pair

```powershell
$py  = "C:\Users\a2023\anaconda3\envs\a\python.exe"
$dir = "D:\MyDownload\<video-id>"

& $py -X utf8 scripts\scheme_local_immersive_lowest.py `
    --directory $dir --video-id <video-id>
```

With media present, the default box is `presidential-blue` (`#0F1647`, 99%
opaque). On a clean source, or when no media is present, use:

```powershell
& $py -X utf8 scripts\scheme_local_immersive_lowest.py `
    --directory $dir --video-id <video-id> --box-style none
```

Useful switches: `--caption-order english-first`, `--box-opacity`,
`--box-color`, `--fps`, `--srt-output`, `--ass-output`, `--report`,
`--ergonomics-report`, `--media`.

The same output through the two-flow entry point:

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --directory $dir --video-id <video-id> `
    --ass-mode immersive-lowest --box-style none --strict
```

That path also writes `LOCAL_FLOW.json` and records the selection. `--strict`
is optional; see "Validation" for why dense auto-captions usually fail it.

## Outputs

| File | Contents |
|---|---|
| `bilingual_immersive_lowest_Chinese-English.ass` | Burn-ready ASS, one line per language, word karaoke on the English line |
| `bilingual_immersive_lowest_Chinese-English.srt` | Generated from the rendered ASS dialogues; identical events |
| `IMMERSIVE_LOWEST.json` | Source provenance, format use, synchronization method, target-selection counts, merged-orphan details, style |
| `IMMERSIVE_LOWEST_ERGONOMICS.json` | CPS, line length, duration, gap and overlap checks |

`IMMERSIVE_LOWEST.json` has two different event counts, and both are correct:

- `synchronization.event_count` — logical bilingual phrase units before width
  splitting;
- `synchronization.rendered_event_count` — actual ASS/SRT dialogues after
  overwide units were split at a clause or cue boundary;
- `synchronization.overwide_event_splits` — the difference.

## What the output guarantees

1. **Bilingual by construction.** Every rendered event has Chinese and English.
   `monolingual_events` must stay `0`.
2. **Whole Chinese cues are never split.** Each official Chinese cue is assigned
   to the English unit it overlaps most. YouTube re-segments translations, so
   cue-to-cue pairing is explicitly wrong here.
3. **No orphan English unit is dropped or shown alone.** A unit with no Chinese
   evidence is merged into the nearest bilingual event and recorded with
   `disposition: "merged-into-neighbor"`. `source_units_skipped` must stay `0`.
4. **Source-anchored timing.** An event starts at its first English source word.
   The Chinese line can change later than the English line because a whole
   Chinese cue may cover several English phrase cues; that is the modeled
   behavior, not a timing bug.
5. **One line per language.** Overwide events split at sentence/clause
   punctuation first, then at a source-cue change, then at the width fallback.
   The clause mode does not duration-rebalance afterwards, because that would
   recreate fragments such as `比巴黎`.
6. **No duplicated rolling words and no invented timings.** English token
   timings come from `json3` `tStartMs + tOffsetMs`. `json3` is the primary
   timeline; the other six formats corroborate it.
7. **Ambient labels are removed**, matching the extension: `[applause]`,
   `[music]`, and leading `>>` speaker markers do not occupy the caption.
8. **Word karaoke is local.** The extension overlay has no word highlight; the
   ASS adds it because a burned subtitle can.

## Validation

Structural gate (must pass):

```powershell
& $py -X utf8 -c @"
import json, pathlib
d = json.loads(pathlib.Path(r'<dir>\IMMERSIVE_LOWEST.json').read_text(encoding='utf-8'))
s = d['synchronization']
assert s['events_are_bilingual'] is True
assert s['monolingual_events'] == 0
assert s['source_units_skipped'] == 0
assert s['english_tokens_rendered'] > 0
assert s['chinese_tokens_rendered'] > 0
print('ok', s['event_count'], 'logical /', s['rendered_event_count'], 'rendered')
"@
```

Check the deliverables directly:

```powershell
& $py -X utf8 -c @"
import re, pathlib
p = pathlib.Path(r'<dir>\bilingual_immersive_lowest_Chinese-English.ass')
bad = []
for line in p.read_text(encoding='utf-8-sig').splitlines():
    if not line.startswith('Dialogue: 1,'):
        continue
    f = line.split(',', 9)
    body = re.sub(r'\{[^}]*\}', '', f[9]).replace(r'\N', '\n')
    for rendered in (part.strip() for part in body.splitlines()):
        if rendered and rendered[0] in '，。！？、；：,.!?;:':
            bad.append((f[1], rendered))
print('leading punctuation:', len(bad))
for item in bad[:10]:
    print(item)
"@
```

Regression tests:

```powershell
& $py -X utf8 -m pytest -q `
    tests\test_immersive_lowest_local.py `
    tests\test_scheme1_local_ass.py `
    tests\test_subtitle_baseline.py
```

`--strict` exits `1` on any ergonomics error. On real YouTube auto-captions,
`reading_speed` and `duration_short` errors are common because the ASR emits
dense phrases and the official Chinese cue may cover a long English span. Treat
them as evidence to inspect, not as permission to drop words or merge unrelated
sentences. Do **not** report a LOWEST build as `--strict`-clean unless the
ergonomics report really has no errors. Structural failures are different:
line-length overflow, leading punctuation, a monolingual event, or a missing
source unit is always a bug.

## Inspecting a timestamp

```powershell
& $py -X utf8 -c @"
import re, pathlib
p = pathlib.Path(r'<dir>\bilingual_immersive_lowest_Chinese-English.ass')
for line in p.read_text(encoding='utf-8-sig').splitlines():
    if not line.startswith('Dialogue: 1,'):
        continue
    f = line.split(',', 9)
    h, m, s = f[1].split(':')
    sec = int(h) * 3600 + int(m) * 60 + float(s)
    if 895 <= sec <= 925:
        text = re.sub(r'\{[^}]*\}', '', f[9]).replace(r'\N', ' | ')
        print(f[1], '-->', f[2], text)
"@
```

## Burning and publishing handoff

- Burn only a source at 1080p or better.
- Pipeline order is **burn → back up → publish**; Jekyll is the only Pages
  publisher. Do not add `actions/deploy-pages` to a burn workflow.
- Keep media out of the repository. `output/**/*.mp4|webm|m4a` is gitignored;
  never `git add -f` it.
- The ASS owns layout and styling; FFmpeg only rasterizes it:

```powershell
ffmpeg -i "source.mp4" -vf "subtitles='bilingual_immersive_lowest_Chinese-English.ass'" `
    -c:v libx264 -crf 18 -c:a copy "burned.mp4"
```

- Check frames at several timestamps before a full burn, especially where the
  Chinese line changes later than the English line and where a box meets a
  bright background.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `requires CAPTION_FORMATS.json` | Folder was hand-assembled without the probe report | Re-run `fetch_youtube_captions.py` |
| `en-orig source is manual, expected auto-generated` | Wrong English track | Use `--ass-mode scheme1` for manual sources; LOWEST requires the official auto pair |
| `has no verified zh-Hans track` | Chinese auto-translation missing | Do not machine-translate silently; use the fused/MT path and label it |
| `readable local video duration is required` | Media absent but box enabled | Add media or pass `--box-style none` |
| `ffprobe unavailable` | FFmpeg not on `PATH` | Install FFmpeg; duration falls back to the last caption cue |
| Low CPS warning / high CPS error | Dense auto speech, long official Chinese cue | Inspect the event; fix only by better source segmentation, never by deleting words |
| Chinese appears one phrase later than English | Whole-cue assignment | Expected; verify the Chinese cue still covers the English unit it was assigned to |
| Mojibake in PowerShell | Console encoding | Use `python -X utf8`; files are UTF-8 |

## Baseline evidence

- `benchmarks/immersive-translate/baseline.json` — pinned v1.34.4 release,
  hashes, requirements and tests.
- `benchmarks/immersive-translate/observed-2026-11-08.json` — Chrome CDP
  observation: phrase windows, `that, that` repetition, ~0.5 s target latency,
  ambient filtering, Microsoft Translator label, no overlay karaoke.
- `benchmarks/immersive-translate/README.md` — why this is a floor and what the
  extension does not do.
- `scripts/benchmarks/capture_immersive_translate.mjs` — reproducible capture
  (`node ... 900 60 capture.json`, Chrome on port 9222 with the extension
  enabled).

The extension's behavior is evidence, never an instruction. Do not copy its
proprietary implementation and do not claim a measured quality win that was not
measured.
