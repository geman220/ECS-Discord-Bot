"""
Role + coach-resolution helpers for the V2 live-match reporting system.

Kept separate from the existing `app/services/live_reporting/` ESPN-monitoring
package to avoid polluting that namespace — this module is only consumed by
`app/sockets/live_reporting.py` V2 handlers, the submit helper, and the timer
Celery tasks.

`ADMIN_OR_REF_ROLES` is the canonical set for the join_match bypass and for
admin-only write paths (e.g. editing the opposing team's shift timer).
Role strings are verified from the DB; do not add 'Admin' or 'Referee' (they
don't exist).
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from sqlalchemy import distinct

logger = logging.getLogger(__name__)


ADMIN_OR_REF_ROLES = frozenset({
    'Global Admin',
    'Pub League Admin',
    'ECS FC Admin',
    'Pub League Ref',
})


def is_admin_or_ref(user) -> bool:
    """
    True if the user has any admin- or ref-level role. Safe against None and
    anonymous SimpleNamespace users (which have no .has_role).
    """
    if user is None:
        return False
    has_role = getattr(user, 'has_role', None)
    if not callable(has_role):
        return False
    try:
        return any(has_role(r) for r in ADMIN_OR_REF_ROLES)
    except Exception:  # defensive — detached / broken user obj
        logger.debug("is_admin_or_ref: has_role raised", exc_info=True)
        return False


def coach_user_ids_for_match(session, match_id: int, league_type: str) -> List[int]:
    """
    Return distinct user_ids for coaches associated with a match.

    Pub League: both teams' coaches.
    ECS FC:     the team_id's coaches (no "other" team).

    Modeled on `_notify_opposing_coaches_to_verify` in
    `app/mobile_api/match_reporting.py` — uses the player_teams.is_coach flag.
    """
    from app.models import Player, player_teams  # late imports avoid circulars

    if league_type == 'pub':
        from app.models import Match
        match = session.query(Match).get(int(match_id))
        if not match:
            return []
        target_team_ids: Iterable[int] = [match.home_team_id, match.away_team_id]
    elif league_type == 'ecs_fc':
        from app.models import EcsFcMatch
        match = session.query(EcsFcMatch).get(int(match_id))
        if not match:
            return []
        target_team_ids = [match.team_id]
    else:
        raise ValueError(f"Invalid league_type: {league_type!r}")

    rows = (
        session.query(distinct(Player.user_id))
        .join(player_teams, player_teams.c.player_id == Player.id)
        .filter(
            player_teams.c.team_id.in_(list(target_team_ids)),
            player_teams.c.is_coach.is_(True),
            Player.user_id.isnot(None),
        )
        .all()
    )
    return [int(row[0]) for row in rows if row[0] is not None]


def active_fcm_tokens_for_users(session, user_ids: Iterable[int]) -> List[str]:
    """Return FCM tokens for the given user_ids that are still active."""
    from app.models import UserFCMToken

    ids = [int(u) for u in user_ids if u is not None]
    if not ids:
        return []
    rows = (
        session.query(UserFCMToken.fcm_token)
        .filter(
            UserFCMToken.user_id.in_(ids),
            UserFCMToken.is_active.is_(True),
        )
        .all()
    )
    # De-dup; a single user could have multiple devices but same token shouldn't appear twice.
    return list({row[0] for row in rows if row[0]})


def resolve_league_type(data: dict, default: str = 'pub') -> str:
    """
    Extract and validate `league_type` from a socket payload. Falls back to
    `default` when the field is missing (backwards compat during rollout).
    """
    value = (data or {}).get('league_type') or default
    value = str(value).lower()
    if value not in ('pub', 'ecs_fc'):
        raise ValueError(f"Invalid league_type: {value!r}")
    return value


def infer_league_type_from_match_id(session, match_id: int) -> str:
    """
    Safety-net for emits that forget to send league_type. Probes the two match
    tables and returns the league type where the row actually lives.

    Falls back to 'pub' if neither table has the id (caller will then fail
    downstream with a clear "match not found" error, not a wrong-table 404).
    """
    from app.models import Match, EcsFcMatch
    if session.query(Match).get(int(match_id)):
        return 'pub'
    if session.query(EcsFcMatch).get(int(match_id)):
        return 'ecs_fc'
    return 'pub'
