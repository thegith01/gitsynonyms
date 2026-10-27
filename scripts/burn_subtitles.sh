#!/bin/bash
set -euo pipefail

# Script to burn Chinese and English subtitles into video using ffmpeg
# Usage: ./burn_subtitles.sh <video_file> [english_srt] [chinese_srt] [output_file]

VIDEO_FILE="${1:-}"
EN_SUB="${2:-/workspace/videos/english_subtitles.srt}"
CN_SUB="${3:-/workspace/videos/chinese_subtitles.srt}"
OUTPUT="${4:-/workspace/processed_videos/final_with_subtitles.mp4}"

if [[ -z "$VIDEO_FILE" ]]; then
    echo "Usage: $0 <video_file> [english_srt] [chinese_srt] [output_file]"
    exit 1
fi

if [[ ! -f "$VIDEO_FILE" ]]; then
    echo "ERROR: Video file not found: $VIDEO_FILE"
    exit 1
fi

# Export PATH and fontconfig for ffmpeg/libass
export PATH="/workspace/bin:$PATH"
export FONTCONFIG_FILE="/workspace/.config/fontconfig/fonts.conf"

mkdir -p "$(dirname "$OUTPUT")"

echo "=== Burning Subtitles into Video ==="
echo "Video: $VIDEO_FILE"
echo "English subtitles: $EN_SUB"
echo "Chinese subtitles: $CN_SUB"
echo "Output: $OUTPUT"
echo "Fontconfig: $FONTCONFIG_FILE"

# Create combined subtitle file (burn both English and Chinese)
COMBINED_SUB="/workspace/videos/combined_subtitles.srt"

python3 << PYEOF
import sys

def parse_srt(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = content.strip().split('\n\n')
    entries = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            index = lines[0]
            timestamp = lines[1]
            text = ' '.join(lines[2:])
            entries.append((index, timestamp, text))
    return entries

en_entries = parse_srt('$EN_SUB')
cn_entries = parse_srt('$CN_SUB')

# Create combined subtitles: English on top, Chinese below
combined = []
min_len = min(len(en_entries), len(cn_entries))
for i in range(min_len):
    _, ts, en_text = en_entries[i]
    _, _, cn_text = cn_entries[i]
    combined.append(f'{i+1}\n{ts}\n{en_text}\n{cn_text}\n')

with open('$COMBINED_SUB', 'w', encoding='utf-8') as f:
    f.write('\n'.join(combined))

print(f'Created combined subtitle file: {len(combined)} entries')
PYEOF

echo "Created combined subtitle file: $COMBINED_SUB"

# Burn subtitles into video using libass subtitles filter
echo "Burning subtitles into video (this may take several minutes)..."

ffmpeg -y -i "$VIDEO_FILE" \
    -vf "subtitles=${COMBINED_SUB}:fontsdir=/workspace/fonts:force_style='FontName=DejaVuSans,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Bold=1,BorderStyle=1,Outline=2,Shadow=1,MarginV=30,Alignment=2'" \
    -c:a copy \
    -c:v libx264 \
    -preset medium \
    -crf 23 \
    "$OUTPUT"

echo "========================================="
echo "✓ Video with burned subtitles: $OUTPUT"
echo "========================================="

# Verify output
if [[ -f "$OUTPUT" ]]; then
    echo "Output file size: $(du -h "$OUTPUT" | cut -f1)"
    /workspace/bin/ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 "$OUTPUT"
else
    echo "ERROR: Output file was not created!"
    exit 1
fi
