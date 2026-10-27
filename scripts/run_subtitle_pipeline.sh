#!/bin/bash
set -euo pipefail

echo "=== Video Subtitle Processing Pipeline ==="
VIDEO_PATH="/workspace/videos/Trump_Rally_Michigan_2024.mp4"
echo "Step 1: Video path: $VIDEO_PATH"
ls -la "$VIDEO_PATH" 2>&1 || echo "Video not found (expected - need YouTube access)"
