#!/bin/sh
# Maintenance container entrypoint
# Monitors the webui service and writes deploy_time.json when it goes down,
# so all clients share the same server-authoritative start time.

DATA_DIR="/usr/share/nginx/html/data"
TIMESTAMP_FILE="$DATA_DIR/deploy_time.json"
WEBUI_URL="http://webui:5000/"
CHECK_INTERVAL=3

mkdir -p "$DATA_DIR"

# Background watcher: detect webui up/down transitions
(
    was_up="unknown"

    while true; do
        # Quick HEAD request with short timeout
        if wget -q --spider --timeout=2 "$WEBUI_URL" 2>/dev/null; then
            is_up="yes"
        else
            is_up="no"
        fi

        if [ "$is_up" = "no" ] && [ "$was_up" != "no" ]; then
            # Webui just went down — record the timestamp (ms since epoch)
            now_ms=$(date +%s)000
            echo "{\"start\": $now_ms}" > "$TIMESTAMP_FILE"
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
