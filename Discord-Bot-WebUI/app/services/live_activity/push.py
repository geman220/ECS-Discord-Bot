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

Payload contract (canonical full-state, per mobile spec 2026-04-28):
ActivityKit replaces the entire content-state on every push (no merge). So
every push carries the SAME canonical schema regardless of which signal
triggered it. Mobile decodes one Swift ContentState struct off this — partial
slices would null out un-mentioned fields on the lock screen.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
# Canonical full-state builder
# -----------------------------------------------------------------------------

def _empty_last_event() -> Dict[str, Any]:
    """Pre-event default. All four event fields are nullable as a group."""
    return {
        'last_event_type': None,
        'last_event_minute': None,
        'last_event_player': None,
        'last_event_team': None,
        'last_event_at_epoch_ms': None,
    }


def _get_match_teams(session, match_id: int, league_type: str) -> Tuple[str, str]:
    """Return (home_name, away_name). Falls back to 'TBD' on missing rows."""
    from app.models import Team
    if league_type == 'pub':
        from app.models import Match
        match = session.query(Match).get(int(match_id))
        if not match:
            return ('TBD', 'TBD')
        home = session.query(Team).get(match.home_team_id) if match.home_team_id else None
        away = session.query(Team).get(match.away_team_id) if match.away_team_id else None
        return (
            home.name if home and home.name else 'TBD',
            away.name if away and away.name else 'TBD',
        )
    if league_type == 'ecs_fc':
        from app.models.ecs_fc import EcsFcMatch
        match = session.query(EcsFcMatch).get(int(match_id))
        if not match:
            return ('TBD', 'TBD')
        team = session.query(Team).get(match.team_id) if match.team_id else None
        team_name = team.name if team and team.name else 'TBD'
        opponent_name = getattr(match, 'opponent_name', None) or 'External Opponent'
        if getattr(match, 'is_home_match', True):
            return (team_name, opponent_name)
        return (opponent_name, team_name)
    return ('TBD', 'TBD')


def _get_latest_event(session, match_id: int, league_type: str) -> Optional[Dict[str, Any]]:
    """
    Latest event from SQL for this match. Returns None pre-event.

    Read happens once per push (cheap — single indexed query). We don't cache
    in Redis because event writes can happen out-of-band (admin web edits a
    historical event) and we'd rather pay the query than ship stale state.
    """
    from app.models import Player, Team
    event = None
    if league_type == 'pub':
        # MatchEvent lives in app.database.db_models alongside the other live
        # reporting tables (LiveMatch, ActiveMatchReporter, PlayerShift).
        from app.database.db_models import MatchEvent
        event = (
            session.query(MatchEvent)
            .filter(MatchEvent.match_id == int(match_id))
            .order_by(MatchEvent.timestamp.desc())
            .first()
        )
    elif league_type == 'ecs_fc':
        from app.models.ecs_fc import EcsFcMatchEvent
        event = (
            session.query(EcsFcMatchEvent)
            .filter(EcsFcMatchEvent.match_id == int(match_id))
            .order_by(EcsFcMatchEvent.timestamp.desc())
            .first()
        )
    if event is None:
        return None
    player = session.query(Player).get(event.player_id) if event.player_id else None
    team = session.query(Team).get(event.team_id) if event.team_id else None
    ts = event.timestamp
    return {
        'last_event_type': event.event_type,
        'last_event_minute': event.minute,
        'last_event_player': player.name if player else None,
        'last_event_team': team.name if team else None,
        'last_event_at_epoch_ms': int(ts.timestamp() * 1000) if ts else None,
    }


def _compute_phase(state: Dict[str, Any], timer_proj: Dict[str, Any]) -> str:
    """
    pre_match: timer hasn't started yet (no elapsed time, not running, no scores).
    live:      anything in progress.
    complete:  the report has been submitted.
    """
    if state.get('report_status') == 'SUBMITTED':
        return 'complete'
    has_timer_activity = (
        bool(timer_proj.get('is_running')) or
        bool(timer_proj.get('is_paused')) or
        bool(timer_proj.get('is_stopped')) or
        int(timer_proj.get('base_elapsed_ms') or 0) > 0
    )
    if has_timer_activity:
        return 'live'
    has_score = (
        int(state.get('home_score') or 0) > 0 or
        int(state.get('away_score') or 0) > 0
    )
    return 'live' if has_score else 'pre_match'


def _full_content_state(
    match_id: int,
    league_type: str,
    ended_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the canonical full content-state for a Live Activity push.

    Reads V2 Redis state via load_state. If no Redis state exists yet (e.g.
    a Live Activity registered for a match that hasn't been opened by any
    coach), synthesizes a sensible pre-match default WITHOUT writing Redis
    (we don't want a passive push to seed permanent state).

    Always returns the full canonical schema documented in the module header.
    Every key is present; nullable fields are explicit `None` per mobile spec.
    """
    from app.services.live_reporting import redis_state

    session = db.session
    state = redis_state.load_state(league_type, int(match_id))
    if state is None:
        state = {
            'home_score': 0,
            'away_score': 0,
            'timer': redis_state.initial_timer(),
            'report_status': 'IN_PROGRESS',
        }

    timer_proj = redis_state.derive_timer_projection(
        state.get('timer') or redis_state.initial_timer()
    )

    home_name, away_name = _get_match_teams(session, match_id, league_type)
    last_event = _get_latest_event(session, match_id, league_type) or _empty_last_event()
    phase = _compute_phase(state, timer_proj)

    return {
        'home_score': int(state.get('home_score') or 0),
        'away_score': int(state.get('away_score') or 0),
        'home_team_name': home_name,
        'away_team_name': away_name,

        'period': timer_proj.get('period') or '1H',
        'is_running': bool(timer_proj.get('is_running')),
        'is_paused': bool(timer_proj.get('is_paused')),
        'is_stopped': bool(timer_proj.get('is_stopped')),
        'base_elapsed_ms': int(timer_proj.get('base_elapsed_ms') or 0),
        'last_start_epoch_ms': timer_proj.get('last_start_epoch_ms'),
        'pause_reason': timer_proj.get('pause_reason'),

        'last_event_type': last_event['last_event_type'],
        'last_event_minute': last_event['last_event_minute'],
        'last_event_player': last_event['last_event_player'],
        'last_event_team': last_event['last_event_team'],
        'last_event_at_epoch_ms': last_event['last_event_at_epoch_ms'],

        'phase': 'complete' if ended_reason else phase,
        'ended_reason': ended_reason,

        'server_epoch_ms': redis_state.now_ms(),
    }


# -----------------------------------------------------------------------------
# Public push helpers — signatures unchanged; payload is now canonical full-state
# -----------------------------------------------------------------------------

def push_score_update(
    match_id: int,
    league_type: str,
    home_score: int,
    away_score: int,
    home_team_name: Optional[str] = None,
    away_team_name: Optional[str] = None,
) -> None:
    """
    Score changed — high-priority Live Activity update with full content-state.

    The home_score/away_score/team_name parameters are accepted for backward
    compatibility but are NOT trusted — the canonical state is read from Redis
    inside _full_content_state. This avoids drift if the caller's local copy
    is stale.
    """
    if not has_active_tokens(match_id, league_type):
        return
    state = _full_content_state(match_id, league_type)
    alert = {
        'title': 'Goal',
        'body': f"{state['home_team_name']} {state['home_score']}-{state['away_score']} {state['away_team_name']}",
    }
    _push_to_match(match_id, league_type, state, alert=alert, priority=10)


def push_timer_update(
    match_id: int,
    league_type: str,
    timer_projection: Dict[str, Any],
    state_changed: bool = False,
) -> None:
    """
    Timer state changed — full-state Live Activity push.

    `state_changed=True` for start / pause / stop / reset / set_period
    transitions; we mark those high priority. Plain elapsed-time ticks stay
    low-priority and the iOS widget computes elapsed locally from the anchor
    fields (base_elapsed_ms + last_start_epoch_ms) without needing every push.
    The timer_projection arg is accepted for legacy callers but the canonical
    timer state is read fresh from Redis.
    """
    if not has_active_tokens(match_id, league_type):
        return
    state = _full_content_state(match_id, league_type)
    _push_to_match(
        match_id, league_type, state,
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
    """
    A goal / card / sub / substitution fired — high-priority full-state push.

    Args are still accepted but the canonical last-event fields come from a
    fresh DB read inside _full_content_state. This guarantees the lock-screen
    banner matches what's actually persisted (no race between client emit and
    DB commit).
    """
    if not has_active_tokens(match_id, league_type):
        return
    state = _full_content_state(match_id, league_type)
    # Build alert from the FRESH state, not the caller's args, so lock-screen
    # banner copy matches the canonical content-state exactly.
    le_type = state.get('last_event_type') or event_type
    le_min = state.get('last_event_minute') or minute
    le_player = state.get('last_event_player') or player_name
    le_team = state.get('last_event_team') or team_name
    alert_parts = [le_type or 'Match update']
    if le_min:
        alert_parts.append(f"{le_min}'")
    if le_player:
        alert_parts.append(le_player)
    alert = {
        'title': le_team or 'Match update',
        'body': ' '.join(alert_parts),
    }
    _push_to_match(match_id, league_type, state, alert=alert, priority=10)


def end_activities(match_id: int, league_type: str, reason: str = 'submitted') -> int:
    """
    Send `event: end` to all active Live Activities for this match and mark
    the rows ended. Returns the count of tokens we attempted to end.

    The end push carries the full canonical content-state with phase='complete'
    and the supplied ended_reason ('submitted', 'abandoned', 'reset'), plus a
    dismissal-date ~10 minutes out so users have time to glance at the final.
    """
    tokens = _active_tokens(match_id, league_type)
    if not tokens:
        return 0
    now = datetime.utcnow()
    state = _full_content_state(match_id, league_type, ended_reason=reason)
    dismissal_ts = int(time.time()) + (10 * 60)
    aps_extra = {'dismissal-date': dismissal_ts}
    _send_to_tokens(
        tokens,
        content_state=state,
        event='end',
        aps_extra=aps_extra,
        priority=10,
    )
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
    _send_to_tokens(
        tokens,
        content_state=content_state,
        event='update',
        aps_extra=aps_extra,
        priority=priority,
    )


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
