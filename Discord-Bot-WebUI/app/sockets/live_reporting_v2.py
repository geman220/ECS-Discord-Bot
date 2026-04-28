"""
V2 handlers for the /live socket namespace.

Registered from `app/sockets/live_reporting.py` — this module contains pure
handler functions that the V1 decorated handlers delegate to when
`LIVE_MATCH_STATE_V2_ENABLED` is true.

V2 differences vs V1:
  - Timer math is server-authoritative (`base_elapsed_ms + last_start_epoch_ms`).
  - Live state persists in Redis via `app.services.live_reporting.redis_state`.
  - `add_event` dual-writes MatchEvent + PlayerEvent (Pub League) or
    EcsFcMatchEvent + EcsFcPlayerEvent (ECS FC) with live stat rollup.
  - Admins/refs join without a team_id and show up as observers.
  - Timer start/resume enqueues halftime/fulltime/autostop Celery jobs.
  - `update_score` writes the permanent scores immediately, not on submit.
  - `submit_report` is a status flip via the shared submit_helper.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import request
from flask_socketio import emit, join_room, leave_room, disconnect

from app.core import socketio, db
from app.sockets.session import socket_session
from app.database.db_models import (
    ActiveMatchReporter,
    LiveMatch,
    MatchEvent,
    PlayerShift,
)
from app.models import (
    Match,
    Team,
    Player,
    User,
    PlayerEvent,
    PlayerEventType,
    EcsFcMatch,
    EcsFcPlayerEvent,
    EcsFcLiveMatch,
    EcsFcMatchEvent,
)
from app.teams_helpers import update_player_stats
from app.services.event_deduplication import (
    check_duplicate_match_event,
    find_near_duplicate_match_events,
    serialize_match_event_with_reporter,
    parse_client_timestamp,
)
from app.services.live_reporting import redis_state
from app.services.live_reporting.live_match_roles import (
    is_admin_or_ref,
    resolve_league_type,
    infer_league_type_from_match_id,
)
from app.services.live_reporting.submit_helper import (
    submit_match_report,
    STATUS_ALREADY_SUBMITTED,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Admin presence tracker (in-memory; single-worker deploy assumed)
# -----------------------------------------------------------------------------
#
# Admins don't get an ActiveMatchReporter row — per decision #2 — so we track
# their Socket.IO presence here. Keyed by room (match_{id}), value is a dict
# of {sid: {user_id, username, role}}.

_ADMIN_REGISTRY: Dict[str, Dict[str, Dict[str, Any]]] = {}
_ADMIN_LOCK = threading.Lock()


def _match_room(league_type: str, match_id: int) -> str:
    # NOTE: keep legacy "match_{id}" room name for Pub League to match existing
    # V1 emit sites that broadcast into the same room. ECS FC gets its own
    # namespace-safe prefix to avoid cross-league collisions on matching ids.
    if league_type == redis_state.LEAGUE_ECS_FC:
        return f"ecs_fc_match_{int(match_id)}"
    return f"match_{int(match_id)}"


def _register_admin(room: str, sid: str, info: Dict[str, Any]) -> None:
    with _ADMIN_LOCK:
        _ADMIN_REGISTRY.setdefault(room, {})[sid] = info


def _unregister_admin(room: str, sid: str) -> Optional[Dict[str, Any]]:
    with _ADMIN_LOCK:
        room_map = _ADMIN_REGISTRY.get(room) or {}
        info = room_map.pop(sid, None)
        if not room_map:
            _ADMIN_REGISTRY.pop(room, None)
        return info


def _admin_observers_for_room(room: str) -> List[Dict[str, Any]]:
    with _ADMIN_LOCK:
        return list((_ADMIN_REGISTRY.get(room) or {}).values())


def cleanup_admin_sid(sid: str) -> List[Dict[str, Any]]:
    """
    Called from the V1 disconnect handler. Removes this sid from any admin
    rooms and returns the (room, info) pairs for each so the caller can emit
    admin_left broadcasts.
    """
    removed: List[Dict[str, Any]] = []
    with _ADMIN_LOCK:
        for room, sid_map in list(_ADMIN_REGISTRY.items()):
            info = sid_map.pop(sid, None)
            if info is not None:
                removed.append({'room': room, **info})
            if not sid_map:
                _ADMIN_REGISTRY.pop(room, None)
    return removed


# -----------------------------------------------------------------------------
# Match lookup + team resolution
# -----------------------------------------------------------------------------

def _load_match_obj(session, league_type: str, match_id: int):
    if league_type == redis_state.LEAGUE_PUB:
        return session.query(Match).get(int(match_id))
    return session.query(EcsFcMatch).get(int(match_id))


def _match_home_away_team_ids(league_type: str, match) -> (Optional[int], Optional[int]):
    if match is None:
        return None, None
    if league_type == redis_state.LEAGUE_PUB:
        return match.home_team_id, match.away_team_id
    # ECS FC: one real team; "away" is an external opponent (no team_id).
    if match.is_home_match:
        return match.team_id, None
    return None, match.team_id


def _team_dict(session, team_id: Optional[int]) -> Optional[Dict[str, Any]]:
    if team_id is None:
        return None
    team = session.query(Team).get(int(team_id))
    if not team:
        return None
    return {
        'id': team.id,
        'name': team.name,
        'logo_url': getattr(team, 'kit_url', None) or getattr(team, 'logo_url', None),
    }


# -----------------------------------------------------------------------------
# Event serialization
# -----------------------------------------------------------------------------

def _serialize_match_event(event: MatchEvent, session) -> Dict[str, Any]:
    team = session.query(Team).get(event.team_id) if event.team_id else None
    player = session.query(Player).get(event.player_id) if event.player_id else None
    return {
        'id': event.id,
        'event_type': event.event_type,
        'team_id': event.team_id,
        'team_name': team.name if team else None,
        'player_id': event.player_id,
        'player_name': player.name if player else None,
        'minute': event.minute,
        'period': event.period,
        'timestamp': event.timestamp.isoformat() if event.timestamp else None,
        'reported_by': event.reported_by,
        'idempotency_key': event.idempotency_key,
        'client_timestamp': event.client_timestamp.isoformat() if event.client_timestamp else None,
        'sync_status': event.sync_status,
    }


def _serialize_ecs_fc_match_event(event: EcsFcMatchEvent, session) -> Dict[str, Any]:
    team = session.query(Team).get(event.team_id) if event.team_id else None
    player = session.query(Player).get(event.player_id) if event.player_id else None
    return {
        'id': event.id,
        'event_type': event.event_type,
        'team_id': event.team_id,
        'team_name': team.name if team else None,
        'player_id': event.player_id,
        'player_name': player.name if player else None,
        'minute': event.minute,
        'period': event.period,
        'timestamp': event.timestamp.isoformat() if event.timestamp else None,
        'reported_by': event.reported_by,
        'idempotency_key': event.idempotency_key,
        'client_timestamp': event.client_timestamp.isoformat() if event.client_timestamp else None,
        'sync_status': event.sync_status,
    }


def _fetch_events_for_match_state(session, league_type: str, match_id: int) -> List[Dict[str, Any]]:
    if league_type == redis_state.LEAGUE_PUB:
        events = (
            session.query(MatchEvent)
            .filter(MatchEvent.match_id == int(match_id))
            .order_by(MatchEvent.timestamp.asc())
            .all()
        )
        return [_serialize_match_event(e, session) for e in events]
    events = (
        session.query(EcsFcMatchEvent)
        .filter(EcsFcMatchEvent.match_id == int(match_id))
        .order_by(EcsFcMatchEvent.timestamp.asc())
        .all()
    )
    return [_serialize_ecs_fc_match_event(e, session) for e in events]


# -----------------------------------------------------------------------------
# Connected coach list (ActiveMatchReporter)
# -----------------------------------------------------------------------------

def _connected_coaches(session, match_id: int) -> List[Dict[str, Any]]:
    """
    Active reporters within last 5 min window. Excludes admins (they never
    insert ActiveMatchReporter rows).
    """
    from datetime import timedelta
    threshold = datetime.utcnow() - timedelta(minutes=5)
    rows = (
        session.query(ActiveMatchReporter, User, Player)
        .join(User, ActiveMatchReporter.user_id == User.id)
        .outerjoin(Player, Player.user_id == User.id)
        .filter(
            ActiveMatchReporter.match_id == int(match_id),
            ActiveMatchReporter.last_active > threshold,
        )
        .all()
    )
    return [
        {
            'user_id': user.id,
            'team_id': reporter.team_id,
            'username': user.username,
            'profile_picture_url': player.profile_picture_url if player else None,
            'joined_at': reporter.joined_at.isoformat() if reporter.joined_at else None,
        }
        for reporter, user, player in rows
    ]


# -----------------------------------------------------------------------------
# Stub LiveMatch creation (FK hook for MatchEvent / EcsFcMatchEvent)
# -----------------------------------------------------------------------------

def _ensure_pub_live_match_stub(session, match_id: int) -> None:
    stub = session.query(LiveMatch).filter_by(match_id=int(match_id)).first()
    if stub is None:
        session.add(LiveMatch(match_id=int(match_id), status='in_progress', last_updated=datetime.utcnow()))


def _ensure_ecs_fc_live_match_stub(session, match_id: int) -> None:
    stub = session.query(EcsFcLiveMatch).filter_by(ecs_fc_match_id=int(match_id)).first()
    if stub is None:
        session.add(EcsFcLiveMatch(ecs_fc_match_id=int(match_id), status='in_progress'))


# -----------------------------------------------------------------------------
# match_state payload (F3)
# -----------------------------------------------------------------------------

def build_match_state_payload(session, league_type: str, match_id: int) -> Dict[str, Any]:
    state = redis_state.load_or_seed(session, league_type, int(match_id))
    match = _load_match_obj(session, league_type, match_id)
    home_team_id, away_team_id = _match_home_away_team_ids(league_type, match)
    events = _fetch_events_for_match_state(session, league_type, match_id)
    connected = _connected_coaches(session, match_id) if league_type == redis_state.LEAGUE_PUB else []
    observers = _admin_observers_for_room(_match_room(league_type, match_id))

    payload = redis_state.build_match_state_payload(
        state=state,
        events=events,
        connected_coaches=connected,
        observers=observers,
        home_team=_team_dict(session, home_team_id),
        away_team=_team_dict(session, away_team_id),
    )
    # Back-compat fields for legacy Flutter clients reading the V1 match_state shape.
    timer = payload['timer']
    payload.update({
        'status': 'completed' if payload['report_status'] == redis_state.REPORT_SUBMITTED else 'in_progress',
        'period': timer.get('period'),
        'elapsed_seconds': (timer.get('elapsed_time_ms') or 0) // 1000,
        'elapsed_time_ms': timer.get('elapsed_time_ms') or 0,
        'formatted_time': timer.get('formatted_time'),
        'match_minute': timer.get('match_minute'),
        'is_running': timer.get('is_running'),
        'is_paused': timer.get('is_paused'),
        'is_stopped': timer.get('is_stopped'),
        'timer_running': timer.get('is_running'),
        'report_submitted': payload['report_status'] == redis_state.REPORT_SUBMITTED,
        'report_submitted_by': payload.get('submitted_by_user_id'),
        'home_team_id': home_team_id,
        'away_team_id': away_team_id,
        'home_team_name': (payload.get('home_team') or {}).get('name'),
        'away_team_name': (payload.get('away_team') or {}).get('name'),
    })
    return payload


# -----------------------------------------------------------------------------
# Handlers — join_match / leave_match / resync_match
# -----------------------------------------------------------------------------

def _resolve_user(session):
    """Shared auth check. Returns User or emits 'error' + disconnects and returns None."""
    from app.sockets.live_reporting import get_socket_current_user
    user = get_socket_current_user(session)
    if not user:
        emit('error', {'reason': 'auth_failed', 'message': 'Authentication required'})
        disconnect()
        return None
    return user


def on_join_match(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return

        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'reason': 'league_type_mismatch', 'message': str(exc)}); return

        match_id = data.get('match_id')
        team_id = data.get('team_id')
        role_hint = (data.get('role') or '').lower() or None

        if not match_id:
            emit('error', {'reason': 'bad_request', 'message': 'Match ID is required'}); return

        match = _load_match_obj(session, league_type, match_id)
        if not match:
            emit('error', {'reason': 'match_not_found', 'message': f'Match {match_id} not found'}); return

        admin = is_admin_or_ref(user)
        user_id = user.id
        room = _match_room(league_type, int(match_id))

        if admin:
            # Admin / ref: team_id optional; skip membership check.
            join_room(room)
            admin_player = session.query(Player).filter_by(user_id=user_id).first()
            admin_profile_url = admin_player.profile_picture_url if admin_player else None
            _register_admin(room, request.sid, {
                'user_id': user_id,
                'username': user.username,
                'role': role_hint or 'admin',
                'profile_picture_url': admin_profile_url,
            })
            # Observer announcement (separate from coach broadcasts).
            admin_payload = {
                'match_id': int(match_id),
                'league_type': league_type,
                'user_id': user_id,
                'username': user.username,
                'role': role_hint or 'admin',
                'profile_picture_url': admin_profile_url,
            }
            socketio.emit('admin_joined', admin_payload, room=room, namespace='/live')
            # Refreshed observer roster (mirror of active_reporters for coaches).
            socketio.emit(
                'active_observers',
                {
                    'match_id': int(match_id),
                    'league_type': league_type,
                    'observers': _admin_observers_for_room(room),
                },
                room=room,
                namespace='/live',
            )
        else:
            # Coach path — requires a valid team_id for one of the playing sides.
            if not team_id:
                emit('error', {'reason': 'bad_request', 'message': 'Team ID is required for coaches'}); return
            home_tid, away_tid = _match_home_away_team_ids(league_type, match)
            if int(team_id) not in {t for t in (home_tid, away_tid) if t is not None}:
                emit('error', {'reason': 'team_not_in_match', 'message': 'Selected team is not playing in this match'}); return

            # Upsert ActiveMatchReporter (Pub League only — ECS FC has a single team).
            if league_type == redis_state.LEAGUE_PUB:
                reporter = session.query(ActiveMatchReporter).filter_by(
                    match_id=int(match_id), user_id=user_id
                ).first()
                if reporter:
                    reporter.team_id = int(team_id)
                    reporter.last_active = datetime.utcnow()
                else:
                    session.add(ActiveMatchReporter(
                        match_id=int(match_id),
                        user_id=user_id,
                        team_id=int(team_id),
                        joined_at=datetime.utcnow(),
                        last_active=datetime.utcnow(),
                    ))
                session.commit()

            join_room(room)

            # Legacy reporter_joined event — kept so pre-V2 clients still work.
            team = session.query(Team).get(int(team_id))
            joining_player = session.query(Player).filter_by(user_id=user_id).first()
            socketio.emit(
                'reporter_joined',
                {
                    'match_id': int(match_id),
                    'league_type': league_type,
                    'user_id': user_id,
                    'username': user.username,
                    'team_id': int(team_id),
                    'team_name': team.name if team else None,
                    'profile_picture_url': joining_player.profile_picture_url if joining_player else None,
                },
                room=room,
                namespace='/live',
            )

        # Seed LiveMatch stub so MatchEvent / EcsFcMatchEvent FKs resolve.
        if league_type == redis_state.LEAGUE_PUB:
            _ensure_pub_live_match_stub(session, int(match_id))
        else:
            _ensure_ecs_fc_live_match_stub(session, int(match_id))
        session.commit()

        # Emit the full match_state to this socket only.
        payload = build_match_state_payload(session, league_type, int(match_id))
        emit('match_state', payload, to=request.sid)

        # Broadcast refreshed coach list to room (coaches only).
        if league_type == redis_state.LEAGUE_PUB and not admin:
            from app.sockets.live_reporting import get_active_reporters
            socketio.emit(
                'active_reporters',
                {
                    'match_id': int(match_id),
                    'reporters': get_active_reporters(session, int(match_id)),
                },
                room=room,
                namespace='/live',
            )

        logger.info(
            f"V2 join_match: user={user_id} match={league_type}:{match_id} "
            f"role={'admin' if admin else 'coach'} team_id={team_id}"
        )


def on_leave_match(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return

        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'message': str(exc)}); return

        match_id = data.get('match_id')
        if not match_id:
            emit('error', {'message': 'Match ID is required'}); return

        room = _match_room(league_type, int(match_id))
        leave_room(room)

        admin_info = _unregister_admin(room, request.sid)
        if admin_info is not None:
            socketio.emit(
                'admin_left',
                {
                    'match_id': int(match_id),
                    'league_type': league_type,
                    'user_id': admin_info['user_id'],
                    'username': admin_info['username'],
                    'role': admin_info.get('role'),
                },
                room=room,
                namespace='/live',
            )
            socketio.emit(
                'active_observers',
                {
                    'match_id': int(match_id),
                    'league_type': league_type,
                    'observers': _admin_observers_for_room(room),
                },
                room=room,
                namespace='/live',
            )
            return

        # Coach leave — remove ActiveMatchReporter (Pub League only).
        if league_type == redis_state.LEAGUE_PUB:
            reporter = session.query(ActiveMatchReporter).filter_by(
                match_id=int(match_id), user_id=user.id
            ).first()
            if reporter:
                team_id = reporter.team_id
                session.delete(reporter)
                session.commit()
                socketio.emit(
                    'reporter_left',
                    {
                        'match_id': int(match_id),
                        'league_type': league_type,
                        'user_id': user.id,
                        'username': user.username,
                        'team_id': team_id,
                    },
                    room=room,
                    namespace='/live',
                )
                from app.sockets.live_reporting import get_active_reporters
                socketio.emit(
                    'active_reporters',
                    {
                        'match_id': int(match_id),
                        'reporters': get_active_reporters(session, int(match_id)),
                    },
                    room=room,
                    namespace='/live',
                )


def on_resync_match(data):
    """Targeted match_state replay. Also handles the legacy `request_state`."""
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return
        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'reason': 'league_type_mismatch', 'message': str(exc)}); return
        match_id = data.get('match_id')
        if not match_id:
            emit('error', {'reason': 'bad_request', 'message': 'Match ID is required'}); return

        payload = build_match_state_payload(session, league_type, int(match_id))
        emit('match_state', payload, to=request.sid)


# -----------------------------------------------------------------------------
# Timer
# -----------------------------------------------------------------------------

def _broadcast_timer_update(
    league_type: str,
    match_id: int,
    state: Dict[str, Any],
    action: str,
    user_id: Optional[int],
    updated_by_name: Optional[str],
    include_self: bool = False,
) -> None:
    timer_proj = redis_state.derive_timer_projection(state['timer'])
    payload = {
        'match_id': int(match_id),
        'league_type': league_type,
        'action': action,
        'server_epoch_ms': redis_state.now_ms(),
        'timestamp': datetime.utcnow().isoformat(),
        'updated_by': user_id,
        'updated_by_name': updated_by_name,
        **timer_proj,
    }
    emit(
        'timer_updated',
        payload,
        room=_match_room(league_type, int(match_id)),
        include_self=include_self,
    )


def on_update_timer(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return
        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'message': str(exc)}); return

        match_id = data.get('match_id')
        action = (data.get('action') or '').lower()
        if not match_id or action not in redis_state.TIMER_ACTIONS:
            emit('error', {'message': 'Invalid update_timer payload'}); return

        state = redis_state.load_or_seed(session, league_type, int(match_id))
        if _reject_if_submitted(state):
            return
        period = data.get('period')
        # Client can request an explicit elapsed override (used by halftime "Apply"
        # action which pauses at exactly 25:00). We only honor it for pause/stop.
        elapsed_override_ms = data.get('target_elapsed_ms') if action in ('pause', 'stop') else None
        if elapsed_override_ms is not None:
            try:
                elapsed_override_ms = int(elapsed_override_ms)
            except (ValueError, TypeError):
                elapsed_override_ms = None
        pause_reason = data.get('pause_reason')

        redis_state.apply_main_timer_action(
            state,
            action=action,
            user_id=user.id,
            pause_reason=pause_reason,
            period=period,
            elapsed_override_ms=elapsed_override_ms,
        )

        # Enqueue / revoke scheduled jobs. set_period is metadata-only — it must
        # not touch scheduled timer jobs (a running timer's period-end FCM stays
        # scheduled when the period label changes mid-flight).
        from app.tasks.tasks_live_reporting_timers import enqueue_timer_jobs, revoke_timer_jobs
        if action in ('start', 'resume'):
            revoke_timer_jobs(state)  # cancel any stragglers before re-enqueueing
            enqueue_timer_jobs(state, int(match_id), league_type)
        elif action in ('pause', 'stop', 'reset'):
            revoke_timer_jobs(state)
        # set_period: no-op for scheduling.

        redis_state.save_state(league_type, int(match_id), state)

        # V1 fallback safety belt — mirror timer state to the legacy LiveMatch row.
        _sync_live_match_shim(session, league_type, int(match_id), state)
        session.commit()

        _broadcast_timer_update(
            league_type=league_type,
            match_id=int(match_id),
            state=state,
            action=action,
            user_id=user.id,
            updated_by_name=user.username,
            include_self=False,
        )


def on_update_shift_timer(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return
        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'message': str(exc)}); return

        match_id = data.get('match_id')
        team_id = data.get('team_id')
        action = (data.get('action') or '').lower()
        if not match_id or not team_id or action not in redis_state.TIMER_ACTIONS:
            emit('error', {'message': 'Invalid update_shift_timer payload'}); return

        admin = is_admin_or_ref(user)

        # Coach path requires the socket's ActiveMatchReporter to own this team.
        if not admin and league_type == redis_state.LEAGUE_PUB:
            reporter = session.query(ActiveMatchReporter).filter_by(
                match_id=int(match_id), user_id=user.id
            ).first()
            if not reporter or reporter.team_id != int(team_id):
                emit('error', {'message': "You can only control your own team's shift timer"})
                return

        state = redis_state.load_or_seed(session, league_type, int(match_id))
        if _reject_if_submitted(state):
            return
        period = data.get('period')
        elapsed_override_ms = data.get('target_elapsed_ms') if action in ('pause', 'stop') else None
        if elapsed_override_ms is not None:
            try:
                elapsed_override_ms = int(elapsed_override_ms)
            except (ValueError, TypeError):
                elapsed_override_ms = None

        redis_state.apply_shift_timer_action(
            state,
            team_id=int(team_id),
            action=action,
            user_id=user.id,
            pause_reason=data.get('pause_reason'),
            period=period,
            elapsed_override_ms=elapsed_override_ms,
        )
        redis_state.save_state(league_type, int(match_id), state)

        team = session.query(Team).get(int(team_id))
        timer_proj = redis_state.derive_timer_projection(state['shift_timers'][str(int(team_id))])
        payload = {
            'match_id': int(match_id),
            'league_type': league_type,
            'team_id': int(team_id),
            'team_name': team.name if team else None,
            'action': action,
            'server_epoch_ms': redis_state.now_ms(),
            'timestamp': datetime.utcnow().isoformat(),
            'updated_by': user.id,
            'updated_by_name': user.username,
            **timer_proj,
        }
        emit(
            'shift_timer_updated',
            payload,
            room=_match_room(league_type, int(match_id)),
            include_self=False,
        )


# -----------------------------------------------------------------------------
# Score
# -----------------------------------------------------------------------------

def on_update_score(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return
        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'message': str(exc)}); return

        match_id = data.get('match_id')
        home_score = data.get('home_score')
        away_score = data.get('away_score')
        if match_id is None or home_score is None or away_score is None:
            emit('error', {'message': 'match_id, home_score, away_score are required'})
            return
        try:
            home_score = int(home_score)
            away_score = int(away_score)
        except (ValueError, TypeError):
            emit('error', {'message': 'Scores must be integers'})
            return

        state = redis_state.load_or_seed(session, league_type, int(match_id))
        if _reject_if_submitted(state):
            return

        match = _load_match_obj(session, league_type, match_id)
        if not match:
            emit('error', {'message': f'Match {match_id} not found'})
            return

        if league_type == redis_state.LEAGUE_PUB:
            match.home_team_score = home_score
            match.away_team_score = away_score
        else:
            # ECS FC: team-perspective convention — write directly, server does not flip.
            match.home_score = home_score
            match.away_score = away_score

        # Update Redis + bump sequence for client-side tie-break.
        redis_state.set_scores(state, home_score, away_score, user.id)
        redis_state.save_state(league_type, int(match_id), state)

        # V1 fallback safety belt — mirror to legacy LiveMatch row.
        _sync_live_match_shim(session, league_type, int(match_id), state)
        session.commit()

        emit(
            'score_updated',
            {
                'match_id': int(match_id),
                'league_type': league_type,
                'home_score': home_score,
                'away_score': away_score,
                'last_score_sequence': state['last_score_sequence'],
                'server_epoch_ms': redis_state.now_ms(),
                'updated_by': user.id,
                'updated_by_name': user.username,
            },
            room=_match_room(league_type, int(match_id)),
        )


# -----------------------------------------------------------------------------
# Post-submit rejection (Q3.3 — shared by every write handler)
# -----------------------------------------------------------------------------

def _reject_if_submitted(state: Dict[str, Any]) -> bool:
    """
    Returns True after emitting a structured error if the match is already
    submitted. Caller should early-return.

    We reject post-submit writes (add_event, force_add_event, update_score,
    update_timer, update_shift_timer, update_player_shift) because they'd
    re-trigger `reset_verification()` on the Match row and confuse the
    two-coach handshake. Flutter's UI disables these buttons post-submit, so
    this rejection only fires on race or stale-client scenarios.
    """
    if state.get('report_status') == redis_state.REPORT_SUBMITTED:
        emit('error', {
            'reason': 'match_submitted',
            'message': 'Match has already been submitted; further edits are blocked.',
            'submitted_by_user_id': state.get('submitted_by_user_id'),
            'submitted_at': state.get('submitted_at'),
        })
        return True
    return False


def _sync_live_match_shim(session, league_type: str, match_id: int, state: Dict[str, Any]) -> None:
    """
    Kill-switch safety belt (Q6.2). V1 handlers read scores + elapsed from the
    `live_matches` SQL table; V2 writes to `matches.*` directly. If V2 is
    flipped off mid-game, V1 would see stale data unless we also write to
    LiveMatch here. Small cost (2 UPDATEs per write), big consistency win.

    Pub League only — ECS FC has no LiveMatch row (stub is ecs_fc_live_matches
    and V1 never read from it).
    """
    if league_type != redis_state.LEAGUE_PUB:
        return
    try:
        stub = session.query(LiveMatch).filter_by(match_id=int(match_id)).first()
        if stub is None:
            return  # join_match path hasn't created one yet; nothing to shim
        stub.home_score = int(state.get('home_score') or 0)
        stub.away_score = int(state.get('away_score') or 0)
        timer = state.get('timer') or {}
        stub.elapsed_seconds = redis_state.computed_elapsed_ms(timer) // 1000
        stub.timer_running = bool(timer.get('is_running'))
        stub.current_period = timer.get('period')
        stub.last_updated = datetime.utcnow()
    except Exception:
        logger.exception(f"LiveMatch shim sync failed for match {match_id}")


# -----------------------------------------------------------------------------
# Event add — dual-write
# -----------------------------------------------------------------------------

# Whitelist of event types accepted by V2 live reporting. `SUBSTITUTION` is
# intentionally excluded — not wired end-to-end on Flutter + no stat rollup path.
VALID_LIVE_EVENT_TYPES = frozenset({'GOAL', 'ASSIST', 'YELLOW_CARD', 'RED_CARD', 'OWN_GOAL'})


def _normalize_minute(raw) -> Optional[str]:
    """
    Both `match_events.minute` and `player_event.minute` are VARCHAR(10) post
    the 2026_04_20 migration — preserve "45+2" stoppage-time notation through
    the live feed. Flutter may send int or string; either is stringified here.
    """
    if raw is None:
        return None
    return str(raw)


_PLAYER_EVENT_TYPE_MAP = {
    'GOAL': (PlayerEventType.GOAL, 'goal'),
    'ASSIST': (PlayerEventType.ASSIST, 'assist'),
    'YELLOW_CARD': (PlayerEventType.YELLOW_CARD, 'yellow_card'),
    'RED_CARD': (PlayerEventType.RED_CARD, 'red_card'),
    'OWN_GOAL': (PlayerEventType.OWN_GOAL, 'own_goal'),
}


def _assist_idempotency_key(match_event_key: Optional[str]) -> Optional[str]:
    """Derived key for the paired ASSIST PlayerEvent; format: '{goal_uuid}::assist'."""
    if not match_event_key:
        return None
    return f"{match_event_key}::assist"


def _dual_write_player_event_pub(session, match_event: MatchEvent, match: Match) -> Optional[PlayerEvent]:
    """
    Create the permanent PlayerEvent row sibling to a just-written MatchEvent.
    Returns the GOAL PlayerEvent or None if the event type isn't stat-roll-upable.

    For GOAL events with `additional_data.assist_player_id`, also creates a
    second PlayerEvent (type=ASSIST) in the same transaction so assist stats
    roll up without Flutter emitting a second add_event. Mirrors the existing
    REST `/report_match` behavior for shape-consistency across both entry paths.
    """
    mapped = _PLAYER_EVENT_TYPE_MAP.get(match_event.event_type)
    if not mapped:
        return None
    player_event_enum, event_type_value = mapped

    derived_key = f"pe_{match_event.idempotency_key}" if match_event.idempotency_key else None
    if derived_key:
        existing = session.query(PlayerEvent).filter_by(
            match_id=match.id, idempotency_key=derived_key
        ).first()
        if existing:
            return existing

    pe = PlayerEvent(
        player_id=match_event.player_id,
        match_id=match.id,
        team_id=match_event.team_id if match_event.event_type == 'OWN_GOAL' else None,
        minute=_normalize_minute(match_event.minute),
        event_type=player_event_enum,
        idempotency_key=derived_key,
        client_timestamp=match_event.client_timestamp,
        reported_by=match_event.reported_by,
    )
    session.add(pe)
    session.flush()

    # Stat rollup — Pub League only, non-own-goal only.
    if match_event.event_type != 'OWN_GOAL' and pe.player_id:
        try:
            update_player_stats(
                session,
                pe.player_id,
                event_type_value,
                match,
                increment=True,
                is_sub_event=False,
            )
        except Exception:
            logger.exception(f"update_player_stats failed for player_event {pe.id}")

    # ----- Paired ASSIST PlayerEvent from additional_data.assist_player_id -----
    # Only for GOAL. Own-goals have no assister; cards/assists-as-primary don't apply.
    if match_event.event_type == 'GOAL':
        assist_player_id = None
        additional = match_event.additional_data or {}
        if isinstance(additional, dict):
            assist_player_id = additional.get('assist_player_id')

        if assist_player_id is not None and pe.player_id is not None and int(assist_player_id) == int(pe.player_id):
            logger.warning(
                f"Skipping assist split for match_event {match_event.id}: "
                f"assist_player_id == scorer ({assist_player_id})"
            )
            assist_player_id = None

        if assist_player_id:
            assist_key = _assist_idempotency_key(match_event.idempotency_key)
            existing_assist = None
            if assist_key:
                existing_assist = session.query(PlayerEvent).filter_by(
                    match_id=match.id, idempotency_key=assist_key
                ).first()
            if existing_assist is None:
                assist_pe = PlayerEvent(
                    player_id=int(assist_player_id),
                    match_id=match.id,
                    team_id=None,
                    minute=_normalize_minute(match_event.minute),
                    event_type=PlayerEventType.ASSIST,
                    idempotency_key=assist_key,
                    client_timestamp=match_event.client_timestamp,
                    reported_by=match_event.reported_by,
                )
                session.add(assist_pe)
                session.flush()
                try:
                    update_player_stats(
                        session,
                        assist_pe.player_id,
                        'assist',
                        match,
                        increment=True,
                        is_sub_event=False,
                    )
                except Exception:
                    logger.exception(f"update_player_stats failed for assist player_event {assist_pe.id}")

    return pe


def _dual_write_player_event_ecs_fc(session, match_event: EcsFcMatchEvent) -> Optional[EcsFcPlayerEvent]:
    mapped = _PLAYER_EVENT_TYPE_MAP.get(match_event.event_type)
    if not mapped:
        return None
    _, event_type_value = mapped

    derived_key = f"ecsfc_pe_{match_event.idempotency_key}" if match_event.idempotency_key else None
    if derived_key:
        existing = session.query(EcsFcPlayerEvent).filter_by(
            ecs_fc_match_id=match_event.match_id, idempotency_key=derived_key
        ).first()
        if existing:
            return existing

    pe = EcsFcPlayerEvent(
        player_id=match_event.player_id,
        ecs_fc_match_id=match_event.match_id,
        team_id=match_event.team_id if match_event.event_type == 'OWN_GOAL' else None,
        minute=_normalize_minute(match_event.minute),
        event_type=event_type_value,
        created_by=match_event.reported_by,
        idempotency_key=derived_key,
        client_timestamp=match_event.client_timestamp,
    )
    session.add(pe)
    session.flush()
    return pe


def _apply_goal_score_bump(
    session,
    state: Dict[str, Any],
    match,
    league_type: str,
    match_event,
    user_id: Optional[int],
) -> bool:
    """
    Auto-bump scores for goal-shaped events so Flutter doesn't have to emit a
    separate update_score for every goal. Semantics differ per league:

    Pub League (fixture-based columns):
        GOAL by home team  → home_team_score += 1
        GOAL by away team  → away_team_score += 1
        OWN_GOAL handled explicitly by Flutter via update_score.

    ECS FC (team-perspective columns — home_score = team's score regardless of
    is_home_match; confirmed against DB row id=29):
        GOAL      with team_id == match.team_id  → home_score += 1   (our goal)
        OWN_GOAL  with team_id == match.team_id  → away_score += 1   (we own-goaled; opponent benefits)
        Opponent goals aren't emitted as events in this system — coaches drive
        them via explicit update_score, so nothing to auto-bump here.
    """
    if league_type == redis_state.LEAGUE_PUB:
        if match_event.event_type != 'GOAL' or match_event.team_id is None:
            return False
        if match_event.team_id == match.home_team_id:
            match.home_team_score = (match.home_team_score or 0) + 1
            redis_state.increment_score(state, is_home=True, delta=1, user_id=user_id)
            return True
        if match_event.team_id == match.away_team_id:
            match.away_team_score = (match.away_team_score or 0) + 1
            redis_state.increment_score(state, is_home=False, delta=1, user_id=user_id)
            return True
        return False

    # ECS FC — team-perspective storage
    if match_event.event_type == 'GOAL' and match_event.team_id == match.team_id:
        match.home_score = (match.home_score or 0) + 1
        redis_state.increment_score(state, is_home=True, delta=1, user_id=user_id)
        return True
    if match_event.event_type == 'OWN_GOAL' and match_event.team_id == match.team_id:
        match.away_score = (match.away_score or 0) + 1
        redis_state.increment_score(state, is_home=False, delta=1, user_id=user_id)
        return True
    return False


def _handle_add_event_core(data, force: bool = False):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return
        try:
            league_type = resolve_league_type(data)
        except ValueError as exc:
            emit('error', {'message': str(exc)}); return

        match_id = data.get('match_id')
        event_data = data.get('event') or {}
        idempotency_key = data.get('idempotency_key')
        client_timestamp_str = data.get('client_timestamp')

        if not match_id or not event_data:
            emit('error', {'message': 'Match ID and event data are required'})
            return
        event_type = event_data.get('event_type')
        if not event_type:
            emit('error', {'message': 'Event must include event_type'})
            return

        # Whitelist event types. SUBSTITUTION is intentionally blocked — it's
        # not wired end-to-end on Flutter and has no stat rollup path.
        if event_type not in VALID_LIVE_EVENT_TYPES:
            emit('error', {
                'reason': 'unsupported_event_type',
                'message': f'Event type {event_type!r} is not supported in live reporting.',
            })
            return

        match = _load_match_obj(session, league_type, match_id)
        if not match:
            emit('error', {'message': f'Match {match_id} not found'}); return

        # Ensure stub row exists before inserting event (FK dependency).
        if league_type == redis_state.LEAGUE_PUB:
            _ensure_pub_live_match_stub(session, int(match_id))
        else:
            _ensure_ecs_fc_live_match_stub(session, int(match_id))
        session.commit()

        state = redis_state.load_or_seed(session, league_type, int(match_id))
        if _reject_if_submitted(state):
            return
        client_timestamp = parse_client_timestamp(client_timestamp_str)

        # --- Exact duplicate guard via idempotency_key ---
        if idempotency_key:
            if league_type == redis_state.LEAGUE_PUB:
                existing = check_duplicate_match_event(session, int(match_id), idempotency_key)
            else:
                existing = session.query(EcsFcMatchEvent).filter_by(
                    match_id=int(match_id), idempotency_key=idempotency_key
                ).first()
            if existing:
                serialized = (
                    serialize_match_event_with_reporter(session, existing)
                    if league_type == redis_state.LEAGUE_PUB
                    else _serialize_ecs_fc_match_event(existing, session)
                )
                emit('event_ack', {
                    'status': 'duplicate',
                    'is_duplicate': True,
                    'idempotency_key': idempotency_key,
                    'event_id': existing.id,
                    'original_event_id': existing.id,
                    'event': serialized,
                })
                return

        # --- Near-duplicate guard (Pub League only, non-force path) ---
        if not force and league_type == redis_state.LEAGUE_PUB:
            near_dupes = find_near_duplicate_match_events(
                session=session,
                match_id=int(match_id),
                player_id=event_data.get('player_id'),
                event_type=event_type,
                minute=event_data.get('minute'),
                exclude_idempotency_key=idempotency_key,
            )
            if near_dupes:
                emit('event_ack', {
                    'status': 'near_duplicate',
                    'is_duplicate': False,
                    'idempotency_key': idempotency_key,
                    'near_duplicates': [
                        serialize_match_event_with_reporter(session, e) for e in near_dupes
                    ],
                    'message': 'Similar events found - use force_add_event to confirm creation',
                })
                return

        # --- Write live event (MatchEvent or EcsFcMatchEvent) ---
        score_bumped = False
        if league_type == redis_state.LEAGUE_PUB:
            match_event = MatchEvent(
                match_id=int(match_id),
                event_type=event_type,
                team_id=event_data.get('team_id'),
                player_id=event_data.get('player_id'),
                minute=_normalize_minute(event_data.get('minute')),
                period=event_data.get('period'),
                timestamp=datetime.utcnow(),
                reported_by=user.id,
                additional_data=event_data.get('additional_data'),
                idempotency_key=idempotency_key,
                client_timestamp=client_timestamp,
                sync_status='synced',
            )
            session.add(match_event)
            session.flush()

            # Dual-write PlayerEvent + stat rollup.
            _dual_write_player_event_pub(session, match_event, match)

            score_bumped = _apply_goal_score_bump(
                session,
                state=state,
                match=match,
                league_type=league_type,
                match_event=match_event,
                user_id=user.id,
            )

            session.commit()
            event_out = _serialize_match_event(match_event, session)

        else:  # ECS FC
            match_event = EcsFcMatchEvent(
                match_id=int(match_id),
                event_type=event_type,
                team_id=event_data.get('team_id'),
                player_id=event_data.get('player_id'),
                minute=_normalize_minute(event_data.get('minute')),
                period=event_data.get('period'),
                timestamp=datetime.utcnow(),
                reported_by=user.id,
                additional_data=event_data.get('additional_data'),
                idempotency_key=idempotency_key,
                client_timestamp=client_timestamp,
                sync_status='synced',
            )
            session.add(match_event)
            session.flush()

            # Dual-write EcsFcPlayerEvent (no stat rollup for ECS FC).
            _dual_write_player_event_ecs_fc(session, match_event)

            score_bumped = _apply_goal_score_bump(
                session,
                state=state,
                match=match,
                league_type=league_type,
                match_event=match_event,
                user_id=user.id,
            )

            session.commit()
            event_out = _serialize_ecs_fc_match_event(match_event, session)

        redis_state.save_state(league_type, int(match_id), state)

        # V1 fallback safety belt: if we auto-bumped the score, keep the
        # legacy LiveMatch.home_score/away_score in sync too.
        if score_bumped:
            _sync_live_match_shim(session, league_type, int(match_id), state)
            session.commit()

        # Ack to sender.
        emit('event_ack', {
            'status': 'created',
            'idempotency_key': idempotency_key,
            'event_id': match_event.id,
            'event': event_out,
            **({'forced': True} if force else {}),
        })

        # Broadcast to room.
        emit(
            'event_added',
            {
                'match_id': int(match_id),
                'league_type': league_type,
                'event': event_out,
                'reported_by': user.id,
                'reported_by_name': user.username,
                'idempotency_key': idempotency_key,
            },
            room=_match_room(league_type, int(match_id)),
        )

        # Broadcast score_updated whenever the event triggered an auto-bump so
        # clients that don't synthesize score from event_added stay in sync.
        if score_bumped:
            emit(
                'score_updated',
                {
                    'match_id': int(match_id),
                    'league_type': league_type,
                    'home_score': int(state.get('home_score') or 0),
                    'away_score': int(state.get('away_score') or 0),
                    'last_score_sequence': state['last_score_sequence'],
                    'server_epoch_ms': redis_state.now_ms(),
                    'updated_by': user.id,
                    'updated_by_name': user.username,
                    'source': 'goal_event',
                },
                room=_match_room(league_type, int(match_id)),
            )


def on_add_event(data):
    _handle_add_event_core(data, force=False)


def on_force_add_event(data):
    _handle_add_event_core(data, force=True)


# -----------------------------------------------------------------------------
# Player shift (no structural change; admin bypass)
# -----------------------------------------------------------------------------

def on_update_player_shift(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return

        match_id = data.get('match_id')
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        action = data.get('action')
        if not all([match_id, player_id, team_id, action]):
            emit('error', {'message': 'match_id, player_id, team_id, and action are required'})
            return
        if action not in ('sit', 'stay', 'undo_sit', 'undo_stay'):
            emit('error', {'message': "action must be 'sit', 'stay', 'undo_sit', or 'undo_stay'"})
            return

        admin = is_admin_or_ref(user)
        if not admin:
            reporter = session.query(ActiveMatchReporter).filter_by(
                match_id=int(match_id), user_id=user.id
            ).first()
            if not reporter or reporter.team_id != int(team_id):
                emit('error', {'message': 'You can only update shifts for your own team'})
                return

        # Post-submit rejection (Redis state lookup — seeds if missing).
        try:
            league_type = resolve_league_type(data)
        except ValueError:
            league_type = 'pub'
        _state = redis_state.load_or_seed(session, league_type, int(match_id))
        if _reject_if_submitted(_state):
            return

        shift = session.query(PlayerShift).filter_by(
            match_id=int(match_id),
            player_id=int(player_id),
            team_id=int(team_id),
        ).first()
        if not shift:
            shift = PlayerShift(
                match_id=int(match_id),
                player_id=int(player_id),
                team_id=int(team_id),
                sit_count=0,
                stay_count=0,
                updated_by=user.id,
            )
            session.add(shift)

        if action == 'sit':
            shift.sit_count += 1
        elif action == 'stay':
            shift.stay_count += 1
        elif action == 'undo_sit':
            shift.sit_count = max(0, shift.sit_count - 1)
        elif action == 'undo_stay':
            shift.stay_count = max(0, shift.stay_count - 1)

        shift.last_updated = datetime.utcnow()
        shift.updated_by = user.id
        session.commit()

        player = session.query(Player).get(int(player_id))
        team_reporters = session.query(ActiveMatchReporter).filter_by(
            match_id=int(match_id), team_id=int(team_id)
        ).all()

        for team_reporter in team_reporters:
            emit(
                'player_shift_updated',
                {
                    'match_id': int(match_id),
                    'player_id': int(player_id),
                    'player_name': player.name if player else f'Player {player_id}',
                    'sit_count': shift.sit_count,
                    'stay_count': shift.stay_count,
                    'team_id': int(team_id),
                    'updated_by': user.id,
                    'updated_by_name': user.username,
                },
                room=f"user_{team_reporter.user_id}",
            )


# -----------------------------------------------------------------------------
# Submit report — delegates to shared helper
# -----------------------------------------------------------------------------

def on_submit_report(data):
    with socket_session(db.engine) as session:
        user = _resolve_user(session)
        if user is None:
            return

        match_id = data.get('match_id')
        if not match_id:
            emit('error', {'message': 'Match ID is required'}); return

        # submit_report is the one handler that's commonly emitted with a
        # minimal payload (no league_type). Probe to infer rather than mis-route
        # an ECS FC submit to the Pub League table and 404.
        if (data or {}).get('league_type'):
            try:
                league_type = resolve_league_type(data)
            except ValueError as exc:
                emit('error', {'message': str(exc)}); return
        else:
            league_type = infer_league_type_from_match_id(session, int(match_id))

        result = submit_match_report(
            session=session,
            match_id=int(match_id),
            league_type=league_type,
            submitted_by_user_id=user.id,
            socketio=socketio,
        )

        if result['status'] == STATUS_ALREADY_SUBMITTED:
            emit('report_submission_error', {
                'message': 'A report has already been submitted for this match',
                'reason': 'already_submitted',
                'submitted_by_name': result.get('submitted_by_name'),
            })
            return
        # submit_helper already broadcast report_submitted; nothing more here.
