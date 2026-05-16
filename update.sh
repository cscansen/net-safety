#!/usr/bin/env bash
# Pulls latest net-safety from GitHub and redeploys if anything changed.
# Runs as root via systemd timer.
set -euo pipefail

REPO_DIR="/opt/net-safety-src"
DEPLOY_DIR="/opt/kid-proxy"
LOG="/var/log/kid-proxy-update.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

if [ ! -d "$REPO_DIR/.git" ]; then
    log "ERROR: $REPO_DIR not a git repo — run setup.sh first"
    exit 1
fi

cd "$REPO_DIR"
git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

log "Update detected: $LOCAL -> $REMOTE"
git pull origin main --quiet

rsync -a --delete \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='update.sh' \
    --exclude='kid-update.service' \
    --exclude='kid-update.timer' \
    "$REPO_DIR/" "$DEPLOY_DIR/"

chown -R kidproxy:kidproxy "$DEPLOY_DIR"

# Ensure always-allowed domains exist in the DB (idempotent upsert).
sqlite3 /var/lib/kid-proxy/db.sqlite \
    "INSERT OR IGNORE INTO whitelist (domain, daily_limit_minutes, weekly_limit_minutes, approved_by, active)
     VALUES ('microbit.org', NULL, NULL, 'system', 1);"

systemctl restart kid-proxy kid-admin
log "Redeployed successfully"
