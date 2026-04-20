"""
Celery timer tasks for V2 live match reporting.

Three scheduled jobs per running match timer:
  - timer_reminder_halftime  (fires at 30-min elapsed)
  - timer_reminder_fulltime  (fires at 60-min elapsed)
  - timer_autostop           (fires at 70-min elapsed; pauses the timer)

Enqueued from `update_timer` on start/resume; revoked on pause/stop/reset and
on submit_report. Each task re-reads Redis LiveMatchState before firing so a
stale queued job no-ops cleanly when the timer has moved on.

Queue: `live-reporting` (pre-existing dedicated worker; keeps timer jobs off
the general queue so ad-hoc admin pushes don't starve them).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from celery.result import AsyncResult

from app.decorators import celery_task
from app.services.live_reporting import redis_state
from app.services.live_reporting.live_match_roles import (
    active_fcm_tokens_for_users,
    coach_user_ids_for_match,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Config accessors (late-bound so tests can override web_config easily)
# -----------------------------------------------------------------------------

def _cfg():
    from web_config import Config
    return Config


def _halftime_reminder_ms() -> int:
    return int(_cfg().LIVE_MATCH_TIMER_HALFTIME_REMINDER_MIN) * 60 * 1000


def _fulltime_reminder_ms() -> int:
    return int(_cfg().LIVE_MATCH_TIMER_FULLTIME_REMINDER_MIN) * 60 * 1000


def _autostop_ms() -> int:
    return int(_cfg().LIVE_MATCH_TIMER_AUTOSTOP_MINUTES) * 60 * 1000


def _halftime_target_ms() -> int:
    return int(_cfg().LIVE_MATCH_HALFTIME_TARGET_ELAPSED_MS)


def _fulltime_target_ms() -> int:
    return int(_cfg().LIVE_MATCH_FULLTIME_TARGET_ELAPSED_MS)


def _deep_link(match_id: int) -> str:
    return f"ecs-fc-scheme://match/{match_id}"


# -----------------------------------------------------------------------------
# Enqueue / revoke — called from update_timer
# -----------------------------------------------------------------------------

def _remaining_seconds(target_ms: int, current_elapsed_ms: int) -> Optional[float]:
    remaining_ms = target_ms - current_elapsed_ms
    if remaining_ms <= 0:
        return None
    return remaining_ms / 1000.0


def enqueue_timer_jobs(state: dict, match_id: int, league_type: str) -> dict:
    """
    Enqueue halftime, fulltime, and autostop jobs based on current elapsed.
    Any target already past is skipped (e.g. timer resumed after 35 min skips
    halftime). Task IDs written into state so callers can revoke later.

    Returns the mutated state.
    """
    current_elapsed_ms = redis_state.computed_elapsed_ms(state.get('timer') or {})

    jobs = {
        'timer_halftime_task_id': (timer_reminder_halftime, _halftime_reminder_ms()),
        'timer_fulltime_task_id': (timer_reminder_fulltime, _fulltime_reminder_ms()),
        'timer_autostop_task_id':  (timer_autostop,          _autostop_ms()),
    }

    for field, (task_fn, target_ms) in jobs.items():
        countdown = _remaining_seconds(target_ms, current_elapsed_ms)
        if countdown is None:
            state[field] = None
            continue
        try:
            result = task_fn.apply_async(
                args=[int(match_id), str(league_type)],
                countdown=countdown,
                queue='live-reporting',
                expires=countdown + 3600,  # give the worker an hour's slack
            )
            state[field] = result.id
            logger.info(
                f"Enqueued {field}={result.id} for match {league_type}:{match_id} "
                f"in {countdown:.0f}s (elapsed={current_elapsed_ms}ms)"
            )
        except Exception:
            logger.exception(f"Failed to enqueue {field} for match {league_type}:{match_id}")
            state[field] = None

    return state


def revoke_timer_jobs(state: dict) -> dict:
    """
    Revoke any pending task_ids stored on state. Safe to call multiple times.
    Returns the mutated state with task_id fields set to None.

    We use `terminate=False` (prevent execution only if not started) instead of
    terminate=True. Each task's pre-flight state check makes late execution a
    no-op, so terminating mid-task would risk partial DB writes for no benefit.
    """
    for field in ('timer_halftime_task_id', 'timer_fulltime_task_id', 'timer_autostop_task_id'):
        task_id = state.get(field)
        if not task_id:
            continue
        try:
            AsyncResult(task_id).revoke(terminate=False)
        except Exception:
            logger.exception(f"Failed to revoke {field}={task_id}")
        state[field] = None
    return state


# -----------------------------------------------------------------------------
# Internal: send a reminder push
# -----------------------------------------------------------------------------

def _send_timer_fcm(
    session,
    match_id: int,
    league_type: str,
    title: str,
    body: str,
    data: dict,
    apns_category: Optional[str],
) -> dict:
    """Resolve coach tokens and hand off to notification_service. Never raises."""
    try:
        coach_ids = coach_user_ids_for_match(session, int(match_id), league_type)
        if not coach_ids:
            logger.info(
                f"No coach user_ids for match {league_type}:{match_id}; skipping timer FCM"
            )
            return {'success': 0, 'failure': 0}
        tokens = active_fcm_tokens_for_users(session, coach_ids)
        if not tokens:
            logger.info(
                f"No active FCM tokens for match {league_type}:{match_id} coaches; skipping"
            )
            return {'success': 0, 'failure': 0}
        # Module-level singleton initialised by app/init/services.py
        from app.services.notification_service import notification_service as _ns_instance
        return _ns_instance.send_push_notification(
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            apns_category=apns_category,
        )
    except Exception:
        logger.exception(f"Timer FCM send failed for match {league_type}:{match_id}")
        return {'success': 0, 'failure': -1}


def _dedup_recent(state: dict, field: str, window_ms: int = 5 * 60 * 1000) -> bool:
    """True if a push on this field was sent within the last window."""
    last_ms = state.get(field)
    if not last_ms:
        return False
    return (redis_state.now_ms() - int(last_ms)) < window_ms


# -----------------------------------------------------------------------------
# Halftime reminder (30 min elapsed)
# -----------------------------------------------------------------------------

@celery_task(
    name='app.tasks.tasks_live_reporting_timers.timer_reminder_halftime',
    queue='live-reporting',
)
def timer_reminder_halftime(self, session, match_id, league_type):
    state = redis_state.load_state(league_type, int(match_id))
    if not state:
        return {'success': True, 'skipped': 'no_state'}
    if state.get('report_status') == redis_state.REPORT_SUBMITTED:
        return {'success': True, 'skipped': 'submitted'}
    timer = state.get('timer') or {}
    if not timer.get('is_running'):
        return {'success': True, 'skipped': 'not_running'}
    current_elapsed = redis_state.computed_elapsed_ms(timer)
    if current_elapsed >= _fulltime_reminder_ms():
        return {'success': True, 'skipped': 'past_fulltime'}
    if _dedup_recent(state, 'last_halftime_fcm_at_ms'):
        return {'success': True, 'skipped': 'recent_dedup'}

    data = {
        'type': 'match_timer_reminder',
        'match_id': str(int(match_id)),
        'league_type': str(league_type),
        'action_hint': 'halftime',
        'target_elapsed_ms': str(_halftime_target_ms()),
        'deep_link': _deep_link(int(match_id)),
        'priority': 'high',
        'click_action': 'FLUTTER_NOTIFICATION_CLICK',
    }
    result = _send_timer_fcm(
        session,
        int(match_id),
        league_type,
        title='Halftime?',
        body='Timer is at 30 minutes. Tap Apply to set 25:00 and pause.',
        data=data,
        apns_category='TIMER_HALFTIME',
    )
    state['last_halftime_fcm_at_ms'] = redis_state.now_ms()
    redis_state.save_state(league_type, int(match_id), state)
    return {'success': True, 'fcm': result}


# -----------------------------------------------------------------------------
# Full-time reminder (60 min elapsed)
# -----------------------------------------------------------------------------

@celery_task(
    name='app.tasks.tasks_live_reporting_timers.timer_reminder_fulltime',
    queue='live-reporting',
)
def timer_reminder_fulltime(self, session, match_id, league_type):
    state = redis_state.load_state(league_type, int(match_id))
    if not state:
        return {'success': True, 'skipped': 'no_state'}
    if state.get('report_status') == redis_state.REPORT_SUBMITTED:
        return {'success': True, 'skipped': 'submitted'}
    timer = state.get('timer') or {}
    if not timer.get('is_running'):
        return {'success': True, 'skipped': 'not_running'}
    if _dedup_recent(state, 'last_fulltime_fcm_at_ms'):
        return {'success': True, 'skipped': 'recent_dedup'}

    data = {
        'type': 'match_timer_reminder',
        'match_id': str(int(match_id)),
        'league_type': str(league_type),
        'action_hint': 'full_time',
        'target_elapsed_ms': str(_fulltime_target_ms()),
        'deep_link': _deep_link(int(match_id)),
        'priority': 'high',
        'click_action': 'FLUTTER_NOTIFICATION_CLICK',
    }
    result = _send_timer_fcm(
        session,
        int(match_id),
        league_type,
        title='Full time?',
        body='Timer is at 60 minutes. Tap Apply to stop at 50:00.',
        data=data,
        apns_category='TIMER_FULLTIME',
    )
    state['last_fulltime_fcm_at_ms'] = redis_state.now_ms()
    redis_state.save_state(league_type, int(match_id), state)
    return {'success': True, 'fcm': result}


# -----------------------------------------------------------------------------
# Auto-stop (70 min elapsed) — pauses the timer and broadcasts
# -----------------------------------------------------------------------------

@celery_task(
    name='app.tasks.tasks_live_reporting_timers.timer_autostop',
    queue='live-reporting',
)
def timer_autostop(self, session, match_id, league_type):
    state = redis_state.load_state(league_type, int(match_id))
    if not state:
        return {'success': True, 'skipped': 'no_state'}
    if state.get('report_status') == redis_state.REPORT_SUBMITTED:
        return {'success': True, 'skipped': 'submitted'}
    timer = state.get('timer') or {}
    if not timer.get('is_running'):
        return {'success': True, 'skipped': 'not_running'}

    # Apply pause with pause_reason='auto_stopped' — server becomes truth.
    redis_state.apply_main_timer_action(
        state,
        action='pause',
        user_id=None,
        pause_reason='auto_stopped',
    )
    redis_state.save_state(league_type, int(match_id), state)

    # Broadcast the frozen timer state to the match room so in-room clients
    # see the pause immediately.
    try:
        from app import socketio
        broadcast = redis_state.derive_timer_projection(state['timer'])
        broadcast.update({
            'match_id': int(match_id),
            'league_type': str(league_type),
            'action': 'auto_stopped',
            'server_epoch_ms': redis_state.now_ms(),
            'timestamp': datetime.utcnow().isoformat(),
        })
        socketio.emit(
            'timer_updated',
            broadcast,
            room=f"match_{int(match_id)}",
            namespace='/live',
        )
    except Exception:
        logger.exception(f"timer_autostop broadcast failed for {league_type}:{match_id}")

    # And FCM the coaches so they know to confirm.
    data = {
        'type': 'match_timer_autostopped',
        'match_id': str(int(match_id)),
        'league_type': str(league_type),
        'deep_link': _deep_link(int(match_id)),
        'priority': 'high',
        'click_action': 'FLUTTER_NOTIFICATION_CLICK',
    }
    fcm_result = _send_timer_fcm(
        session,
        int(match_id),
        league_type,
        title='Timer auto-paused',
        body='70 min reached. Confirm the match to report it.',
        data=data,
        apns_category=None,
    )
    return {'success': True, 'fcm': fcm_result}
