# app/services/team_visibility.py

"""
Team-assignment visibility ("reveal") gating.

Backed by the `make_teams_public` AdminConfig toggle on /admin-panel/features.
While OFF, team assignments stay hidden from regular players across the web
UI, the mobile API, and Discord team channels — coaches and admins are
exempt. The toggle is reset to OFF on season rollover and flipped ON at the
reveal party, which also opens each team's Discord channel to its players
(see sync_team_channel_visibility_task).
"""

import logging

from app.models.admin_config import AdminConfig

logger = logging.getLogger(__name__)

TEAMS_PUBLIC_KEY = 'make_teams_public'

ADMIN_ROLES = ('Global Admin', 'Pub League Admin')
COACH_ROLES = ('Pub League Coach', 'Premier Coach', 'Classic Coach', 'ECS FC Coach')


def teams_are_public() -> bool:
    """Whether team assignments are currently revealed to players."""
    # Default True: if the setting row doesn't exist yet, behave like today
    # (everything visible) rather than hiding a live season.
    return bool(AdminConfig.get_setting(TEAMS_PUBLIC_KEY, True))


def user_is_team_exempt(user, session=None) -> bool:
    """
    True if this user may see team assignments even while teams are hidden:
    admins, division/league coaches (role-based), or anyone with a
    player_teams.is_coach row (drafted coaches).
    """
    if user is None or not getattr(user, 'is_authenticated', True):
        return False

    try:
        role_names = {role.name for role in user.roles}
    except Exception:
        role_names = set()

    if role_names.intersection(ADMIN_ROLES) or role_names.intersection(COACH_ROLES):
        return True

    player = getattr(user, 'player', None)
    if player is not None:
        if getattr(player, 'is_coach', False):
            return True
        try:
            from app.models.players import player_teams
            if session is None:
                from flask import g
                session = getattr(g, 'db_session', None)
            if session is not None:
                row = session.execute(
                    player_teams.select().where(
                        player_teams.c.player_id == player.id,
                        player_teams.c.is_coach == True  # noqa: E712
                    ).limit(1)
                ).first()
                if row is not None:
                    return True
        except Exception as e:
            logger.warning(f"team_visibility per-team coach check failed for user {getattr(user, 'id', '?')}: {e}")

    return False


def user_can_view_teams(user, session=None) -> bool:
    """Single gate: teams are public, or the user is coach/admin-exempt."""
    if teams_are_public():
        return True
    return user_is_team_exempt(user, session=session)


def mobile_user_can_view_teams(session, user_id) -> bool:
    """JWT variant of user_can_view_teams for the mobile API."""
    if teams_are_public():
        return True
    from app.models import User
    user = session.query(User).get(user_id) if user_id else None
    return user_is_team_exempt(user, session=session)


def reset_teams_reveal(session):
    """
    Force make_teams_public to 'false'. Called from every path that makes a
    Pub League season current, so each new season starts with assignments
    hidden until an admin flips the toggle at the reveal party.

    Also closes the Classic rating window (classic_ratings_window_open) —
    ratings are per-season, so a rollover must never leave last season's
    window open against the new season's roster.
    """
    from app.models.admin_config import AdminConfig
    from datetime import datetime

    def _force_false(key, description, category):
        row = session.query(AdminConfig).filter_by(key=key).first()
        if row:
            row.value = 'false'
            row.updated_at = datetime.utcnow()
        else:
            session.add(AdminConfig(
                key=key,
                value='false',
                description=description,
                category=category,
                data_type='boolean'
            ))

    _force_false(
        TEAMS_PUBLIC_KEY,
        'Reveal team assignments to players (web, mobile app, and Discord team channels).',
        'pub_league')
    _force_false(
        'classic_ratings_window_open',
        'Allow Classic coaches to submit/edit player ratings',
        'classic_ratings')
    session.flush()
    AdminConfig._l2_invalidate()
    logger.info("make_teams_public reset to false (new Pub League season becoming current)")


def request_viewer_can_view_teams(session) -> bool:
    """
    Resolve the current request's viewer (mobile JWT first, then web session)
    and apply the gate. For use inside shared helpers that serve both stacks.
    Fails closed: no identifiable viewer -> not exempt.
    """
    if teams_are_public():
        return True
    try:
        from flask_jwt_extended import get_jwt_identity
        raw = get_jwt_identity()
        if raw is not None:
            from app.models import User
            user = session.query(User).get(int(raw))
            return user_is_team_exempt(user, session=session)
    except Exception:
        pass
    try:
        from flask_login import current_user
        if getattr(current_user, 'is_authenticated', False):
            return user_is_team_exempt(current_user, session=session)
    except Exception:
        pass
    return False


def hidden_pub_league_team_ids(session, team_ids) -> set:
    """Subset of team_ids that are current-season Premier/Classic teams (the
    ones subject to the reveal gate). Used to filter history rows that carry
    only a team_id."""
    team_ids = [t for t in (team_ids or []) if t]
    if not team_ids:
        return set()
    from app.models import Team, League, Season
    rows = (
        session.query(Team.id)
        .join(League, Team.league_id == League.id)
        .join(Season, League.season_id == Season.id)
        .filter(
            Team.id.in_(set(team_ids)),
            League.name.in_(('Premier', 'Classic')),
            Season.is_current == True  # noqa: E712
        )
        .all()
    )
    return {r[0] for r in rows}


def is_current_pub_league_team(team) -> bool:
    """Whether this team is subject to the reveal gate (current-season Premier/Classic)."""
    return bool(team and team.league and team.league.name in ('Premier', 'Classic')
                and team.league.season and team.league.season.is_current)
