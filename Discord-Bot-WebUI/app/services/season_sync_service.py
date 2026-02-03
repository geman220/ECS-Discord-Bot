# app/services/season_sync_service.py

"""
Season Sync Service

This module provides business logic for ensuring players are assigned to
the correct current season leagues. It solves the problem of players being
stuck in old season leagues (e.g., having primary_league_id pointing to
"2024 Fall Classic" instead of "2026 Spring Classic").

Key features:
- Dynamic lookup of current season leagues by name (instead of hardcoded IDs)
- Finding players with stale/old season league assignments
- Syncing players to current season leagues
- Getting current league mapping for use in activation/approval flows
"""

import logging
from typing import Dict, List, Optional

from flask import g
from sqlalchemy.orm import Session

from app.core import db
from app.models import League, Season, Player

logger = logging.getLogger(__name__)


class SeasonSyncService:
    """
    Service for managing player-to-season synchronization.

    This service provides dynamic league lookup based on the current season,
    replacing hardcoded league IDs that caused players to be assigned to
    old season leagues.
    """

    @staticmethod
    def get_current_league_by_name(
        session: Session,
        league_name: str,
        league_type: str = 'Pub League'
    ) -> Optional[League]:
        """
        Get the current season's league by name.

        This replaces hardcoded mappings like:
            {'Classic': 11, 'Premier': 10}

        With dynamic lookups:
            get_current_league_by_name(session, 'Classic') -> League(id=25)

        Args:
            session: Database session to use for query
            league_name: Name of the league (e.g., 'Classic', 'Premier', 'ECS FC')
            league_type: Type of season (default: 'Pub League')

        Returns:
            League object for the current season, or None if not found

        Example:
            >>> league = SeasonSyncService.get_current_league_by_name(db.session, 'Classic')
            >>> league.id  # Returns current season's Classic league ID (e.g., 25)
        """
        return session.query(League).join(Season).filter(
            League.name == league_name,
            Season.is_current == True,
            Season.league_type == league_type
        ).first()

    @staticmethod
    def get_current_league_mapping(
        session: Session,
        league_type: str = 'Pub League'
    ) -> Dict[str, int]:
        """
        Get a dynamic mapping of league names to current season league IDs.

        This replaces hardcoded constants like:
            DIVISION_LEAGUE_IDS = {'Classic': 11, 'Premier': 10}

        With dynamic mappings:
            {'Classic': 25, 'Premier': 24}  # Current season IDs

        Args:
            session: Database session to use for query
            league_type: Type of season (default: 'Pub League')

        Returns:
            Dictionary mapping league names to their current season IDs

        Example:
            >>> mapping = SeasonSyncService.get_current_league_mapping(db.session)
            >>> mapping  # {'Classic': 25, 'Premier': 24}
        """
        leagues = session.query(League).join(Season).filter(
            Season.is_current == True,
            Season.league_type == league_type
        ).all()
        return {league.name: league.id for league in leagues}

    @staticmethod
    def get_current_league_id_for_division(
        session: Session,
        division: str,
        league_type: str = 'Pub League'
    ) -> Optional[int]:
        """
        Convenience method to get just the league ID for a division name.

        Args:
            session: Database session to use for query
            division: Division name ('Classic' or 'Premier')
            league_type: Type of season (default: 'Pub League')

        Returns:
            The current season's league ID, or None if not found
        """
        league = SeasonSyncService.get_current_league_by_name(session, division, league_type)
        return league.id if league else None

    @staticmethod
    def sync_player_to_current_season(session: Session, player: Player) -> bool:
        """
        Ensure a player's league assignment points to the current season.

        If the player is assigned to an old season league (e.g., "2024 Fall Classic"),
        this method updates them to the current season's equivalent league
        (e.g., "2026 Spring Classic").

        Args:
            session: Database session to use for query
            player: Player object to sync

        Returns:
            True if player was updated, False if no update needed

        Example:
            >>> player.primary_league_id  # 11 (old "2024 Fall Classic")
            >>> synced = SeasonSyncService.sync_player_to_current_season(session, player)
            >>> synced  # True
            >>> player.primary_league_id  # 25 (current "2026 Spring Classic")
        """
        if not player.primary_league_id:
            return False

        # Get the player's current league
        league = session.query(League).get(player.primary_league_id)
        if not league:
            return False

        # Check if the league is already in the current season
        if league.season and league.season.is_current:
            return False  # Already in current season, no update needed

        # Get the league type from the season
        league_type = league.season.league_type if league.season else 'Pub League'

        # Find the equivalent league in the current season
        current_league = SeasonSyncService.get_current_league_by_name(
            session, league.name, league_type
        )

        if current_league:
            old_league_id = player.primary_league_id
            player.primary_league_id = current_league.id
            player.league_id = current_league.id
            logger.info(
                f"Synced player {player.id} ({player.name}) from old league {old_league_id} "
                f"to current season league {current_league.id} ({current_league.name})"
            )
            return True

        logger.warning(
            f"Could not find current season equivalent for league '{league.name}' "
            f"(type: {league_type}) to sync player {player.id}"
        )
        return False

    @staticmethod
    def find_stale_players(
        session: Session,
        league_type: str = 'Pub League'
    ) -> List[Player]:
        """
        Find active players who are assigned to non-current season leagues.

        These are "orphaned" players whose primary_league_id points to an old
        season (e.g., 2024 Fall) instead of the current season (e.g., 2026 Spring).

        Args:
            session: Database session to use for query
            league_type: Filter by league type (default: 'Pub League')

        Returns:
            List of Player objects with stale league assignments

        Example:
            >>> stale_players = SeasonSyncService.find_stale_players(session)
            >>> len(stale_players)  # 28 players in old season leagues
        """
        return session.query(Player).join(
            League, Player.primary_league_id == League.id
        ).join(Season).filter(
            Player.is_current_player == True,
            Season.is_current == False,
            Season.league_type == league_type
        ).all()

    @staticmethod
    def find_all_stale_players(session: Session) -> List[Player]:
        """
        Find all active players with stale league assignments across all league types.

        Args:
            session: Database session to use for query

        Returns:
            List of Player objects with stale league assignments
        """
        return session.query(Player).join(
            League, Player.primary_league_id == League.id
        ).join(Season).filter(
            Player.is_current_player == True,
            Season.is_current == False
        ).all()

    @staticmethod
    def bulk_sync_stale_players(
        session: Session,
        league_type: str = 'Pub League'
    ) -> Dict[str, int]:
        """
        Find and sync all stale players to current season leagues.

        This is a batch operation to fix all players with old season assignments.

        Args:
            session: Database session to use for query
            league_type: Filter by league type (default: 'Pub League')

        Returns:
            Dictionary with counts: {'found': N, 'fixed': M, 'failed': P}
        """
        stale_players = SeasonSyncService.find_stale_players(session, league_type)

        result = {
            'found': len(stale_players),
            'fixed': 0,
            'failed': 0
        }

        for player in stale_players:
            try:
                if SeasonSyncService.sync_player_to_current_season(session, player):
                    result['fixed'] += 1
            except Exception as e:
                result['failed'] += 1
                logger.error(f"Failed to sync player {player.id}: {e}")

        logger.info(
            f"Bulk sync complete: found {result['found']} stale players, "
            f"fixed {result['fixed']}, failed {result['failed']}"
        )

        return result

    @staticmethod
    def get_league_for_role(
        session: Session,
        role_name: str
    ) -> Optional[League]:
        """
        Get the current season league based on a Flask role name.

        This maps role names to league names:
            'pl-classic' -> 'Classic'
            'pl-premier' -> 'Premier'
            'pl-ecs-fc' -> 'ECS FC'

        Args:
            session: Database session to use for query
            role_name: Flask role name (e.g., 'pl-classic')

        Returns:
            Current season League object, or None if not found
        """
        role_to_league = {
            'pl-classic': ('Classic', 'Pub League'),
            'pl-premier': ('Premier', 'Pub League'),
            'pl-ecs-fc': ('ECS FC', 'ECS FC'),
            'classic': ('Classic', 'Pub League'),
            'premier': ('Premier', 'Pub League'),
            'ecs-fc': ('ECS FC', 'ECS FC'),
        }

        mapping = role_to_league.get(role_name.lower())
        if mapping:
            league_name, league_type = mapping
            return SeasonSyncService.get_current_league_by_name(session, league_name, league_type)

        return None

    @staticmethod
    def get_session() -> Session:
        """
        Get the appropriate database session.

        Prefers g.db_session if available (request context),
        falls back to db.session.

        Returns:
            SQLAlchemy Session object
        """
        return getattr(g, 'db_session', db.session)
