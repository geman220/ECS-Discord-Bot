# app/services/mobile/profile_service.py

"""
Mobile Profile Service

Handles profile operations for mobile clients including:
- Profile retrieval
- Profile updates
- Profile picture management
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.base_service import BaseService, ServiceResult
from app.models import User, Player, Season

logger = logging.getLogger(__name__)


class MobileProfileService(BaseService):
    """
    Service for mobile profile operations.

    Handles all profile-related business logic for mobile clients.
    """

    def __init__(self, session: Session):
        super().__init__(session)

    def get_player_profile(
        self,
        player_id: int,
        include_stats: bool = False,
        include_teams: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get a player's profile data.

        Args:
            player_id: The player's ID
            include_stats: Include player statistics
            include_teams: Include team memberships

        Returns:
            ServiceResult with profile data
        """
        player = self.session.query(Player).get(player_id)
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        profile = {
            "id": player.id,
            "name": player.name,
            "jersey_number": player.jersey_number,
            "favorite_position": player.favorite_position,
            "is_current_player": player.is_current_player,
            "is_coach": player.is_coach,
            "discord_id": player.discord_id,
            "profile_picture_url": player.profile_picture_url,
        }

        if include_teams and player.teams:
            profile["teams"] = [
                {
                    "id": team.id,
                    "name": team.name,
                    "is_primary": team.id == player.primary_team_id
                }
                for team in player.teams
            ]

        if include_stats:
            profile["stats"] = self._get_season_stats(player)

        return ServiceResult.ok(profile)

    def update_player_profile(
        self,
        user_id: int,
        updates: Dict[str, Any]
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Update a player's profile.

        Args:
            user_id: The user's ID
            updates: Dictionary of fields to update

        Returns:
            ServiceResult with updated profile
        """
        player = self.session.query(Player).filter_by(user_id=user_id).first()
        if not player:
            return ServiceResult.fail("Player profile not found", "PLAYER_NOT_FOUND")

        # Update allowed fields
        allowed_fields = ['jersey_number', 'favorite_position', 'phone']
        for field in allowed_fields:
            if field in updates:
                setattr(player, field, updates[field])

        self.session.commit()

        return ServiceResult.ok({
            "id": player.id,
            "name": player.name,
            "jersey_number": player.jersey_number,
            "favorite_position": player.favorite_position
        })

    def _get_season_stats(self, player: Player) -> Dict[str, Any]:
        """Get current season statistics for a player."""
        from app.models import PlayerSeasonStats

        current_season = self.session.query(Season).filter_by(is_current=True).first()
        if not current_season:
            return {}

        stats = self.session.query(PlayerSeasonStats).filter_by(
            player_id=player.id,
            season_id=current_season.id
        ).first()

        if stats:
            return {
                "season": current_season.name,
                "goals": stats.goals,
                "assists": stats.assists,
                "games_played": stats.games_played,
                "yellow_cards": stats.yellow_cards,
                "red_cards": stats.red_cards
            }

        return {"season": current_season.name}
