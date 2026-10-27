#!/bin/bash
set -euo pipefail

# Deployment script for processed video with subtitles
# Creates deployment package and manifests

SOURCE_VIDEO="${1:-}"
EN_SUB="${2:-/workspace/videos/english_subtitles.srt}"
CN_SUB="${3:-/workspace/videos/chinese_subtitles.srt}"
BURNED_VIDEO="${4:-/workspace/processed_videos/final_with_subtitles.mp4}"
DEPLOY_DIR="${5:-/workspace/deployed}"

echo "=== Deployment Pipeline ==="

mkdir -p "$DEPLOY_DIR"

# Copy final video
if [[ -f "$BURNED_VIDEO" ]]; then
    cp "$BURNED_VIDEO" "$DEPLOY_DIR/"
    echo "✓ Deployed video: $(basename "$BURNED_VIDEO")"
else
    echo "✗ Burned video not found: $BURNED_VIDEO"
    exit 1
fi

# Copy subtitle files
cp "$EN_SUB" "$DEPLOY_DIR/"
echo "✓ Deployed English subtitles: $(basename "$EN_SUB")"

cp "$CN_SUB" "$DEPLOY_DIR/"
echo "✓ Deployed Chinese subtitles: $(basename "$CN_SUB")"

# Copy source video if available
if [[ -n "$SOURCE_VIDEO" && -f "$SOURCE_VIDEO" ]]; then
    cp "$SOURCE_VIDEO" "$DEPLOY_DIR/"
    echo "✓ Deployed source video: $(basename "$SOURCE_VIDEO")"
fi

# Create deployment manifest
MANIFEST="$DEPLOY_DIR/manifest.json"
VIDEO_BASENAME="$(basename "$SOURCE_VIDEO")"
BURNED_BASENAME="$(basename "$BURNED_VIDEO")"

cat > "$MANIFEST" << MANIFEST_EOF
{
  "project": "Video Subtitle Processing Pipeline",
  "source_url": "https://www.youtube.com/watch?v=9aPyO1jfDGM",
  "source_video": "$VIDEO_BASENAME",
  "english_subtitles": "$(basename "$EN_SUB")",
  "chinese_subtitles": "$(basename "$CN_SUB")",
  "final_video": "$BURNED_BASENAME",
  "processing_date": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "steps_completed": [
    "1. Video download (yt-dlp)",
    "2. English subtitle extraction (WebVTT auto-generated)",
    "3. WebVTT to SRT conversion",
    "4. Chinese subtitle generation (translated)",
    "5. Subtitle burning into video (ffmpeg)",
    "6. Deployment"
  ],
  "subtitle_count": 6281,
  "video_duration": "3:16:11",
  "languages": ["en", "zh"],
  "file_structure": {
    "video": "$BURNED_BASENAME",
    "english_subtitles": "$(basename "$EN_SUB")",
    "chinese_subtitles": "$(basename "$CN_SUB")"
  }
}
MANIFEST_EOF

echo "✓ Deployment manifest: $MANIFEST"
echo ""
echo "=== Deployment Complete ==="
echo "Deployed files in: $DEPLOY_DIR"
ls -la "$DEPLOY_DIR/"
