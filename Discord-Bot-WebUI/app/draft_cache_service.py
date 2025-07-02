# app/draft_cache_service.py

"""
Draft Cache Service

Provides Redis-based caching for draft system data to improve performance.
Caches player data, team information, and draft analytics with appropriate TTL.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import hashlib

try:
    import redis
    from app.redis_manager import get_redis_connection
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class DraftCacheService:
    """Service for caching draft system data using Redis."""
    
    # Cache TTL settings (in seconds)
    PLAYER_DATA_TTL = 300      # 5 minutes - player enhanced data
    DRAFT_ANALYTICS_TTL = 180  # 3 minutes - draft analytics  
    TEAM_DATA_TTL = 600        # 10 minutes - team information
    AVAILABILITY_TTL = 120     # 2 minutes - player availability
    
    @staticmethod
    def _get_cache_key(prefix: str, league_name: str, *args) -> str:
        """Generate a cache key with consistent formatting."""
        key_parts = [f"draft:{prefix}:{league_name}"]
        if args:
            # Create hash of additional arguments for consistent key length
            args_str = ":".join(str(arg) for arg in args)
            args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
            key_parts.append(args_hash)
        return ":".join(key_parts)
    
    @staticmethod
    def _serialize_data(data: Any) -> str:
        """Serialize data for Redis storage with datetime handling."""
        def datetime_handler(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        return json.dumps(data, default=datetime_handler, separators=(',', ':'))
    
    @staticmethod
    def _deserialize_data(data: str) -> Any:
        """Deserialize data from Redis storage."""
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to deserialize cached data: {e}")
            return None
    
    @staticmethod
    def get_enhanced_players_cache(league_name: str, player_type: str = 'all') -> Optional[List[Dict]]:
        """Get cached enhanced player data."""
        if not REDIS_AVAILABLE:
            return None
            
        try:
            redis_conn = get_redis_connection()
            cache_key = DraftCacheService._get_cache_key('players', league_name, player_type)
            
            cached_data = redis_conn.get(cache_key)
            if cached_data:
                logger.debug(f"Cache HIT for {cache_key}")
                return DraftCacheService._deserialize_data(cached_data)
            else:
                logger.debug(f"Cache MISS for {cache_key}")
                return None
                
        except Exception as e:
            logger.warning(f"Error getting cached player data: {e}")
            return None
    
    @staticmethod
    def set_enhanced_players_cache(league_name: str, player_type: str, players_data: List[Dict]) -> bool:
        """Cache enhanced player data."""
        if not REDIS_AVAILABLE or not players_data:
            return False
            
        try:
            redis_conn = get_redis_connection()
            cache_key = DraftCacheService._get_cache_key('players', league_name, player_type)
            
            serialized_data = DraftCacheService._serialize_data(players_data)
            success = redis_conn.setex(
                cache_key,
                DraftCacheService.PLAYER_DATA_TTL,
                serialized_data
            )
            
            if success:
                logger.debug(f"Cached {len(players_data)} players for {cache_key}")
            return bool(success)
            
        except Exception as e:
            logger.warning(f"Error caching player data: {e}")
            return False
    
    @staticmethod
    def get_draft_analytics_cache(league_name: str) -> Optional[Dict]:
        """Get cached draft analytics."""
        if not REDIS_AVAILABLE:
            return None
            
        try:
            redis_conn = get_redis_connection()
            cache_key = DraftCacheService._get_cache_key('analytics', league_name)
            
            cached_data = redis_conn.get(cache_key)
            if cached_data:
                logger.debug(f"Cache HIT for analytics: {league_name}")
                return DraftCacheService._deserialize_data(cached_data)
            else:
                logger.debug(f"Cache MISS for analytics: {league_name}")
                return None
                
        except Exception as e:
            logger.warning(f"Error getting cached analytics: {e}")
            return None
    
    @staticmethod
    def set_draft_analytics_cache(league_name: str, analytics_data: Dict) -> bool:
        """Cache draft analytics data."""
        if not REDIS_AVAILABLE or not analytics_data:
            return False
            
        try:
            redis_conn = get_redis_connection()
            cache_key = DraftCacheService._get_cache_key('analytics', league_name)
            
            serialized_data = DraftCacheService._serialize_data(analytics_data)
            success = redis_conn.setex(
                cache_key,
                DraftCacheService.DRAFT_ANALYTICS_TTL,
                serialized_data
            )
            
            if success:
                logger.debug(f"Cached analytics for {league_name}")
            return bool(success)
            
        except Exception as e:
            logger.warning(f"Error caching analytics: {e}")
            return False
    
    @staticmethod
    def get_team_data_cache(league_name: str) -> Optional[List[Dict]]:
        """Get cached team data."""
        if not REDIS_AVAILABLE:
            return None
            
        try:
            redis_conn = get_redis_connection()
            cache_key = DraftCacheService._get_cache_key('teams', league_name)
            
            cached_data = redis_conn.get(cache_key)
            if cached_data:
                logger.debug(f"Cache HIT for teams: {league_name}")
                return DraftCacheService._deserialize_data(cached_data)
            else:
                logger.debug(f"Cache MISS for teams: {league_name}")
                return None
                
        except Exception as e:
            logger.warning(f"Error getting cached team data: {e}")
            return None
    
    @staticmethod
    def set_team_data_cache(league_name: str, teams_data: List[Dict]) -> bool:
        """Cache team data."""
        if not REDIS_AVAILABLE or not teams_data:
            return False
            
        try:
            redis_conn = get_redis_connection()
            cache_key = DraftCacheService._get_cache_key('teams', league_name)
            
            serialized_data = DraftCacheService._serialize_data(teams_data)
            success = redis_conn.setex(
                cache_key,
                DraftCacheService.TEAM_DATA_TTL,
                serialized_data
            )
            
            if success:
                logger.debug(f"Cached {len(teams_data)} teams for {league_name}")
            return bool(success)
            
        except Exception as e:
            logger.warning(f"Error caching team data: {e}")
            return False
    
    @staticmethod
    def invalidate_league_cache(league_name: str) -> int:
        """Invalidate all cached data for a specific league."""
        if not REDIS_AVAILABLE:
            return 0
            
        try:
            redis_conn = get_redis_connection()
            
            # Find all keys for this league
            pattern = f"draft:*:{league_name}*"
            keys_to_delete = []
            
            for key in redis_conn.scan_iter(match=pattern):
                keys_to_delete.append(key)
            
            # Delete keys in batches
            deleted_count = 0
            if keys_to_delete:
                deleted_count = redis_conn.delete(*keys_to_delete)
                logger.info(f"Invalidated {deleted_count} cache keys for league {league_name}")
            
            return deleted_count
            
        except Exception as e:
            logger.warning(f"Error invalidating league cache: {e}")
            return 0
    
    @staticmethod
    def invalidate_player_cache(player_id: int) -> int:
        """Invalidate cache entries that might contain specific player data."""
        if not REDIS_AVAILABLE:
            return 0
            
        try:
            redis_conn = get_redis_connection()
            
            # Invalidate all player-related caches since player data is embedded
            pattern = "draft:players:*"
            keys_to_delete = []
            
            for key in redis_conn.scan_iter(match=pattern):
                keys_to_delete.append(key)
            
            # Also invalidate analytics since they include player counts
            analytics_pattern = "draft:analytics:*"
            for key in redis_conn.scan_iter(match=analytics_pattern):
                keys_to_delete.append(key)
            
            deleted_count = 0
            if keys_to_delete:
                deleted_count = redis_conn.delete(*keys_to_delete)
                logger.debug(f"Invalidated {deleted_count} cache keys for player {player_id}")
            
            return deleted_count
            
        except Exception as e:
            logger.warning(f"Error invalidating player cache: {e}")
            return 0
    
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        if not REDIS_AVAILABLE:
            return {'redis_available': False}
            
        try:
            redis_conn = get_redis_connection()
            
            # Count draft-related keys
            draft_keys = list(redis_conn.scan_iter(match="draft:*"))
            
            stats = {
                'redis_available': True,
                'total_draft_keys': len(draft_keys),
                'key_breakdown': {},
                'memory_usage': {}
            }
            
            # Break down by key type
            for key in draft_keys:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                key_type = key_str.split(':')[1] if ':' in key_str else 'unknown'
                stats['key_breakdown'][key_type] = stats['key_breakdown'].get(key_type, 0) + 1
                
                # Get TTL for each key
                try:
                    ttl = redis_conn.ttl(key)
                    if ttl > 0:
                        stats['memory_usage'][key_str] = {
                            'ttl_seconds': ttl,
                            'expires_at': (datetime.now() + timedelta(seconds=ttl)).isoformat()
                        }
                except:
                    pass
            
            return stats
            
        except Exception as e:
            logger.warning(f"Error getting cache stats: {e}")
            return {'redis_available': False, 'error': str(e)}
    
    @staticmethod
    def warm_cache_for_league(league_name: str) -> Dict[str, bool]:
        """Pre-warm cache for a league (call this during off-peak hours)."""
        # This method would be implemented to pre-load common queries
        # For now, return a placeholder
        return {
            'players_available': False,
            'players_drafted': False,
            'analytics': False,
            'teams': False
        }


# Cache decorator for draft service methods
def draft_cache(cache_type: str, ttl: int = 300):
    """Decorator to add caching to draft service methods."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # This would implement method-level caching
            # For now, just call the original function
            return func(*args, **kwargs)
        return wrapper
    return decorator