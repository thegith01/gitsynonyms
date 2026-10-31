$ErrorActionPreference = "Stop"

# The scan logic lives in resolve_channel_feed.py so it can be unit tested and
# shared by Linux and Windows runners.  Keep this wrapper for older workflow
# templates that still call the PowerShell entry point.
& python (Join-Path $PSScriptRoot "resolve_channel_feed.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
