# app/services/audience_service.py

"""
Audience Service — ONE resolver for "who is this admin message for?".

Resolves an (audience_type, ids) pair into user ids, and previews per-channel
reachability using the SAME preference semantics the NotificationOrchestrator
applies at send time (global channel flag + announcement type flag + contact
info; NULL preference = opted in). Used by the multi-channel composer.

audience_type values:
    all_active          — every approved, active user
    active_this_season  — approved, active users who are current-season players
                          (Player.is_current_player) — "only people playing now"
    team                — players on the given team ids (current rosters)
    league              — players on teams in the given league ids
    role                — users holding any of the given role names
    users               — the given user ids verbatim (still filtered to active)

audience_type values that need NO ids (NO_ID_AUDIENCE_TYPES) resolve without a
selection; everything else requires at least one id.
"""

import logging
from typing import Dict, List, Optional, Set

from app.models import User, Player, Team, League, Role
from app.models.players import player_teams
from app.models.notifications import UserFCMToken

logger = logging.getLogger(__name__)

AUDIENCE_TYPES = ('all_active', 'active_this_season', 'team', 'league', 'role', 'users')
# These resolve from the base filter alone — no target ids required.
NO_ID_AUDIENCE_TYPES = ('all_active', 'active_this_season')
# Channels that a "force delivery" override can push past a member's opt-out.
# SMS is intentionally excluded — TCPA requires verified + consented numbers,
# which the orchestrator enforces even under force_sms.
FORCEABLE_CHANNELS = ('push', 'email', 'discord')


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
    elif audience_type == 'active_this_season':
        # "People playing this season" — approved/active accounts flagged as a
        # current player. is_current_player is the app's canonical season-active
        # flag (set on registration/approval, cleared at rollover), so it also
        # covers registered members not yet drafted onto a roster.
        query = _base_users(session).join(
            Player, Player.user_id == User.id
        ).filter(Player.is_current_player == True)  # noqa: E712
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
        if audience_type == 'active_this_season':
            return 'Active players (this season)'
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


def channel_reach(session, user_ids: List[int],
                  force_channels: Optional[Set[str]] = None) -> Dict[str, int]:
    """Per-channel reachable counts for an admin announcement, mirroring the
    orchestrator's gates (global channel flag AND announcement flag AND contact
    info present; SMS additionally requires verified phone + consent).

    force_channels: channels the admin has chosen to FORCE past member opt-outs
    (see FORCEABLE_CHANNELS). For a forced channel the count ignores the
    member's channel + announcement preferences and requires only that we have
    a way to reach them there (an email address, an active device token, or a
    linked Discord id) — matching what the orchestrator does under force_*.
    SMS can never be forced past the verified-phone/consent gate, so passing it
    here has no effect.

    Counts are estimates for the compose preview — the orchestrator remains
    the authority at send time.
    """
    force_channels = force_channels or set()
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

    force_push = 'push' in force_channels
    force_email = 'email' in force_channels
    force_discord = 'discord' in force_channels

    for user in users:
        # The announcement type-flag gates every channel — UNLESS forced, in
        # which case only the forced channels ignore it (the orchestrator's
        # force_* short-circuits ahead of the announcement check).
        announce_ok = _pref_on(getattr(user, 'announcement_notifications', True))
        player = players.get(user.id)

        if user.id in token_uids and (force_push or (announce_ok and _pref_on(getattr(user, 'push_notifications', True)))):
            reach['push'] += 1
        if user.email and (force_email or (announce_ok and _pref_on(user.email_notifications))):
            reach['email'] += 1
        if player and player.discord_id and (force_discord or (announce_ok and _pref_on(user.discord_notifications))):
            reach['discord'] += 1
        # SMS is never forceable — always requires opt-in + verified + consent +
        # an actual phone on file (the orchestrator gates on preferences['phone'],
        # so a verified/consented player whose number was cleared must not count).
        if (announce_ok and _pref_on(user.sms_notifications) and player
                and getattr(player, 'is_phone_verified', False)
                and getattr(player, 'sms_consent_given', False)
                and getattr(player, 'phone', None)):
            reach['sms'] += 1

    return reach
