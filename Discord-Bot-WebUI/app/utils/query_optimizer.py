"""
Query Optimization Utilities

This module provides optimized query patterns and utilities to reduce memory usage
and improve performance across celery tasks. Implements batch processing, efficient
loading strategies, and memory-conscious query patterns.
"""

import logging
from typing import Dict, List, Optional, Any, Iterator, Tuple, Callable
from contextlib import contextmanager
from dataclasses import dataclass
import math

from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import text, and_, or_, func
from sqlalchemy.orm.query import Query

from app.models import Player, Team, League, Season, User, Availability, Match
from app.utils.cache_manager import reference_cache, get_or_cache, CacheKey

logger = logging.getLogger(__name__)

@dataclass
class BatchConfig:
    """Configuration for batch processing"""
    batch_size: int = 100
    enable_expunge: bool = True  # Clear session between batches
    enable_logging: bool = True  # Log batch progress
    memory_threshold_mb: int = 500  # Memory warning threshold


class QueryOptimizer:
    """Provides optimized query patterns for common operations"""
    
    @staticmethod
    def get_current_season_id(session: Session) -> Optional[int]:
        """Get current season ID with caching"""
        season_data = reference_cache.get_current_season(session)
        return season_data['id'] if season_data else None
    
    @staticmethod
    def batch_process_players_with_discord_ids(
        session: Session,
        batch_size: int = 100,
        filter_func: Optional[Callable] = None
    ) -> Iterator[List[Dict]]:
        """
        Memory-efficient batch processing of players with Discord IDs.
        
        Yields batches of player data instead of loading all into memory.
        Uses cursor-based pagination to avoid offset performance issues.
        """
        logger.info("Starting batch processing of players with Discord IDs")
        
        # Get total count for progress logging
        base_query = session.query(Player).filter(Player.discord_id.isnot(None))
        if filter_func:
            base_query = filter_func(base_query)
        
        total_count = base_query.count()
        batch_count = math.ceil(total_count / batch_size)
        logger.info(f"Processing {total_count} players in {batch_count} batches of {batch_size}")
        
        # Use cursor-based pagination for better performance
        last_id = 0
        processed = 0
        
        while True:
            # Query next batch using cursor
            query = session.query(Player).filter(
                and_(
                    Player.discord_id.isnot(None),
                    Player.id > last_id
                )
            ).options(
                selectinload(Player.user).selectinload(User.roles)
            ).order_by(Player.id).limit(batch_size)
            
            if filter_func:
                query = filter_func(query)
            
            batch_players = query.all()
            
            if not batch_players:
                break
            
            # Process batch into lightweight data structures
            batch_data = []
            for player in batch_players:
                try:
                    # Get current season teams efficiently
                    teams = QueryOptimizer.get_player_current_season_teams(session, player)
                    
                    # Extract user roles safely
                    user_roles = []
                    if player.user and player.user.roles:
                        user_roles = [role.name for role in player.user.roles]
                    
                    batch_data.append({
                        'id': player.id,
                        'discord_id': player.discord_id,
                        'name': player.name,
                        'teams': teams,
                        'user_roles': user_roles,
                        'current_roles': player.discord_roles or []
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing player {player.id}: {e}", exc_info=True)
                    continue
            
            # Update cursor and counters
            last_id = batch_players[-1].id
            processed += len(batch_data)
            
            logger.info(f"Processed batch {math.ceil(processed/batch_size)}/{batch_count} ({processed}/{total_count} players)")
            
            # Clear session to free memory
            session.expunge_all()
            
            yield batch_data
    
    @staticmethod
    def get_player_current_season_teams(session: Session, player: Player) -> List[Dict]:
        """
        Get current season teams for a player with optimized caching.
        
        Uses batch loading and caching to avoid N+1 queries.
        """
        cache_key = f"player_teams:current:{player.id}"
        
        def load_teams(session):
            current_season_id = QueryOptimizer.get_current_season_id(session)
            if not current_season_id:
                return []
            
            # Use efficient query with current season filter
            teams = session.query(Team).join(
                'player_team_seasons'  # Assuming this relationship exists
            ).filter(
                and_(
                    Player.id == player.id,
                    Season.id == current_season_id
                )
            ).options(
                joinedload(Team.league)
            ).all()
            
            return [
                {
                    'id': team.id,
                    'name': team.name,
                    'league_name': team.league.name if team.league else None,
                    'league_id': team.league_id
                }
                for team in teams
            ]
        
        return get_or_cache(session, cache_key, load_teams, ttl=300)
    
    @staticmethod
    def bulk_get_player_teams_mapping(
        session: Session, 
        player_ids: List[int]
    ) -> Dict[int, List[Dict]]:
        """
        Efficiently get team mappings for multiple players in a single query.
        
        Replaces N individual queries with one batch query + post-processing.
        """
        if not player_ids:
            return {}
        
        current_season_id = QueryOptimizer.get_current_season_id(session)
        if not current_season_id:
            return {player_id: [] for player_id in player_ids}
        
        # Single query to get all player-team relationships
        results = session.query(
            Player.id.label('player_id'),
            Team.id.label('team_id'),
            Team.name.label('team_name'),
            League.id.label('league_id'),
            League.name.label('league_name')
        ).join(
            # Assuming PlayerTeamSeason table exists
            'player_team_seasons'
        ).join(
            Team, Team.id == PlayerTeamSeason.team_id
        ).outerjoin(
            League, League.id == Team.league_id
        ).filter(
            and_(
                Player.id.in_(player_ids),
                PlayerTeamSeason.season_id == current_season_id
            )
        ).all()
        
        # Group results by player_id
        player_teams = {player_id: [] for player_id in player_ids}
        for result in results:
            player_teams[result.player_id].append({
                'id': result.team_id,
                'name': result.team_name,
                'league_id': result.league_id,
                'league_name': result.league_name
            })
        
        return player_teams
    
    @staticmethod
    def get_players_by_discord_ids_optimized(
        session: Session,
        discord_ids: List[str],
        batch_size: int = 50
    ) -> List[Dict]:
        """
        Optimized loading of players by Discord IDs with batch processing
        and efficient relationship loading.
        """
        if not discord_ids:
            return []
        
        all_players_data = []
        
        # Process in batches to avoid memory issues
        for i in range(0, len(discord_ids), batch_size):
            batch_ids = discord_ids[i:i + batch_size]
            
            # Load players with optimized eager loading
            players = session.query(Player).filter(
                Player.discord_id.in_(batch_ids)
            ).options(
                selectinload(Player.user).selectinload(User.roles)
            ).all()
            
            # Get batch team mappings efficiently
            player_ids = [p.id for p in players]
            teams_mapping = QueryOptimizer.bulk_get_player_teams_mapping(session, player_ids)
            
            # Build result data
            for player in players:
                user_roles = []
                if player.user and player.user.roles:
                    user_roles = [role.name for role in player.user.roles]
                
                all_players_data.append({
                    'id': player.id,
                    'discord_id': player.discord_id,
                    'name': player.name,
                    'teams': teams_mapping.get(player.id, []),
                    'user_roles': user_roles,
                    'current_roles': player.discord_roles or []
                })
            
            # Clear session between batches
            session.expunge_all()
        
        logger.info(f"Loaded {len(all_players_data)} players from {len(discord_ids)} Discord IDs")
        return all_players_data


class BulkOperationHelper:
    """Helper for efficient bulk database operations"""
    
    @staticmethod
    def bulk_delete_with_conditions(
        session: Session,
        model_class,
        conditions: List,
        batch_size: int = 1000,
        dry_run: bool = False
    ) -> int:
        """
        Perform bulk delete operation with batching to avoid memory issues.
        
        Uses SQL DELETE instead of loading records into memory.
        """
        # Build the delete query
        delete_query = session.query(model_class)
        for condition in conditions:
            delete_query = delete_query.filter(condition)
        
        if dry_run:
            count = delete_query.count()
            logger.info(f"DRY RUN: Would delete {count} records from {model_class.__tablename__}")
            return count
        
        # For large deletes, process in batches
        total_deleted = 0
        
        while True:
            # Delete in batches using subquery
            subquery = delete_query.limit(batch_size).subquery()
            batch_delete = session.query(model_class).filter(
                model_class.id.in_(
                    session.query(subquery.c.id)
                )
            )
            
            deleted_count = batch_delete.delete(synchronize_session=False)
            if deleted_count == 0:
                break
            
            total_deleted += deleted_count
            session.commit()
            
            logger.info(f"Deleted batch of {deleted_count} records (total: {total_deleted})")
        
        return total_deleted
    
    @staticmethod
    def bulk_update_discord_roles(
        session: Session,
        role_updates: List[Dict],
        batch_size: int = 100
    ) -> int:
        """
        Efficiently update Discord roles for multiple players.
        
        Uses bulk update operations instead of individual record updates.
        """
        if not role_updates:
            return 0
        
        updated_count = 0
        
        # Process in batches
        for i in range(0, len(role_updates), batch_size):
            batch = role_updates[i:i + batch_size]
            
            # Prepare bulk update data
            update_mappings = []
            for update in batch:
                update_mappings.append({
                    'id': update['player_id'],
                    'discord_roles': update['current_roles'],
                    'discord_last_verified': update.get('last_verified'),
                    'discord_needs_update': False,
                    'sync_status': update.get('sync_status', 'success')
                })
            
            # Execute bulk update
            result = session.bulk_update_mappings(Player, update_mappings)
            session.commit()
            
            updated_count += len(batch)
            logger.info(f"Bulk updated {len(batch)} player Discord roles")
        
        return updated_count


@contextmanager
def memory_efficient_session(session: Session, batch_config: BatchConfig = None):
    """
    Context manager for memory-efficient database operations.
    
    Automatically manages session state and provides memory monitoring.
    """
    config = batch_config or BatchConfig()
    
    try:
        yield session
    finally:
        if config.enable_expunge:
            # Clear all objects from session to free memory
            session.expunge_all()
        
        # Log memory usage if enabled
        if config.enable_logging:
            try:
                import psutil
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                if memory_mb > config.memory_threshold_mb:
                    logger.warning(f"High memory usage detected: {memory_mb:.1f}MB")
                else:
                    logger.debug(f"Memory usage: {memory_mb:.1f}MB")
            except ImportError:
                pass  # psutil not available


# Convenience functions for common patterns
def efficient_player_discord_batch(session: Session, discord_ids: List[str]) -> List[Dict]:
    """Convenience function for efficient Discord player batch processing"""
    return QueryOptimizer.get_players_by_discord_ids_optimized(session, discord_ids)


def stream_players_with_discord_ids(session: Session, batch_size: int = 100) -> Iterator[List[Dict]]:
    """Convenience function for streaming Discord players"""
    yield from QueryOptimizer.batch_process_players_with_discord_ids(session, batch_size)