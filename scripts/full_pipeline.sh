#!/bin/bash
set -euo pipefail

# =============================================================================
# FULL PIPELINE: Proxy -> Download YouTube video + subtitles -> Translate
# -> Burn bilingual subtitles -> Publish to Release + GitHub Pages
# Runs on GitHub Actions runner (ubuntu-latest) or locally.
# Uses repository proxy code: scripts/select_public_ytdlp_proxy.py
# =============================================================================

VIDEO_ID="${1:-9aPyO1jfDGM}"
YOUTUBE_URL="https://www.youtube.com/watch?v=${VIDEO_ID}"
OUTPUT_DIR="output"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export PATH="${REPO_ROOT}/bin:${PATH}"

echo "============================================================"
echo "  FULL PIPELINE: ${VIDEO_ID}"
echo "============================================================"
echo "Video URL: ${YOUTUBE_URL}"
echo "Output dir: ${OUTPUT_DIR}"
echo ""

# ---- Step 0: Select fastest public proxy (repo code) ----
echo "Step 0: Selecting public proxy..."
export YTDLP_PROXY=""
if python scripts/select_public_ytdlp_proxy.py; then
  echo "Proxy selected: ${YTDLP_PROXY:-<none>}"
else
  echo "No public proxy available; will try direct connection."
fi

# ---- Step 1: Download video + bilingual subtitles and burn-in ----
echo ""
echo "Step 1: Downloading video + subtitles and burning-in..."
python scripts/download_youtube_bilingual_srt.py \
  "${YOUTUBE_URL}" \
  --languages "zh-Hans,en-orig" \
  --output-dir "${OUTPUT_DIR}" \
  --burn-in

BURNED_MP4="$(find "${OUTPUT_DIR}" -type f -name "Burned_Bilingual_${VIDEO_ID}.mp4" -print -quit)"
if [[ -z "${BURNED_MP4}" || ! -f "${BURNED_MP4}" ]]; then
  echo "::error::Burned MP4 not found: ${BURNED_MP4}"
  exit 1
fi
echo "Burned video: ${BURNED_MP4}"

# ---- Step 2: Publish MP4 to GitHub Release ----
echo ""
echo "Step 2: Publishing MP4 to GitHub Release..."
if gh release view "${VIDEO_ID}" >/dev/null 2>&1; then
  gh release upload "${VIDEO_ID}" "${BURNED_MP4}" --clobber
else
  gh release create "${VIDEO_ID}" "${BURNED_MP4}" \
    --title "Bilingual Video ${VIDEO_ID}" \
    --notes "Automatically archived from YouTube with Chinese and English subtitles burned in."
fi

# ---- Step 3: Generate video pages (GitHub Pages site) ----
echo ""
echo "Step 3: Generating Pages site..."
python scripts/generate_video_pages.py

# ---- Step 4: Commit and push site/ + output/ to repo ----
echo ""
echo "Step 4: Committing and pushing site + output..."
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add output/ site/
if ! git diff --cached --quiet; then
  git commit -m "Publish bilingual video ${VIDEO_ID}"
  git push origin HEAD:main
else
  echo "No changes to commit."
fi

echo ""
echo "============================================================"
echo "  PIPELINE COMPLETE: ${VIDEO_ID}"
echo "============================================================"
echo "Burned MP4: ${BURNED_MP4}"
echo "Release: https://github.com/gitsynonyms01/gitsynonyms/releases/tag/${VIDEO_ID}"
echo "Pages:    https://gitsynonyms01.github.io/gitsynonyms/videos/${VIDEO_ID}.html"
echo "============================================================"
