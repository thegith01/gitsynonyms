$ErrorActionPreference = "Stop"

if ($env:GITHUB_REF -ne "refs/heads/main") {
    throw "The White House monitor must run from main to publish the site."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "../..")
$stateFile = Join-Path $repoRoot ".github/state/whitehouse-processed-videos.txt"
$processed = if (Test-Path $stateFile) { Get-Content $stateFile } else { @() }
$failureFile = Join-Path $repoRoot ".github/state/whitehouse-failed-videos.txt"
$failureLimit = 3
$failures = @{}
if (Test-Path $failureFile) {
    foreach ($line in Get-Content $failureFile) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match "^\s*#") { continue }
        $fields = $line.Trim() -split "\s+", 2
        if ($fields[0] -notmatch "^[A-Za-z0-9_-]{11}$" -or $fields.Count -lt 2) { continue }
        $count = 0
        if ([int]::TryParse($fields[1], [ref]$count)) {
            $failures[$fields[0]] = $count
        }
    }
}
$videoId = ""
$videoTitle = ""
$channels = @(
      "https://www.youtube.com/@WhiteHouse/videos",
      "https://www.youtube.com/@WhiteHouse/streams"
)
$forcedVideoId = $env:FORCE_VIDEO_ID
if (-not [string]::IsNullOrWhiteSpace($forcedVideoId)) {
    if ($forcedVideoId -notmatch "^[A-Za-z0-9_-]{11}$") {
        throw "FORCE_VIDEO_ID must be an 11-character YouTube video ID: $forcedVideoId"
    }
    $videoId = $forcedVideoId
    $videoTitle = $forcedVideoId
    $channels = @()
    Write-Host "Processing the operator-selected video $videoId instead of the channel listing."
}

$proxyArguments = @()
if (-not [string]::IsNullOrWhiteSpace($env:YTDLP_PROXY)) {
    $proxyArguments = @("--proxy", $env:YTDLP_PROXY)
}
$foundItems = 0
foreach ($channel in $channels) {
      $listing = & yt-dlp @proxyArguments --no-warnings --ignore-errors --flat-playlist --playlist-end 10 --print "%(id)s|%(title)s" $channel
      if ($LASTEXITCODE -ne 0 -and $listing.Count -eq 0) {
          throw "Could not inspect White House channel: $channel"
      }
      foreach ($line in $listing) {
          $parts = $line -split "\|", 2
          $candidate = $parts[0]
          if ($candidate -notmatch "^[A-Za-z0-9_-]{11}$") { continue }
          $foundItems++
          if ($env:FORCE_CHECK -ne "true" -and $processed -contains $candidate) { continue }
          if ($env:FORCE_CHECK -ne "true" -and $failures.ContainsKey($candidate) -and $failures[$candidate] -ge $failureLimit) {
              Write-Host "Skipping $candidate after $($failures[$candidate]) failed attempts so newer uploads can proceed."
              continue
          }

          $videoId = $candidate
          $videoTitle = if ($parts.Count -gt 1 -and $parts[1]) { $parts[1] } else { $videoId }
          break
      }
      if ($videoId) { break }
}
if (-not $videoId -and $foundItems -eq 0) {
      throw "No video IDs were returned by either White House channel listing."
}

if ($videoId) {
    Write-Host "Discovered ${videoId}: $videoTitle"
} else {
      Write-Host "No unprocessed uploads found in the latest channel entries."
}

$videoTitle = $videoTitle.Replace("%", "%25").Replace("`r", "%0D").Replace("`n", "%0A")
"video_id=$videoId" | Add-Content -Path $env:GITHUB_OUTPUT -Encoding utf8
"video_title=$videoTitle" | Add-Content -Path $env:GITHUB_OUTPUT -Encoding utf8
