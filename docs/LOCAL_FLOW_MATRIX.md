# Local caption flow matrix (copy-paste PowerShell)

`scripts/local_subtitle_flow.py` exposes every supported source dimension with
`--preset` (or the lower-level `--english-source` / `--chinese-source` flags).
The preset is recorded in `LOCAL_FLOW.json` under `selection`, together with the
flow, reason, engines and output formats.

## Dimensions

| # | Preset | Media | English | Chinese |
|---|--------|-------|---------|---------|
| 1 | `local-youtube-official` | local file | YouTube official (manual/auto) | YouTube official translation |
| 2 | `local-youtube-mt` | local file | YouTube official (manual/auto) | machine translation |
| 3 | `local-asr-mt` | local file | AssemblyAI / faster-whisper ASR | machine translation |
| 4 | `local-asr-official` | local file | AssemblyAI / faster-whisper ASR | YouTube official translation |
| 5 | `url-youtube-official` | none (URL only) | YouTube official (manual/auto) | YouTube official translation |
| 6 | `url-youtube-mt` | none (URL only) | YouTube official (manual/auto) | machine translation |
| 7 | `offline-official` | local captions | existing local English | existing local Chinese |
| 8 | `offline-mt` | local captions | existing local English | machine translation |

`local-asr-official` is the case where YouTube published Chinese but no English
track; ASR supplies English and the official Chinese translation is kept.

## PowerShell runner: line-by-line or batch

`scripts\local_subtitle_flow.ps1` wraps the same presets so one file can be
used either way.

```powershell
# Print the variable block and one command per preset, then copy any line.
.\scripts\local_subtitle_flow.ps1 -List

# Batch: run two presets in order (comma-separated names are split).
.\scripts\local_subtitle_flow.ps1 -Preset local-youtube-official,local-youtube-mt `
    -Url "https://youtu.be/<video-id>" -Directory "D:\MyDownload\a"

# Batch: all eight presets, no confirmation prompt.
.\scripts\local_subtitle_flow.ps1 -All -Yes `
    -Url "https://youtu.be/<video-id>" -Directory "D:\MyDownload\a"

# Print and log without calling Python.
.\scripts\local_subtitle_flow.ps1 -Preset local-asr-mt -DryRun `
    -Url "https://youtu.be/<video-id>" -Directory "D:\MyDownload\a"
```

- `-KeepGoing` continues after a failing preset; the script exits `1` if any
  preset failed.
- `-LogPath` overrides the command log location.
- `-Python`, `-TranslationEngine` and `-AsrEngine` are forwarded to the Python
  entry point when they apply to the selected preset.

### Which file records every command?

| File | Written by | Contents |
|------|------------|----------|
| `<Directory>\LOCAL_FLOW_COMMANDS.jsonl` | `local_subtitle_flow.ps1` | One JSON line per invocation: `observed_at`, `preset`, `command`, `exit_code`, `duration_seconds`, `directory`, `url`, `video_id`, `dry_run` |
| `<Directory>\LOCAL_FLOW.json` | `local_subtitle_flow.py` | Flow decision: `flow`, `reason`, `selection`, engines, output formats, `status`, `error` |

`LOCAL_FLOW_COMMANDS.jsonl` is gitignored; `LOCAL_FLOW.json` is a per-run
artifact and is not part of the repository either.

## Manual command notebook (`manual_local_flow.ps1`)

`scripts\manual_local_flow.ps1` is the human-operated counterpart: every step
has Chinese notes plus a copy-paste command, and the URL is the first positional
parameter. `yt-dlp` itself still receives the URL last, as its CLI expects.

```powershell
# List steps 0-10 with notes and commands, then copy any line.
.\scripts\manual_local_flow.ps1 -List

# One step: inspect the official subtitle list.
.\scripts\manual_local_flow.ps1 "https://www.youtube.com/watch?v=shMvm9S_4n4" -Step 1

# Several steps: download video, seven subtitle formats, canonical names.
.\scripts\manual_local_flow.ps1 "https://youtu.be/<video-id>" -Step 3,4,5 `
    -OutDir "D:\MyDownload\a"

# Main-path batch: 0-3, 5, 6, 9, 10; steps 4/7/8 are manual alternatives.
.\scripts\manual_local_flow.ps1 "https://youtu.be/<video-id>" -All -Yes
```

- Step 3 is the requested
  `yt-dlp --concurrent-fragments 50 --merge-output-format mp4` download.
- Step 4 downloads all seven official subtitle serializations with raw
  `yt-dlp` for manual inspection; step 5 is the main-path wrapper that
  downloads them again under canonical `en-orig` / `zh-Hans` names and writes
  `CAPTION_FORMATS.json`. `-All` skips step 4 to avoid duplicate requests.
- Step 6 renders the offline ASS; steps 7/8 are the machine-translation and ASR
  alternatives.
- `-DryRun` prints and logs without executing; `-KeepGoing` continues after a
  failing step.
- Every external command is appended to
  `<OutDir>\MANUAL_FLOW_COMMANDS.jsonl` with step, command, exit code, duration
  and dry-run flag.

## Raw command notebook (`manual_youtube_commands.ps1`)

If you want to edit the commands themselves instead of passing parameters, use
`scripts\manual_youtube_commands.ps1`. It is a command notebook: each step is
an `if ($RunIds -contains N) { ... }` block with the literal `yt-dlp` / `ffmpeg`
command inside. The AssemblyAI step calls the existing local subtitle flow so
the API, word-timed JSON3, translation, and reports share the tested pipeline.

The step selector is a real parameter, so it can be changed on the command line
instead of editing the file:

```powershell
# One step.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 -Run 0

# Several steps; -File passes "1,3,5" as one string and the script splits it.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 -Run 1,3,5

# Main path, plus a different URL and output directory.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 `
    -Url "https://youtu.be/<video-id>" -OutDir "D:\MyDownload\a" `
    -Run 0,1,2,3,5,6,9,10

# Edit the default in the file instead; @(0) is the same as -Run 0.
$Run = @(1)                   # only step 1
$Run = @(1,3,5)               # steps 1, 3, 5
$Run = @(0,1,2,3,5,6,9,10)    # main path
$Run = @(0..10)               # original steps (4/7/8 duplicate or overwrite)
```

The optional audio/API steps are intentionally excluded from the original full
range because they download media and incur paid API usage:

```powershell
# Step 11: module 1 downloads and extracts audio into OutDir.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 `
    -Url "https://www.youtube.com/watch?v=<video-id>" `
    -OutDir "D:\MyDownload\a" -Run 11

# Step 12: module 2 uses AssemblyAI only when step 5's fresh report confirms
# YouTube provides no subtitle track in any language.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 `
    -Url "https://www.youtube.com/watch?v=<video-id>" `
    -OutDir "D:\MyDownload\a" -Run 12
```

Step 11 is source acquisition (module 1), not module 2 processing. Run step 5
first; step 12 requires its matching, less-than-24-hour-old
`CAPTION_FORMATS.json` report to show that YouTube provides no subtitle track
in any language. A present track, missing/stale report, or probe error stops
before upload. When ASR is allowed, step 12 prefers an audio file in `OutDir`
whose filename contains the video ID; if none exists, it uses the matching
video and extracts audio before upload. Outputs are saved under
`OutDir\assemblyai`: English SRT/VTT, transcript text/full JSON, paragraphs,
sentences and word-timed JSON, plus translated Chinese text. The AssemblyAI key
is read from the process environment or the gitignored `input\api_keys` file,
never from a command-line argument.

The commands are literal and can be changed in place:

```powershell
yt-dlp -v --list-subs "$Url"

yt-dlp --concurrent-fragments 50 --merge-output-format mp4 `
    -f "bv*[height<=1080]+ba/b[height<=1080]" `
    -o "$OutDir\%(title)s [%(id)s].%(ext)s" "$Url"

yt-dlp -x --audio-quality 0 `
    -o "$OutDir\%(title)s [%(id)s].%(ext)s" "$Url"
```

## Copy-paste commands

Open PowerShell in the repository root and set the two paths once. Every
command below can then be copied and run as-is.

```powershell
$py  = "C:\Users\a2023\anaconda3\envs\a\python.exe"
$dir = "D:\MyDownload\a"
$url = "https://youtu.be/<video-id>"
```

### 1. Local media + official English + official Chinese

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --url $url --directory $dir `
    --preset local-youtube-official
```

### 2. Local media + official English + machine-translated Chinese

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --url $url --directory $dir `
    --preset local-youtube-mt --translation-engine argos
```

Use `--translation-engine assemblyai` when `ASSEMBLYAI` is set and you want the
LLM gateway instead of the local Argos floor.

### 3. Local media + ASR English + machine-translated Chinese

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --url $url --directory $dir `
    --preset local-asr-mt --asr-engine whisper
```

With an AssemblyAI key, use `--asr-engine assemblyai` for word-timed cloud ASR.
Without a key, `whisper` runs faster-whisper locally.

### 4. Local media + ASR English + official Chinese

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --url $url --directory $dir `
    --preset local-asr-official --asr-engine whisper
```

### 5. URL only + official English + official Chinese

No media file is needed; the folder only receives captions and the ASS.

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --url $url --directory $dir `
    --preset url-youtube-official
```

### 6. URL only + official English + machine-translated Chinese

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --url $url --directory $dir `
    --preset url-youtube-mt --translation-engine argos
```

### 7. Offline + existing official English + existing official Chinese

No network request at all. The folder must already contain the caption files.

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --directory $dir --video-id <video-id> `
    --preset offline-official
```

### 8. Offline + existing official English + machine-translated Chinese

```powershell
& $py -X utf8 scripts\local_subtitle_flow.py `
    --directory $dir --video-id <video-id> `
    --preset offline-mt --translation-engine argos
```

## Cloud runner

The cloud chain is the GitHub Actions workflow, not the local script. It
auto-selects YouTube first and ASR only when the probe proves English is absent.

```powershell
gh workflow run auto-pipeline.yml -f video_id=<video-id> -f mode=full
```

Force the ASR dimension on the runner:

```powershell
gh workflow run auto-pipeline.yml -f video_id=<video-id> -f force_asr=true
```

## Lower-level flags

`--preset` is a shortcut. The same choices can be made explicitly:

```powershell
--english-source youtube|asr|auto
--chinese-source youtube|mt|auto
```

`--chinese-source mt` replaces an existing Chinese track with a fresh machine
translation. `--chinese-source youtube` fails instead of translating when the
official Chinese track is absent. `--english-source youtube` fails instead of
falling back to paid ASR. `auto` keeps the historical YouTube-first behavior.
