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

## PowerShell

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
