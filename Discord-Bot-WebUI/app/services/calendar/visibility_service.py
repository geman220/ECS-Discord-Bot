# app/services/calendar/visibility_service.py

"""
Calendar Visibility Service

Handles role-based filtering of calendar events.
Determines what matches and events each user can see based on their roles and team affiliations.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models import User, Player, Match, Team, Season, LeagueEvent

logger = logging.getLogger(__name__)


# Role constants
ADMIN_ROLES = {'Global Admin', 'Pub League Admin'}
COACH_ROLES = {'Pub League Coach', 'ECS FC Coach'}
REF_ROLES = {'Pub League Ref'}


class VisibilityService:
    """
    Service for determining calendar event visibility based on user roles.

    This service centralizes all visibility logic to ensure consistent
    access control across the calendar system.
    """

    def __init__(self, session: Session):
        """
        Initialize the visibility service.

        Args:
            session: SQLAlchemy database session
        """
        self.session = session

    def get_user_roles(self, user: User) -> Set[str]:
        """
        Get the set of role names for a user.

        Args:
            user: The user to get roles for

        Returns:
            Set of role name strings
        """
        if not user or not user.roles:
            return set()

        # Handle both Role objects and string role names
        # (UserAuthData stores roles as strings, User model stores as Role objects)
        roles = set()
        for role in user.roles:
            if isinstance(role, str):
                roles.add(role)
            else:
                roles.add(role.name)
        return roles

    def is_admin(self, user: User) -> bool:
        """
        Check if user has admin privileges.

        Args:
            user: The user to check

        Returns:
            True if user is an admin
        """
        user_roles = self.get_user_roles(user)
        return bool(user_roles & ADMIN_ROLES)

    def is_coach(self, user: User) -> bool:
        """
        Check if user has coach privileges.

        Args:
            user: The user to check

        Returns:
            True if user is a coach
        """
        user_roles = self.get_user_roles(user)
        return bool(user_roles & COACH_ROLES)

    def is_referee(self, user: User) -> bool:
        """
        Check if user is a referee.

        Args:
            user: The user to check

        Returns:
            True if user is a referee
        """
        user_roles = self.get_user_roles(user)
        return bool(user_roles & REF_ROLES)

    def get_user_player(self, user: User) -> Optional[Player]:
        """
        Get the Player record associated with a user.

        Args:
            user: The user to get the player for

        Returns:
            Player instance or None
        """
        if hasattr(user, 'player') and user.player:
            return user.player

        # Query if not already loaded
        return self.session.query(Player).filter_by(user_id=user.id).first()

    def get_user_team_ids(self, user: User) -> List[int]:
        """
        Get list of team IDs the user is associated with.

        Args:
            user: The user to get teams for

        Returns:
            List of team IDs
        """
        player = self.get_user_player(user)
        if not player or not player.teams:
            return []
        return [team.id for team in player.teams]

    def get_user_league_ids(self, user: User) -> List[int]:
        """
        Get list of league IDs the user is associated with via their teams.

        Args:
            user: The user to get leagues for

        Returns:
            List of unique league IDs
        """
        player = self.get_user_player(user)
        if not player or not player.teams:
            return []
        return list(set(
            team.league_id for team in player.teams
            if team.league_id is not None
        ))

    def can_view_all_matches(self, user: User) -> bool:
        """
        Check if user can view all matches (not just their team's).

        Args:
            user: The user to check

        Returns:
            True if user can view all matches
        """
        return self.is_admin(user)

    def can_edit_events(self, user: User) -> bool:
        """
        Check if user can create/edit/delete league events.

        Args:
            user: The user to check

        Returns:
            True if user has event management privileges
        """
        return self.is_admin(user)

    def can_assign_refs(self, user: User) -> bool:
        """
        Check if user can assign referees to matches.
        Only admins can assign refs (not coaches).

        Args:
            user: The user to check

        Returns:
            True if user can assign referees
        """
        return self.is_admin(user)

    def get_visible_match_query(
        self,
        user: User,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ):
        """
        Get a query for matches visible to the user.

        Args:
            user: The user to filter for
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            SQLAlchemy query for visible matches
        """
        query = self.session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.ref)
        )

        # Apply date filters if provided
        if start_date:
            query = query.filter(Match.date >= start_date.date())
        if end_date:
            query = query.filter(Match.date <= end_date.date())

        # Admins see all matches
        if self.can_view_all_matches(user):
            return query.order_by(Match.date, Match.time)

        # Get user's teams
        team_ids = self.get_user_team_ids(user)

        # Check if user is a referee
        player = self.get_user_player(user)
        is_ref = player and player.is_ref if player else False

        if team_ids and is_ref:
            # User has teams AND is a ref - see team matches + assigned matches
            query = query.filter(
                (Match.home_team_id.in_(team_ids)) |
                (Match.away_team_id.in_(team_ids)) |
                (Match.ref_id == player.id)
            )
        elif team_ids:
            # User has teams but is not a ref - see only team matches
            query = query.filter(
                (Match.home_team_id.in_(team_ids)) |
                (Match.away_team_id.in_(team_ids))
            )
        elif is_ref:
            # User is only a ref (no teams) - see only assigned matches
            query = query.filter(Match.ref_id == player.id)
        else:
            # User has no teams and is not a ref - return empty query
            query = query.filter(False)  # No results

        return query.order_by(Match.date, Match.time)

    def get_visible_matches(
        self,
        user: User,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Match]:
        """
        Get list of matches visible to the user.

        Args:
            user: The user to filter for
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            List of visible Match objects
        """
        return self.get_visible_match_query(user, start_date, end_date).all()

    def get_visible_league_events_query(
        self,
        user: User,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ):
        """
        Get a query for league events visible to the user.

        All authenticated users can see league-wide events.
        Team-specific events are visible to team members only.

        Args:
            user: The user to filter for
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            SQLAlchemy query for visible league events
        """
        query = self.session.query(LeagueEvent).filter(
            LeagueEvent.is_active == True
        )

        # Apply date filters if provided
        if start_date:
            query = query.filter(LeagueEvent.start_datetime >= start_date)
        if end_date:
            query = query.filter(LeagueEvent.start_datetime <= end_date)

        # Get user's leagues
        league_ids = self.get_user_league_ids(user)

        # All users see league-wide events (league_id IS NULL)
        # Plus events for their specific leagues
        if league_ids:
            query = query.filter(
                (LeagueEvent.league_id.is_(None)) |
                (LeagueEvent.league_id.in_(league_ids))
            )
        else:
            # User not in any league - only see league-wide events
            query = query.filter(LeagueEvent.league_id.is_(None))

        return query.order_by(LeagueEvent.start_datetime)

    def get_visible_league_events(
        self,
        user: User,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[LeagueEvent]:
        """
        Get list of league events visible to the user.

        Args:
            user: The user to filter for
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            List of visible LeagueEvent objects
        """
        return self.get_visible_league_events_query(user, start_date, end_date).all()

    def get_all_visible_events(
        self,
        user: User,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Tuple[List[Match], List[LeagueEvent]]:
        """
        Get all visible events (matches and league events) for a user.

        Args:
            user: The user to filter for
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Tuple of (matches, league_events)
        """
        matches = self.get_visible_matches(user, start_date, end_date)
        events = self.get_visible_league_events(user, start_date, end_date)
        return matches, events

    def can_view_match(self, user: User, match: Match) -> bool:
        """
        Check if a user can view a specific match.

        Args:
            user: The user to check
            match: The match to check visibility for

        Returns:
            True if user can view the match
        """
        if self.can_view_all_matches(user):
            return True

        team_ids = self.get_user_team_ids(user)

        # Check if match involves user's team
        if match.home_team_id in team_ids or match.away_team_id in team_ids:
            return True

        # Check if user is the assigned referee
        player = self.get_user_player(user)
        if player and match.ref_id == player.id:
            return True

        return False

    def can_view_league_event(self, user: User, event: LeagueEvent) -> bool:
        """
        Check if a user can view a specific league event.

        Args:
            user: The user to check
            event: The event to check visibility for

        Returns:
            True if user can view the event
        """
        if not event.is_active:
            return self.is_admin(user)

        # League-wide events are visible to all
        if event.league_id is None:
            return True

        # Check if user is in the event's league
        league_ids = self.get_user_league_ids(user)
        return event.league_id in league_ids


def create_visibility_service(session: Session) -> VisibilityService:
    """
    Factory function to create a VisibilityService instance.

    Args:
        session: SQLAlchemy database session

    Returns:
        Configured VisibilityService instance
    """
    return VisibilityService(session)
