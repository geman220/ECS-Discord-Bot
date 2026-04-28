"""
APNs Live Activity push helpers.

These mirror the V2 socket broadcasts but target backgrounded iOS clients via
their per-Activity push token (registered through the
/api/v1/live-activity/register endpoint).

Auth: reuses the existing PushService._get_apns_jwt_token (same APNs auth key
used for Wallet pushes — Apple keys are per-team, not per-topic).
Topic: <IOS_BUNDLE_ID>.push-type.liveactivity (required header for Live Activities).
Priority: 10 (immediate) for score / event / end. 5 (background) for timer ticks
unless the timer transitioned states (start/pause/stop), in which case 10.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core import db
from app.models.live_activity import LiveActivityToken

logger = logging.getLogger(__name__)

# Determined at module load. iOS bundle ID is set via env (validated by the
# App Link startup guard, so we know it's not a placeholder in production).
_IOS_BUNDLE_ID = os.getenv('IOS_BUNDLE_ID', 'com.example.ecsfc')
_LIVE_ACTIVITY_TOPIC = f"{_IOS_BUNDLE_ID}.push-type.liveactivity"

# APNs hosts. Sandbox is used by default for safety; flip APNS_USE_SANDBOX=false
# in prod env when the App Store build is uploaded.
_APNS_USE_SANDBOX = os.getenv('APNS_USE_SANDBOX', 'true').lower() == 'true'
_APNS_HOST = (
    'https://api.sandbox.push.apple.com' if _APNS_USE_SANDBOX
    else 'https://api.push.apple.com'
)

# Request timeout — APNs is fast; if it's slow it's broken.
_HTTP_TIMEOUT_SECONDS = 4.0

# After this many consecutive failures we mark a token ended so we stop trying.
_MAX_FAILURES_PER_TOKEN = 3


# -----------------------------------------------------------------------------
# Token lookup
# -----------------------------------------------------------------------------

def has_active_tokens(match_id: int, league_type: str) -> bool:
    """Cheap pre-check before building a payload — skip everything if no one's listening."""
    return db.session.query(LiveActivityToken.id).filter(
        LiveActivityToken.match_id == int(match_id),
        LiveActivityToken.league_type == league_type,
        LiveActivityToken.ended_at.is_(None),
    ).first() is not None


def _active_tokens(match_id: int, league_type: str) -> List[LiveActivityToken]:
    return db.session.query(LiveActivityToken).filter(
        LiveActivityToken.match_id == int(match_id),
        LiveActivityToken.league_type == league_type,
        LiveActivityToken.ended_at.is_(None),
    ).all()


# -----------------------------------------------------------------------------
# Public push helpers (one per signal type the live-reporting layer cares about)
# -----------------------------------------------------------------------------

def push_score_update(
    match_id: int,
    league_type: str,
    home_score: int,
    away_score: int,
    home_team_name: Optional[str] = None,
    away_team_name: Optional[str] = None,
) -> None:
    """Score changed — send a high-priority Live Activity update."""
    if not has_active_tokens(match_id, league_type):
        return
    content_state = {
        'home_score': int(home_score),
        'away_score': int(away_score),
    }
    if home_team_name:
        content_state['home_team_name'] = home_team_name
    if away_team_name:
        content_state['away_team_name'] = away_team_name
    alert = None
    if home_team_name and away_team_name:
        alert = {
            'title': 'Goal',
            'body': f'{home_team_name} {home_score}-{away_score} {away_team_name}',
        }
    _push_to_match(match_id, league_type, content_state, alert=alert, priority=10)


def push_timer_update(
    match_id: int,
    league_type: str,
    timer_projection: Dict[str, Any],
    state_changed: bool = False,
) -> None:
    """
    Timer state shipped from `derive_timer_projection`. `state_changed=True` for
    start / pause / stop / reset / set_period transitions; we mark those high
    priority. Plain elapsed-time ticks shouldn't fire Live Activity pushes —
    iOS side computes elapsed locally from anchor data. If the live-reporting
    layer ever wants to push a periodic refresh, pass state_changed=False and
    accept the lower-priority background delivery.
    """
    if not has_active_tokens(match_id, league_type):
        return
    content_state = {
        'period': timer_projection.get('period'),
        'is_running': bool(timer_projection.get('is_running')),
        'is_paused': bool(timer_projection.get('is_paused')),
        'is_stopped': bool(timer_projection.get('is_stopped')),
        'base_elapsed_ms': int(timer_projection.get('base_elapsed_ms') or 0),
        'last_start_epoch_ms': timer_projection.get('last_start_epoch_ms'),
        'pause_reason': timer_projection.get('pause_reason'),
    }
    _push_to_match(
        match_id, league_type, content_state,
        priority=10 if state_changed else 5,
    )


def push_event(
    match_id: int,
    league_type: str,
    event_type: str,
    minute: Optional[str] = None,
    player_name: Optional[str] = None,
    team_name: Optional[str] = None,
) -> None:
    """A goal / card / sub fired — high priority Live Activity push."""
    if not has_active_tokens(match_id, league_type):
        return
    content_state = {
        'last_event_type': event_type,
        'last_event_minute': minute,
        'last_event_player': player_name,
        'last_event_team': team_name,
    }
    alert_body_parts = [event_type]
    if minute:
        alert_body_parts.append(f"{minute}'")
    if player_name:
        alert_body_parts.append(player_name)
    alert = {
        'title': team_name or 'Match update',
        'body': ' '.join(alert_body_parts),
    }
    _push_to_match(match_id, league_type, content_state, alert=alert, priority=10)


def end_activities(match_id: int, league_type: str, reason: str = 'submitted') -> int:
    """
    Send `event: end` to all active Live Activities for this match and mark
    the rows ended. Returns the count of tokens we attempted to end.
    """
    tokens = _active_tokens(match_id, league_type)
    if not tokens:
        return 0
    now = datetime.utcnow()
    # Apple expects a dismissal-date so the activity disappears from lock screen.
    # Set 10 minutes from now so users have time to glance at the final state.
    dismissal_ts = int(time.time()) + (10 * 60)
    aps_extra = {'dismissal-date': dismissal_ts}
    _send_to_tokens(tokens, content_state={'ended_reason': reason}, event='end',
                    aps_extra=aps_extra, priority=10)
    for t in tokens:
        t.ended_at = now
    db.session.commit()
    return len(tokens)


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------

def _push_to_match(
    match_id: int,
    league_type: str,
    content_state: Dict[str, Any],
    alert: Optional[Dict[str, str]] = None,
    priority: int = 10,
) -> None:
    tokens = _active_tokens(match_id, league_type)
    if not tokens:
        return
    aps_extra = {}
    if alert:
        aps_extra['alert'] = alert
    _send_to_tokens(tokens, content_state=content_state, event='update',
                    aps_extra=aps_extra, priority=priority)


def _send_to_tokens(
    tokens: List[LiveActivityToken],
    content_state: Dict[str, Any],
    event: str,
    aps_extra: Optional[Dict[str, Any]] = None,
    priority: int = 10,
) -> None:
    """
    Send the same payload to every active token. Each token gets its own
    HTTP/2 POST since APNs requires per-token requests; we keep a single
    httpx.Client open for connection reuse across tokens within this call.

    Failures are logged + counted. Tokens that fail _MAX_FAILURES_PER_TOKEN
    in a row are marked ended so we stop wasting cycles on them.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — Live Activity push skipped")
        return

    jwt_token = _get_jwt_token()
    if not jwt_token:
        logger.warning("APNs JWT not available — Live Activity push skipped")
        return

    aps: Dict[str, Any] = {
        'timestamp': int(time.time()),
        'event': event,
        'content-state': content_state,
    }
    if aps_extra:
        aps.update(aps_extra)
    payload = {'aps': aps}

    headers_template = {
        'apns-topic': _LIVE_ACTIVITY_TOPIC,
        'apns-push-type': 'liveactivity',
        'apns-priority': str(priority),
        'authorization': f'bearer {jwt_token}',
        'content-type': 'application/json',
    }

    now = datetime.utcnow()
    rows_to_end: List[LiveActivityToken] = []

    try:
        with httpx.Client(http2=True, timeout=_HTTP_TIMEOUT_SECONDS) as client:
            for tok in tokens:
                url = f"{_APNS_HOST}/3/device/{tok.push_token}"
                try:
                    resp = client.post(url, json=payload, headers=headers_template)
                    if resp.status_code == 200:
                        tok.last_pushed_at = now
                        tok.push_failure_count = 0
                        tok.last_error = None
                        continue
                    body = resp.text[:500] if resp.text else ''
                    logger.warning(
                        f"APNs Live Activity push failed: status={resp.status_code} "
                        f"token={tok.push_token[:8]}… body={body!r}"
                    )
                    tok.push_failure_count = (tok.push_failure_count or 0) + 1
                    tok.last_error = f"{resp.status_code}: {body[:200]}"
                    # 410 Gone = invalid token; bail out immediately.
                    if resp.status_code == 410 or tok.push_failure_count >= _MAX_FAILURES_PER_TOKEN:
                        rows_to_end.append(tok)
                except httpx.HTTPError as exc:
                    logger.warning(f"APNs Live Activity HTTP error: {exc}")
                    tok.push_failure_count = (tok.push_failure_count or 0) + 1
                    tok.last_error = str(exc)[:200]
                    if tok.push_failure_count >= _MAX_FAILURES_PER_TOKEN:
                        rows_to_end.append(tok)
    finally:
        # Mark dead tokens ended so future pushes skip them.
        for tok in rows_to_end:
            tok.ended_at = now
        db.session.commit()


def _get_jwt_token() -> Optional[str]:
    """Borrow the existing wallet PushService's JWT generation."""
    try:
        from app.wallet_pass.services.push_service import push_service
    except Exception as exc:
        logger.warning(f"wallet push_service not importable: {exc}")
        return None
    try:
        return push_service._get_apns_jwt_token()
    except Exception as exc:
        logger.warning(f"APNs JWT generation failed: {exc}")
        return None
