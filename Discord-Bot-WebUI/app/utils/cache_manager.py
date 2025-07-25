"""
Cache Manager for Frequently Accessed Reference Data

This module provides efficient caching mechanisms for data that is frequently
accessed across celery tasks but changes infrequently (seasons, leagues, etc.).
"""

import json
import logging
from typing import Dict, List, Optional, Any, Callable
from functools import wraps
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.utils.safe_redis import get_safe_redis
from app.models import Season, League, Team
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_TTL = {
    'current_season': 3600,  # 1 hour - changes rarely
    'leagues': 7200,         # 2 hours - static reference data
    'league_teams': 1800,    # 30 minutes - can change during season
    'player_roles': 300,     # 5 minutes - can change frequently
    'discord_channels': 600, # 10 minutes - moderate change frequency
}

@dataclass
class CacheKey:
    """Standard cache key patterns"""
    CURRENT_SEASON = "ref:current_season"
    LEAGUES = "ref:leagues"
    LEAGUE_TEAMS = "ref:league_teams:{league_id}"
    CURRENT_SEASON_TEAMS = "ref:current_season_teams"
    PLAYER_DISCORD_ROLES = "roles:player:{player_id}"
    DISCORD_GUILD_CHANNELS = "discord:channels:{guild_id}"


class CacheManager:
    """Manages Redis caching for frequently accessed reference data"""
    
    def __init__(self, redis_client=None):
        self.redis = redis_client or get_safe_redis()
        
    def _serialize(self, data: Any) -> str:
        """Serialize data for Redis storage"""
        try:
            return json.dumps(data, default=str)
        except Exception as e:
            logger.error(f"Error serializing data: {e}")
            return "{}"
    
    def _deserialize(self, data: str) -> Any:
        """Deserialize data from Redis"""
        try:
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Error deserializing data: {e}")
            return None
    
    def get(self, key: str) -> Optional[Any]:
        """Get data from cache"""
        try:
            cached_data = self.redis.get(key)
            return self._deserialize(cached_data) if cached_data else None
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            return None
    
    def set(self, key: str, data: Any, ttl: int = 3600) -> bool:
        """Set data in cache with TTL"""
        try:
            serialized = self._serialize(data)
            return self.redis.setex(key, ttl, serialized)
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete cache key"""
        try:
            return bool(self.redis.delete(key))
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching pattern"""
        try:
            keys = self.redis.keys(pattern)
            if keys:
                return self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Error invalidating pattern {pattern}: {e}")
            return 0


class ReferenceDataCache(CacheManager):
    """Specialized cache for reference data used across tasks"""
    
    def get_current_season(self, session: Session) -> Optional[Dict]:
        """Get current season with caching"""
        cached = self.get(CacheKey.CURRENT_SEASON)
        if cached:
            return cached
        
        # Load from database
        season = session.query(Season).filter_by(is_current=True).first()
        if season:
            data = {
                'id': season.id,
                'name': season.name,
                'is_current': season.is_current,
                'start_date': season.start_date.isoformat() if season.start_date else None,
                'end_date': season.end_date.isoformat() if season.end_date else None
            }
            self.set(CacheKey.CURRENT_SEASON, data, CACHE_TTL['current_season'])
            return data
        return None
    
    def get_leagues(self, session: Session) -> List[Dict]:
        """Get all leagues with caching"""
        cached = self.get(CacheKey.LEAGUES)
        if cached:
            return cached
        
        # Load from database
        leagues = session.query(League).all()
        data = [
            {
                'id': league.id,
                'name': league.name,
                'abbreviation': getattr(league, 'abbreviation', ''),
                'is_active': getattr(league, 'is_active', True)
            }
            for league in leagues
        ]
        self.set(CacheKey.LEAGUES, data, CACHE_TTL['leagues'])
        return data
    
    def get_current_season_teams(self, session: Session, league_id: Optional[int] = None) -> List[Dict]:
        """Get teams for current season with caching"""
        cache_key = CacheKey.CURRENT_SEASON_TEAMS
        if league_id:
            cache_key = f"{cache_key}:league:{league_id}"
            
        cached = self.get(cache_key)
        if cached:
            return cached
        
        # Load current season
        current_season = self.get_current_season(session)
        if not current_season:
            return []
        
        # Query teams for current season
        query = session.query(Team).join(
            'leagues'  # Assuming teams have league relationship
        ).filter(
            # Add season filter if PlayerTeamSeason table exists
            # For now, get all teams
        )
        
        if league_id:
            query = query.filter(Team.league_id == league_id)
            
        teams = query.all()
        data = [
            {
                'id': team.id,
                'name': team.name,
                'league_id': team.league_id,
                'league_name': team.league.name if team.league else None,
                'is_active': getattr(team, 'is_active', True)
            }
            for team in teams
        ]
        
        self.set(cache_key, data, CACHE_TTL['league_teams'])
        return data
    
    def invalidate_season_cache(self):
        """Invalidate all season-related cache"""
        patterns = [
            "ref:current_season*",
            "ref:current_season_teams*",
            "ref:league_teams:*"
        ]
        for pattern in patterns:
            self.invalidate_pattern(pattern)


def cached_query(cache_key_template: str, ttl: int = 3600):
    """Decorator for caching database query results"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract session from args (assumes it's first argument)
            session = args[0] if args else None
            if not isinstance(session, Session):
                # If no session, execute function directly
                return func(*args, **kwargs)
            
            # Build cache key from template and arguments
            cache_key = cache_key_template.format(*args[1:], **kwargs)
            
            # Try to get from cache
            cache_manager = CacheManager()
            cached_result = cache_manager.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for key: {cache_key}")
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache_manager.set(cache_key, result, ttl)
            logger.debug(f"Cache miss - stored result for key: {cache_key}")
            return result
        return wrapper
    return decorator


# Global cache instance
reference_cache = ReferenceDataCache()


def warm_cache(session: Session):
    """Warm up commonly used cache entries"""
    try:
        logger.info("Warming up reference data cache...")
        
        # Warm current season cache
        reference_cache.get_current_season(session)
        
        # Warm leagues cache
        reference_cache.get_leagues(session)
        
        # Warm current season teams cache
        reference_cache.get_current_season_teams(session)
        
        logger.info("Reference data cache warmed successfully")
        
    except Exception as e:
        logger.error(f"Error warming cache: {e}", exc_info=True)


# Utility functions for common cache patterns
def get_or_cache(session: Session, cache_key: str, query_func: Callable, ttl: int = 3600):
    """Generic get-or-cache pattern"""
    cache_manager = CacheManager()
    
    # Try cache first
    cached = cache_manager.get(cache_key)
    if cached is not None:
        return cached
    
    # Execute query and cache
    result = query_func(session)
    cache_manager.set(cache_key, result, ttl)
    return result


def clear_player_cache(player_id: int):
    """Clear all cache entries for a specific player"""
    cache_manager = CacheManager()
    patterns = [
        f"roles:player:{player_id}*",
        f"player:{player_id}:*"
    ]
    for pattern in patterns:
        cache_manager.invalidate_pattern(pattern)