#requires -Version 5.1
<#
.SYNOPSIS
Run one or more explicit local caption dimensions, or print the commands for
line-by-line execution.

.DESCRIPTION
Every run is appended to LOCAL_FLOW_COMMANDS.jsonl next to the caption folder.
The Python entry point writes its own decision record to LOCAL_FLOW.json.

Line-by-line:
    .\scripts\local_subtitle_flow.ps1 -List
    # copy any single "& $py ..." line and run it

Batch:
    .\scripts\local_subtitle_flow.ps1 -Preset local-youtube-official,local-youtube-mt
    .\scripts\local_subtitle_flow.ps1 -All -Yes

Dry run (prints and logs the command, does not call Python):
    .\scripts\local_subtitle_flow.ps1 -Preset local-asr-mt -DryRun

.PARAMETER Preset
One or more preset names. Use -List to print all names and commands.

.PARAMETER All
Run every preset in order. Requires -Yes unless -DryRun is used.

.PARAMETER List
Print the variable block and one executable command per preset.

.PARAMETER KeepGoing
Continue with the next preset when one fails (batch mode).
#>
[CmdletBinding()]
param(
    [string[]]$Preset,
    [string]$Url,
    [string]$Directory = "D:\MyDownload\a",
    [string]$VideoId,
    [string]$Python = "C:\Users\a2023\anaconda3\envs\a\python.exe",
    [string]$TranslationEngine,
    [string]$AsrEngine,
    [switch]$All,
    [switch]$List,
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$KeepGoing,
    [string]$LogPath
)

$ErrorActionPreference = "Stop"

$script:PresetNames = @(
    "local-youtube-official",
    "local-youtube-mt",
    "local-asr-mt",
    "local-asr-official",
    "url-youtube-official",
    "url-youtube-mt",
    "offline-official",
    "offline-mt"
)

$script:PresetInfo = @{
    "local-youtube-official" = @{ Kind = "local"; English = "youtube"; Chinese = "official" }
    "local-youtube-mt"       = @{ Kind = "local"; English = "youtube"; Chinese = "mt" }
    "local-asr-mt"           = @{ Kind = "local"; English = "asr";     Chinese = "mt" }
    "local-asr-official"     = @{ Kind = "local"; English = "asr";     Chinese = "official" }
    "url-youtube-official"   = @{ Kind = "url";   English = "youtube"; Chinese = "official" }
    "url-youtube-mt"         = @{ Kind = "url";   English = "youtube"; Chinese = "mt" }
    "offline-official"       = @{ Kind = "offline"; English = "youtube"; Chinese = "official" }
    "offline-mt"             = @{ Kind = "offline"; English = "youtube"; Chinese = "mt" }
}

$script:FlowScript = Join-Path $PSScriptRoot "local_subtitle_flow.py"
if (-not (Test-Path -LiteralPath $script:FlowScript)) {
    throw "local_subtitle_flow.py not found next to this script: $script:FlowScript"
}

function Quote-Argument {
    param([string]$Value)
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Expand-PresetNames {
    param([string[]]$Names)
    $result = @()
    foreach ($name in $Names) {
        foreach ($part in ($name -split ',')) {
            $trimmed = $part.Trim()
            if ($trimmed) { $result += $trimmed }
        }
    }
    return $result
}

function Format-Command {
    param([string[]]$Arguments)
    $all = @($Python) + $Arguments
    return ($all | ForEach-Object { Quote-Argument $_ }) -join " "
}

function New-FlowArguments {
    param(
        [string]$Name,
        [switch]$Placeholder
    )
    $info = $script:PresetInfo[$Name]
    if (-not $info) {
        throw "Unknown preset '$Name'. Use -List to see the supported names."
    }

    $arguments = @("-X", "utf8", $script:FlowScript)
    if ($info.Kind -eq "offline") {
        $id = $VideoId
        if (-not $id -and $Placeholder) { $id = '$vid' }
        if ($id) { $arguments += @("--video-id", $id) }
    }
    else {
        $target = $Url
        if (-not $target -and $Placeholder) { $target = '$url' }
        if (-not $target) {
            throw "Preset '$Name' needs -Url (or use -List to print the command)."
        }
        $arguments += @("--url", $target)
    }

    $arguments += @("--directory", $Directory, "--preset", $Name)

    if ($TranslationEngine -and $info.Chinese -eq "mt") {
        $arguments += @("--translation-engine", $TranslationEngine)
    }
    if ($AsrEngine -and $info.English -eq "asr") {
        $arguments += @("--asr-engine", $AsrEngine)
    }
    return $arguments
}

function Show-FlowCommands {
    $shownUrl = if ($Url) { $Url } else { 'https://youtu.be/<video-id>' }
    $shownId = if ($VideoId) { $VideoId } else { '<video-id>' }
    Write-Output ('$py  = "' + $Python + '"')
    Write-Output ('$dir = "' + $Directory + '"')
    Write-Output ('$url = "' + $shownUrl + '"')
    Write-Output ('$vid = "' + $shownId + '"')
    Write-Output ""
    foreach ($name in $script:PresetNames) {
        $arguments = New-FlowArguments -Name $name -Placeholder
        Write-Output ("# " + $name)
        Write-Output ("& " + (Format-Command -Arguments $arguments))
        Write-Output ""
    }
}

function Write-FlowLog {
    param(
        [string]$Name,
        [string]$CommandLine,
        [int]$ExitCode,
        [double]$DurationSeconds
    )
    $entry = [ordered]@{
        observed_at      = (Get-Date).ToString("o")
        preset           = $Name
        command          = $CommandLine
        exit_code        = $ExitCode
        duration_seconds = [math]::Round($DurationSeconds, 3)
        directory        = $Directory
        url              = $Url
        video_id         = $VideoId
        dry_run          = [bool]$DryRun
    }
    Add-Content -LiteralPath $script:LogFile -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found: $Python (pass -Python <path>)."
}

if ($All -and $Preset) {
    throw "Use either -All or -Preset, not both."
}

if ($List) {
    Show-FlowCommands
    return
}

$selected = @()
if ($All) {
    $selected = $script:PresetNames
}
elseif ($Preset) {
    foreach ($name in (Expand-PresetNames -Names $Preset)) {
        if (-not $script:PresetInfo.ContainsKey($name)) {
            throw "Unknown preset '$name'. Use -List to see the supported names."
        }
        $selected += $name
    }
}
else {
    Show-FlowCommands
    Write-Output "Pass -Preset <name> or -All to run."
    return
}

if ($All -and -not $Yes -and -not $DryRun) {
    $answer = Read-Host "Run all 8 presets in order? [y/N]"
    if ($answer -notmatch '^[yY]') {
        Write-Output "Cancelled."
        return
    }
}

if (-not $LogPath) {
    if (-not (Test-Path -LiteralPath $Directory)) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
    $LogPath = Join-Path $Directory "LOCAL_FLOW_COMMANDS.jsonl"
}
$logParent = Split-Path -Parent ([System.IO.Path]::GetFullPath($LogPath))
if ($logParent -and -not (Test-Path -LiteralPath $logParent)) {
    New-Item -ItemType Directory -Path $logParent -Force | Out-Null
}
$script:LogFile = [System.IO.Path]::GetFullPath($LogPath)

$failed = 0
foreach ($name in $selected) {
    $arguments = New-FlowArguments -Name $name
    $commandLine = "& " + (Format-Command -Arguments $arguments)
    Write-Output ("== " + $name + " ==")
    Write-Output $commandLine

    if ($DryRun) {
        Write-FlowLog -Name $name -CommandLine $commandLine -ExitCode 0 -DurationSeconds 0
        continue
    }

    $start = Get-Date
    & $Python @arguments
    $code = $LASTEXITCODE
    $duration = ((Get-Date) - $start).TotalSeconds
    Write-FlowLog -Name $name -CommandLine $commandLine -ExitCode $code -DurationSeconds $duration

    if ($code -ne 0) {
        $failed += 1
        Write-Warning ("Preset '" + $name + "' failed with exit code " + $code + ".")
        if (-not $KeepGoing) {
            throw "Preset '$name' failed; stopping. Use -KeepGoing to continue."
        }
    }
}

Write-Output ("command log: " + $script:LogFile)
if ($failed -gt 0) {
    exit 1
}
exit 0
