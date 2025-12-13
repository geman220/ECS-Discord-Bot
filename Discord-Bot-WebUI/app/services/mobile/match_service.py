# app/services/mobile/match_service.py

"""
Mobile Match Service

Handles match operations for mobile clients including:
- Match listing
- Match details
- Match events
- Match availability
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.services.base_service import BaseService, ServiceResult
from app.models import Match, Player, Team, Availability

logger = logging.getLogger(__name__)


class MobileMatchService(BaseService):
    """
    Service for mobile match operations.

    Handles all match-related business logic for mobile clients.
    """

    def __init__(self, session: Session):
        super().__init__(session)

    def get_matches(
        self,
        player: Optional[Player] = None,
        team_id: Optional[int] = None,
        upcoming: bool = False,
        completed: bool = False,
        limit: int = 20
    ) -> ServiceResult[List[Dict[str, Any]]]:
        """
        Get matches with optional filters.

        Args:
            player: Optional player to filter by their teams
            team_id: Optional specific team filter
            upcoming: Only future matches
            completed: Only past matches
            limit: Maximum matches to return

        Returns:
            ServiceResult with list of matches
        """
        query = self.session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        )

        # Filter by team
        if team_id:
            query = query.filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )
        elif player and player.teams:
            team_ids = [t.id for t in player.teams]
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )

        # Filter by date
        today = datetime.now().date()
        if upcoming:
            query = query.filter(Match.date >= today)
            query = query.order_by(Match.date.asc())
        elif completed:
            query = query.filter(Match.date < today)
            query = query.order_by(Match.date.desc())
        else:
            query = query.order_by(Match.date.desc())

        matches = query.limit(limit).all()

        matches_data = [self._build_match_data(m) for m in matches]

        return ServiceResult.ok(matches_data)

    def get_match_details(
        self,
        match_id: int,
        include_events: bool = False,
        include_availability: bool = False,
        player_id: Optional[int] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get details for a specific match.

        Args:
            match_id: The match ID
            include_events: Include match events
            include_availability: Include RSVP data
            player_id: Optional player ID for personal availability

        Returns:
            ServiceResult with match details
        """
        match = self.session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return ServiceResult.fail("Match not found", "MATCH_NOT_FOUND")

        match_data = self._build_match_data(match)

        if include_events:
            match_data['events'] = self._get_match_events(match_id)

        if include_availability:
            match_data['home_team_availability'] = self._get_team_availability(
                match_id, match.home_team_id
            )
            match_data['away_team_availability'] = self._get_team_availability(
                match_id, match.away_team_id
            )

            if player_id:
                match_data['my_availability'] = self._get_player_availability(
                    match_id, player_id
                )

        return ServiceResult.ok(match_data)

    def get_match_availability(
        self,
        match_id: int,
        player_id: Optional[int] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get availability data for a match.

        Args:
            match_id: The match ID
            player_id: Optional player for personal availability

        Returns:
            ServiceResult with availability data
        """
        match = self.session.query(Match).get(match_id)
        if not match:
            return ServiceResult.fail("Match not found", "MATCH_NOT_FOUND")

        data = {
            "match_id": match_id,
            "home_team": {
                "id": match.home_team_id,
                "availability": self._get_team_availability(match_id, match.home_team_id)
            },
            "away_team": {
                "id": match.away_team_id,
                "availability": self._get_team_availability(match_id, match.away_team_id)
            }
        }

        if player_id:
            data['my_availability'] = self._get_player_availability(match_id, player_id)

        return ServiceResult.ok(data)

    def update_availability(
        self,
        match_id: int,
        player_id: int,
        response: str
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Update player availability for a match.

        Args:
            match_id: The match ID
            player_id: The player ID
            response: The availability response ('yes', 'no', 'maybe', 'no_response')

        Returns:
            ServiceResult with update confirmation
        """
        valid_responses = {'yes', 'no', 'maybe', 'no_response'}
        if response not in valid_responses:
            return ServiceResult.fail(
                f"Invalid response. Must be one of: {valid_responses}",
                "INVALID_RESPONSE"
            )

        match = self.session.query(Match).get(match_id)
        if not match:
            return ServiceResult.fail("Match not found", "MATCH_NOT_FOUND")

        player = self.session.query(Player).get(player_id)
        if not player:
            return ServiceResult.fail("Player not found", "PLAYER_NOT_FOUND")

        # Get or create availability record
        availability = self.session.query(Availability).filter_by(
            match_id=match_id,
            player_id=player_id
        ).first()

        if availability:
            availability.response = response
        else:
            availability = Availability(
                match_id=match_id,
                player_id=player_id,
                response=response
            )
            self.session.add(availability)

        self.session.commit()

        return ServiceResult.ok({
            "match_id": match_id,
            "player_id": player_id,
            "availability": response
        })

    def _build_match_data(self, match: Match) -> Dict[str, Any]:
        """Build match data dictionary."""
        return {
            "id": match.id,
            "date": match.date.isoformat() if match.date else None,
            "time": match.time.isoformat() if match.time else None,
            "home_team": {
                "id": match.home_team_id,
                "name": match.home_team.name if match.home_team else None,
                "score": match.home_team_score
            },
            "away_team": {
                "id": match.away_team_id,
                "name": match.away_team.name if match.away_team else None,
                "score": match.away_team_score
            },
            "location": getattr(match, 'location', None),
            "status": getattr(match, 'status', None)
        }

    def _get_match_events(self, match_id: int) -> List[Dict[str, Any]]:
        """Get events for a match."""
        from app.models import PlayerEvent

        events = self.session.query(PlayerEvent).filter_by(
            match_id=match_id
        ).order_by(PlayerEvent.minute).all()

        return [
            {
                "id": e.id,
                "minute": e.minute,
                "event_type": e.event_type.value if hasattr(e.event_type, 'value') else e.event_type,
                "player_id": e.player_id,
                "player_name": e.player.name if e.player else None
            }
            for e in events
        ]

    def _get_team_availability(self, match_id: int, team_id: int) -> Dict[str, int]:
        """Get availability summary for a team."""
        from app.models import player_teams

        # Get all players on the team
        player_ids = [
            pt.player_id for pt in
            self.session.query(player_teams).filter_by(team_id=team_id).all()
        ]

        if not player_ids:
            return {"yes": 0, "no": 0, "maybe": 0, "no_response": 0}

        availabilities = self.session.query(Availability).filter(
            Availability.match_id == match_id,
            Availability.player_id.in_(player_ids)
        ).all()

        summary = {"yes": 0, "no": 0, "maybe": 0, "no_response": 0}
        responded_ids = set()

        for av in availabilities:
            if av.response in summary:
                summary[av.response] += 1
            responded_ids.add(av.player_id)

        # Count players who haven't responded
        summary["no_response"] += len(player_ids) - len(responded_ids)

        return summary

    def _get_player_availability(self, match_id: int, player_id: int) -> Optional[str]:
        """Get availability for a specific player."""
        availability = self.session.query(Availability).filter_by(
            match_id=match_id,
            player_id=player_id
        ).first()

        return availability.response if availability else None
