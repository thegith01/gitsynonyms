<#
.SYNOPSIS
Build the Immersive Translate LOWEST bilingual Chinese-English ASS/SRT from a
local YouTube caption folder.

.DESCRIPTION
Thin, path-stable wrapper around scripts/scheme_local_immersive_lowest.py.
It resolves the repository root from GITSYNONYMS_REPO, then from this skill's
own location, so another agent can call it from any working directory.

.PARAMETER Directory
Folder containing the fourteen caption files and CAPTION_FORMATS.json.

.PARAMETER VideoId
YouTube video id, for example e038Q_qaltQ.

.PARAMETER BoxStyle
Caption background style. Use none when no local media is present.

.PARAMETER CaptionOrder
chinese-first (default) or english-first.

.PARAMETER Media
Optional local video path used to derive the full caption-box duration.

.PARAMETER Strict
Fail on ergonomics errors. Real YouTube auto-captions often have reading-speed
warnings; inspect them instead of dropping words.

.PARAMETER Fetch
Fetch the seven en-orig and seven zh-Hans formats first. Requires network.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Directory,

    [Parameter(Mandatory = $true)]
    [string]$VideoId,

    [ValidateSet('none', 'presidential-blue', 'solid-color', 'glass-diamond')]
    [string]$BoxStyle = 'none',

    [ValidateSet('chinese-first', 'english-first')]
    [string]$CaptionOrder = 'chinese-first',

    [string]$Media,

    [switch]$Strict,

    [switch]$Fetch
)

$ErrorActionPreference = 'Stop'

$scriptPath = $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptPath
$skillDirItem = Get-Item -LiteralPath $skillDir
if ($skillDirItem.LinkType -in @('Junction', 'SymbolicLink') -and $skillDirItem.Target) {
    $target = $skillDirItem.Target
    if (-not [System.IO.Path]::IsPathRooted($target)) {
        $target = Join-Path (Split-Path -Parent $skillDir) $target
    }
    $skillDir = [System.IO.Path]::GetFullPath($target)
}
$repo = $env:GITSYNONYMS_REPO
if (-not $repo) {
    $candidate = (Resolve-Path (Join-Path $skillDir '..\..\..')).Path
    if (Test-Path (Join-Path $candidate 'scripts\scheme_local_immersive_lowest.py')) {
        $repo = $candidate
    }
}
if (-not $repo -or -not (Test-Path (Join-Path $repo 'scripts\scheme_local_immersive_lowest.py'))) {
    throw "Cannot locate the gitsynonyms repository. Set GITSYNONYMS_REPO to its root."
}

$py = $env:GITSYNONYMS_PYTHON
if (-not $py) {
    foreach ($candidate in @(
            (Join-Path $env:USERPROFILE 'anaconda3\envs\a\python.exe'),
            'C:\Users\a2023\anaconda3\envs\a\python.exe'
        )) {
        if (Test-Path $candidate) {
            $py = $candidate
            break
        }
    }
}
if (-not $py) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $py = $pythonCommand.Source }
}
if (-not $py) {
    throw "Python not found. Set GITSYNONYMS_PYTHON to a Python 3.11+ interpreter."
}

if (-not (Test-Path -LiteralPath $Directory)) {
    throw "Caption directory not found: $Directory"
}

if ($Fetch) {
    & $py -X utf8 (Join-Path $repo 'scripts\fetch_youtube_captions.py') `
        --video-id $VideoId --output-dir $Directory --require en-orig,zh-Hans
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$cliArgs = @(
    '-X', 'utf8',
    (Join-Path $repo 'scripts\scheme_local_immersive_lowest.py'),
    '--directory', $Directory,
    '--video-id', $VideoId,
    '--box-style', $BoxStyle,
    '--caption-order', $CaptionOrder
)
if ($Media) { $cliArgs += @('--media', $Media) }
if ($Strict) { $cliArgs += '--strict' }

& $py @cliArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ass = Join-Path $Directory 'bilingual_immersive_lowest_Chinese-English.ass'
$srt = Join-Path $Directory 'bilingual_immersive_lowest_Chinese-English.srt'
$report = Join-Path $Directory 'IMMERSIVE_LOWEST.json'
$ergonomics = Join-Path $Directory 'IMMERSIVE_LOWEST_ERGONOMICS.json'

if (-not (Test-Path -LiteralPath $ass)) { throw "ASS was not produced: $ass" }
if (-not (Test-Path -LiteralPath $srt)) { throw "SRT was not produced: $srt" }
if (-not (Test-Path -LiteralPath $report)) { throw "Report was not produced: $report" }

Write-Host "ASS:         $ass"
Write-Host "SRT:         $srt"
Write-Host "Report:      $report"
Write-Host "Ergonomics:  $ergonomics"
Write-Host "Repository:  $repo"
