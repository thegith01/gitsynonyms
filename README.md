
# 🎬 视频下载与中英字幕生成 / 刻录 / 部署流水线

本项目展示了一个完整的视频字幕处理流水线，支持从 YouTube 下载视频、提取自动生成的英文字幕、生成中文字幕、将字幕刻录到视频中，最后部署输出。

**目标视频**: [https://www.youtube.com/watch?v=9aPyO1jfDGM](https://www.youtube.com/watch?v=9aPyO1jfDGM)  
**视频时长**: 3小时16分11秒  
**字幕条数**: 6,281 条  
**支持语言**: 英文 (en) → 中文 (zh)

---

## 📁 项目结构

```
/workspace/
├── README.md                      # 本说明文档
├── bin/                           # 二进制工具
│   ├── ffmpeg                     # FFmpeg 音视频处理工具
│   └── ffprobe                    # FFprobe 媒体信息工具
├── scripts/                       # 处理脚本
│   ├── full_pipeline.sh           # 主流水线脚本（编排所有步骤）
│   ├── burn_subtitles.sh          # 字幕刻录脚本（ffmpeg 烧录字幕）
│   ├── deploy.sh                  # 部署脚本（打包输出并生成 manifest）
│   ├── subtitle_processor.py      # WebVTT → SRT 转换 + 中文字幕生成
│   ├── subtitle_converter.py      # WebVTT 转 SRT 转换工具
│   └── generate_chinese_subtitles.py  # 中文字幕生成（模拟翻译）
├── videos/                        # 输入视频与原始字幕
│   ├── *.en.vtt                   # YouTube 自动生成英文字幕 (WebVTT 格式)
│   ├── english_subtitles.srt      # 转换后的英文 SRT 字幕
│   └── chinese_subtitles.srt      # 生成的中文 SRT 字幕
├── processed_videos/              # 中间处理输出（刻录后视频等）
└── deployed/                      # 最终部署输出
    ├── final_with_subtitles.mp4   # 刻录字幕后的最终视频
    ├── english_subtitles.srt      # 英文字幕
    ├── chinese_subtitles.srt      # 中文字幕
    └── manifest.json              # 部署清单
```

---

## 🚀 快速开始

### 1. 环境准备

确保已安装以下工具：

```bash
# 检查 ffmpeg 和 yt-dlp
which ffmpeg ffprobe yt-dlp python3

# 如需安装 ffmpeg（Debian/Ubuntu）
apt-get update && apt-get install -y ffmpeg

# 安装 yt-dlp
pip3 install yt-dlp
```

本项目已预置 `bin/ffmpeg` 和 `bin/ffprobe`（静态编译版本）。

### 2. 下载视频与英文字幕

由于 YouTube 反爬虫保护，下载视频需要携带 Cookies 认证：

```bash
# 下载视频 + 英文自动字幕（推荐 480p 以节省带宽）
yt-dlp --write-auto-sub --sub-langs en \
  -f "bestvideo[height<=480]+bestaudio" \
  --cookies-from-browser chrome \
  "https://www.youtube.com/watch?v=9aPyO1jfDGM" \
  -o "/workspace/videos/%(title)s.%(ext)s"
```

> **注意**: 若无浏览器 Cookies，可先仅下载字幕：
> ```bash
> yt-dlp --write-auto-sub --sub-langs en --skip-download \
>   "https://www.youtube.com/watch?v=9aPyO1jfDGM"
> ```

### 3. 运行完整流水线

```bash
cd /workspace
chmod +x scripts/*.sh

# 运行主流水线（下载 → 字幕提取 → 转换 → 中文翻译 → 刻录 → 部署）
bash scripts/full_pipeline.sh
```

### 4. 单独执行各步骤

#### 步骤 A: WebVTT 转 SRT + 生成中文字幕

```bash
python3 scripts/subtitle_processor.py \
  /workspace/videos/*.en.vtt \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt
```

#### 步骤 B: 将字幕刻录到视频

```bash
bash scripts/burn_subtitles.sh \
  /workspace/videos/<视频文件>.mp4 \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt \
  /workspace/processed_videos/final_with_subtitles.mp4
```

#### 步骤 C: 部署输出

```bash
bash scripts/deploy.sh \
  /workspace/videos/<视频文件>.mp4 \
  /workspace/videos/english_subtitles.srt \
  /workspace/videos/chinese_subtitles.srt \
  /workspace/processed_videos/final_with_subtitles.mp4 \
  /workspace/deployed
```

---

## 📋 流水线步骤详解

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1 | `full_pipeline.sh` | 创建目录、协调所有步骤 |
| 2 | `yt-dlp` | 下载视频 + 提取英文自动字幕 (WebVTT) |
| 3 | `subtitle_processor.py` | WebVTT → SRT 转换 + 中文翻译生成 |
| 4 | `burn_subtitles.sh` | ffmpeg 将双语字幕烧录进视频 |
| 5 | `deploy.sh` | 复制文件到部署目录 + 生成 manifest.json |

---

## 🎯 字幕示例

**英文 SRT** (`english_subtitles.srt`):
```
1
00:00:02,639 --> 00:00:16,310
USA.

3
00:00:18,870 --> 00:00:18,880
>> Thank you. Thank you. And God bless each
```

**中文 SRT** (`chinese_subtitles.srt`):
```
1
00:00:02,639 --> 00:00:16,310
美国.

3
00:00:18,870 --> 00:00:18,880
>> 谢谢. 谢谢. 愿上帝保佑每一位
```

---

## ⚙️ 配置说明

### 中文翻译（当前为模拟模式）

`scripts/subtitle_processor.py` 中内置了常见字幕短语的英文→中文映射表。未匹配的内容会标记为 `[待翻译]`。

如需接入真实翻译 API（如有道、百度、谷歌翻译），请修改 `generate_chinese_subtitles.py` 中的 `simple_translate()` 函数，替换为实际的 API 调用。

### ffmpeg 字幕样式

`burn_subtitles.sh` 中使用的字幕样式可自定义：

```bash
-vf "subtitles=subtitle.srt:force_style='FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Bold=1,BorderStyle=1,Outline=2,Shadow=1,MarginV=30,Alignment=2'"
```

---

## 📦 部署输出

运行完流水线后，`/workspace/deployed/` 目录包含：

```
deployed/
├── final_with_subtitles.mp4    # 刻录中英字幕后的最终视频
├── english_subtitles.srt        # 英文字幕文件
├── chinese_subtitles.srt        # 中文字幕文件
└── manifest.json               # 部署清单（包含处理日期、步骤、文件结构等）
```

`manifest.json` 示例：
```json
{
  "project": "Video Subtitle Processing Pipeline",
  "source_url": "https://www.youtube.com/watch?v=9aPyO1jfDGM",
  "processing_date": "2026-10-26T...Z",
  "steps_completed": [...],
  "subtitle_count": 6281,
  "languages": ["en", "zh"]
}
```

---

## ⚠️ 已知限制

1. **YouTube 视频下载**: 由于 YouTube 反爬虫机制，直接下载视频流可能返回 HTTP 403。建议使用 `--cookies-from-browser` 或手动导出 Cookies。
2. **字幕语言**: 目标视频仅提供英文自动生成字幕，不提供中文字幕。中文字幕由本项目模拟翻译生成。
3. **视频文件**: 仓库中目前未包含实际的 `.mp4` 视频文件（受 YouTube 限制未能下载），仅包含已提取的 `.en.vtt` 字幕和生成的 `.srt` 字幕。

---

## 🛠 技术栈

| 工具 | 用途 | 版本 |
|------|------|------|
| yt-dlp | YouTube 视频/字幕下载 | 2026.10.21 |
| ffmpeg / ffprobe | 音视频处理、字幕烧录 | 7.0.2-static |
| Python 3 | 字幕格式转换、翻译生成 | 3.11 |
| Bash | 流水线编排 | - |

---

## 📄 许可证

MIT License

---

**项目地址**: https://github.com/gitsynonyms01/gitsynonyms.git  
**目标视频**: https://www.youtube.com/watch?v=9aPyO1jfDGM
ranslations such as `zh-Hans`.

### One-command English + Chinese + bilingual SRT

```bash
gitsynonyms-youtube-srt --url "https://www.youtube.com/watch?v=IySF_8OArvw"
```

This prefers the automatic English original (`en-orig`) and YouTube's Simplified Chinese auto-translation (`zh-Hans`), waits 56 seconds before requesting the Chinese track, then creates an event/date/video-ID folder containing separately labeled English, Chinese, and time-aligned bilingual `.srt` files. Override track codes, wait time, output root, event title, or date with `--english`, `--chinese`, `--sleep-subtitles`, `--output-dir`, `--event`, and `--date`. Availability and access depend on YouTube and the network; no downloader can guarantee every video is accessible.

The GitHub Actions workflow defaults to the latest White House channel upload. Run **Download YouTube subtitles** manually to resolve the channel's latest video in the cloud and upload its English, Chinese, and bilingual SRTs as a downloadable Actions artifact. Manual downloads use a working public HTTP proxy selected by testing candidates from the [TheSpeedX](https://github.com/TheSpeedX/PROXY-List), [monosans](https://github.com/monosans/proxy-list), and [proxifly](https://github.com/proxifly/free-proxy-list) lists against YouTube's HTTPS connectivity endpoint. The fastest responding candidate is used; if none pass the probe, the workflow fails rather than silently making a direct connection. When no proxy is configured and the direct connection cannot complete a download, the workflow iterates the aggregated proxy lists (the proxyindex list of lists, falling back to the validated `alive_http` pool) and retries through the fastest public HTTP proxy that passes YouTube's HTTPS connectivity probe. Set the repository Actions secret `YTDLP_PROXY` to use your own proxy instead; when set, public proxy lookup is skipped and the fallback only applies to a direct egress.

The scheduled White House monitor may download with YouTube cookies, so it only uses the optional private `YTDLP_PROXY` secret; when that secret is absent it connects directly, and when a direct download cannot complete it falls back to the fastest working public proxy from the proxy index. Public proxy operators can observe connection metadata and may be unreliable; YouTube HTTPS certificate validation remains enabled, and no cookies are sent through a public proxy. For a specific video, set the manual workflow's `source` to its URL (for example, `https://www.youtube.com/watch?v=5E09UkJq4Jo`) and enable `burn_in` if you also want a subtitled MP4.

### Local standalone script (no Python environment changes)

Run from any Windows PowerShell; the command locates Anaconda under the current user's profile with `$env:USERPROFILE`, without requiring an activated environment or hard-coding a username:

```powershell
& (Join-Path $env:USERPROFILE "anaconda3\python.exe") .\scripts\download_youtube_bilingual_srt.py "https://www.youtube.com/watch?v=IySF_8OArvw" --languages zh-Hans,en-orig --output-dir "D:\MyDownload"
```

The downloader retains every caption format YouTube publishes for both languages and writes aligned bilingual `.vtt`, `.srt`, and `.ass` files. Each language is requested as `vtt`, `srt`, `ttml`, `srv3`, `srv2`, `srv1`, and `json3`; the downloaded files are kept byte-for-byte as yt-dlp writes them. The bilingual VTT preserves both language lines in each merged cue; the bilingual ASS applies the selected visual style. GitHub Actions uploads all outputs as an artifact.

The script itself uses only the Python standard library and the `yt-dlp` command already available on `PATH`. It prints each processing step and streams yt-dlp's wait/download progress directly to PowerShell, rather than hiding output until completion. It downloads the second language track first; English is requested immediately, while the Chinese track waits 56 seconds by default, and that wait is applied before every format request of the delayed track. Every downloaded caption file is kept unchanged as the original single-language track; the bilingual SRT and ASS are additional outputs. The merge and the ASS read the track format that carries the most precise timing, in the order `json3`, `srv3`, `srv2`, `srv1`, `vtt`, `ttml`, `srt`; `json3`, `srv3` and `srv2` expose YouTube's own per-word offsets, so the English karaoke highlight follows the spoken word instead of a uniform estimate. VTT cue timings are parsed, and inline word timestamps are used for ASS cut points when available. The bilingual SRT pairs cues whose end times match (to the millisecond), even if their start times differ, placing Chinese and English on separate lines in one block. A newer cue replaces an overlapping older cue in the same language, so each language contributes at most one line and rolling captions are not accumulated. Unpaired cues remain time-aligned at their source boundaries; unrelated cues are not paired merely because they are nearest in time. Original source text and markup remain unchanged in the downloaded single-language files. ASS output groups connected rolling cues in each language and reconstructs their unique text. When Chinese and English rolling groups have matching source cue boundaries, both use those shared boundaries and keep each corresponding cue's full text together instead of independently splitting by words or characters. Unpaired groups use a uniform word-rate estimate and split at later cue starts by rounding to the nearest token; if a preceding cue ends at that split, its text is prefixed to the first segment. This fallback is a coarse estimate, not YouTube-provided word timing. CJK text is placed above Latin text regardless of source track order, centered in the caption area, and reduced to fit when needed. ASS English text uses karaoke timing to highlight words in sequence, evenly distributing each caption interval's duration across its English words. The homepage reads the one shared settings record managed by the subtitle settings page rather than presenting duplicate style controls. The `classic` preset uses vivid gold Chinese (`#FFC928`) above white English; Chinese font size is 1.2 times English, with bold text and a soft shadow. English words highlight in bright cyan (`#00D7FF`) as they are spoken, clearly distinguishing the active English word from the gold Chinese line. The selectable `cinema` preset uses a sample-like serif style with English above Chinese in warm ivory. The background box is always visible from video time zero through the full video duration, including caption gaps, to cover persistent source banners. Generation stops with an explicit error if YouTube does not provide the video duration, since a shorter fallback cannot guarantee full-video coverage. `--box-style glass-diamond` gives a translucent, faceted glass-like look (an ASS-compatible visual treatment, not actual background blur); `--box-style presidential-blue` uses the user-selected color `#0F1647` (RGB 15, 22, 71), matching the blue listed for the U.S. presidential flag (1959–1994) in [Flag Color Codes](https://www.flagcolorcodes.com/president-of-the-united-states-of-america-usa-1959-1994). The default geometry remains `(66,883)`–`(1852,1022)` on a `1920x1080` canvas and scales proportionally with the frame. Use `--box-x`, `--box-y`, `--box-width`, and `--box-height` to customize position and size; `--box-color` and `--box-opacity` override the selected style. Pass `--chinese-font`, `--english-font`, `--english-font-size`, `--chinese-font-scale`, `--chinese-color`, and `--english-color` to customize typography. To retain the downloaded video and create a hard-subtitled MP4, add `--burn-in`; the source video is retained in the output folder alongside the rendered MP4. Pass `--source-video PATH` to burn the subtitles into a video that is already on disk instead of downloading it again. Pass `--local-file LANGUAGE=PATH` to build one language from a caption file you already have, for example a translation produced by `gitsynonyms-youtube`, when YouTube rate-limits that language's track. A local Intel Quick Sync example is `--burn-in --video-encoder h264_qsv --global-quality 1`; it requires an FFmpeg build with `h264_qsv` and compatible hardware. Use `yt-dlp --list-subs URL` to see the video's language codes; choose any two listed codes.

The VTT parser tolerates a blank line between a cue's timing header and its caption text, and snaps inline word timestamps that YouTube rounds up to 10 ms past a cue's end onto that cue boundary; timestamps further outside their cue still stop generation with an explicit error. For ASS output only, if inline word timings show that a caption's final word ends more than three seconds before the cue end, the ASS cue is shortened to half a second after that word; matching Chinese and English cues share the same shortened end. The downloaded source VTT and bilingual SRT timings are not changed by this ASS-only correction.

ASS preserves source cue start times and gaps without lead-in or gap filling. When the source VTT contains inline word timestamps, karaoke switches each complete English word to its timestamp. Without word timestamps, the script retains an even text-based estimate; subtitle text alone cannot recover exact pronunciation timing. See the [BBC timing guidance](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/#Timing) and [Aegisub ASS override tag reference](https://aegisub.org/docs/latest/ass_tags/).

Burn-in uses a single FFmpeg filter invocation; all typography, color, subtitle placement, and adaptive black-box styling stays in the ASS:

```powershell
ffmpeg -i "a.mp4" -vf "subtitles='transcript.ass'" -c:v h264_qsv -global_quality 1 -c:a copy "output_with_subtitle.mp4"
```

The reusable YouTube subtitle workflow skill is in `.github/skills/youtube-bilingual-srt/SKILL.md`.

### GitHub Pages subtitle web app

After GitHub Pages is enabled with **GitHub Actions** as the source, the web app is available at `https://gitsynonyms.github.io/gitsynonyms/`. Paste a YouTube link and choose either local Anaconda or a GitHub-hosted runner. Local mode generates a PowerShell command that locates Anaconda under `$env:USERPROFILE\anaconda3`, without requiring environment activation or hard-coding a username. Select either the gold Chinese-first style or the sample-like serif English-first style, then customize fonts, colors, and sizes. The settings page also offers day, night, and paper-like reading palettes, with calculated text/background contrast ratios; these are configurable suggestions, not medical claims about eye strain. Choose whether the subtitle background remains for the whole video (to cover a persistent original banner) or appears only with captions (for videos without a banner), and select a glass-diamond visual treatment or the user-selected presidential-blue color. Box color, opacity, position, and dimensions are editable. Check the burn-in option to download the source video and render a hard-subtitled MP4; local mode uses Intel Quick Sync (`h264_qsv`, quality 1), so the machine must have compatible hardware and FFmpeg support. The cloud workflow uses software encoding. Runner mode generates a `gh workflow run` command; run `gh auth login` first if needed, or open Actions and manually start the workflow. No token is pasted into or stored by the page. Cloud jobs require a GitHub account with permission to run the repository workflow.
The settings page also provides instant cross-page synchronization, a subtitle preview that follows the configured position and size, and a warm-gold plaque palette inspired by the supplied example. The comfort palette choices include the day, night, paper, and warm-gold combinations (the warm-gold pair has a 9.83:1 WCAG contrast ratio); selecting one applies a dedicated solid-color background and matching Chinese/English text colors.

### 最新成片

`https://gitsynonyms.github.io/gitsynonyms/latest.html` 展示最近一次刻录的成片：540p 预览直接在页面播放，1080p 硬字幕 MP4 作为 GitHub Release 资源（标签 `roundtable-2026-10-21`）提供下载，双语 ASS/SRT/VTT 跟随站点发布。Release 资源不适合作为页面内嵌播放源（GitHub 以附件形式返回），因此预览文件保持在 100 MB 以内并提交到 `site/media/`，符合 GitHub 单文件限制与 Pages 站点 1 GB 上限。

### Module 2: processing an already-selected video

Module 2's formal five-unit organization and responsibility boundaries are
archived in [`organization/module-2-video-processing.md`](organization/module-2-video-processing.md).

`scripts/video_processing.py` is the video-processing department. It starts
after the video and its subtitles have been selected, never downloads anything,
and turns exactly those files into a publishable burn-in. It accepts a selection
manifest or explicit paths:

```bash
python3 scripts/video_processing.py --selection selection.json
python3 scripts/video_processing.py \
  --video work/TLH3gXrPCTU.source.mp4 \
  --subtitle output/2026-10-21_.../bilingual_Chinese-English.ass \
  --video-id TLH3gXrPCTU --event-date 2026-10-21 \
  --output-dir output/2026-10-21_... --preview --poster
```

A manifest either points at an archive folder that holds YouTube's published
caption formats (preferred) or at one prepared subtitle file. Relative paths
resolve against the manifest directory first and the current directory second:

```json
{
  "video_id": "TLH3gXrPCTU",
  "title": "President Trump Participates in a Roundtable, Oct. 21, 2026",
  "event_date": "2026-10-21",
  "video": "../work/TLH3gXrPCTU.source.mp4",
  "caption_dir": "output/2026-10-21_...",
  "languages": ["zh-Hans", "en-orig"],
  "output_dir": "output/2026-10-21_...",
  "preview": true,
  "poster": true
}
```

For the same job without a manifest:

```bash
python3 scripts/video_processing.py \
  --video work/5YerQHGsX04.source.mp4 --video-id 5YerQHGsX04 \
  --caption-dir output/2026-10-19_... \
  --languages zh-Hans,en-orig --caption-box auto \
  --output-dir output/2026-10-19_... --preview --poster
```

#### Seven-format timing fusion (subtitle timing office)

With `caption_dir`, module 2 reads every published format for both languages
(`vtt`, `srt`, `ttml`, `srv3`, `srv2`, `srv1`, `json3`) and fuses them:

- `json3` is the primary per-word source (`tStartMs` + `tOffsetMs`). `srv3` and
  `srv2` repeat the offsets as XML attributes and corroborate them; `srv1`,
  `ttml`, `vtt`, and `srt` contribute cue boundaries. Cue boundaries use a
  weighted median across all matching formats; word starts keep the json3
  value and use the other formats only to fill gaps, because the XML formats
  often group several words into one segment. `srv3` offsets are relative to
  their paragraph (the parser previously treated them as absolute).
- The fused timeline is kept in **integer nanoseconds**. YouTube's sources are
  at best 1 ms, so the values are exact multiples of that resolution instead
  of invented precision; integer math keeps the medians and sums lossless.
- `TIMING.json` stores that nanosecond model with every cue, word, source list,
  and disagreement report, plus the measured quantization error.
- A per-language `*.precision.vtt` sidecar writes the same timeline at 1 ms,
  the highest resolution a normal subtitle file preserves.
- The styled ASS is generated from the fused tracks. **ASS cannot represent
  sub-centisecond time**: libass accepts exactly two fractional digits, and we
  verified at 1000 fps that `0:00:01.234` (or more digits) makes the entire
  event disappear. The ASS therefore rounds every start/end to the nearest
  10 ms; the maximum error is 5 ms and the measured error is recorded in
  `BURN.json` and the ASS header. Video frames themselves are 33–40 ms at
  25/30 fps, so this is also below the visible frame interval.

| Representation | Resolution | Purpose |
|---|---|---|
| `TIMING.json` | 1 ns integers | lossless fused model and provenance |
| `*.precision.vtt` | 1 ms | portable precise subtitles |
| `bilingual_precise_*.ass` | 10 ms | styled burn-in (libass limit) |
| burned MP4 | 33–40 ms | 25/30 fps frame timing |

#### Third-party caption comparison (caption comparison office)

When API keys are available, the same audio is sent to AssemblyAI, Deepgram,
Gladia, Rev AI, ElevenLabs Scribe v2, and OpenAI Whisper API. Each provider's
word-level transcript is normalized to cues, aligned with the fused reference,
and scored:

- Word Error Rate (WER) after lower-casing/punctuation removal
- Median absolute start-time offset (ms) on aligned words
- Ergonomics score (CPS, line length, duration, gaps)
- Estimated cost at current published rates

Results are written to `COMPARISON.json`/`COMPARISON.md` for side-by-side
vendor ranking.

#### Speech model research (model ranking office)

`scripts/speech_model_research.py` downloads the Hugging Face Open ASR
Leaderboard (English short-form) CSV snapshot and ranks models by WER and
RTFx. Open-weight filter (`--open-weights`) removes proprietary services.
The snapshot lives in `docs/subtitles/data/open_asr_english_short_latest.csv`
and can be refreshed with `--refresh`.

Current top 3 (2026-10-22 snapshot):
1. OtterAI/speech-v3.1 – 3.88% WER (proprietary)
2. reson8/resonant-1-flash – 4.02% WER (proprietary)
3. zoom/scribe_v1 – 4.15% WER (proprietary)

Best open-weight model: ibm-granite/granite-speech-5.0-2b – 5.06% WER, 544 RTFx.

#### Caption box or clean text

`--caption-box auto` samples the caption band (plus an equally tall control
band above it) from the video, measures pixels that are both temporally static
and high-gradient, and treats that pattern as a persistent banner. A banner
gets the **semi-transparent presidential-blue** box (`--box-opacity`, default
0.85); a clean source gets no box, so the subtitles sit directly on the picture
with their outline and shadow. `--caption-box on` and `off` force either
choice. The decision, metrics, thresholds, and sampled region are recorded in
`BURN.json`; a failed detection falls back to the box so a banner can never
make the captions unreadable. Long videos are sampled from keyframes only.

#### Subtitle ergonomics office (human-factor compliance)

`scripts/subtitle_ergonomics.py` validates the generated ASS against published
human-factor standards:

- **Netflix** (English 20/17 CPS, Simplified Chinese 9/7 CPS; 42/16 chars/line;
  min 20 frames, max 7 s; 2-frame gap)
- **BBC/Ofcom** (160–180 WPM ceiling; >200 WPM hard to follow)
- **WCAG 2.x** contrast ≥4.5:1 for text vs. background (computed from ASS
  `PrimaryColour`/`BackColour` with alpha)
- **Layout zones** (action safe, title safe, subtitle, information/chyron,
  logo corners, face region) scaled from the 1920×1080 ASS canvas to the
  actual frame
- **Typography metrics** parsed from the ASS style table: font, size (% of
  frame height), Chinese/English ratio, outline/shadow, caption box colour &
  opacity
- **Children preset** (`--children`): English 17 CPS, Chinese 7 CPS

Outputs `ERGONOMICS.json` with per-cue measurements, summary statistics, and
violation list. Modes: `--ergonomics off|warn|strict` (strict fails the burn
on any error). Reports include per-line CPS, line length, duration, gap, and
zone overlap.

The rest of the processing:

1. probes the video with `ffprobe` and rejects files with no video stream or no
   duration;
2. inspects the generated subtitle, counts cues, reports first/last cue and
   coverage, and warns when the captions run past the end of the video
   (`--strict` makes that an error);
3. runs the ergonomics office, records its report in `BURN.json`;
4. burns the subtitle in a single `subtitles=` libass pass with libx264, audio
   copied when the container allows it and re-encoded to AAC when an MP4 target
   cannot carry the source codec. The render goes to a temporary `.part` file
   and is moved into place only after its duration is verified;
5. optionally renders a 540p preview (H.264/AAC, for the Pages site) and a
   poster frame;
6. writes `BURN.json` next to the output with the status (`burned`, `reused`,
   `dry-run`, or `failed`), input/output SHA-256 hashes, stream metadata, cue
   statistics, timing sources, banner metrics, font substitutions, ergonomics
   summary, and the exact FFmpeg command. The publishing module consumes this
   report instead of re-probing the files.

Without `caption_dir`, the module burns the one prepared subtitle file that was
supplied; in that mode the ASS layout (including any box) is already embedded
and `--caption-box` does not alter it.

Existing fresh outputs are reused unless `--force` is passed, so a retry does
not re-encode a long video. `--dry-run` performs every validation, samples the
caption band, and writes the generated subtitle hand-off, but records the
planned render commands instead of encoding the video. The command exits `0`
for `burned`/`reused`/`dry-run` and `1` for any validation or FFmpeg failure; a
failed run still writes `BURN.json` with `"status": "failed"` and the error, and
leaves neither a partial MP4 nor a `.part` file behind.
The rest of the processing:

1. probes the video with `ffprobe` and rejects files with no video stream or no
   duration;
2. inspects the generated subtitle, counts cues, reports first/last cue and
   coverage, and warns when the captions run past the end of the video
   (`--strict` makes that an error);
3. runs the ergonomics office, records its report in `BURN.json`;
4. burns the subtitle in a single `subtitles=` libass pass with libx264, audio
   copied when the container allows it and re-encoded to AAC when an MP4 target
   cannot carry the source codec. The render goes to a temporary `.part` file
   and is moved into place only after its duration is verified;
5. optionally renders a 540p preview (H.264/AAC, for the Pages site) and a
   poster frame;
6. writes `BURN.json` next to the output with the status (`burned`, `reused`,
   `dry-run`, or `failed`), input/output SHA-256 hashes, stream metadata, cue
   statistics, timing sources, banner metrics, font substitutions, ergonomics
   summary, and the exact FFmpeg command. The publishing module consumes this
   report instead of re-probing the files.

Without `caption_dir`, the module burns the one prepared subtitle file that was
supplied; in that mode the ASS layout (including any box) is already embedded
and `--caption-box` does not alter it.

Existing fresh outputs are reused unless `--force` is passed, so a retry does
not re-encode a long video. `--dry-run` performs every validation, samples the
caption band, and writes the generated subtitle hand-off, but records the
planned render commands instead of encoding the video. The command exits `0`
for `burned`/`reused`/`dry-run` and `1` for any validation or FFmpeg failure; a
failed run still writes `BURN.json` with `"status": "failed"` and the error, and
leaves neither a partial MP4 nor a `.part` file behind.

