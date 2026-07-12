#!/bin/sh
# Maintenance container entrypoint
#
# Watches the webui service and publishes deploy_time.json, which the 503 page
# reads so every client shares one server-authoritative view of the restart.
#
# The file carries three things, all of them observed rather than guessed:
#
#   start  when webui actually stopped answering (epoch ms)
#   phase  "down"     — nothing listening on the port yet
#          "starting" — port is open but /api/health/ isn't 200 yet, i.e. Flask
#                       is booting: building assets, connecting to the DB
#   eta    how long restarts REALLY take on this box, as the median of the last
#          few. Seeded with a guess, then replaced by measurement. The 503 page
#          used to hardcode "~3 min" and draw a curve against it; now the number
#          comes from what actually happened.

DATA_DIR="/usr/share/nginx/html/data"
TIMESTAMP_FILE="$DATA_DIR/deploy_time.json"
HISTORY_FILE="$DATA_DIR/restart_history"   # one duration (ms) per line, newest last

# Probe the health endpoint, NOT "/". "/" is a 302 to the login page, which wget
# follows — so every poll rendered the whole login template and cost 4 queries.
# At a 1-second interval that was ~86k requests and ~350k queries a day.
WEBUI_HOST="webui"
WEBUI_PORT="5000"
WEBUI_URL="http://${WEBUI_HOST}:${WEBUI_PORT}/api/health/"

CHECK_INTERVAL=5
STALE_THRESHOLD=300    # seconds — a timestamp older than this is from a dead run
HISTORY_KEEP=5         # how many past restarts to average over
DEFAULT_ETA_MS=180000  # only used until we've measured a real restart

mkdir -p "$DATA_DIR"

# ── Cleanup on exit ──────────────────────────────────────
cleanup() {
    rm -f "$TIMESTAMP_FILE" "${TIMESTAMP_FILE}.tmp"
}
trap cleanup EXIT TERM INT

now_ms() { echo "$(date +%s)000"; }

# ── Probe: distinguish "not listening" from "listening but not ready" ──
# These are the only two states observable from outside the container, but they
# are real, which the old six-step phase list was not.
# Health is authoritative for "up". nc is only used to tell a hard "down" (nothing
# listening) apart from "starting" (port open, app still booting) — so if this image
# ever ships without nc, we degrade to the old up/down behaviour instead of breaking.
probe_phase() {
    if wget -q --spider --timeout=3 "$WEBUI_URL" 2>/dev/null; then
        echo "up"
    elif command -v nc >/dev/null 2>&1 && nc -z -w 2 "$WEBUI_HOST" "$WEBUI_PORT" 2>/dev/null; then
        echo "starting"
    else
        echo "down"
    fi
}

# ── ETA: median of the last few real restarts ────────────
current_eta() {
    if [ -s "$HISTORY_FILE" ]; then
        count=$(wc -l < "$HISTORY_FILE")
        if [ "$count" -gt 0 ]; then
            # median: sort, take the middle line
            mid=$(( count / 2 + 1 ))
            sort -n "$HISTORY_FILE" | sed -n "${mid}p"
            return
        fi
    fi
    echo "$DEFAULT_ETA_MS"
}

record_restart() {
    # $1 = duration in ms. Ignore absurd values (clock jumps, container rebuilds
    # that idled for hours) so one bad sample can't poison the estimate.
    d="$1"
    [ "$d" -lt 5000 ] && return
    [ "$d" -gt 1800000 ] && return
    echo "$d" >> "$HISTORY_FILE"
    # keep only the most recent HISTORY_KEEP entries
    tail -n "$HISTORY_KEEP" "$HISTORY_FILE" > "${HISTORY_FILE}.tmp" 2>/dev/null \
        && mv -f "${HISTORY_FILE}.tmp" "$HISTORY_FILE"
}

# ── Atomic write of the state file ───────────────────────
write_state() {
    # $1 = start (ms), $2 = phase
    printf '{"start": %s, "phase": "%s", "eta": %s}\n' "$1" "$2" "$(current_eta)" \
        > "${TIMESTAMP_FILE}.tmp"
    mv -f "${TIMESTAMP_FILE}.tmp" "$TIMESTAMP_FILE"
}

# ── Purge a stale timestamp left by a previous container run ──
if [ -f "$TIMESTAMP_FILE" ]; then
    stale_start=$(sed 's/.*"start":[[:space:]]*\([0-9]*\).*/\1/' "$TIMESTAMP_FILE" | head -c 10)
    now=$(date +%s)
    if [ -n "$stale_start" ] && [ $(( now - stale_start )) -gt "$STALE_THRESHOLD" ]; then
        rm -f "$TIMESTAMP_FILE"
    fi
fi

# ── Initial check BEFORE nginx starts, so the very first 503 has a timestamp ──
start_ms=""
init_phase=$(probe_phase)
if [ "$init_phase" != "up" ]; then
    start_ms=$(now_ms)
    write_state "$start_ms" "$init_phase"
fi

# ── Watcher ──────────────────────────────────────────────
(
    was="$init_phase"

    while true; do
        sleep "$CHECK_INTERVAL"
        phase=$(probe_phase)

        if [ "$phase" != "up" ]; then
            if [ "$was" = "up" ] || [ -z "$start_ms" ]; then
                # Just went down — this is the moment the restart began.
                start_ms=$(now_ms)
            fi
            # Rewrite every tick so the page sees down -> starting as it happens.
            write_state "$start_ms" "$phase"
        elif [ "$was" != "up" ] && [ -n "$start_ms" ]; then
            # Back up — measure how long that actually took, then learn from it.
            record_restart $(( $(date +%s)000 - start_ms ))
            rm -f "$TIMESTAMP_FILE"
            start_ms=""
        fi

        was="$phase"
    done
) &

# Start nginx in the foreground
exec nginx -g 'daemon off;'
