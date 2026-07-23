# app/services/substitute_authority.py

"""
Substitute authority — the SINGLE source of truth for who may do what with subs.

Hard invariant (locked 2026-07-22):
  - ECS FC coaches may REQUEST and ASSIGN — but only for THEIR OWN team.
  - Pub League (Premier/Classic) coaches may REQUEST only. ADMINS assign, always.
  - Admins (Global / Pub League / ECS FC Admin) may do everything.
  - Discord /subs stays request-only (enforced in the cog); assignment is never exposed there.

This replaces the four divergent `is_coach_for_team` copies and the league-wide
`validate_ecs_fc_coach_access` (which let any ECS FC coach act on any ECS FC team).
Every request/assign/cancel route — web, mobile, internal — should gate through here.
"""

import logging

from sqlalchemy import and_
from sqlalchemy.orm import joinedload

from app.models import User, Player, player_teams

logger = logging.getLogger(__name__)

GLOBAL_ADMIN = 'Global Admin'
PUB_LEAGUE_ADMIN = 'Pub League Admin'
ECS_FC_ADMIN = 'ECS FC Admin'
# 'Admin' is a legacy catch-all still present in some role sets.
ADMIN_ROLES = {GLOBAL_ADMIN, PUB_LEAGUE_ADMIN, ECS_FC_ADMIN, 'Admin'}

# Programs
PUB_LEAGUE = 'Pub League'
ECS_FC = 'ECS FC'

# league_type string -> program
_PROGRAM_BY_LEAGUE_TYPE = {
    'Classic': PUB_LEAGUE, 'Premier': PUB_LEAGUE, 'Pub League': PUB_LEAGUE,
    'ECS FC': ECS_FC,
}


def program_for_league_type(league_type):
    """Map a sub league_type string ('Classic'/'Premier'/'ECS FC') to its program."""
    return _PROGRAM_BY_LEAGUE_TYPE.get(league_type, PUB_LEAGUE)


def _user_role_names(session, user_id):
    user = session.query(User).options(joinedload(User.roles)).filter(User.id == user_id).first()
    if not user or not user.roles:
        return set()
    return {r.name for r in user.roles}


def is_admin(session, user_id, program=None):
    """True if the user holds ANY admin role.

    The assignment invariant restricts COACHES (Pub League coaches can't assign;
    ECS FC coaches only their own team) — NOT admins. Per the plan, admins may do
    everything across both leagues, so any admin role qualifies regardless of
    `program` (the param is kept for call-site clarity/compat)."""
    return bool(_user_role_names(session, user_id) & ADMIN_ROLES)


def is_coach_for_team(session, user_id, team_id):
    """True if the user is a coach OF THIS SPECIFIC team (player_teams.is_coach).
    This is the canonical, per-team check (the mobile-proven one) — not the old
    league-wide 'any ECS FC coach' grant."""
    if not team_id:
        return False
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return False
    row = session.execute(
        player_teams.select().where(and_(
            player_teams.c.player_id == player.id,
            player_teams.c.team_id == team_id,
            player_teams.c.is_coach == True,
        ))
    ).fetchone()
    return row is not None


def coach_team_ids(session, user_id):
    """All team ids where the user is a coach."""
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return []
    rows = session.execute(
        player_teams.select().where(and_(
            player_teams.c.player_id == player.id,
            player_teams.c.is_coach == True,
        ))
    ).fetchall()
    return [r.team_id for r in rows]


def can_request(session, user_id, *, team_id, program):
    """May this user CREATE a sub request for this team?
    Admins for the program, or the team's own coach (either league)."""
    return is_admin(session, user_id, program) or is_coach_for_team(session, user_id, team_id)


def can_assign(session, user_id, *, team_id, program):
    """May this user ASSIGN a sub — the invariant's core gate.

      - ECS FC : admin OR the team's own coach.
      - Pub League : admin ONLY (coaches never assign).
    """
    if program == ECS_FC:
        return is_admin(session, user_id, ECS_FC) or is_coach_for_team(session, user_id, team_id)
    return is_admin(session, user_id, PUB_LEAGUE)


def can_assign_request(session, user_id, sub_request, program=None):
    """Convenience: derive (program, team_id) from a request object then can_assign().
    Works for both SubstituteRequest and EcsFcSubRequest (has .team_id; Pub League
    also has .league_type)."""
    if program is None:
        lt = getattr(sub_request, 'league_type', None)
        program = program_for_league_type(lt) if lt else ECS_FC  # EcsFcSubRequest has no league_type
    return can_assign(session, user_id, team_id=sub_request.team_id, program=program)
