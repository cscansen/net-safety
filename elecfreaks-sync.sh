#!/usr/bin/env bash
# Mirror the ElecFreaks micro:bit wiki for offline use.
# Stores under /var/www/elecfreaks-kb/en/microbit/ (no host dir).
# Safe to re-run — wget only fetches changed files.

set -euo pipefail

DEST="/var/www/elecfreaks-kb"
LOG="/var/log/elecfreaks-sync.log"
URL="https://wiki.elecfreaks.com/en/microbit/"

mkdir -p "$DEST"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ElecFreaks KB sync..." | tee -a "$LOG"

wget \
    --mirror \
    --no-host-directories \
    --convert-links \
    --adjust-extension \
    --page-requisites \
    --no-parent \
    --no-verbose \
    --restrict-file-names=windows \
    -e robots=off \
    --wait=1 \
    --random-wait \
    --directory-prefix="$DEST" \
    "$URL" 2>>"$LOG" || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync complete." | tee -a "$LOG"
