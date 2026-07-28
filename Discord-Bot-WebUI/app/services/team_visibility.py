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


def reveal_exempt_coach_roles():
    """Coach roles exempt from the reveal gate, across every program.

    The literal above omits any newer program's coach role, so those coaches
    could not see their own roster before the reveal -- on their own board.
    """
    roles = set(COACH_ROLES)
    try:
        from app.services import program_registry
        for p in program_registry.all_programs():
            if p.flask_coach_role:
                roles.add(p.flask_coach_role)
    except Exception:
        pass
    return tuple(roles)


def _gated_program_names(session=None):
    """League names currently hidden: hide_until_reveal AND not yet revealed.

    Kept separate from teams_are_public() so the keyless "is everything
    revealed?" branch can call it without recursing -- the per-program checks
    below always pass a key.

    Memoised per request. is_current_pub_league_team() calls this once PER TEAM
    inside list comprehensions over schedules, calendars and reminder batches,
    and each call rebuilt the tuple and re-read one AdminConfig row per program.
    """
    try:
        from flask import g, has_request_context
        if has_request_context():
            _cached = getattr(g, '_gated_program_names', None)
            if _cached is not None:
                return _cached
    except Exception:
        pass
    names = _compute_gated_program_names(session)
    try:
        from flask import g, has_request_context
        if has_request_context():
            g._gated_program_names = names
    except Exception:
        pass
    return names


def _compute_gated_program_names(session=None):
    try:
        from app.services import program_registry
        programs = list(program_registry.all_programs(session))
        names = tuple(p.league_name for p in programs
                      if p.hide_until_reveal and not teams_are_public(p.key))
        if names:
            return names
        # Every gated program has revealed -> nothing to hide. Distinguish that
        # from "registry unavailable", which must keep hiding.
        if any(p.hide_until_reveal for p in programs):
            return ()
    except Exception:
        pass
    return ('Premier', 'Classic')


def _coerce_bool(value, default=False):
    """Robustly coerce an AdminConfig value to bool.

    AdminConfig._parse_value only returns a real bool when the row's
    `data_type` is 'boolean'. A row created with data_type='string' comes back
    as the STRING 'false', and bool('false') is True -- so the reveal would
    silently flip ON. This codebase has already shipped that exact bug once
    (a cutover flag stored as "False").
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ('true', '1', 'yes', 'on')


def program_reveal_key(program_key) -> str:
    """AdminConfig key holding a single program's reveal override."""
    return f'{TEAMS_PUBLIC_KEY}:{program_key}'


def teams_are_public(program_key=None) -> bool:
    """Whether team assignments are revealed.

    `make_teams_public` is ONE GLOBAL BOOLEAN shared by every reveal-gated
    program, which breaks as soon as two programs run on different calendars:
    a Pub League rollover resets it and would re-hide a mid-season program's
    rosters. A per-program override (`make_teams_public:<key>`) lets each
    program reveal on its own schedule; absent an override the global still
    decides, so nothing changes for Premier/Classic.
    """
    if program_key:
        override = AdminConfig.get_setting(program_reveal_key(program_key), None)
        if override is not None:
            return _coerce_bool(override)
        # Default True: if the setting row doesn't exist yet, behave like today
        # (everything visible) rather than hiding a live season.
        return _coerce_bool(AdminConfig.get_setting(TEAMS_PUBLIC_KEY, True), default=True)

    # ── No program named: "is EVERYTHING revealed?" ──────────────────────────
    # This is the form every caller uses (user_can_view_teams,
    # mobile_user_can_view_teams, request_viewer_can_view_teams), and each one
    # RETURNS EARLY on True. If it answered from the global alone, a program
    # whose own override is still OFF would be revealed the moment another
    # program flipped the global at its reveal party -- the gate would never be
    # consulted. So it is True only when nothing is currently gated; otherwise
    # callers fall through to the exemption check and the per-program filter in
    # reveal_gated_league_names() decides what actually hides.
    _global = _coerce_bool(AdminConfig.get_setting(TEAMS_PUBLIC_KEY, True), default=True)
    try:
        return not _gated_program_names()
    except Exception:
        return _global


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

    if role_names.intersection(ADMIN_ROLES) or role_names.intersection(reveal_exempt_coach_roles()):
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


def reset_teams_reveal(session, season_league_type=None):
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

    # Capture the global BEFORE _force_false mutates it. The preservation branch
    # below asks "was the reveal on?" -- reading that after the write would see
    # the value we just set (or not, depending on cache timing) and preserve the
    # wrong state.
    _global_was_public = _coerce_bool(AdminConfig.get_setting(TEAMS_PUBLIC_KEY, True), default=True)

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

    # Scope the reset when the caller names a season type: only that season's
    # programs get re-hidden. Without this, rolling Pub League over would flip
    # the shared flag and re-hide a DIFFERENT program's rosters mid-season.
    if season_league_type:
        try:
            from app.services import program_registry
            for _pr in program_registry.all_programs(session):
                if not _pr.hide_until_reveal:
                    continue
                if _pr.season_league_type == season_league_type:
                    # DELETE the override so this program falls back to the
                    # global flag, which was just forced false.
                    #
                    # ⚠️ Do NOT write an explicit 'false' here. teams_are_public()
                    # checks the override FIRST and returns early, so an explicit
                    # false permanently masks the global -- and nothing in the
                    # app ever writes these keys back to 'true'. Rolling Pub
                    # League over used to pin premier/classic to false forever,
                    # and the reveal party then did nothing at all: the admin
                    # flips make_teams_public, _gated_program_names still reports
                    # both as gated, and no roster appears. Falling back to the
                    # global keeps the reveal party working exactly as before.
                    _row = session.query(AdminConfig).filter_by(
                        key=program_reveal_key(_pr.key)).first()
                    if _row is not None:
                        session.delete(_row)
                else:
                    # Explicitly PRESERVE the other program's current state, so
                    # the global reset above cannot silently re-hide it.
                    # Check the ROW, not the parsed value: _parse_value returns
                    # None for a blank stored value too, so a row that exists
                    # with an empty string looked identical to "no override" and
                    # was skipped -- leaving that program to be re-hidden by
                    # another program's rollover.
                    row = session.query(AdminConfig).filter_by(
                        key=program_reveal_key(_pr.key)).first()
                    if row is None and _global_was_public:
                        session.add(AdminConfig(
                            key=program_reveal_key(_pr.key), value='true',
                            description=f'Reveal {_pr.display_name} team assignments.',
                            category='pub_league', data_type='boolean'))
                    elif row is not None and not (row.value or '').strip():
                        # Row exists but is blank -> it would parse as "no
                        # override". Materialise the state we are preserving.
                        row.value = 'true' if _global_was_public else 'false'
        except Exception as _rv_err:
            logger.warning(f"per-program reveal scoping failed: {_rv_err}")
    _force_false(
        'classic_ratings_window_open',
        'Allow Classic coaches to submit/edit player ratings',
        'classic_ratings')
    session.flush()
    AdminConfig._l2_invalidate()
    # The per-request memo below is now stale.
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, '_gated_program_names'):
            del g._gated_program_names
    except Exception:
        pass
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
            League.name.in_(reveal_gated_league_names(session)),
            Season.is_current == True  # noqa: E712
        )
        .all()
    )
    return {r[0] for r in rows}


def reveal_gated_league_names(session=None):
    """League names whose team assignments are hidden until the reveal.

    Single definition for what used to be the literal ('Premier', 'Classic')
    repeated in six places (here x2, mobile teams/auth/players/stats). A program
    missing from this set has its rosters exposed before the draft is announced,
    which silently spoils the reveal — there is no error, the teams simply show.

    ⚠️ Falls back to ('Premier', 'Classic') if the registry is unavailable.
    That direction matters: the fallback must keep HIDING what is hidden today.
    An empty set would gate nothing and reveal every roster.
    """
    return _gated_program_names(session)


def is_current_pub_league_team(team) -> bool:
    """Whether this team is subject to the reveal gate (current-season, gated program)."""
    return bool(team and team.league
                and team.league.name in reveal_gated_league_names()
                and team.league.season and team.league.season.is_current)
