# app/services/audience_service.py

"""
Audience Service — ONE resolver for "who is this admin message for?".

Resolves an (audience_type, ids) pair into user ids, and previews per-channel
reachability using the SAME preference semantics the NotificationOrchestrator
applies at send time (global channel flag + announcement type flag + contact
info; NULL preference = opted in). Used by the multi-channel composer.

audience_type values:
    all_active  — every approved, active user
    team        — players on the given team ids (current rosters)
    league      — players on teams in the given league ids
    role        — users holding any of the given role names
    users       — the given user ids verbatim (still filtered to active)
"""

import logging
from typing import Dict, List, Optional

from app.models import User, Player, Team, League, Role
from app.models.players import player_teams
from app.models.notifications import UserFCMToken

logger = logging.getLogger(__name__)

AUDIENCE_TYPES = ('all_active', 'team', 'league', 'role', 'users')


def _base_users(session):
    # Approved AND active — same membership definition the email broadcast
    # service uses; pending/unapproved accounts never receive admin blasts.
    return session.query(User.id).filter(
        User.is_active == True,   # noqa: E712
        User.is_approved == True  # noqa: E712
    )


def resolve_user_ids(session, audience_type: str, ids: Optional[list]) -> List[int]:
    """Resolve the audience to a sorted, de-duplicated list of user ids."""
    ids = ids or []

    if audience_type == 'all_active':
        query = _base_users(session)
    elif audience_type == 'team':
        team_ids = [int(i) for i in ids]
        if not team_ids:
            return []
        query = _base_users(session).join(
            Player, Player.user_id == User.id
        ).join(
            player_teams, player_teams.c.player_id == Player.id
        ).filter(player_teams.c.team_id.in_(team_ids))
    elif audience_type == 'league':
        league_ids = [int(i) for i in ids]
        if not league_ids:
            return []
        query = _base_users(session).join(
            Player, Player.user_id == User.id
        ).join(
            player_teams, player_teams.c.player_id == Player.id
        ).join(
            Team, Team.id == player_teams.c.team_id
        ).filter(Team.league_id.in_(league_ids))
    elif audience_type == 'role':
        role_names = [str(r) for r in ids]
        if not role_names:
            return []
        query = _base_users(session).join(User.roles).filter(Role.name.in_(role_names))
    elif audience_type == 'users':
        user_ids = [int(i) for i in ids]
        if not user_ids:
            return []
        query = _base_users(session).filter(User.id.in_(user_ids))
    else:
        logger.warning(f"Unknown audience type: {audience_type}")
        return []

    return sorted({row[0] for row in query.distinct().all()})


def describe(session, audience_type: str, ids: Optional[list]) -> str:
    """Human-readable audience description for history rows."""
    ids = ids or []
    try:
        if audience_type == 'all_active':
            return 'Everyone (active members)'
        if audience_type == 'team':
            names = [t.name for t in session.query(Team).filter(Team.id.in_([int(i) for i in ids])).all()]
            return 'Team: ' + ', '.join(names) if names else 'Team (none selected)'
        if audience_type == 'league':
            names = [l.name for l in session.query(League).filter(League.id.in_([int(i) for i in ids])).all()]
            return 'League: ' + ', '.join(names) if names else 'League (none selected)'
        if audience_type == 'role':
            return 'Role: ' + ', '.join(str(r) for r in ids) if ids else 'Role (none selected)'
        if audience_type == 'users':
            return f'{len(ids)} hand-picked member{"" if len(ids) == 1 else "s"}'
    except Exception as e:
        logger.warning(f"Could not describe audience: {e}")
    return audience_type


def _pref_on(value) -> bool:
    """Mirror the orchestrator's gate semantics exactly: it reads the raw
    column value and treats falsy (False OR NULL) as opted out — e.g.
    `if not preferences.get('email_enabled', False)`. The ORM defaults these
    columns to True, so NULL only exists on rows predating a column."""
    return bool(value)


def channel_reach(session, user_ids: List[int]) -> Dict[str, int]:
    """Per-channel reachable counts for an admin announcement, mirroring the
    orchestrator's gates (global channel flag AND announcement flag AND contact
    info present; SMS additionally requires verified phone + consent).

    Counts are estimates for the compose preview — the orchestrator remains
    the authority at send time.
    """
    reach = {'total': len(user_ids), 'in_app': len(user_ids),
             'push': 0, 'email': 0, 'sms': 0, 'discord': 0}
    if not user_ids:
        return reach

    users = session.query(User).filter(User.id.in_(user_ids)).all()
    players = {
        p.user_id: p for p in session.query(Player).filter(Player.user_id.in_(user_ids)).all()
    }
    token_uids = {
        row[0] for row in session.query(UserFCMToken.user_id).filter(
            UserFCMToken.user_id.in_(user_ids),
            UserFCMToken.is_active == True  # noqa: E712
        ).distinct().all()
    }

    for user in users:
        if not _pref_on(getattr(user, 'announcement_notifications', True)):
            continue
        player = players.get(user.id)

        if _pref_on(getattr(user, 'push_notifications', True)) and user.id in token_uids:
            reach['push'] += 1
        if _pref_on(user.email_notifications) and user.email:
            reach['email'] += 1
        if _pref_on(user.discord_notifications) and player and player.discord_id:
            reach['discord'] += 1
        if (_pref_on(user.sms_notifications) and player
                and getattr(player, 'is_phone_verified', False)
                and getattr(player, 'sms_consent_given', False)):
            reach['sms'] += 1

    return reach
