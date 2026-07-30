"""
Shared submit-report helper — called from both the /live socket
`submit_report` handler and the legacy REST `POST /api/v2/report_match/<id>`.

Under V2 (dual-write + server-authoritative), submit becomes a status flip:
  - Freeze Redis LiveMatchState as SUBMITTED.
  - Revoke pending timer Celery jobs.
  - Sync scores from Redis → matches.home_team_score/away_team_score (defensive).
  - Stamp matches.report_submitted_at = now.
  - Clear the two-coach verification handshake via Match.reset_verification().
  - Recompute standings (Pub League only).
  - Fire the opposing-coach verify FCM (Pub League only).
  - Broadcast `report_submitted` to the /live match room.

For already-in-flight matches that have MatchEvents but no PlayerEvents (pre-V2
adds), run create_player_events_from_match_events as a safety net — the helper
itself is idempotent via derived idempotency keys.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.live_reporting import redis_state

logger = logging.getLogger(__name__)


STATUS_OK = 'ok'
STATUS_ALREADY_SUBMITTED = 'already_submitted'


def submit_match_report(
    session,
    match_id: int,
    league_type: str,
    submitted_by_user_id: int,
    socketio=None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Idempotent submit. Returns a result dict:

        {
            'status': 'ok' | 'already_submitted',
            'state':  <Redis state dict>,
            'submitted_by_user_id': int,
            'submitted_by_name': str | None,
            'home_score': int,
            'away_score': int,
        }

    Never raises for "already submitted" — the caller inspects `status` and
    decides whether to emit an error event or just ignore.
    """
    from app.models import User

    state = redis_state.load_or_seed(session, league_type, int(match_id))

    submitter = session.query(User).get(int(submitted_by_user_id))
    submitter_name = submitter.username if submitter else None

    if state.get('report_status') == redis_state.REPORT_SUBMITTED:
        already_id = state.get('submitted_by_user_id')
        already_user = session.query(User).get(int(already_id)) if already_id else None
        return {
            'status': STATUS_ALREADY_SUBMITTED,
            'state': state,
            'submitted_by_user_id': already_id,
            'submitted_by_name': already_user.username if already_user else None,
            'home_score': int(state.get('home_score') or 0),
            'away_score': int(state.get('away_score') or 0),
        }

    now_iso = datetime.utcnow().isoformat()
    now_dt = datetime.utcnow()

    # Revoke pending timer jobs before flipping state so a late-firing reminder
    # doesn't race the status check.
    try:
        from app.tasks.tasks_live_reporting_timers import revoke_timer_jobs
        revoke_timer_jobs(state)
    except Exception:
        logger.exception("revoke_timer_jobs failed during submit")

    # Flip Redis state.
    redis_state.freeze_state_for_submit(state, int(submitted_by_user_id), now_iso)
    redis_state.save_state(league_type, int(match_id), state)

    if league_type == redis_state.LEAGUE_PUB:
        _finalize_pub_match(session, int(match_id), state, now_dt,
                            submitted_by_user_id=submitted_by_user_id,
                            notes=notes)
    elif league_type == redis_state.LEAGUE_ECS_FC:
        _finalize_ecs_fc_match(session, int(match_id), state, now_dt, notes=notes)
    else:
        logger.warning(f"submit_match_report called with unknown league_type={league_type!r}")

    # Broadcast to the /live room.
    #
    # Room name must match live_reporting_v2._match_room: ECS FC coaches are
    # joined to `ecs_fc_match_<id>`, not `match_<id>`. Hardcoding the latter
    # meant that on an ECS FC match the second coach never received
    # report_submitted — they kept recording until the server rejected them
    # with match_submitted, and their scoreboard never flipped to FULL TIME.
    try:
        from app.sockets.live_reporting_v2 import _match_room
        broadcast_room = _match_room(league_type, int(match_id))
    except Exception:
        # Same rule, inlined, if the import isn't available in this context.
        broadcast_room = (
            f"ecs_fc_match_{int(match_id)}"
            if league_type == redis_state.LEAGUE_ECS_FC
            else f"match_{int(match_id)}"
        )

    if socketio is not None:
        try:
            socketio.emit(
                'report_submitted',
                {
                    'match_id': int(match_id),
                    'league_type': league_type,
                    'submitted_by': int(submitted_by_user_id),
                    'submitted_by_name': submitter_name,
                    'submitted_at': now_iso,
                    'home_score': int(state.get('home_score') or 0),
                    'away_score': int(state.get('away_score') or 0),
                },
                room=broadcast_room,
                namespace='/live',
            )
        except Exception:
            logger.exception(f"Failed to broadcast report_submitted for {league_type}:{match_id}")

    return {
        'status': STATUS_OK,
        'state': state,
        'submitted_by_user_id': int(submitted_by_user_id),
        'submitted_by_name': submitter_name,
        'home_score': int(state.get('home_score') or 0),
        'away_score': int(state.get('away_score') or 0),
    }


# -----------------------------------------------------------------------------
# Per-league finalization
# -----------------------------------------------------------------------------

def _submitter_side(session, match, submitted_by_user_id) -> str:
    """'home' or 'away' — which side the submitting coach belongs to.

    Defaults to 'home' when the submitter can't be resolved to either team (an
    admin submitting on someone's behalf), which keeps the previous behaviour
    for that case rather than guessing.
    """
    if not submitted_by_user_id:
        return 'home'
    try:
        from app.models import Player, player_teams
        row = (
            session.query(player_teams.c.team_id)
            .join(Player, Player.id == player_teams.c.player_id)
            .filter(
                Player.user_id == int(submitted_by_user_id),
                player_teams.c.team_id.in_([match.home_team_id, match.away_team_id]),
            )
            .first()
        )
        if row and row[0] == match.away_team_id:
            return 'away'
    except Exception:
        logger.debug("Could not resolve submitter side; defaulting to home", exc_info=True)
    return 'home'


def _finalize_pub_match(session, match_id: int, state: Dict[str, Any], now_dt: datetime,
                        submitted_by_user_id=None, notes: Optional[str] = None) -> None:
    from app.models import Match
    from app.teams_helpers import update_standings

    match = session.query(Match).get(match_id)
    if not match:
        logger.warning(f"submit finalize: Match {match_id} not found")
        session.commit()
        return

    # Defensive score sync — update_score already writes these, but the REST
    # path or a raced deploy might leave them stale.
    state_home = int(state.get('home_score') or 0)
    state_away = int(state.get('away_score') or 0)
    if match.home_team_score != state_home:
        match.home_team_score = state_home
    if match.away_team_score != state_away:
        match.away_team_score = state_away

    # V2 report timestamp column (new per F6 migration).
    if hasattr(match, 'report_submitted_at'):
        match.report_submitted_at = now_dt

    # Match notes from the submit dialog — parity with V1's live_reporting.py.
    # `is not None` rather than truthiness so a coach can clear notes by
    # submitting an empty string.
    if notes is not None:
        match.notes = notes

    # Any prior two-coach verify is invalidated by a fresh submit.
    try:
        match.reset_verification()
    except Exception:
        logger.debug("reset_verification not available on match", exc_info=True)

    # Safety net for matches that transitioned from V1 mid-flight: translate
    # any MatchEvent rows that don't yet have PlayerEvent siblings.
    #
    # Guard against double-rollup: if MatchEvent-count ≤ PlayerEvent-count for
    # this match, every live event already has a PlayerEvent sibling (the V2
    # dual-write did its job), so the translation would only produce duplicates.
    try:
        from app.database.db_models import MatchEvent
        from app.models import PlayerEvent as _PlayerEvent
        match_event_count = session.query(MatchEvent).filter_by(match_id=match_id).count()
        player_event_count = session.query(_PlayerEvent).filter_by(match_id=match_id).count()
        if match_event_count > player_event_count:
            from app.sockets.live_reporting import create_player_events_from_match_events
            create_player_events_from_match_events(session, match_id)
        else:
            logger.info(
                f"Skipping PlayerEvent translation for match {match_id}: "
                f"MatchEvents={match_event_count}, PlayerEvents={player_event_count}"
            )
    except Exception:
        logger.exception(f"create_player_events_from_match_events failed for {match_id}")

    session.commit()

    # Standings and verify-opposing-coach push happen after commit so the
    # read-your-writes behavior is intact.
    try:
        update_standings(session, match)
    except Exception:
        logger.exception(f"update_standings failed for match {match_id}")

    try:
        from app.mobile_api.match_reporting import _notify_opposing_coaches_to_verify
        # Fire a verification ping to the other team's coaches. No-op if already
        # fully verified.
        #
        # The side must be the SUBMITTER'S, not a hardcoded 'home': that argument
        # picks both the recipients (the opposing team's coaches) and the name in
        # the copy. Hardcoded, an away-coach submit pushed "<Home Team> confirmed
        # the result" to the AWAY coaches — the people who needed to verify got
        # nothing, and the ones who did get it were told their own opponent had
        # confirmed something that had in fact just been un-verified.
        _notify_opposing_coaches_to_verify(
            session, match,
            just_verified=_submitter_side(session, match, submitted_by_user_id),
            action='submitted',
        )
    except Exception:
        logger.exception(f"Opposing-coach verify notification failed for match {match_id}")


def _finalize_ecs_fc_match(session, match_id: int, state: Dict[str, Any], now_dt: datetime,
                           notes: Optional[str] = None) -> None:
    from app.models import EcsFcMatch

    match = session.query(EcsFcMatch).get(match_id)
    if not match:
        logger.warning(f"submit finalize: EcsFcMatch {match_id} not found")
        session.commit()
        return

    state_home = int(state.get('home_score') or 0)
    state_away = int(state.get('away_score') or 0)
    if match.home_score != state_home:
        match.home_score = state_home
    if match.away_score != state_away:
        match.away_score = state_away
    match.status = 'COMPLETED'
    match.updated_at = now_dt

    # Match notes from the submit dialog — same contract as the Pub League path.
    if notes is not None:
        match.notes = notes

    session.commit()
