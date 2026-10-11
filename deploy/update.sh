#!/usr/bin/env bash
# Deploy a newer version of the code. Keeps .env and the CV database.
#
#   sudo bash deploy/update.sh
set -euo pipefail
APP_DIR="/opt/europass-cv"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

echo "==> Backing up the database"
install -d -o europass -g europass "$APP_DIR/backups"
[[ -f "$APP_DIR/data/cvs.db" ]] && sqlite3 "$APP_DIR/data/cvs.db" ".backup '$APP_DIR/backups/cvs-$(date +%F-%H%M).db'" 2>/dev/null || true

echo "==> Copying new code"
rsync -a --delete \
    --exclude venv --exclude .venv --exclude __pycache__ --exclude .git \
    --exclude data --exclude output --exclude backups --exclude .env \
    "$SRC_DIR"/ "$APP_DIR"/
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R europass:europass "$APP_DIR"

systemctl restart europass-cv
sleep 2
systemctl is-active --quiet europass-cv && echo "Updated and running." || journalctl -u europass-cv -n 20 --no-pager
