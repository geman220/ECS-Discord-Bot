#!/usr/bin/env bash
# backup_public_media.sh — nightly tarball of the public-site media dirs.
#
# The uploads live on a host bind mount (gitignored) — without this there is
# NO copy of the marketing site's images anywhere else. Run from the repo's
# Discord-Bot-WebUI directory via host cron, e.g.:
#   15 3 * * * cd /path/to/ECS-Discord-Bot/Discord-Bot-WebUI && ./scripts/backup_public_media.sh
#
# Keeps the last 14 backups locally. Copy backups/ offsite (rclone/rsync) —
# a host-disk loss otherwise still loses everything.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups/public-media}"
STAMP="$(date +%Y%m%d-%H%M%S)"
KEEP=14

mkdir -p "$BACKUP_DIR"
tar czf "$BACKUP_DIR/public-media-$STAMP.tar.gz" \
    app/static/img/publeague \
    app/static/img/uploads 2>/dev/null

# Prune to the newest $KEEP
ls -1t "$BACKUP_DIR"/public-media-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "backup written: $BACKUP_DIR/public-media-$STAMP.tar.gz ($(du -h "$BACKUP_DIR/public-media-$STAMP.tar.gz" | cut -f1))"
