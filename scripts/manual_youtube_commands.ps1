#requires -Version 5.1
<#
.SYNOPSIS
    本地 YouTube 双语字幕：原汁原味 PowerShell 命令集合。

.DESCRIPTION
    这个文件不是参数生成器，也不是自动流水线。
    每条命令都按你在终端里直接输入的样子写；要改并发数、清晰度、代理、文件名，
    直接改命令本身即可。

    用法：
      1. 改 param 默认值，或命令行传 -Url / -OutDir / -Run。
      2. -Run 0 只跑第 0 步；-Run 1,3,5 跑多步；
         -Run 0,1,2,3,5,6,9,10 跑主路径；
         -Run 0,1,2,3,4,5,6,7,8,9,10 跑原有步骤；
         第 11 步下载音频，第 12 步调用 AssemblyAI API（单独运行）。
      3. 保存后直接运行本文件，或只复制某一步里的一行到 PowerShell 单独执行。
      4. 也可以直接改文件里的 $Run 默认值（@(0) 等价于 -Run 0）。
    步骤：
      模块一消息 线索 事件:
        submodule1:
            消息获取,视频种子链接 比如白宫 rollcall
        submodule2:
            线索分析,根据消息和视频种子链接,分析出事件发生的时间,地点,人物,事件类型,事件经过,并获取到事件的相关视频素材,并下载到本地
        submodule3:
            事件生成 事件分析
        submodule4:
            背景材料比对 确认素材 高清1080p 以上,干净无遮挡,多角度,可信源,时长足够非静态重复和杂质解说

      模块二 视频处理生成:
        sub模块1 素材获取:
                0 环境检查
                1 详查官方字幕（yt-dlp -v --list-subs）
                2 查看可用清晰度（yt-dlp -F）
                3 下载视频（50 并发分片 + 合并 mp4）
                4 原始 yt-dlp 下载七种字幕格式（手工检查用）
                5 规范字幕文件名（en-orig / zh-Hans）
                11 下载并提取选定视频的音频
        sub模块2 字幕生成:
            6 官方英文 + 官方中文 -> 本地双语 ASS
            7 官方英文 + 机器翻译中文（备选）
            8 ASR 英文 + 机器翻译中文（备选）
            12 YouTube 无字幕时，调用 AssemblyAI 逐词转写并翻译
        sub模块3 视频刻录:
            9 ffmpeg 刻录 ASS
            10 ffprobe 验收

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 -Run 0

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 -Run 1,3,5

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 `
        -Url "https://youtu.be/xxx" -OutDir "D:\MyDownload\a" -Run 3
#>

[CmdletBinding()]
param(
    # 视频链接（放在最前面；命令行可用 -Url 覆盖）
    [Parameter(Position = 0)]
    [string]$Url = "https://www.youtube.com/watch?v=2xrn-nfxk2w",

    # 视频、字幕、ASS 的输出目录（命令行可用 -OutDir 覆盖）
    [string]$OutDir = "D:\MyDownload\a",

    # 要执行哪些步骤：-Run 0 / -Run 1,3,5 / -Run 11,12
    [string[]]$Run = @("0")
)

# ===========================================================================
# 变量区：默认值可在命令行覆盖
# ===========================================================================
# 命令行示例：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 -Run 0
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 -Run 1,3,5
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manual_youtube_commands.ps1 `
#       -Url "https://youtu.be/xxx" -OutDir "D:\MyDownload\a" -Run 3
#
# 也可以直接改上面的 param 默认值，或只改下面这些变量。

# Python：conda 环境 a
$py = Join-Path $env:USERPROFILE "anaconda3\envs\a\python.exe"

# 可选：video id。留空则从 $Url 自动解析；解析失败时手动填 11 位 id。
$VideoId = ""

# 可选：代理 / cookies。这里不设开关；需要时把参数直接加进下面某条 yt-dlp 命令：
#   yt-dlp --proxy "http://127.0.0.1:7890" -v --list-subs "$Url"
#   yt-dlp --cookies-from-browser chrome -v --list-subs "$Url"
#   yt-dlp --cookies "D:\cookies.txt" -v --list-subs "$Url"

# ===========================================================================
# 派生变量（一般不用改）
# ===========================================================================

if (-not $VideoId -and $Url -match '(?:[?&]v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})') {
    $VideoId = $Matches[1]
}

function Invoke-AssemblyAIWordJsonAndTranslation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$SourceDirectory,

        [Parameter(Mandatory)]
        [string]$VideoId
    )

    $captionReportPath = Join-Path $SourceDirectory "CAPTION_FORMATS.json"
    if (-not (Test-Path -LiteralPath $captionReportPath -PathType Leaf)) {
        throw "找不到 YouTube 字幕检查报告：$captionReportPath；请先运行第 5 步。"
    }
    try {
        $captionReport = Get-Content -LiteralPath $captionReportPath -Raw |
            ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "无法读取 YouTube 字幕检查报告 $captionReportPath：$($_.Exception.Message)"
    }
    if ($captionReport.video_id -ne $VideoId -or $captionReport.source -ne "youtube") {
        throw "字幕检查报告与当前视频不匹配；请先运行第 5 步刷新报告。"
    }
    if (-not $captionReport.generated_at) {
        throw "字幕检查报告缺少检查时间；请先运行第 5 步刷新报告。"
    }
    try {
        $reportTime = [DateTimeOffset]::Parse(
            [string]$captionReport.generated_at,
            [Globalization.CultureInfo]::InvariantCulture
        )
    } catch {
        throw "字幕检查报告时间无效；请先运行第 5 步刷新报告。"
    }
    if ([DateTimeOffset]::UtcNow - $reportTime.ToUniversalTime() -gt [TimeSpan]::FromDays(1)) {
        throw "字幕检查报告已超过 24 小时；请先运行第 5 步刷新报告。"
    }
    if ($null -eq $captionReport.available_languages) {
        throw "字幕检查报告未记录可用语种；请先运行第 5 步刷新报告。"
    }
    $availableLanguages = @($captionReport.available_languages)
    if ($availableLanguages.Count -gt 0) {
        throw (
            "YouTube 仍提供字幕轨（$($availableLanguages -join ', ')）；" +
            "根据字幕来源规则，不上传音频到 AssemblyAI。"
        )
    }

    $audioExtensions = @(".m4a", ".mp3", ".opus", ".aac", ".wav", ".flac", ".ogg")
    $videoExtensions = @(".mp4", ".mkv", ".webm", ".mov")
    $audioCandidates = @(
        Get-ChildItem -LiteralPath $SourceDirectory -File |
            Where-Object {
                $_.Extension.ToLowerInvariant() -in $audioExtensions -and
                $_.BaseName.Contains($VideoId)
            }
    )
    $videoCandidates = @(
        Get-ChildItem -LiteralPath $SourceDirectory -File |
            Where-Object {
                $_.Extension.ToLowerInvariant() -in $videoExtensions -and
                $_.BaseName.Contains($VideoId)
            }
    )
    if ($audioCandidates.Count -eq 1) {
        $media = $audioCandidates[0]
    } elseif ($audioCandidates.Count -gt 1) {
        throw "目录中有多个音频文件名包含视频 ID $VideoId；请先整理源音频。"
    } elseif ($videoCandidates.Count -eq 1) {
        $media = $videoCandidates[0]
    } elseif ($videoCandidates.Count -gt 1) {
        throw "目录中有多个视频文件名包含视频 ID $VideoId；请先整理源视频。"
    } else {
        $allCandidates = @(
            Get-ChildItem -LiteralPath $SourceDirectory -File |
                Where-Object {
                    $_.Extension.ToLowerInvariant() -in ($audioExtensions + $videoExtensions)
                }
        )
        if ($allCandidates.Count -eq 1) {
            $media = $allCandidates[0]
        } else {
            throw "无法在 $SourceDirectory 中唯一确定源音频/视频；请确保只有一个媒体文件，或文件名包含 $VideoId。"
        }
    }

    $outputDirectory = Join-Path $SourceDirectory "assemblyai"
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $apiKey = $env:ASSEMBLYAI_API_KEY
    if (-not $apiKey) {
        $apiKey = $env:ASSEMBLYAI
    }
    if (-not $apiKey) {
        $keyFile = Join-Path $PSScriptRoot "..\input\api_keys"
        if (Test-Path -LiteralPath $keyFile -PathType Leaf) {
            $keyLine = Select-String -LiteralPath $keyFile `
                -Pattern '^\s*assemblyai(?:_api_key)?\s*:\s*(.+?)\s*$' |
                Select-Object -First 1
            if ($keyLine) {
                $apiKey = $keyLine.Matches[0].Groups[1].Value.Trim()
            }
        }
    }
    if (-not $apiKey) {
        throw "未找到 AssemblyAI 密钥；请设置 ASSEMBLYAI_API_KEY/ASSEMBLYAI，或检查 input\api_keys。"
    }
    $apiKey = $apiKey.Trim()
    if (-not $apiKey) {
        throw "AssemblyAI 密钥为空；请检查 ASSEMBLYAI_API_KEY/ASSEMBLYAI 或 input\api_keys。"
    }

    Write-Host "源音频/视频：$($media.FullName)" -ForegroundColor Cyan
    Write-Host "AssemblyAI 结果：$outputDirectory" -ForegroundColor Cyan
    Write-Host "YouTube 报告确认无字幕轨；将上传音频并调用 ASR/翻译 API，可能产生费用。" `
        -ForegroundColor Yellow

    $audio = $media
    if ($media.Extension.ToLowerInvariant() -in $videoExtensions) {
        $audio = Get-Item -LiteralPath (Join-Path $outputDirectory "$VideoId.asr.mp3") `
            -ErrorAction SilentlyContinue
        if (-not $audio) {
            $audioPath = Join-Path $outputDirectory "$VideoId.asr.mp3"
            ffmpeg -nostdin -y -hide_banner -loglevel error `
                -i $media.FullName -vn -ac 1 -ar 16000 -b:a 48k $audioPath
            if ($LASTEXITCODE -ne 0) {
                throw "ffmpeg 音频提取失败，退出码：$LASTEXITCODE"
            }
            $audio = Get-Item -LiteralPath $audioPath
        }
    }

    $headers = @{ authorization = $apiKey }
    $baseUrl = "https://api.assemblyai.com/v2"
    Write-Host "上传音频：$($audio.FullName) ($([math]::Round($audio.Length / 1MB, 1)) MB)" `
        -ForegroundColor Cyan
    $upload = Invoke-RestMethod -Uri "$baseUrl/upload" -Method Post `
        -Headers $headers -InFile $audio.FullName `
        -ContentType "application/octet-stream" -ErrorAction Stop
    if (-not $upload.upload_url) {
        throw "AssemblyAI 上传接口未返回 upload_url。"
    }

    $requestBody = @{
        audio_url = $upload.upload_url
        language_detection = $true
        speech_understanding = @{
            request = @{
                translation = @{
                    target_languages = @("zh")
                }
            }
        }
    } | ConvertTo-Json -Depth 8
    $transcript = Invoke-RestMethod -Uri "$baseUrl/transcript" -Method Post `
        -Headers $headers -Body $requestBody -ContentType "application/json" `
        -ErrorAction Stop
    if (-not $transcript.id) {
        throw "AssemblyAI 转写接口未返回 transcript id。"
    }

    $transcriptId = [string]$transcript.id
    $transcriptUrl = "$baseUrl/transcript/$transcriptId"
    $deadline = [DateTimeOffset]::UtcNow.AddHours(2)
    do {
        Start-Sleep -Seconds 3
        $result = Invoke-RestMethod -Uri $transcriptUrl -Headers $headers -ErrorAction Stop
        if ($result.status -eq "error") {
            throw "AssemblyAI 转写失败：$($result.error)"
        }
        if ($result.status -eq "completed") {
            break
        }
        Write-Host "AssemblyAI 状态：$($result.status)" -ForegroundColor DarkGray
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ($result.status -ne "completed") {
        throw "AssemblyAI 转写超过 2 小时仍未完成（transcript id: $transcriptId）。"
    }
    if (-not $result.words -or -not $result.text) {
        throw "AssemblyAI 已返回 completed，但缺少逐词结果或转写文本。"
    }
    $translationProperty = if ($result.translated_texts) {
        $result.translated_texts.PSObject.Properties["zh"]
    }
    if (-not $translationProperty -or [string]::IsNullOrWhiteSpace([string]$translationProperty.Value)) {
        throw "AssemblyAI 未返回简体中文翻译 translated_texts.zh。"
    }

    $outputBase = Join-Path $outputDirectory $VideoId
    $srt = Invoke-RestMethod -Uri "$transcriptUrl/srt" -Headers $headers -ErrorAction Stop
    $vtt = Invoke-RestMethod -Uri "$transcriptUrl/vtt" -Headers $headers -ErrorAction Stop
    $paragraphs = Invoke-RestMethod -Uri "$transcriptUrl/paragraphs" -Headers $headers -ErrorAction Stop
    $sentences = Invoke-RestMethod -Uri "$transcriptUrl/sentences" -Headers $headers -ErrorAction Stop

    Set-Content -LiteralPath "$outputBase.en.srt" -Value $srt -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.en.vtt" -Value $vtt -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.txt" -Value $result.text -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.full.json" `
        -Value (ConvertTo-Json -InputObject $result -Depth 30) -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.paragraphs.json" `
        -Value (ConvertTo-Json -InputObject $paragraphs -Depth 20) -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.sentences.json" `
        -Value (ConvertTo-Json -InputObject $sentences -Depth 20) -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.words.json" `
        -Value (ConvertTo-Json -InputObject @($result.words) -Depth 10) -Encoding UTF8
    Set-Content -LiteralPath "$outputBase.zh.txt" `
        -Value $translationProperty.Value -Encoding UTF8

    Write-Host "`n全部完成！生成文件：" -ForegroundColor Green
    @(
        "$outputBase.en.srt",
        "$outputBase.en.vtt",
        "$outputBase.txt",
        "$outputBase.full.json",
        "$outputBase.paragraphs.json",
        "$outputBase.sentences.json",
        "$outputBase.words.json",
        "$outputBase.zh.txt"
    ) | ForEach-Object { Write-Host $_ -ForegroundColor Green }
}

# 把 -Run 0 / -Run 1,3,5 / -Run "@(0,1,2)" 统一解析成整数数组。
$RunIds = @()
foreach ($value in $Run) {
    $normalized = ([string]$value).Trim()
    $normalized = $normalized -replace '^@\(', '' -replace '\)$', ''
    foreach ($part in ($normalized -split ',')) {
        $trimmed = $part.Trim()
        if (-not $trimmed) { continue }
        $parsed = 0
        if (-not [int]::TryParse($trimmed, [ref]$parsed)) {
            throw "无效步骤号：$trimmed（可用 0-12）"
        }
        $RunIds += $parsed
    }
}
$RunIds = @($RunIds | Select-Object -Unique)
$unknown = @($RunIds | Where-Object { $_ -notin 0..12 })
if ($unknown.Count -gt 0) {
    throw "未知步骤：$($unknown -join ', ')（可用 0-12）"
}

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

# ===========================================================================
# 步骤 0：环境检查
# ===========================================================================
# 确认四个工具都能调用。yt-dlp 太旧容易 403，可先运行 yt-dlp -U。
if ($RunIds -contains 0) {
    yt-dlp --version
    ffmpeg -version
    ffprobe -version
    & $py --version
}

# ===========================================================================
# 步骤 1：详查官方字幕
# ===========================================================================
# 原汁原味：
#   yt-dlp -v --list-subs "https://www.youtube.com/watch?v=shMvm9S_4n4"
# 重点看 en / en-orig / zh-Hans 是否存在，以及 manual 还是 auto。
if ($RunIds -contains 1) {
    yt-dlp -v --list-subs "$Url"
}

# ===========================================================================
# 步骤 2：查看可用清晰度
# ===========================================================================
# 原汁原味：
#   yt-dlp -F "https://www.youtube.com/watch?v=shMvm9S_4n4"
# 正式刻录要求源至少 1080p；低于 1080p 不要用于发布。
if ($RunIds -contains 2) {
    yt-dlp -F "$Url"
}

# ===========================================================================
# 步骤 3：下载视频
# ===========================================================================
# 原汁原味：
#   yt-dlp --concurrent-fragments 50 --merge-output-format mp4 `
#       -f "bv*[height<=1080]+ba/b[height<=1080]" `
#       -o "D:\MyDownload\a\%(title)s [%(id)s].%(ext)s" `
#       "https://www.youtube.com/watch?v=shMvm9S_4n4"
#
# 说明：
#   --concurrent-fragments 50 提速明显，但可能触发 403/429；被限速时改成 4-8。
#   --merge-output-format mp4 需要 ffmpeg。
#   已有文件默认跳过；强制重下加 --force-overwrites。
#   需要代理/cookies 时，直接在这条命令里加 --proxy / --cookies-from-browser。
if ($RunIds -contains 3) {
    yt-dlp --concurrent-fragments 50 --merge-output-format mp4 `
        -f "bv*[height<=1080]+ba/b[height<=1080]" `
        -o "$OutDir\%(title)s [%(id)s].%(ext)s" `
        "$Url"
}

# ===========================================================================
# 步骤 4：原始 yt-dlp 下载官方字幕七种格式（手工检查用）
# ===========================================================================
# 说明：
#   七种格式：json3 / srv3 / srv2 / srv1 / ttml / vtt / srt。
#   每种格式单独跑一次，避免 --sub-format 只保留一个文件。
#   --sleep-subtitles 56 秒用于降低 429；英文和中文都会等待。
#   输出文件名是 <id>.<语言>.<格式>，例如 <id>.en-orig.vtt。
#   这一步只用于手工检查；主路径第 5 步会重新下载并规范命名。
if ($RunIds -contains 4) {
    $formats = @("json3", "srv3", "srv2", "srv1", "ttml", "vtt", "srt")
    foreach ($fmt in $formats) {
        yt-dlp --write-subs --write-auto-subs --sub-langs "en-orig" `
            --sub-format $fmt --skip-download `
            -o "$OutDir\%(id)s.%(ext)s" `
            "$Url"
    }
    foreach ($fmt in $formats) {
        yt-dlp --write-subs --write-auto-subs --sub-langs "zh-Hans" `
            --sub-format $fmt --skip-download --sleep-subtitles 56 `
            -o "$OutDir\%(id)s.%(ext)s" `
            "$Url"
    }
}

# ===========================================================================
# 步骤 5：规范字幕文件名（en-orig / zh-Hans）
# ===========================================================================
# 说明：
#   本地流程只认 en-orig / zh-Hans；原始 yt-dlp 可能下载成 en / zh-Hans。
#   fetch_youtube_captions.py 会下载七格式、重命名并写 CAPTION_FORMATS.json。
#   这个 wrapper 不转发代理/cookies；需要时先设置 HTTPS_PROXY，或改用第 6 步。
if ($RunIds -contains 5) {
    if (-not $VideoId) {
        throw "无法从链接解析 video id；请在变量区手动填 `$VideoId。"
    }
    & $py -X utf8 scripts\fetch_youtube_captions.py `
        --video-id $VideoId `
        --output-dir $OutDir `
        --groups en,zh `
        --sleep-subtitles 56
}

# ===========================================================================
# 步骤 6：官方英文 + 官方中文 -> 本地双语 ASS
# ===========================================================================
# 说明：
#   offline-official 只读本地字幕，不再访问网络。
#   前提：第 5 步已经生成 en-orig 和 zh-Hans；官方中文缺失时这一步会失败。
#   官方中文缺失时改用第 7 步（机器翻译中文）。
#   输出：bilingual_precise_Chinese-English.ass、TIMING.json、LOCAL_FLOW.json。
if ($RunIds -contains 6) {
    & $py -X utf8 scripts\local_subtitle_flow.py `
        --url "$Url" `
        --directory "$OutDir" `
        --preset offline-official
}

# ===========================================================================
# 步骤 7：官方英文 + 机器翻译中文（备选）
# ===========================================================================
# 说明：
#   local-youtube-mt 会重新探测并下载官方英文，再用机器翻译生成中文。
#   即使本地已有中文轨，也会被替换。
#   翻译引擎默认 argos（本地、无需 key）；有 ASSEMBLYAI 时可改成 assemblyai。
if ($RunIds -contains 7) {
    & $py -X utf8 scripts\local_subtitle_flow.py `
        --url "$Url" `
        --directory "$OutDir" `
        --preset local-youtube-mt `
        --translation-engine argos
}

# ===========================================================================
# 步骤 8：ASR 英文 + 机器翻译中文（备选）
# ===========================================================================
# 说明：
#   local-asr-mt 强制 ASR，不探测 YouTube 英文字幕。
#   默认 whisper（faster-whisper，本地）；有 ASSEMBLYAI 时可改成 assemblyai。
#   只有确认 YouTube 没有英文轨时才建议用这一步，避免不必要的付费转写。
if ($RunIds -contains 8) {
    & $py -X utf8 scripts\local_subtitle_flow.py `
        --url "$Url" `
        --directory "$OutDir" `
        --preset local-asr-mt `
        --asr-engine whisper
}

# ===========================================================================
# 步骤 9：刻录 ASS 到视频
# ===========================================================================
# 说明：
#   ffmpeg 用 libx264 重编码视频，音频直接 copy。
#   下面自动找 OutDir 里最新的 mp4（排除 *_bilingual.mp4）和默认 ASS。
#   也可以把 $video / $ass 直接改成你的文件名。
if ($RunIds -contains 9) {
    $video = Get-ChildItem -LiteralPath $OutDir -File |
        Where-Object {
            $_.Extension -in ".mp4", ".mkv", ".webm" -and
            $_.BaseName -notmatch '(_bilingual|_burn)$'
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $video) {
        throw "找不到视频；先跑第 3 步，或把 `$video 改成你的文件名。"
    }

    $ass = Join-Path $OutDir "bilingual_precise_Chinese-English.ass"
    if (-not (Test-Path -LiteralPath $ass)) {
        throw "找不到 ASS；先跑第 6/7/8 步，或把 `$ass 改成你的文件名。"
    }

    # ffmpeg 滤镜里的 Windows 盘符冒号必须转义；路径分隔符统一成正斜杠。
    $assFilter = ($ass -replace '\\', '/') -replace ':', '\:'

    ffmpeg -y -i $video.FullName `
        -vf "ass=filename='$assFilter'" `
        -c:v libx264 -crf 30 -preset veryfast -c:a copy `
        "$OutDir\$($video.BaseName)_bilingual.mp4"
}

# ===========================================================================
# 步骤 10：验收输出
# ===========================================================================
# 说明：
#   看时长、文件大小、码率；再人工播放一遍，确认字幕位置和断句。
if ($RunIds -contains 10) {
    $latest = Get-ChildItem -LiteralPath $OutDir -File -Filter "*_bilingual.mp4" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "找不到 *_bilingual.mp4；先跑第 9 步。"
    }

    ffprobe -v error `
        -show_entries format=duration,size,bit_rate `
        -of default=noprint_wrappers=1 `
        $latest.FullName
}

# ===========================================================================
# 步骤 11：下载并提取选定视频的音频（模块1：素材获取）
# ===========================================================================
# 说明：
#   音频下载属于素材获取职责，按 DIRECTIVE.md 归模块1，不归模块2。
#   -x 从视频源提取音频；输出文件名保留视频 ID，写入 OutDir，供第 12 步使用。
#   此步骤只下载音频，不上传 AssemblyAI；媒体获取仍须遵守云端执行要求。
if ($RunIds -contains 11) {
    if (-not $VideoId) {
        throw "无法从链接解析 video id；请在变量区手动填 `$VideoId。"
    }

    yt-dlp -x --audio-quality 0 `
        -o "$OutDir\%(title)s [%(id)s].%(ext)s" `
        "$Url"
    if ($LASTEXITCODE -ne 0) {
        throw "yt-dlp 音频下载/提取失败，退出码：$LASTEXITCODE"
    }
}

# ===========================================================================
# 步骤 12：AssemblyAI 逐词 JSON + 中文字幕翻译（模块2：视频处理）
# ===========================================================================
# 说明：
#   先运行第 5 步下载/检查 YouTube 七格式；只有 CAPTION_FORMATS.json 确认没有任何
#   可用语种时，才把本地音频发给 AssemblyAI 做 ASR 和简体中文翻译。
#   有字幕、报告缺失/过期或探测失败时均中止，不上传音频。
#   优先使用 OutDir 中与 VideoId 匹配的现成音频；没有时使用匹配的视频并提取音频。
#   输出写入 OutDir\assemblyai，避免覆盖原目录里的字幕：
#   <VideoId>.en.srt/.vtt、完整 transcript JSON、paragraphs/sentences/words JSON
#   与 <VideoId>.zh.txt；完整 JSON 中保留服务返回的逐词时间和中文翻译。
#   API 密钥通过 ASSEMBLYAI / ASSEMBLYAI_API_KEY 环境变量或 input\api_keys 读取；
#   不要把密钥写入本脚本或命令行。仅缺失字幕时才调用相应 API 并产生用量费用。
if ($RunIds -contains 12) {
    if (-not $VideoId) {
        throw "无法从链接解析 video id；请在变量区手动填 `$VideoId。"
    }
    Invoke-AssemblyAIWordJsonAndTranslation `
        -SourceDirectory $OutDir `
        -VideoId $VideoId
}

# ===========================================================================
# 结束
# ===========================================================================
Write-Host ""
Write-Host ("完成。执行步骤：" + ($RunIds -join ", ")) -ForegroundColor Green
Write-Host ("输出目录：" + $OutDir) -ForegroundColor Green
