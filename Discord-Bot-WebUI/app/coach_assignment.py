"""
Auto-promote a drafted division coach to per-team coach.

Two separate coach concepts live in the app and were never linked:
  * DIVISION coach  = the Flask Role 'Premier Coach' / 'Classic Coach' (team-independent),
                      managed at /admin-panel/seasons/coaches.
  * PER-TEAM coach  = player_teams.is_coach (team-scoped), which is what actually drives the
                      division Discord coach role via discord_utils.get_expected_roles.

When a division coach is drafted onto a team IN THEIR division they should become that
team's coach automatically. This module bridges the two gaps: it consults the division Role
and, when the role matches the drafted team's league, flips player_teams.is_coach (plus the
season snapshot and the global convenience flag) so the Discord sync that already runs after
every draft grants the coach role with no extra admin step.

A player flagged 'Premier Coach' who lands on a Classic team stays a player there — the league
name won't match — exactly as intended (coach in Premier, player in Classic).
"""
import logging

from sqlalchemy import select, update

from app.models.core import Role, user_roles
from app.models.players import Player, PlayerTeamSeason, player_teams

logger = logging.getLogger(__name__)


def division_coach_role_name(league_name: str) -> str:
    """League display name -> the Flask role that marks a division coach.

    'Premier' -> 'Premier Coach', 'Classic' -> 'Classic Coach'.
    """
    return f"{(league_name or '').strip()} Coach"


def player_is_division_coach(session, player_id: int, league_name: str) -> bool:
    """True if the player's linked user holds the '<League> Coach' Flask role.

    Team-independent — it only answers "is this person the division's coach", which is the
    signal we use to decide whether a draft pick should also make them the team's coach.
    """
    role_name = division_coach_role_name(league_name)
    if not role_name.strip() or role_name == 'Coach':
        return False

    row = session.execute(
        select(Player.user_id).where(Player.id == player_id)
    ).first()
    user_id = row[0] if row else None
    if not user_id:
        return False

    hit = session.execute(
        select(user_roles.c.user_id)
        .select_from(user_roles.join(Role, Role.id == user_roles.c.role_id))
        .where(user_roles.c.user_id == user_id, Role.name == role_name)
    ).first()
    return hit is not None


def apply_draft_coach_status(session, player_id: int, team_id: int, league_name: str,
                             season_id=None) -> bool:
    """If the drafted player is a division coach for `league_name`, make them coach of `team_id`.

    Sets player_teams.is_coach = True, mirrors it into the PlayerTeamSeason snapshot for the
    season (when season_id is given), and sets the global Player.is_coach convenience flag.
    Returns True when the player was promoted, False (a no-op) otherwise, so ordinary drafts
    are entirely unaffected.

    NOTE: the caller must have already inserted the player_teams row (the draft assignment).
    A flush is issued so an update-by-criteria reliably targets a freshly-appended row.
    """
    if not player_is_division_coach(session, player_id, league_name):
        return False

    session.flush()  # ensure a just-appended player_teams row is queryable by the UPDATE

    session.execute(
        update(player_teams)
        .where(player_teams.c.player_id == player_id, player_teams.c.team_id == team_id)
        .values(is_coach=True)
    )
    if season_id is not None:
        session.execute(
            update(PlayerTeamSeason)
            .where(
                PlayerTeamSeason.player_id == player_id,
                PlayerTeamSeason.team_id == team_id,
                PlayerTeamSeason.season_id == season_id,
            )
            .values(is_coach=True)
        )
    session.execute(
        update(Player).where(Player.id == player_id).values(is_coach=True)
    )
    logger.info(
        f"Auto-promoted player {player_id} to coach of team {team_id} "
        f"({league_name} division coach)"
    )
    return True
