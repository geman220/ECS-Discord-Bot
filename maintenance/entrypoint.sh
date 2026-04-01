#!/bin/sh
# Maintenance container entrypoint
# Monitors the webui service and writes deploy_time.json when it goes down,
# so all clients share the same server-authoritative start time.

DATA_DIR="/usr/share/nginx/html/data"
TIMESTAMP_FILE="$DATA_DIR/deploy_time.json"
WEBUI_URL="http://webui:5000/"
CHECK_INTERVAL=1
STALE_THRESHOLD=300   # seconds — files older than 5 min are stale

mkdir -p "$DATA_DIR"

# ── Cleanup on exit ──────────────────────────────────────
cleanup() {
    rm -f "$TIMESTAMP_FILE" "${TIMESTAMP_FILE}.tmp"
}
trap cleanup EXIT TERM INT

# ── Helper: atomic write ─────────────────────────────────
write_timestamp() {
    echo "{\"start\": $(date +%s)000}" > "${TIMESTAMP_FILE}.tmp"
    mv -f "${TIMESTAMP_FILE}.tmp" "$TIMESTAMP_FILE"
}

# ── Purge stale timestamp from a previous container run ──
if [ -f "$TIMESTAMP_FILE" ]; then
    stale_start=$(sed 's/.*"start":[[:space:]]*\([0-9]*\).*/\1/' "$TIMESTAMP_FILE" | head -c 10)
    now=$(date +%s)
    if [ $(( now - stale_start )) -gt "$STALE_THRESHOLD" ]; then
        rm -f "$TIMESTAMP_FILE"
    fi
fi

# ── Initial check BEFORE nginx starts ────────────────────
# If webui is already down, create the file now so the very
# first 503 page load has a timestamp available.
if ! wget -q --spider --timeout=2 "$WEBUI_URL" 2>/dev/null; then
    write_timestamp
fi

# ── Background watcher (1-second interval) ────────────────
(
    was_up="unknown"

    while true; do
        if wget -q --spider --timeout=2 "$WEBUI_URL" 2>/dev/null; then
            is_up="yes"
        else
            is_up="no"
        fi

        if [ "$is_up" = "no" ] && [ "$was_up" != "no" ]; then
            # Webui just went down — record the timestamp
            write_timestamp
        elif [ "$is_up" = "yes" ] && [ "$was_up" != "yes" ]; then
            # Webui just came back — clear the timestamp
            rm -f "$TIMESTAMP_FILE"
        fi

        was_up="$is_up"
        sleep "$CHECK_INTERVAL"
    done
) &

# Start nginx in the foreground
exec nginx -g 'daemon off;'
