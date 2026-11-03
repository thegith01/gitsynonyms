#requires -Version 5.1
<#
.SYNOPSIS
    本地 YouTube 双语字幕手工流程：命令集合 + 笔记 + 单条执行 / 批处理。

.DESCRIPTION
    这个脚本不是全自动流水线，而是一份可以直接复制命令的“操作台”：
      * 每一步都有中文注释、注意事项和一条可复制的命令；
      * -List 只打印步骤和命令，方便逐行复制到 PowerShell；
      * -Step 3 只执行第 3 步；
      * -All -Yes 按顺序执行“主路径”步骤（跳过 4/7/8 三个手工/备选分支）。

    主路径：
      0 环境检查
      1 详查官方字幕（yt-dlp -v --list-subs）
      2 查看可用清晰度（yt-dlp -F）
      3 下载视频（1080p / mp4 / 50 并发分片）
      5 用仓库 wrapper 下载七格式并规范文件名（en-orig / zh-Hans）
      6 官方英文 + 官方中文 -> 本地双语 ASS
      9 用 ffmpeg 把 ASS 刻录到视频
     10 用 ffprobe 验收输出

    手工/备选分支（默认不参与 -All）：
      4 用原始 yt-dlp 下载七格式，手工检查文件名
      7 官方英文 + 机器翻译中文
      8 ASR 英文 + 机器翻译中文

.PARAMETER Url
    视频链接。放在第一个位置参数，方便直接写：
      .\scripts\manual_local_flow.ps1 "https://www.youtube.com/watch?v=..."

.PARAMETER OutDir
    视频、字幕和 ASS 的输出目录。默认 D:\MyDownload\a。

.PARAMETER VideoId
    手动指定 11 位 video id；不填则从 Url 自动解析。

.PARAMETER MaxHeight
    下载清晰度上限，默认 1080。低于 1080 的源不应用于正式刻录。

.PARAMETER Format
    直接覆盖 yt-dlp 的 -f 选择器；不填则按 MaxHeight 生成。

.PARAMETER ConcurrentFragments
    yt-dlp 分片并发数，默认 50。被 403/429 限速时降到 4-8。

.PARAMETER SubLangs
    字幕语言过滤，默认 "en.*,zh-Hans.*"。

.PARAMETER SleepSubtitles
    中文字幕请求之间的等待秒数，默认 56，降低 429 风险。

.PARAMETER Browser
    从浏览器读取 cookies，例如 chrome / edge / firefox。
    与 CookiesFile 二选一，CookiesFile 优先。

.PARAMETER Proxy
    代理地址，例如 http://127.0.0.1:7890。

.PARAMETER CookiesFile
    Netscape 格式 cookies.txt 路径。

.PARAMETER Python
    Python 解释器路径，默认 conda 环境 a。

.PARAMETER FlowPreset
    第 6 步使用的本地流程 preset，默认 offline-official。

.PARAMETER AsrEngine
    第 8 步的 ASR 引擎：assemblyai 或 whisper。

.PARAMETER TranslationEngine
    第 7/8 步的翻译引擎：assemblyai / argos / mymemory。

.PARAMETER InputVideo
    第 9 步输入视频；不填则自动找 OutDir 里最新的 mp4/mkv/webm。

.PARAMETER AssFile
    第 9 步 ASS 文件；不填则自动找 bilingual_precise_Chinese-English.ass。

.PARAMETER OutputVideo
    第 9 步输出视频；不填则生成 <原文件名>_bilingual.mp4。

.PARAMETER Crf
    x264 CRF，默认 30。

.PARAMETER X264Preset
    x264 preset，默认 veryfast。

.PARAMETER Step
    只执行指定步骤，可多个：-Step 1,2,4。

.PARAMETER All
    按顺序执行主路径步骤（0-3、5、6、9、10），需要 -Yes 确认。

.PARAMETER List
    只打印步骤、注释和命令，不执行。

.PARAMETER DryRun
    打印并记录命令，但不真正调用外部程序。

.PARAMETER Yes
    批处理时跳过确认。

.PARAMETER KeepGoing
    某一步失败后继续；字幕七格式下载时尤其有用。

.PARAMETER LogPath
    命令日志，默认 <OutDir>\MANUAL_FLOW_COMMANDS.jsonl。

.EXAMPLE
    # 只看命令，逐行复制
    .\scripts\manual_local_flow.ps1 -List

.EXAMPLE
    # 只详查官方字幕（用户给的原始命令）
    .\scripts\manual_local_flow.ps1 "https://www.youtube.com/watch?v=shMvm9S_4n4" -Step 1

.EXAMPLE
    # 只下载视频
    .\scripts\manual_local_flow.ps1 "https://youtu.be/xxxx" -Step 3 -OutDir "D:\MyDownload\a"

.EXAMPLE
    # 主路径批处理
    .\scripts\manual_local_flow.ps1 "https://youtu.be/xxxx" -All -Yes

.EXAMPLE
    # 只跑 ASR + 机器翻译分支
    .\scripts\manual_local_flow.ps1 "https://youtu.be/xxxx" -Step 8 -AsrEngine whisper
#>
# ===========================================================================
# 命令速查（打开文件先看这里；下面每条都可以直接复制到 PowerShell）
# ---------------------------------------------------------------------------
# 变量区（按你的实际路径改）：
#   $Url    = "https://www.youtube.com/watch?v=shMvm9S_4n4"
#   $OutDir = "D:\MyDownload\a"
#   $py     = "C:\Users\a2023\anaconda3\envs\a\python.exe"
#
# 1) 详查官方字幕（只列，不下载）
#   yt-dlp -v --list-subs "$Url"
#
# 2) 看可用清晰度
#   yt-dlp -F "$Url"
#
# 3) 下载视频：50 并发分片 + 合并成 mp4
#   yt-dlp --concurrent-fragments 50 --merge-output-format mp4 `
#       -f "bv*[height<=1080]+ba/b[height<=1080]" `
#       -o "$OutDir\%(title)s [%(id)s].%(ext)s" "$Url"
#
# 4) 官方字幕七种格式（json3/srv3/srv2/srv1/ttml/vtt/srt）
#   $formats = @("json3","srv3","srv2","srv1","ttml","vtt","srt")
#   foreach ($fmt in $formats) {
#       yt-dlp --write-subs --write-auto-subs --sub-langs "en.*,zh-Hans.*" `
#           --sub-format $fmt --skip-download --sleep-subtitles 56 `
#           -o "$OutDir\%(id)s.%(ext)s" "$Url"
#   }
#
# 5) 规范成 en-orig / zh-Hans，并写 CAPTION_FORMATS.json
#   & $py -X utf8 scripts\fetch_youtube_captions.py `
#       --video-id <video-id> --output-dir "$OutDir" --groups en,zh --sleep-subtitles 56
#
# 6) 官方英文 + 官方中文 -> 本地双语 ASS（不再访问网络）
#   & $py -X utf8 scripts\local_subtitle_flow.py `
#       --url "$Url" --directory "$OutDir" --preset offline-official
#
# 7) 官方英文 + 机器翻译中文
#   & $py -X utf8 scripts\local_subtitle_flow.py `
#       --url "$Url" --directory "$OutDir" --preset local-youtube-mt --translation-engine argos
#
# 8) ASR 英文 + 机器翻译中文
#   & $py -X utf8 scripts\local_subtitle_flow.py `
#       --url "$Url" --directory "$OutDir" --preset local-asr-mt --asr-engine whisper
#
# 9) 刻录 ASS
#   ffmpeg -y -i "$OutDir\<视频>.mp4" -vf "ass=filename='<ASS>'" `
#       -c:v libx264 -crf 30 -preset veryfast -c:a copy "$OutDir\<视频>_bilingual.mp4"
#
# 10) 验收
#   ffprobe -v error -show_entries format=duration,size,bit_rate `
#       -of default=noprint_wrappers=1 "$OutDir\<视频>_bilingual.mp4"
#
# 单条执行：.\scripts\manual_local_flow.ps1 "<链接>" -Step 3
# 批处理：  .\scripts\manual_local_flow.ps1 "<链接>" -All -Yes
# 只看命令：.\scripts\manual_local_flow.ps1 -List
# ===========================================================================
[CmdletBinding()]
param(
    # 链接放在第一个位置参数：脚本参数里链接最前，yt-dlp 命令里链接按官方习惯放最后。
    [Parameter(Position = 0)]
    [string]$Url = "https://www.youtube.com/watch?v=2xrn-nfxk2w",

    [string]$OutDir = "D:\MyDownload\a",
    [string]$VideoId,

    [int]$MaxHeight = 1080,
    [string]$Format,

    [int]$ConcurrentFragments = 50,
    [string]$SubLangs = "en.*,zh-Hans.*",
    [int]$SleepSubtitles = 56,

    [string]$Browser,
    [string]$Proxy,
    [string]$CookiesFile,

    [string]$Python = "C:\Users\a2023\anaconda3\envs\a\python.exe",
    [string]$FlowPreset = "offline-official",
    [string]$AsrEngine = "whisper",
    [string]$TranslationEngine = "argos",

    [string]$InputVideo,
    [string]$AssFile,
    [string]$OutputVideo,
    [int]$Crf = 30,
    [string]$X264Preset = "veryfast",

    [string[]]$Step,
    [switch]$All,
    [switch]$List,
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$KeepGoing,
    [string]$LogPath
)

$ErrorActionPreference = "Stop"

$script:FlowScript = Join-Path $PSScriptRoot "local_subtitle_flow.py"
$script:FetchScript = Join-Path $PSScriptRoot "fetch_youtube_captions.py"
foreach ($required in @($script:FlowScript, $script:FetchScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "找不到脚本：$required"
    }
}

# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

function Quote-Arg {
    param([string]$Value)
    if ($null -eq $Value) { return '""' }
    if ($Value -match '[\s"&|<>^]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Format-CommandText {
    param(
        [string]$Exe,
        [string[]]$Arguments
    )
    $exeText = Quote-Arg $Exe
    if ($Exe -match '[\\/]') { $exeText = "& $exeText" }
    $parts = @($exeText) + @($Arguments | ForEach-Object { Quote-Arg $_ })
    return ($parts -join " ")
}

function Resolve-VideoId {
    param(
        [string]$Link,
        [string]$Explicit
    )
    if ($Explicit) { return $Explicit }
    if ($Link -match '(?:[?&]v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})') {
        return $Matches[1]
    }
    return $null
}

function Get-YtDlpCommonArgs {
    $items = @("--windows-filenames")
    if ($Proxy) { $items += @("--proxy", $Proxy) }
    if ($CookiesFile) { $items += @("--cookies", $CookiesFile) }
    elseif ($Browser) { $items += @("--cookies-from-browser", $Browser) }
    return $items
}

function Get-DownloadFormat {
    if ($Format) { return $Format }
    return "bv*[height<=$MaxHeight]+ba/b[height<=$MaxHeight]"
}

function Get-VideoDownloadArgs {
    $template = Join-Path $OutDir "%(title)s [%(id)s].%(ext)s"
    return @(
        "--concurrent-fragments", "$ConcurrentFragments",
        "--merge-output-format", "mp4",
        "-f", (Get-DownloadFormat),
        "-o", $template
    ) + (Get-YtDlpCommonArgs) + @($Url)
}

function Get-SubtitleDownloadArgs {
    param([string]$SubFormat)
    $template = Join-Path $OutDir "%(id)s.%(ext)s"
    return @(
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", $SubLangs,
        "--sub-format", $SubFormat,
        "--skip-download",
        "--sleep-subtitles", "$SleepSubtitles",
        "-o", $template
    ) + (Get-YtDlpCommonArgs) + @($Url)
}

function Get-CanonicalCaptionArgs {
    if (-not $script:VideoId) {
        throw "无法从链接解析 video id；请用 -VideoId 指定 11 位 id。"
    }
    return @(
        "-X", "utf8", $script:FetchScript,
        "--video-id", $script:VideoId,
        "--output-dir", $OutDir,
        "--groups", "en,zh",
        "--sleep-subtitles", "$SleepSubtitles"
    )
}

function Get-FlowArgs {
    param([string]$Preset)
    $items = @(
        "-X", "utf8", $script:FlowScript,
        "--url", $Url,
        "--directory", $OutDir,
        "--preset", $Preset
    )
    if ($Preset -like "*-mt") {
        $items += @("--translation-engine", $TranslationEngine)
    }
    if ($Preset -like "*-asr-*" -or $Preset -eq "local-asr-official") {
        $items += @("--asr-engine", $AsrEngine)
    }
    return $items
}

function Find-InputVideo {
    if ($InputVideo) {
        if (-not (Test-Path -LiteralPath $InputVideo)) {
            throw "找不到 -InputVideo：$InputVideo"
        }
        return (Resolve-Path -LiteralPath $InputVideo).Path
    }
    $candidates = @(
        Get-ChildItem -LiteralPath $OutDir -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Extension -in ".mp4", ".mkv", ".webm" -and
                $_.BaseName -notmatch '(_bilingual|_burn)$'
            } |
            Sort-Object LastWriteTime -Descending
    )
    if ($candidates.Count -gt 0) { return $candidates[0].FullName }
    return $null
}

function Find-AssFile {
    if ($AssFile) {
        if (-not (Test-Path -LiteralPath $AssFile)) {
            throw "找不到 -AssFile：$AssFile"
        }
        return (Resolve-Path -LiteralPath $AssFile).Path
    }
    $default = Join-Path $OutDir "bilingual_precise_Chinese-English.ass"
    if (Test-Path -LiteralPath $default) {
        return (Resolve-Path -LiteralPath $default).Path
    }
    $candidates = @(
        Get-ChildItem -LiteralPath $OutDir -File -Filter "*.ass" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    )
    if ($candidates.Count -gt 0) { return $candidates[0].FullName }
    return $null
}

function Get-BurnPaths {
    $video = Find-InputVideo
    $ass = Find-AssFile
    $output = $null
    if ($video) {
        if ($OutputVideo) {
            $output = $OutputVideo
        }
        else {
            $stem = [System.IO.Path]::GetFileNameWithoutExtension($video)
            $output = Join-Path $OutDir ($stem + "_bilingual.mp4")
        }
    }
    $assFilter = $null
    if ($ass) {
        # ffmpeg 滤镜里的 Windows 盘符冒号必须转义；路径分隔符统一成正斜杠。
        $assFilter = ($ass -replace '\\', '/') -replace ':', '\:'
    }
    return [pscustomobject]@{
        Video     = $video
        Ass       = $ass
        AssFilter = $assFilter
        Output    = $output
    }
}

function Get-BurnArgs {
    param($Paths)
    return @(
        "-y",
        "-i", $Paths.Video,
        "-vf", "ass=filename='$($Paths.AssFilter)'",
        "-c:v", "libx264",
        "-crf", "$Crf",
        "-preset", $X264Preset,
        "-c:a", "copy",
        $Paths.Output
    )
}

function Get-VerifyArgs {
    param([string]$Target)
    return @(
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate",
        "-of", "default=noprint_wrappers=1",
        $Target
    )
}

# ---------------------------------------------------------------------------
# 命令日志
# ---------------------------------------------------------------------------

function Write-CommandLog {
    param(
        [int]$StepId,
        [string]$Title,
        [string]$Command,
        [int]$ExitCode,
        [double]$DurationSeconds
    )
    $entry = [ordered]@{
        observed_at      = (Get-Date).ToString("o")
        step             = $StepId
        title            = $Title
        command          = $Command
        exit_code        = $ExitCode
        duration_seconds = [math]::Round($DurationSeconds, 3)
        dry_run          = [bool]$DryRun
        url              = $Url
        directory        = $OutDir
        video_id         = $script:VideoId
    }
    Add-Content -LiteralPath $script:LogFile -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}

function Invoke-External {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [int]$StepId,
        [string]$Title,
        [switch]$AllowFailure
    )
    $text = Format-CommandText -Exe $Exe -Arguments $Arguments
    Write-Host ""
    Write-Host ("$ " + $text) -ForegroundColor Cyan

    if ($DryRun) {
        Write-CommandLog -StepId $StepId -Title $Title -Command $text -ExitCode 0 -DurationSeconds 0
        $script:LastExternalExitCode = 0
        return
    }

    $start = Get-Date
    & $Exe @Arguments
    $code = $LASTEXITCODE
    $duration = ((Get-Date) - $start).TotalSeconds
    Write-CommandLog -StepId $StepId -Title $Title -Command $text -ExitCode $code -DurationSeconds $duration
    $script:LastExternalExitCode = $code

    if ($code -ne 0) {
        if ($AllowFailure) {
            Write-Warning ("步骤 {0}（{1}）退出码 {2}：{3}" -f $StepId, $Title, $code, $text)
            return
        }
        throw ("步骤 {0}（{1}）失败，退出码 {2}。`n命令：{3}" -f $StepId, $Title, $code, $text)
    }
}

# ---------------------------------------------------------------------------
# 步骤定义
#
# 每个步骤都有：
#   Id      步骤号
#   Title   标题
#   Notes   中文注释 / 注意事项（-List 会打印）
#   Batch   是否属于 -All 主路径
#   Preview 返回可复制的命令字符串（不执行）
#   Invoke  真正执行
# ---------------------------------------------------------------------------

$script:Steps = @(

    [pscustomobject]@{
        Id = 0
        Title = "环境检查"
        Batch = $true
        Notes = @(
            "确认 yt-dlp / ffmpeg / ffprobe / python 都能调用。",
            "yt-dlp 太旧容易 403；可先运行 yt-dlp -U 更新。",
            "Python 默认用 conda 环境 a，不是 base。"
        )
        Preview = {
            @(
                "yt-dlp --version",
                "ffmpeg -version",
                "ffprobe -version",
                (Format-CommandText -Exe $Python -Arguments @("--version"))
            )
        }
        Invoke = {
            Invoke-External -Exe "yt-dlp" -Arguments @("--version") -StepId 0 -Title "环境检查"
            Invoke-External -Exe "ffmpeg" -Arguments @("-version") -StepId 0 -Title "环境检查"
            Invoke-External -Exe "ffprobe" -Arguments @("-version") -StepId 0 -Title "环境检查"
            Invoke-External -Exe $Python -Arguments @("--version") -StepId 0 -Title "环境检查"
        }
    },

    [pscustomobject]@{
        Id = 1
        Title = "详查官方字幕"
        Batch = $true
        Notes = @(
            "原始命令：yt-dlp -v --list-subs `"$Url`"",
            "重点看 en / en-orig / zh-Hans 是否存在，以及 manual 还是 auto。",
            "-v 会打印请求细节；403/429 时先看这里的输出。",
            "只列字幕，不下载，不改文件。"
        )
        Preview = {
            $items = @("-v", "--list-subs") + (Get-YtDlpCommonArgs) + @($Url)
            @(Format-CommandText -Exe "yt-dlp" -Arguments $items)
        }
        Invoke = {
            $items = @("-v", "--list-subs") + (Get-YtDlpCommonArgs) + @($Url)
            Invoke-External -Exe "yt-dlp" -Arguments $items -StepId 1 -Title "详查官方字幕"
        }
    },

    [pscustomobject]@{
        Id = 2
        Title = "查看可用清晰度"
        Batch = $true
        Notes = @(
            "确认源至少有 1080p；低于 1080p 不用于正式刻录。",
            "如果 1080p 只有 video-only，下载命令会自动配最佳音频。"
        )
        Preview = {
            $items = @("-F") + (Get-YtDlpCommonArgs) + @($Url)
            @(Format-CommandText -Exe "yt-dlp" -Arguments $items)
        }
        Invoke = {
            $items = @("-F") + (Get-YtDlpCommonArgs) + @($Url)
            Invoke-External -Exe "yt-dlp" -Arguments $items -StepId 2 -Title "查看可用清晰度"
        }
    },

    [pscustomobject]@{
        Id = 3
        Title = "下载视频"
        Batch = $true
        Notes = @(
            "核心命令：yt-dlp --concurrent-fragments 50 --merge-output-format mp4 ... `"$Url`"",
            "--concurrent-fragments 50 提速明显，但可能触发 403/429；被限速时降到 4-8。",
            "--merge-output-format mp4 需要 ffmpeg；已有文件默认跳过，强制重下加 --force-overwrites。",
            "输出模板：<标题> [<id>].<扩展名>。"
        )
        Preview = {
            @(Format-CommandText -Exe "yt-dlp" -Arguments (Get-VideoDownloadArgs))
        }
        Invoke = {
            Invoke-External -Exe "yt-dlp" -Arguments (Get-VideoDownloadArgs) -StepId 3 -Title "下载视频"
        }
    },

    [pscustomobject]@{
        Id = 4
        Title = "下载官方字幕七种格式（手工检查）"
        Batch = $false
        Notes = @(
            "七种格式：json3 / srv3 / srv2 / srv1 / ttml / vtt / srt。",
            "每种格式单独跑一次 yt-dlp，避免 --sub-format 只保留一个文件。",
            "--sleep-subtitles $SleepSubtitles 秒用于降低 429；英文和中文都会等待。",
            "输出文件名是 <id>.<语言>.<格式>，例如 <id>.en-orig.vtt。",
            "这一步用于手工检查；-All 主路径会跳过它，由第 5 步直接下载并规范命名。",
            "某个格式不存在时 yt-dlp 可能返回 0 或非 0；加 -KeepGoing 可继续后面的格式。"
        )
        Preview = {
            $lines = @()
            foreach ($fmt in @("json3", "srv3", "srv2", "srv1", "ttml", "vtt", "srt")) {
                $lines += Format-CommandText -Exe "yt-dlp" -Arguments (Get-SubtitleDownloadArgs -SubFormat $fmt)
            }
            $lines
        }
        Invoke = {
            $formats = @("json3", "srv3", "srv2", "srv1", "ttml", "vtt", "srt")
            $failed = @()
            foreach ($fmt in $formats) {
                Invoke-External -Exe "yt-dlp" -Arguments (Get-SubtitleDownloadArgs -SubFormat $fmt) `
                    -StepId 4 -Title "下载官方字幕 $fmt" -AllowFailure
                $code = $script:LastExternalExitCode
                if ($code -ne 0) {
                    $failed += $fmt
                    if (-not $KeepGoing) {
                        throw "字幕格式 $fmt 下载失败；加 -KeepGoing 可继续其余格式。"
                    }
                }
            }
            if ($failed.Count -eq $formats.Count) {
                throw "七种字幕格式全部失败；先检查第 1 步的 --list-subs 输出和网络。"
            }
            if ($failed.Count -gt 0) {
                Write-Warning ("以下格式失败：" + ($failed -join ", "))
            }
        }
    },

    [pscustomobject]@{
        Id = 5
        Title = "规范字幕文件名（en-orig / zh-Hans）"
        Batch = $true
        Notes = @(
            "第 4 步是原始 yt-dlp 下载，文件名可能是 en / zh-Hans；本地流程只认 en-orig / zh-Hans。",
            "fetch_youtube_captions.py 会下载七格式、重命名并写 CAPTION_FORMATS.json；主路径用它代替第 4 步。",
            "这个 wrapper 目前不转发 -Proxy / -Browser / -CookiesFile；需要时先设置 HTTPS_PROXY 或用第 6 步的在线 preset。",
            "video id 从链接自动解析；解析失败时用 -VideoId 指定。"
        )
        Preview = {
            @(Format-CommandText -Exe $Python -Arguments (Get-CanonicalCaptionArgs))
        }
        Invoke = {
            Invoke-External -Exe $Python -Arguments (Get-CanonicalCaptionArgs) -StepId 5 -Title "规范字幕文件名"
        }
    },

    [pscustomobject]@{
        Id = 6
        Title = "官方英文 + 官方中文 -> 本地双语 ASS"
        Batch = $true
        Notes = @(
            "默认 preset offline-official：只读本地字幕，不再访问网络。",
            "前提：第 5 步已经生成 en-orig 和 zh-Hans；官方中文缺失时这一步会失败。",
            "官方中文缺失时改用第 7 步（机器翻译中文）。",
            "输出：bilingual_precise_Chinese-English.ass、TIMING.json、LOCAL_FLOW.json。"
        )
        Preview = {
            @(Format-CommandText -Exe $Python -Arguments (Get-FlowArgs -Preset $FlowPreset))
        }
        Invoke = {
            Invoke-External -Exe $Python -Arguments (Get-FlowArgs -Preset $FlowPreset) -StepId 6 -Title "生成本地双语 ASS"
        }
    },

    [pscustomobject]@{
        Id = 7
        Title = "官方英文 + 机器翻译中文"
        Batch = $false
        Notes = @(
            "在线 preset local-youtube-mt：YouTube 官方英文 + 机器翻译中文。",
            "即使本地已有中文轨，也会用机器翻译替换。",
            "翻译引擎默认 argos（本地、无需 key）；有 ASSEMBLYAI 时可传 -TranslationEngine assemblyai。",
            "这一步会重新探测并下载官方英文字幕；需要代理/cookies 时用第 4 步的 yt-dlp 参数。"
        )
        Preview = {
            @(Format-CommandText -Exe $Python -Arguments (Get-FlowArgs -Preset "local-youtube-mt"))
        }
        Invoke = {
            Invoke-External -Exe $Python -Arguments (Get-FlowArgs -Preset "local-youtube-mt") -StepId 7 -Title "官方英文 + 机器翻译中文"
        }
    },

    [pscustomobject]@{
        Id = 8
        Title = "ASR 英文 + 机器翻译中文"
        Batch = $false
        Notes = @(
            "在线 preset local-asr-mt：强制 ASR，不探测 YouTube 英文字幕。",
            "默认 whisper（faster-whisper，本地）；有 ASSEMBLYAI 时可传 -AsrEngine assemblyai。",
            "只有确认 YouTube 没有英文轨时才建议用这一步，避免不必要的付费转写。",
            "其他维度（ASR + 官方中文、仅 URL 等）见 docs/LOCAL_FLOW_MATRIX.md。"
        )
        Preview = {
            @(Format-CommandText -Exe $Python -Arguments (Get-FlowArgs -Preset "local-asr-mt"))
        }
        Invoke = {
            Invoke-External -Exe $Python -Arguments (Get-FlowArgs -Preset "local-asr-mt") -StepId 8 -Title "ASR 英文 + 机器翻译中文"
        }
    },

    [pscustomobject]@{
        Id = 9
        Title = "刻录 ASS 到视频"
        Batch = $true
        Notes = @(
            "ffmpeg 用 libx264 重编码视频，音频直接 copy。",
            "ASS 路径里的 Windows 盘符冒号会转义成 \:；路径分隔符统一成正斜杠。",
            "输出默认是 <原文件名>_bilingual.mp4；可用 -OutputVideo 覆盖。",
            "刻录前确认第 6/7/8 步已经生成 ASS。"
        )
        Preview = {
            $paths = Get-BurnPaths
            if (-not $paths.Video -or -not $paths.Ass) {
                @("# 找不到视频或 ASS；先跑第 3、6 步，或用 -InputVideo / -AssFile 指定。")
            }
            else {
                @(Format-CommandText -Exe "ffmpeg" -Arguments (Get-BurnArgs -Paths $paths))
            }
        }
        Invoke = {
            $paths = Get-BurnPaths
            if (-not $paths.Video -or -not $paths.Ass) {
                if ($DryRun) {
                    Write-Host "# dry-run：找不到视频或 ASS，跳过第 9 步。" -ForegroundColor Yellow
                    return
                }
                throw "找不到视频或 ASS；请先跑第 3、6 步，或用 -InputVideo / -AssFile 指定。"
            }
            Invoke-External -Exe "ffmpeg" -Arguments (Get-BurnArgs -Paths $paths) -StepId 9 -Title "刻录 ASS"
        }
    },

    [pscustomobject]@{
        Id = 10
        Title = "验收输出"
        Batch = $true
        Notes = @(
            "用 ffprobe 看时长、文件大小、码率。",
            "再人工播放一遍，确认字幕位置、断句和中英文都没有溢出。",
            "正式发布前还要检查 BURN.json / 字幕人体工学报告。"
        )
        Preview = {
            $paths = Get-BurnPaths
            $target = $null
            if ($paths.Output -and (Test-Path -LiteralPath $paths.Output)) { $target = $paths.Output }
            elseif ($paths.Video) { $target = $paths.Video }
            if (-not $target) {
                @("# 找不到输出视频；先跑第 9 步，或用 -InputVideo 指定。")
            }
            else {
                @(Format-CommandText -Exe "ffprobe" -Arguments (Get-VerifyArgs -Target $target))
            }
        }
        Invoke = {
            $paths = Get-BurnPaths
            $target = $null
            if ($paths.Output -and (Test-Path -LiteralPath $paths.Output)) { $target = $paths.Output }
            elseif ($paths.Video) { $target = $paths.Video }
            if (-not $target) {
                if ($DryRun) {
                    Write-Host "# dry-run：找不到输出视频，跳过第 10 步。" -ForegroundColor Yellow
                    return
                }
                throw "找不到输出视频；请先跑第 9 步，或用 -InputVideo 指定。"
            }
            Invoke-External -Exe "ffprobe" -Arguments (Get-VerifyArgs -Target $target) -StepId 10 -Title "验收输出"
        }
    }
)

# ---------------------------------------------------------------------------
# 展示 / 调度
# ---------------------------------------------------------------------------

function Show-StepList {
    foreach ($item in $script:Steps) {
        Write-Host ""
        Write-Host ("# " + ("=" * 74)) -ForegroundColor DarkGray
        Write-Host ("# 步骤 {0}：{1}" -f $item.Id, $item.Title) -ForegroundColor Yellow
        if (-not $item.Batch) {
            Write-Host "# （手工/备选分支，不参与 -All）" -ForegroundColor DarkYellow
        }
        foreach ($note in $item.Notes) {
            Write-Host ("# " + $note) -ForegroundColor DarkGray
        }
        Write-Host ("# " + ("-" * 74)) -ForegroundColor DarkGray
        $lines = & $item.Preview
        foreach ($line in $lines) {
            Write-Host $line -ForegroundColor White
        }
    }
    Write-Host ""
    Write-Host "用法：" -ForegroundColor Yellow
    Write-Host "  .\scripts\manual_local_flow.ps1 `"<链接>`" -Step 1        # 单步"
    Write-Host "  .\scripts\manual_local_flow.ps1 `"<链接>`" -Step 1,2,4    # 多步"
    Write-Host "  .\scripts\manual_local_flow.ps1 `"<链接>`" -All -Yes      # 主路径批处理"
    Write-Host "  .\scripts\manual_local_flow.ps1 -List                    # 只看命令"
}

function Get-StepById {
    param([int]$Id)
    $found = @($script:Steps | Where-Object { $_.Id -eq $Id })
    if ($found.Count -eq 0) {
        throw "未知步骤 $Id；可用步骤：$((@($script:Steps | ForEach-Object { $_.Id })) -join ', ')"
    }
    return $found[0]
}

function Expand-StepIds {
    param([string[]]$Values)
    $ids = @()
    foreach ($value in $Values) {
        foreach ($part in ($value -split ',')) {
            $trimmed = $part.Trim()
            if (-not $trimmed) { continue }
            $parsed = 0
            if (-not [int]::TryParse($trimmed, [ref]$parsed)) {
                throw "步骤号必须是整数：$trimmed"
            }
            $ids += $parsed
        }
    }
    return $ids
}

$script:VideoId = Resolve-VideoId -Link $Url -Explicit $VideoId

if ($All -and $Step) {
    throw "不能同时使用 -All 和 -Step。"
}

if ($List) {
    Show-StepList
    return
}

$selectedIds = @()
if ($All) {
    $selectedIds = @($script:Steps | Where-Object { $_.Batch } | ForEach-Object { $_.Id })
}
elseif ($Step) {
    $selectedIds = @(Expand-StepIds -Values $Step)
}
else {
    Show-StepList
    return
}

if ($All -and -not $Yes -and -not $DryRun) {
    $answer = Read-Host "将依次执行主路径步骤 $($selectedIds -join ', ')（会下载、刻录）。继续？[y/N]"
    if ($answer -notmatch '^[yY]') {
        Write-Host "已取消。" -ForegroundColor Yellow
        return
    }
}

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

if (-not $LogPath) {
    $LogPath = Join-Path $OutDir "MANUAL_FLOW_COMMANDS.jsonl"
}
$logParent = Split-Path -Parent ([System.IO.Path]::GetFullPath($LogPath))
if ($logParent -and -not (Test-Path -LiteralPath $logParent)) {
    New-Item -ItemType Directory -Path $logParent -Force | Out-Null
}
$script:LogFile = [System.IO.Path]::GetFullPath($LogPath)

$failedSteps = @()
foreach ($id in $selectedIds) {
    $item = Get-StepById -Id $id
    Write-Host ""
    Write-Host ("===== 步骤 {0}：{1} =====" -f $item.Id, $item.Title) -ForegroundColor Green
    try {
        & $item.Invoke
    }
    catch {
        $failedSteps += $id
        Write-Warning $_.Exception.Message
        if (-not $KeepGoing) {
            Write-Host ("命令日志：" + $script:LogFile) -ForegroundColor Yellow
            exit 1
        }
    }
}

Write-Host ""
Write-Host ("命令日志：" + $script:LogFile) -ForegroundColor Yellow
if ($failedSteps.Count -gt 0) {
    Write-Warning ("失败步骤：" + ($failedSteps -join ", "))
    exit 1
}
exit 0
