"""
Redis-backed LiveMatchState for coach-reported live matches.

Durable per-match state that survives client disconnects and (single-worker)
Gunicorn restarts. Paired with `app/sockets/live_reporting.py` V2 handlers and
`app/tasks/tasks_live_reporting_timers.py` Celery jobs.

Key pattern:
    live_match:pub:{match_id}:state       — Pub League
    live_match:ecs_fc:{match_id}:state    — ECS FC

Each key holds a single JSON blob (simple, atomic-set, avoids per-field race
windows in a single-worker deploy). TTL is refreshed on every write.

Timer is never ticked by the server — elapsed_ms is computed on read:
    if is_running:
        elapsed = base_elapsed_ms + (now_ms - last_start_epoch_ms)
    else:
        elapsed = base_elapsed_ms

NOTE: This module is intentionally Celery-free. Enqueueing and revoking timer
tasks lives in `app/tasks/tasks_live_reporting_timers.py` to avoid a circular
import on the Celery app.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)


# League type literals used in Redis key namespace and match_state payload.
LEAGUE_PUB = 'pub'
LEAGUE_ECS_FC = 'ecs_fc'
VALID_LEAGUE_TYPES = (LEAGUE_PUB, LEAGUE_ECS_FC)

# Report-status literals.
REPORT_IN_PROGRESS = 'IN_PROGRESS'
REPORT_SUBMITTED = 'SUBMITTED'

# Timer actions accepted by apply_timer_action.
TIMER_ACTIONS = ('start', 'resume', 'pause', 'stop', 'reset')

# Default period string on reset / fresh state.
DEFAULT_PERIOD = '1H'


# -----------------------------------------------------------------------------
# Time helpers
# -----------------------------------------------------------------------------

def now_ms() -> int:
    """UTC epoch milliseconds. Server-authoritative clock for timer math."""
    return int(time.time() * 1000)


# -----------------------------------------------------------------------------
# Key + TTL
# -----------------------------------------------------------------------------

def _key(league_type: str, match_id: int) -> str:
    if league_type not in VALID_LEAGUE_TYPES:
        raise ValueError(f"Invalid league_type: {league_type!r}")
    return f"live_match:{league_type}:{int(match_id)}:state"


def _ttl_seconds() -> int:
    # Imported lazily to avoid web_config import at module load.
    from web_config import Config
    return int(getattr(Config, 'LIVE_MATCH_STATE_TTL_SECONDS', 86400))


# -----------------------------------------------------------------------------
# Load / save / delete
# -----------------------------------------------------------------------------

def load_state(league_type: str, match_id: int) -> Optional[Dict[str, Any]]:
    """Return the state dict or None if no live state exists for this match."""
    key = _key(league_type, match_id)
    redis = get_safe_redis()
    with redis.safe_operation('live_match_state:get', default_return=None) as (client, ok):
        if not ok or client is None:
            return None
        raw = client.get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.exception(f"Corrupt LiveMatchState JSON at {key}; discarding")
        delete_state(league_type, match_id)
        return None


def save_state(league_type: str, match_id: int, state: Dict[str, Any]) -> None:
    """Persist state + refresh TTL. Bumps updated_at to now_ms()."""
    key = _key(league_type, match_id)
    state = dict(state)  # shallow copy so caller's dict isn't bound to mutations we make
    state['updated_at_ms'] = now_ms()
    payload = json.dumps(state)
    redis = get_safe_redis()
    with redis.safe_operation('live_match_state:set', default_return=None) as (client, ok):
        if not ok or client is None:
            logger.warning(f"Redis unavailable; dropped LiveMatchState write for {key}")
            return
        client.set(key, payload, ex=_ttl_seconds())


def delete_state(league_type: str, match_id: int) -> None:
    key = _key(league_type, match_id)
    redis = get_safe_redis()
    with redis.safe_operation('live_match_state:del', default_return=None) as (client, ok):
        if not ok or client is None:
            return
        client.delete(key)


# -----------------------------------------------------------------------------
# Initial-state factories
# -----------------------------------------------------------------------------

def initial_timer(period: str = DEFAULT_PERIOD) -> Dict[str, Any]:
    return {
        'is_running': False,
        'is_paused': False,
        'is_stopped': False,
        'base_elapsed_ms': 0,
        'last_start_epoch_ms': None,
        'period': period,
        'pause_reason': None,
        'updated_at_ms': now_ms(),
        'updated_by_user_id': None,
    }


def initial_state(
    match_id: int,
    league_type: str,
    home_team_id: Optional[int],
    away_team_id: Optional[int],
    home_score: int = 0,
    away_score: int = 0,
    report_status: str = REPORT_IN_PROGRESS,
    submitted_by_user_id: Optional[int] = None,
    submitted_at: Optional[str] = None,
) -> Dict[str, Any]:
    now = now_ms()
    shift_timers: Dict[str, Dict[str, Any]] = {}
    for tid in (home_team_id, away_team_id):
        if tid is not None:
            shift_timers[str(tid)] = initial_timer()
    return {
        'match_id': int(match_id),
        'league_type': league_type,
        'home_team_id': home_team_id,
        'away_team_id': away_team_id,
        'timer': initial_timer(),
        'shift_timers': shift_timers,
        'home_score': int(home_score or 0),
        'away_score': int(away_score or 0),
        'last_score_sequence': 0,
        'last_score_update_by_user_id': None,
        'report_status': report_status,
        'submitted_by_user_id': submitted_by_user_id,
        'submitted_at': submitted_at,
        'timer_halftime_task_id': None,
        'timer_fulltime_task_id': None,
        'timer_autostop_task_id': None,
        'last_halftime_fcm_at_ms': None,
        'last_fulltime_fcm_at_ms': None,
        'created_at_ms': now,
        'updated_at_ms': now,
    }


# -----------------------------------------------------------------------------
# Timer math
# -----------------------------------------------------------------------------

def computed_elapsed_ms(timer: Dict[str, Any], at_ms: Optional[int] = None) -> int:
    """
    Derive current elapsed time. Server never ticks — this is the read rule.
    Pass `at_ms` for deterministic computation at a specific instant.
    """
    if at_ms is None:
        at_ms = now_ms()
    base = int(timer.get('base_elapsed_ms') or 0)
    if timer.get('is_running') and timer.get('last_start_epoch_ms'):
        return base + (at_ms - int(timer['last_start_epoch_ms']))
    return base


def apply_timer_action(
    timer: Dict[str, Any],
    action: str,
    user_id: Optional[int],
    pause_reason: Optional[str] = None,
    period: Optional[str] = None,
    elapsed_override_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Mutate `timer` in place and return it.

    - start / resume: is_running=True, last_start_epoch_ms=now, base_elapsed_ms unchanged.
    - pause: fold elapsed into base_elapsed_ms, is_running=False, is_paused=True.
    - stop: same as pause but is_stopped=True, is_paused=False.
    - reset: zero base_elapsed_ms, all flags off, period back to default.

    `elapsed_override_ms` lets the halftime "Apply" FCM action set base_elapsed_ms
    to exactly 25:00 (or whatever target) regardless of where the timer was.
    Only applied on pause/stop.
    """
    if action not in TIMER_ACTIONS:
        raise ValueError(f"Invalid timer action: {action!r}")

    now = now_ms()

    if action in ('start', 'resume'):
        timer['is_running'] = True
        timer['is_paused'] = False
        timer['is_stopped'] = False
        timer['last_start_epoch_ms'] = now
        timer['pause_reason'] = None

    elif action == 'pause':
        if elapsed_override_ms is not None:
            timer['base_elapsed_ms'] = int(elapsed_override_ms)
        elif timer.get('is_running') and timer.get('last_start_epoch_ms'):
            timer['base_elapsed_ms'] = int(timer.get('base_elapsed_ms') or 0) + (now - int(timer['last_start_epoch_ms']))
        timer['is_running'] = False
        timer['is_paused'] = True
        timer['is_stopped'] = False
        timer['last_start_epoch_ms'] = None
        timer['pause_reason'] = pause_reason or 'manual'

    elif action == 'stop':
        if elapsed_override_ms is not None:
            timer['base_elapsed_ms'] = int(elapsed_override_ms)
        elif timer.get('is_running') and timer.get('last_start_epoch_ms'):
            timer['base_elapsed_ms'] = int(timer.get('base_elapsed_ms') or 0) + (now - int(timer['last_start_epoch_ms']))
        timer['is_running'] = False
        timer['is_paused'] = False
        timer['is_stopped'] = True
        timer['last_start_epoch_ms'] = None
        timer['pause_reason'] = pause_reason

    elif action == 'reset':
        timer['is_running'] = False
        timer['is_paused'] = False
        timer['is_stopped'] = False
        timer['base_elapsed_ms'] = 0
        timer['last_start_epoch_ms'] = None
        timer['period'] = DEFAULT_PERIOD
        timer['pause_reason'] = None

    if period is not None:
        timer['period'] = period

    timer['updated_at_ms'] = now
    timer['updated_by_user_id'] = user_id
    return timer


def apply_main_timer_action(
    state: Dict[str, Any],
    action: str,
    user_id: Optional[int],
    pause_reason: Optional[str] = None,
    period: Optional[str] = None,
    elapsed_override_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Convenience wrapper: apply action to state['timer'] and return state."""
    state['timer'] = apply_timer_action(
        state.get('timer') or initial_timer(),
        action,
        user_id,
        pause_reason=pause_reason,
        period=period,
        elapsed_override_ms=elapsed_override_ms,
    )
    return state


def apply_shift_timer_action(
    state: Dict[str, Any],
    team_id: int,
    action: str,
    user_id: Optional[int],
    pause_reason: Optional[str] = None,
    period: Optional[str] = None,
    elapsed_override_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply a timer action to a per-team shift timer within `state`."""
    key = str(int(team_id))
    shifts = state.setdefault('shift_timers', {})
    timer = shifts.get(key) or initial_timer()
    shifts[key] = apply_timer_action(
        timer,
        action,
        user_id,
        pause_reason=pause_reason,
        period=period,
        elapsed_override_ms=elapsed_override_ms,
    )
    return state


# -----------------------------------------------------------------------------
# Score mutations
# -----------------------------------------------------------------------------

def set_scores(
    state: Dict[str, Any],
    home_score: int,
    away_score: int,
    user_id: Optional[int],
) -> Dict[str, Any]:
    """Absolute score set with monotonic sequence bump."""
    state['home_score'] = int(home_score)
    state['away_score'] = int(away_score)
    state['last_score_sequence'] = int(state.get('last_score_sequence') or 0) + 1
    state['last_score_update_by_user_id'] = user_id
    return state


def increment_score(
    state: Dict[str, Any],
    is_home: bool,
    delta: int,
    user_id: Optional[int],
) -> Dict[str, Any]:
    """Additive score bump (e.g. from GOAL event). Sequence bumps once per call."""
    if is_home:
        state['home_score'] = max(0, int(state.get('home_score') or 0) + int(delta))
    else:
        state['away_score'] = max(0, int(state.get('away_score') or 0) + int(delta))
    state['last_score_sequence'] = int(state.get('last_score_sequence') or 0) + 1
    state['last_score_update_by_user_id'] = user_id
    return state


# -----------------------------------------------------------------------------
# Submit / freeze
# -----------------------------------------------------------------------------

def freeze_state_for_submit(
    state: Dict[str, Any],
    submitted_by_user_id: int,
    submitted_at_iso: str,
) -> Dict[str, Any]:
    """Transition to SUBMITTED. Caller revokes timer tasks separately."""
    state['report_status'] = REPORT_SUBMITTED
    state['submitted_by_user_id'] = submitted_by_user_id
    state['submitted_at'] = submitted_at_iso
    # Clear task IDs — caller has already revoked them before calling this.
    state['timer_halftime_task_id'] = None
    state['timer_fulltime_task_id'] = None
    state['timer_autostop_task_id'] = None
    return state


# -----------------------------------------------------------------------------
# Lazy seed from DB (F7)
# -----------------------------------------------------------------------------

def seed_from_db(session, league_type: str, match_id: int) -> Dict[str, Any]:
    """
    Construct and persist a fresh state row seeded from the permanent DB tables.

    Raises LookupError if the match does not exist.

    Called on any join_match / resync_match when no Redis state is found, so
    mid-match deploys don't wipe the board.
    """
    if league_type == LEAGUE_PUB:
        from app.models.matches import Match
        match = session.query(Match).get(int(match_id))
        if not match:
            raise LookupError(f"Match {match_id} not found")
        home_score = match.home_team_score if match.home_team_score is not None else 0
        away_score = match.away_team_score if match.away_team_score is not None else 0
        reported = match.reported
        submitted_at = match.report_submitted_at.isoformat() if getattr(match, 'report_submitted_at', None) else None
        state = initial_state(
            match_id=match_id,
            league_type=league_type,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            home_score=home_score,
            away_score=away_score,
            report_status=REPORT_SUBMITTED if reported else REPORT_IN_PROGRESS,
            submitted_by_user_id=None,  # not tracked historically
            submitted_at=submitted_at,
        )
    elif league_type == LEAGUE_ECS_FC:
        from app.models.ecs_fc import EcsFcMatch
        match = session.query(EcsFcMatch).get(int(match_id))
        if not match:
            raise LookupError(f"EcsFcMatch {match_id} not found")
        home_score = match.home_score if match.home_score is not None else 0
        away_score = match.away_score if match.away_score is not None else 0
        # For ECS FC, only one real team_id — shift_timers seeded for it.
        home_team_id = match.team_id if match.is_home_match else None
        away_team_id = match.team_id if not match.is_home_match else None
        reported = match.status == 'COMPLETED'
        state = initial_state(
            match_id=match_id,
            league_type=league_type,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            report_status=REPORT_SUBMITTED if reported else REPORT_IN_PROGRESS,
            submitted_by_user_id=None,
            submitted_at=None,
        )
    else:
        raise ValueError(f"Invalid league_type: {league_type!r}")

    save_state(league_type, match_id, state)
    return state


def load_or_seed(session, league_type: str, match_id: int) -> Dict[str, Any]:
    """Load existing state, or seed a fresh one from DB if none."""
    state = load_state(league_type, match_id)
    if state is None:
        state = seed_from_db(session, league_type, match_id)
    return state


# -----------------------------------------------------------------------------
# Formatting for broadcast
# -----------------------------------------------------------------------------

def _format_mmss(ms: int) -> str:
    seconds = max(0, int(ms) // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def derive_timer_projection(timer: Dict[str, Any], at_ms: Optional[int] = None) -> Dict[str, Any]:
    """
    Render a timer block for outbound socket payloads / match_state.
    Contains derived fields clients need (elapsed_time_ms, formatted_time).
    """
    if at_ms is None:
        at_ms = now_ms()
    elapsed_ms = computed_elapsed_ms(timer, at_ms=at_ms)
    return {
        'is_running': bool(timer.get('is_running')),
        'is_paused': bool(timer.get('is_paused')),
        'is_stopped': bool(timer.get('is_stopped')),
        'elapsed_time_ms': elapsed_ms,
        'base_elapsed_ms': int(timer.get('base_elapsed_ms') or 0),
        'last_start_epoch_ms': timer.get('last_start_epoch_ms'),
        'period': timer.get('period') or DEFAULT_PERIOD,
        'pause_reason': timer.get('pause_reason'),
        'formatted_time': _format_mmss(elapsed_ms),
        'match_minute': str(elapsed_ms // 60000),
        'updated_at_ms': timer.get('updated_at_ms'),
        'updated_by_user_id': timer.get('updated_by_user_id'),
    }


def build_match_state_payload(
    state: Dict[str, Any],
    events: List[Dict[str, Any]],
    connected_coaches: List[Dict[str, Any]],
    observers: List[Dict[str, Any]],
    home_team: Optional[Dict[str, Any]] = None,
    away_team: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Assemble the match_state payload (see spec B3). `events` is passed in by
    the caller — events live in SQL, not Redis.
    """
    at = now_ms()
    shift_timers_out = {
        team_id: derive_timer_projection(t, at_ms=at)
        for team_id, t in (state.get('shift_timers') or {}).items()
    }
    payload = {
        'match_id': state['match_id'],
        'league_type': state.get('league_type', LEAGUE_PUB),
        'server_epoch_ms': at,
        'home_team': home_team,
        'away_team': away_team,
        'home_score': int(state.get('home_score') or 0),
        'away_score': int(state.get('away_score') or 0),
        'last_score_sequence': int(state.get('last_score_sequence') or 0),
        'timer': derive_timer_projection(state.get('timer') or initial_timer(), at_ms=at),
        'shift_timers': shift_timers_out,
        'events': events,
        'report_status': state.get('report_status', REPORT_IN_PROGRESS),
        'submitted_by_user_id': state.get('submitted_by_user_id'),
        'submitted_at': state.get('submitted_at'),
        'connected_coaches': connected_coaches,
        'observers': observers,
    }
    return payload
