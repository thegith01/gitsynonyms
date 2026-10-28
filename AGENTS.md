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

## Subtitle rendering rules

- `CAPTION_AREA = (96, 883, 1824, 1008)` (5% side margins), text anchored with
  `\an2` at `area_bottom - 8`, `WrapStyle: 0`. Do not restore `WrapStyle: 2`;
  that is what let long lines run off the frame.
- `scripts/subtitle_layout.py` wraps: zh ≤16 full-width chars/line, en ≤42
  chars/line, ≤2 lines/language, balanced lines, closing punctuation never
  starts a line, font shrinks before overflow.
- `scripts/subtitle_timeline.py` builds one monotonic token timeline and
  disjoint display events. **Do not re-emit all cues active at each boundary** —
  that is what duplicated the previous sentence. Every word must render once,
  and every spoken word must render.
- English karaoke starts come from `json3` `tStartMs + tOffsetMs` (millisecond
  source). ASS karaoke is centisecond-quantized by the format; `TIMING.json`
  keeps the nanosecond sidecar. Do not evenly distribute when real word timings
  exist.
- Collapse only immediate ASR stutters from closed-class words (`I I`, `the the`);
  never drop repetition that carries meaning.

## Cloud operations

```bash
gh workflow run infogap.yml -f tests_only=true
gh workflow run module2-burn.yml -f video_id=<id> -f stage=full
gh workflow run make-preview.yml -f video_id=<id>
gh workflow run republish-site.yml
gh run view <run-id> --log
```

- `monitor-whitehouse.yml` runs every 5 minutes. Use
  `gh workflow disable monitor-whitehouse.yml` / `enable` around manual runs.
- `auto-pipeline.yml` is the full chain (probe/test/full); it is also callable
  from the monitor. `module2-burn.yml` re-burns an archived film from filebin.
- `make-preview.yml` downloads the Release, cuts a 720p montage and poster,
  regenerates `site/`, and commits both. Preview must stay under 40 MB.
- `republish-site.yml` only regenerates `site/` from the committed `output/`
  archive; it does not touch media.

## Repository map

- `scripts/download_youtube_bilingual_srt.py`: download/parse the seven
  formats, fuse cues, write ASS/SRT/VTT, burn with ffmpeg.
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
