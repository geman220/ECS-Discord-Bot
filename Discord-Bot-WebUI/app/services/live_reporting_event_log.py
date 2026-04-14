"""
Redis-backed ring buffer of recent live-reporting events.

Used by the admin UI (/admin-panel/mls/live-reporting) to surface what the
realtime reporting service is doing in near-real-time without a database
migration or log-file scraping. Events are trimmed to `MAX_EVENTS_PER_SESSION`
per session and expire after `EVENT_TTL_SECONDS`.

Each event is a small JSON blob with:
  - timestamp  (ISO-8601 UTC)
  - stage      ("poll", "espn_event", "ai", "post", "session", "error")
  - outcome    ("ok", "fallback", "rejected", "error", "info")
  - session_id (int)
  - match_id   (str, optional)
  - message    (human-readable short description)
  - context    (optional dict — event_type, player, minute, league, score, etc.)

Reads (`get_recent_events`) are cheap — a single LRANGE. Writes (`record_event`)
are a pipelined LPUSH + LTRIM + EXPIRE.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)


# Tunables — retention is bounded so Redis doesn't grow unbounded even if
# the realtime service is logging aggressively across many sessions.
MAX_EVENTS_PER_SESSION = 500
MAX_EVENTS_GLOBAL = 1000
EVENT_TTL_SECONDS = 24 * 3600  # 24h


def _session_key(session_id: Optional[int]) -> str:
    """Redis key for per-session event list."""
    return f"live_reporting:events:session:{session_id or 'none'}"


def _global_key() -> str:
    """Redis key for the cross-session recent-events list (used by the UI)."""
    return "live_reporting:events:recent"


def record_event(
    *,
    stage: str,
    outcome: str,
    session_id: Optional[int] = None,
    match_id: Optional[str] = None,
    message: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append a live-reporting event to the Redis ring buffers.

    Writes silently (never raises) — the reporting service should never be
    tripped by an audit-log failure. If Redis is unavailable, falls through
    to the SafeRedisClient no-op path.
    """
    try:
        payload = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "epoch": time.time(),
            "stage": stage,
            "outcome": outcome,
            "session_id": session_id,
            "match_id": str(match_id) if match_id is not None else None,
            "message": message[:500],  # bound message size
            "context": context or {},
        }
        encoded = json.dumps(payload, default=str)

        redis = get_safe_redis()
        if not redis.is_available:
            return

        # Per-session list (LPUSH newest-first, trim to MAX_EVENTS_PER_SESSION)
        if session_id is not None:
            session_key = _session_key(session_id)
            redis.lpush(session_key, encoded)
            # SafeRedis doesn't expose LTRIM; use execute_command
            redis.execute_command("LTRIM", session_key, 0, MAX_EVENTS_PER_SESSION - 1)
            redis.expire(session_key, EVENT_TTL_SECONDS)

        # Global cross-session list (for the admin UI)
        global_key = _global_key()
        redis.lpush(global_key, encoded)
        redis.execute_command("LTRIM", global_key, 0, MAX_EVENTS_GLOBAL - 1)
        redis.expire(global_key, EVENT_TTL_SECONDS)
    except Exception as e:
        # Never let audit-logging break the reporting pipeline.
        logger.debug(f"live_reporting_event_log.record_event failed: {e}")


def get_recent_events(
    limit: int = 100, session_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Return the most recent events (newest first).

    Args:
        limit: Max entries to return (capped at 500).
        session_id: If provided, scope to one session's events; otherwise
            returns the cross-session recent list.
    """
    limit = max(1, min(int(limit or 100), 500))
    try:
        redis = get_safe_redis()
        if not redis.is_available:
            return []
        key = _session_key(session_id) if session_id is not None else _global_key()
        raw = redis.lrange(key, 0, limit - 1)
        out: List[Dict[str, Any]] = []
        for entry in raw:
            if isinstance(entry, bytes):
                entry = entry.decode("utf-8")
            try:
                out.append(json.loads(entry))
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        logger.debug(f"live_reporting_event_log.get_recent_events failed: {e}")
        return []


def clear_events(session_id: Optional[int] = None) -> None:
    """
    Remove events from Redis. Pass `session_id=None` to clear the global list.
    """
    try:
        redis = get_safe_redis()
        if not redis.is_available:
            return
        key = _session_key(session_id) if session_id is not None else _global_key()
        redis.delete(key)
    except Exception as e:
        logger.debug(f"live_reporting_event_log.clear_events failed: {e}")
