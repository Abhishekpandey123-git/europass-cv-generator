#!/usr/bin/env bash
# Daily backup of the CV database. Install with:
#   sudo cp deploy/backup.sh /etc/cron.daily/europass-cv-backup && sudo chmod +x /etc/cron.daily/europass-cv-backup
set -euo pipefail
APP_DIR="/opt/europass-cv"
DEST="$APP_DIR/backups"
mkdir -p "$DEST"
sqlite3 "$APP_DIR/data/cvs.db" ".backup '$DEST/cvs-$(date +%F).db'"
find "$DEST" -name 'cvs-*.db' -mtime +30 -delete
