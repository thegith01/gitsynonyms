# Agent entry point

The highest-level instruction for this repository is [`DIRECTIVE.md`](DIRECTIVE.md).
Every agent, account, machine and harness must read it before doing any work.

- `DIRECTIVE.md` is the constitutional authority; `organization/` contains
  subordinate concrete organization rules made under that authority.
  `organization/chart.json` is the machine-readable ladder, not a sketch.
- Record authorized internal unit/process changes in `organization/`; revise
  `DIRECTIVE.md` only when a constitutional principle, authority, or root-level
  hierarchy changes.
- 职能层级 部→司→处→科→组，区域层级 省→市→县→乡→村；模块1/2/3 为部级单位，
  各司归部管辖（`DIRECTIVE.md` 2.1）。总控下辖资源与巡检部、模块1情报与素材部、
  模块2视频处理部、模块3发布与治理部。模块1负责监测、事件归纳与素材获取，模块2
  只处理上游已选定的视频与字幕，模块3负责上传、发布后整改、PDCA 与全流程监察。
- Inspection granularity: one record per smallest independently observable unit
  (MIU); aggregation is allowed in reports only.
- Registries: `inspection/registry.json` (MIU) and `resources/registry.json`
  (one URL per record; designated White House channels must stay live and mapped
  to a real collector).

If a request conflicts with `DIRECTIVE.md`, follow the directive and say so
instead of silently doing the other thing.

## Hard constraints

- **No media in the repo.** The machine stores code, captions, JSON and small
  web assets only. Raw video, burns, audio and archives live on the cloud runner
  and filebin; `output/**/*.mp4|webm|m4a` is gitignored. Never `git add -f` them.
- **Only web exception:** `site/media/<video-id>-preview.mp4` and
  `<video-id>-poster.jpg` are committed deliverables, produced on a cloud runner
  by `make-preview.yml` or the burn workflow. Do not replace the homepage player
  with a YouTube iframe, and never point a `<video>` at the multi-GB Release
  asset (it is an attachment without reliable Range support).
- **Pipeline order:** burn → back up → publish. Jekyll (`jekyll-gh-pages.yml`)
  is the only Pages publisher. Do not add `actions/deploy-pages` to
  `module2-burn.yml` or `auto-pipeline.yml`; older `full-pipeline.yml` /
  `infogap.yml` still contain that call, do not copy the pattern.
- **Sources:** prefer direct download, then the proxy pool; no YouTube cookies
  and no random GitHub accounts. Burn only sources at 1080p or better.
- **Captions:** every film needs Chinese and English. Take YouTube's seven
  formats first (`json3`, `srv3`, `srv2`, `srv1`, `ttml`, `vtt`, `srt`); use
  web comparison / ASR / MT only when they are absent.

## Verify before pushing

CI order (`infogap.yml` validate job):

```bash
python -m pip install -e . pytest
python -m pytest -q
python scripts/resources/check.py check
python scripts/inspection/plan.py check --github
python scripts/org_chart.py check
python scripts/publishing_registry.py check
```

Focused subtitle checks (the regression-prone area):

```bash
python -m pytest -q tests/test_subtitle_layout.py tests/test_subtitle_timeline.py \
  tests/test_subtitle_timing.py tests/test_local_youtube_script.py
```

Tests import `scripts/*.py` directly and add `scripts/` to `sys.path`; run them
from the repository root. `scripts/` is not an installed package —
`pyproject.toml` packages only `src/gitsynonyms`.

### Local environment on this machine

- **Python:** conda env `a`, not `base`:
  `C:\Users\a2023\anaconda3\envs\a\python.exe -X utf8 -m pytest -q`.
  Install once with
  `C:\Users\a2023\anaconda3\envs\a\python.exe -m pip install -e . pytest`.
  `base` (Anaconda) is missing the editable `gitsynonyms` package and will fail
  collection on `tests/test_gitsynonyms.py`, `test_youtube*.py`.
- **GitHub:** the live remote is `gitsynonyms02/gitsynonyms`, so `gh` must be
  authenticated as `gitsynonyms02`
  (`gh auth switch --user gitsynonyms02`, then `gh auth status`). The old
  `gitsynonyms01` account is suspended; `codespaces02` has no access and makes
  every Actions call return 404. If `gh` reports 404 for a repo that exists,
  check the active account before assuming the repo is gone.

## Subtitle rendering rules

- `CAPTION_AREA = (96, 883, 1824, 1008)` (5% side margins), text anchored with
  `\an2` at `area_bottom - 8`, `WrapStyle: 0`. Do not restore `WrapStyle: 2`;
  that is what let long lines run off the frame.
- `scripts/subtitle_layout.py` wraps: zh ≤28 full-width chars/line, en ≤60
  chars/line. Cue-aligned bilingual events are built to fit exactly one line per
  language; the two-line budget is only an overflow guard for single-language
  fallbacks. Closing punctuation never starts a line. Bilingual ASS keeps its
  configured font sizes and splits overwide events at timed token boundaries;
  it does not shrink individual events to fit.
- `scripts/subtitle_timeline.py` builds one monotonic token timeline and
  disjoint display events. When both tracks are full parallel transcripts,
  translation cue starts define the display units and each unit carries the
  English words whose midpoints fall inside it, so every event has both
  languages and neither line needs wrapping. **Do not re-emit all cues active
  at each boundary** — that is what duplicated the previous sentence. Every
  word must render once, and every spoken word must render.
- English karaoke starts come from `json3` `tStartMs + tOffsetMs` (millisecond
  source). ASS karaoke is centisecond-quantized by the format; `TIMING.json`
  keeps the nanosecond sidecar. Do not evenly distribute when real word timings
  exist.
- Collapse only immediate ASR stutters from closed-class words (`I I`, `the the`);
  never drop repetition that carries meaning.
- Translate rolling YouTube cues only after de-duplicating their source words
  into readable time-aligned display units. Keep the Immersive Translate
  v1.34.4 release as an independent behavioral comparison baseline; do not copy
  its proprietary implementation or claim an unmeasured quality win.

## Cloud operations

```bash
gh workflow run infogap.yml -f tests_only=true
gh workflow run module2-burn.yml -f video_id=<id> -f stage=full
gh workflow run make-preview.yml -f video_id=<id>
gh workflow run republish-site.yml
gh run view <run-id> --log
```

- `proxy-pool.yml` keeps the three-tier public proxy pool: tier 1 collects up
  to 1,000,000 proxies every 6 hours, tier 2 keeps the 10,000 fastest
  HTTPS-capable proxies every 30 minutes, tier 3 keeps the 1,000 proxies that
  passed a real `yt-dlp` extraction plus ranged download every 15 minutes.
  `auto-pipeline.yml` restores the tier-3 cache before downloading, so a
  blocked run starts from verified proxies instead of the stale committed
  `proxyindex/alive_http.txt`. Run one tier manually with
  `gh workflow run proxy-pool.yml -f tier=3`.

- `monitor-whitehouse.yml` runs every 5 minutes. Use
  `gh workflow disable monitor-whitehouse.yml` / `enable` around manual runs.
- `auto-pipeline.yml` is the full chain (probe/test/full); it is also callable
  from the monitor. `module2-burn.yml` re-burns an archived film from filebin.
- `make-preview.yml` downloads the Release, cuts a 720p montage and poster,
  regenerates `site/`, and commits both. Preview must stay under 40 MB.
- `republish-site.yml` only regenerates `site/` from the committed `output/`
  archive; it does not touch media.

## Local caption flows

`scripts/local_subtitle_flow.py` is the single local entry point for the two
caption paths allowed by `DIRECTIVE.md` 3.7. It never downloads the video; it
uses the media already in `--directory` and fetches only captions or audio.

```bash
# Flow 1: YouTube has an English track (manual or auto-generated)
python scripts/local_subtitle_flow.py --url "https://youtu.be/<id>" --directory "D:\MyDownload\a"

# Flow 2: the caption report proves YouTube has no English track
python scripts/local_subtitle_flow.py --url "https://youtu.be/<id>" --directory "D:\MyDownload\a"
```

- **Flow 1** calls `fetch_youtube_captions.py` for every published
  `json3`/`srv3`/`srv2`/`srv1`/`ttml`/`vtt`/`srt` file in `en-orig` and
  `zh-Hans`. If YouTube publishes no Chinese track, it machine-translates the
  English display units (AssemblyAI LLM gateway first, Argos without a key),
  then renders the ASS with `local_bilingual_ass.py`. Each subtitle-format
  requests use yt-dlp's `--sleep-subtitles 56` by default; English is not delayed.
  `--sleep-subtitles` overrides the Chinese request interval (`--wait` is a
  compatibility alias), not a process-level workflow pause.
- **Flow 2** runs only when `CAPTION_FORMATS.json` says the English track is
  *absent*. A probe error is transient: the flow aborts instead of paying for
  ASR. It extracts mono audio from the local media, transcribes word-timed
  English with AssemblyAI (`ASSEMBLYAI`), translates to Chinese through the
  same gateway, then renders the same ASS. Without a key it falls back to
  faster-whisper + Argos.
- `LOCAL_FLOW.json` records the flow, reason, engines, output formats and the
  explicit `selection` (`preset`, `english_source`, `chinese_source`).
- Explicit source dimensions are selected with `--preset`:
  `local-youtube-official`, `local-youtube-mt`, `local-asr-mt`,
  `local-asr-official`, `url-youtube-official`, `url-youtube-mt`,
  `offline-official`, `offline-mt`. Copy-paste PowerShell commands for all
  eight are in `docs/LOCAL_FLOW_MATRIX.md`. `--english-source youtube|asr|auto`
  and `--chinese-source youtube|mt|auto` are the lower-level switches.
- `scripts/local_subtitle_flow.ps1` runs the presets from PowerShell. `-List`
  prints one copy-paste command per preset for line-by-line execution;
  `-Preset a,b`, `-All -Yes`, `-DryRun`, `-KeepGoing` and `-LogPath` cover batch
  and dry-run use. Every invocation is appended as one JSON line to
  `<Directory>\LOCAL_FLOW_COMMANDS.jsonl`; the Python decision record stays in
  `<Directory>\LOCAL_FLOW.json`. The command log is gitignored.
- `scripts/manual_local_flow.ps1` is the human-operated command notebook:
  `-List` prints Chinese notes plus one copy-paste command per step,
  `-Step 1,3,5` runs selected steps, and `-All -Yes` runs the main path
  (0-3, 5, 6, 9, 10; 4/7/8 are manual alternatives). The URL is the first positional
  parameter. It logs every external command to
  `<OutDir>\MANUAL_FLOW_COMMANDS.jsonl`.
- `scripts/manual_youtube_commands.ps1` is the raw command notebook: edit
  `$Url`, `$OutDir` and `$Run` at the top, then change the literal
  `yt-dlp`/`ffmpeg` lines in place. `$Run = @(1)` runs one step,
  `@(1,3,5)` runs several, and `@(0,1,2,3,5,6,9,10)` runs the main path.
- `--force-asr` skips the probe; `--refresh` re-probes even a complete local
  set; `--skip-youtube` (alias `--offline`) uses only the files already there.
- When a source banner overlaps the subtitle area, set a persistent box
  explicitly, for example `--box-style solid-color --box-color "#000000"
  --box-opacity 1`; the local default remains `none` for clean sources.
- For manual per-format downloads on Windows, use PowerShell and keep each
  format separate so the source file and wait are auditable:

```powershell
$formats = @("vtt", "srt", "ttml", "srv3", "srv2", "srv1", "json3")
$url = "https://www.youtube.com/watch?v=<id>"
foreach ($fmt in $formats) {
    Write-Host "Downloading $fmt"
    yt-dlp --write-auto-subs --sub-langs "zh-Hans" --sub-format $fmt `
        --skip-download --sleep-subtitles 56 -o "%(title)s.%(ext)s" $url
}
```

## Local caption folder

A manually downloaded video with the fourteen caption files (seven per
language) can be turned into the ASS without any cloud run:

```bash
python scripts/local_bilingual_ass.py --directory "D:\MyDownload\a"
```

It finds the video id in the media name (or takes `--video-id`), fuses all
seven formats per language, and writes `bilingual_precise_Chinese-English.ass`,
`TIMING.json`, the two 1 ms precision VTT sidecars and `ASS_ERGONOMICS.json`
next to the media. The local default is one line per language (`--max-lines 1`);
a dense Chinese phrase shrinks to fit instead of adding a third line. The
pipeline keeps its two-line overflow guard.

## Repository map

- `scripts/download_youtube_bilingual_srt.py`: download/parse the seven
  formats, fuse cues, write ASS/SRT/VTT, burn with ffmpeg.
- `scripts/local_bilingual_ass.py`: local ASS-only build from a hand-made
  caption folder; `--strict` fails on ergonomics errors.
- `scripts/local_subtitle_flow.py`: two-flow local entry point (YouTube seven
  formats, AssemblyAI word-timed ASR fallback); writes `LOCAL_FLOW.json`.
- `scripts/subtitle_timing.py`: seven-format fusion, nanosecond sidecar,
  `build_precise_ass`.
- `scripts/subtitle_layout.py`, `scripts/subtitle_timeline.py`,
  `scripts/subtitle_ergonomics.py`: wrapping, disjoint events, CPS/layout QC.
- `scripts/video_processing.py`: probe/burn orchestration; `tts_dub.py` and
  `voice_clone_dub.py` are Module 2 voice production.
- Module 1: `scripts/monitoring/`, `scripts/verify_event.py`,
  `scripts/rank_video_sources.py`, `scripts/footage_quality.py`.
- Module 3: `scripts/publishing_registry.py`, `publishing/registry.json`,
  `scripts/generate_video_pages.py`, `site/`.
- Archives: `output/<date>_<event>_<video-id>/` (JSON/INFO/subtitles only).
  `site/videos/<id>.html` is generated; `site/media/` holds only previews.

## Gotchas

- `README.md` is stale: it still mentions `deploy-pages.yml`,
  `scripts/full_pipeline.sh` and cookie-based 480p downloads. Trust the
  workflows and scripts over it.
- `MODULE2_ORG.md` at the root predates `organization/`; the latter is canonical.
- Windows PowerShell may display Chinese as mojibake; files are UTF-8. Use
  `python -X utf8` when printing Chinese for diagnosis.
- Workflow `gh` commands need a clean working tree before `gh workflow run` if
  the workflow commits back to `main`.
