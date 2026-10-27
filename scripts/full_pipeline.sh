#!/bin/bash
set -euo pipefail

# =============================================================================
# FULL PIPELINE: Video Download → Subtitle Generation → Burning → Deployment
# Target: https://www.youtube.com/watch?v=9aPyO1jfDGM
# =============================================================================

YOUTUBE_URL="https://www.youtube.com/watch?v=9aPyO1jfDGM"
VIDEO_DIR="/workspace/videos"
OUTPUT_DIR="/workspace/processed_videos"
DEPLOY_DIR="/workspace/deployed"
SCRIPT_DIR="/workspace/scripts"

# Export PATH for ffmpeg and yt-dlp
export PATH="/workspace/bin:$PATH"

echo "=========================================="
echo "  VIDEO SUBTITLE PROCESSING PIPELINE"
echo "=========================================="
echo "YouTube URL: $YOUTUBE_URL"
echo "Video directory: $VIDEO_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Deploy directory: $DEPLOY_DIR"
echo ""

# Step 1: Create directories
echo "Step 1: Creating directories..."
mkdir -p "$VIDEO_DIR" "$OUTPUT_DIR" "$DEPLOY_DIR"
echo "✓ Directories created"

# Step 2: Download video and English subtitles
echo ""
echo "Step 2: Downloading video and English subtitles..."
echo "Running: yt-dlp --write-auto-sub --sub-langs en -f 'bestvideo[height<=480]+bestaudio' \"$YOUTUBE_URL\""
echo ""
echo "NOTE: Due to YouTube bot protection, video download may require:"
echo "  --cookies-from-browser <browser> or --cookies <cookies.txt>"
echo ""

VIDEO_FILE=$(ls "$VIDEO_DIR"/*.mp4 2>/dev/null | head -1 || echo "")
EN_VTT=$(ls "$VIDEO_DIR"/*.en.vtt 2>/dev/null | head -1 || echo "")

if [[ -z "$VIDEO_FILE" ]]; then
    echo "⚠ Video file not found in $VIDEO_DIR"
    echo "  Please run: yt-dlp --write-auto-sub --sub-langs en \"$YOUTUBE_URL\" -o \"$VIDEO_DIR/%(title)s.%(ext)s\""
    echo "  With cookies: --cookies-from-browser chrome"
    echo ""
    read -p "Press Enter to continue with subtitle processing only, or Ctrl+C to abort..."
else
    echo "✓ Video found: $VIDEO_FILE"
fi

if [[ -z "$EN_VTT" ]]; then
    echo "⚠ English VTT subtitles not found"
    echo "  Found: $(ls "$VIDEO_DIR"/*.vtt 2>/dev/null || echo 'none')"
else
    echo "✓ English subtitles found: $EN_VTT"
fi

# Step 3: Convert WebVTT to SRT
echo ""
echo "Step 3: Converting WebVTT to SRT..."
if [[ -n "$EN_VTT" ]]; then
    python3 "$SCRIPT_DIR/subtitle_processor.py" "$EN_VTT" \
        "$OUTPUT_DIR/english_subtitles.srt" \
        "$OUTPUT_DIR/chinese_subtitles.srt"
    echo "✓ SRT subtitles generated"
else
    echo "⚠ Skipping - no English VTT file found"
fi

# Step 4: Burn subtitles into video
echo ""
echo "Step 4: Burning subtitles into video..."
EN_SRT="$OUTPUT_DIR/english_subtitles.srt"
CN_SRT="$OUTPUT_DIR/chinese_subtitles.srt"
BURNED_VIDEO="$OUTPUT_DIR/final_with_subtitles.mp4"

if [[ -n "$VIDEO_FILE" && -f "$EN_SRT" && -f "$CN_SRT" ]]; then
    bash "$SCRIPT_DIR/burn_subtitles.sh" "$VIDEO_FILE" "$EN_SRT" "$CN_SRT" "$BURNED_VIDEO"
    echo "✓ Video with burned subtitles created"
else
    echo "⚠ Skipping subtitle burning - missing required files"
    echo "  Video: ${VIDEO_FILE:-not found}"
    echo "  English SRT: $(test -f "$EN_SRT" && echo 'found' || echo 'not found')"
    echo "  Chinese SRT: $(test -f "$CN_SRT" && echo 'found' || echo 'not found')"
fi

# Step 5: Deploy
echo ""
echo "Step 5: Deploying..."
BURNED_VIDEO="$OUTPUT_DIR/final_with_subtitles.mp4"
if [[ -f "$BURNED_VIDEO" ]]; then
    bash "$SCRIPT_DIR/deploy.sh" "$VIDEO_FILE" "$EN_SRT" "$CN_SRT" "$BURNED_VIDEO" "$DEPLOY_DIR"
    echo "✓ Deployment complete"
else
    echo "⚠ No burned video to deploy"
fi

echo ""
echo "=========================================="
echo "  PIPELINE SUMMARY"
echo "=========================================="
echo "Processed files:"
ls -la "$OUTPUT_DIR/" 2>/dev/null || echo "No output files"
echo ""
echo "Deployed files:"
ls -la "$DEPLOY_DIR/" 2>/dev/null || echo "No deployed files"
echo ""
echo "To complete the video download, run:"
echo "  yt-dlp --write-auto-sub --sub-langs en --cookies-from-browser chrome \\"
echo "    \"$YOUTUBE_URL\" -o \"$VIDEO_DIR/%(title)s.%(ext)s\""
echo "=========================================="
