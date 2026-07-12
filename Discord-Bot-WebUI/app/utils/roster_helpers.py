# app/utils/roster_helpers.py

"""
Roster Helpers Module

One place to bulk-load team rosters and to build the `player_choices` structure
that the match-report modal consumes.

Why this exists
---------------
Six routes independently rebuilt the same "who is on this team" lookup, and most
of them did it with a query PER TEAM PER MATCH:

    for match in matches:
        home = session.query(Player).join(Player.teams).filter(Team.id == match.home_team_id).all()
        away = session.query(Player).join(Player.teams).filter(Team.id == match.away_team_id).all()

That is 2N queries for an N-match dashboard. This app sits behind pgbouncer in
TRANSACTION pooling on a 1-vCPU Postgres, so the number of queries a request
holds a server slot for is the binding constraint, not the size of any one query.
Both helpers below issue exactly ONE query regardless of how many teams or
matches are involved.

Session discipline
------------------
The session is always passed in explicitly. These helpers never touch
`Model.query` (which would bind to `db.session`, a DIFFERENT session from the
request's `g.db_session`) and never write.
"""

import logging
from typing import Dict, Iterable, List, Optional

from app.models import Player
from app.models.players import player_teams

logger = logging.getLogger(__name__)


def rosters_for_teams(session, team_ids: Iterable[Optional[int]]) -> Dict[int, Dict[int, str]]:
    """
    Bulk-load the rosters for many teams in a SINGLE query.

    Args:
        session: The request's SQLAlchemy session (e.g. g.db_session). Never
            `db.session` — see the module docstring.
        team_ids: Any iterable of team ids. None entries are ignored, so callers
            can pass `match.away_team_id` straight through for ECS FC / BYE rows.

    Returns:
        {team_id: {player_id: player_name}}, players ordered by name. Teams with
        no players (or ids that do not exist) are simply absent from the mapping,
        so callers should use `.get(team_id, {})`.
    """
    wanted = {tid for tid in team_ids if tid is not None}
    if not wanted:
        return {}

    rosters: Dict[int, Dict[int, str]] = {}
    rows = (
        session.query(player_teams.c.team_id, Player.id, Player.name)
        .join(Player, Player.id == player_teams.c.player_id)
        .filter(player_teams.c.team_id.in_(wanted))
        .order_by(Player.name)
        .all()
    )
    for team_id, player_id, player_name in rows:
        rosters.setdefault(team_id, {})[player_id] = player_name
    return rosters


def player_choices_for_matches(session, matches: Iterable) -> Dict[int, Dict[str, Dict[int, str]]]:
    """
    Build the report-match modal's `player_choices` for a list of matches using
    ONE roster query total.

    Shape (unchanged from the hand-rolled versions this replaces, and the shape
    `macros/flowbite.html::render_report_match_modal_flowbite` expects):

        {match_id: {team_name: {player_id: player_name}}}

    Player ids stay INTEGERS because the macro compares them to
    `PlayerEvent.player_id` to mark the selected <option>.

    Handles the two match flavours the coach dashboards mix into one list:
      * ECS FC (`match.is_ecs_fc`): exactly one real team (whichever of
        home_team/away_team is set) plus the opponent-as-a-string, which gets an
        empty roster since we have no players for them.
      * Pub League: both sides are real teams.

    A match with no usable team data is omitted entirely (same as before), so
    templates must guard with `match.id in player_choices` where that is possible.

    Args:
        session: The request's SQLAlchemy session.
        matches: Match / EcsFcMatch objects. `home_team` / `away_team` are read
            for their names only; every caller already touches those, so no new
            lazy loads are introduced.
    """
    matches = list(matches)

    team_ids: List[int] = []
    for match in matches:
        for team in (getattr(match, 'home_team', None), getattr(match, 'away_team', None)):
            if team is not None:
                team_ids.append(team.id)

    rosters = rosters_for_teams(session, team_ids)

    player_choices: Dict[int, Dict[str, Dict[int, str]]] = {}
    for match in matches:
        home_team = getattr(match, 'home_team', None)
        away_team = getattr(match, 'away_team', None)

        if getattr(match, 'is_ecs_fc', False):
            team = home_team or away_team
            if team:
                player_choices[match.id] = {
                    team.name: rosters.get(team.id, {}),
                    # opponent_name is NOT NULL on EcsFcMatch; the fallback only
                    # guards a non-ECS object that slipped through the flag.
                    getattr(match, 'opponent_name', None) or 'Opponent': {},
                }
        elif home_team and away_team:
            player_choices[match.id] = {
                home_team.name: rosters.get(home_team.id, {}),
                away_team.name: rosters.get(away_team.id, {}),
            }

    return player_choices
