# app/services/mobile/team_service.py

"""
Mobile Team Service

Handles team operations for mobile clients including:
- Team listing
- Team details
- Roster management
- Team statistics
"""

import logging
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.services.base_service import BaseService, ServiceResult
from app.models import Team, League, Season, Player, Standings, player_teams

logger = logging.getLogger(__name__)


class MobileTeamService(BaseService):
    """
    Service for mobile team operations.

    Handles all team-related business logic for mobile clients.
    """

    def __init__(self, session: Session):
        super().__init__(session)

    def get_teams_for_current_season(
        self,
        league_id: Optional[int] = None
    ) -> ServiceResult[List[Dict[str, Any]]]:
        """
        Get all teams for the current season.

        Args:
            league_id: Optional league filter

        Returns:
            ServiceResult with list of teams
        """
        # Get current seasons
        current_pub_season = self.session.query(Season).filter_by(
            is_current=True, league_type='Pub League'
        ).first()
        current_ecs_season = self.session.query(Season).filter_by(
            is_current=True, league_type='ECS FC'
        ).first()

        conditions = []
        if current_pub_season:
            conditions.append(League.season_id == current_pub_season.id)
        if current_ecs_season:
            conditions.append(League.season_id == current_ecs_season.id)

        query = self.session.query(Team).join(
            League, Team.league_id == League.id
        ).options(joinedload(Team.league))

        if league_id:
            query = query.filter(Team.league_id == league_id)
        elif conditions:
            query = query.filter(or_(*conditions))

        teams = query.order_by(Team.name).all()

        teams_data = [
            {
                **team.to_dict(),
                'league_name': team.league.name if team.league else "Unknown"
            }
            for team in teams
        ]

        return ServiceResult.ok(teams_data)

    def get_team_details(
        self,
        team_id: int,
        include_players: bool = False,
        include_matches: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get details for a specific team.

        Args:
            team_id: The team's ID
            include_players: Include roster
            include_matches: Include upcoming matches

        Returns:
            ServiceResult with team details
        """
        team = self.session.query(Team).get(team_id)
        if not team:
            return ServiceResult.fail("Team not found", "TEAM_NOT_FOUND")

        team_data = team.to_dict(include_players=include_players)

        if include_matches:
            team_data['upcoming_matches'] = self._get_upcoming_matches(team_id)

        return ServiceResult.ok(team_data)

    def get_team_roster(
        self,
        team_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get the roster for a team.

        Args:
            team_id: The team's ID

        Returns:
            ServiceResult with roster data
        """
        team = self.session.query(Team).get(team_id)
        if not team:
            return ServiceResult.fail("Team not found", "TEAM_NOT_FOUND")

        # Get players with coach status
        players_with_status = (
            self.session.query(Player, player_teams.c.is_coach)
            .join(player_teams)
            .filter(player_teams.c.team_id == team_id)
            .order_by(Player.name)
            .all()
        )

        players = []
        for player, is_coach in players_with_status:
            players.append({
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "is_coach": bool(is_coach),
                "favorite_position": player.favorite_position,
                "profile_picture_url": player.profile_picture_url,
                "is_primary_team": player.primary_team_id == team_id
            })

        return ServiceResult.ok({
            "team": {"id": team.id, "name": team.name},
            "players": players
        })

    def get_team_stats(
        self,
        team_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get statistics for a team.

        Args:
            team_id: The team's ID

        Returns:
            ServiceResult with team statistics
        """
        team = self.session.query(Team).get(team_id)
        if not team:
            return ServiceResult.fail("Team not found", "TEAM_NOT_FOUND")

        current_season = self.session.query(Season).filter_by(is_current=True).first()

        standings = self.session.query(Standings).filter_by(
            team_id=team_id,
            season_id=current_season.id if current_season else None
        ).first()

        if standings:
            stats = {
                "wins": standings.wins,
                "losses": standings.losses,
                "draws": standings.draws,
                "goals_for": standings.goals_for,
                "goals_against": standings.goals_against,
                "goal_difference": standings.goal_difference,
                "points": standings.points,
                "games_played": standings.wins + standings.losses + standings.draws
            }
        else:
            stats = {
                "wins": 0, "losses": 0, "draws": 0,
                "goals_for": 0, "goals_against": 0,
                "goal_difference": 0, "points": 0, "games_played": 0
            }

        return ServiceResult.ok({
            "team_id": team_id,
            "team_name": team.name,
            "season": current_season.name if current_season else None,
            "stats": stats
        })

    def get_user_teams(
        self,
        user_id: int
    ) -> ServiceResult[List[Dict[str, Any]]]:
        """
        Get all teams for a user.

        Args:
            user_id: The user's ID

        Returns:
            ServiceResult with list of teams
        """
        player = self.session.query(Player).filter_by(user_id=user_id).first()
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        if not player.teams:
            return ServiceResult.ok([])

        teams = [
            {
                **team.to_dict(),
                'is_primary': team.id == player.primary_team_id,
                'league_name': team.league.name if team.league else None
            }
            for team in player.teams
        ]

        # Sort with primary first
        teams.sort(key=lambda t: (not t['is_primary'], t['name'].lower()))

        return ServiceResult.ok(teams)

    def _get_upcoming_matches(self, team_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Get upcoming matches for a team."""
        from datetime import datetime
        from app.models import Match

        matches = (
            self.session.query(Match)
            .filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
                Match.date >= datetime.now().date()
            )
            .order_by(Match.date)
            .limit(limit)
            .all()
        )

        return [
            {
                "id": m.id,
                "date": m.date.isoformat() if m.date else None,
                "time": m.time.isoformat() if m.time else None,
                "home_team_id": m.home_team_id,
                "away_team_id": m.away_team_id
            }
            for m in matches
        ]
