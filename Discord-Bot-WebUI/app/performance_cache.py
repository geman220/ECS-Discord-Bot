# app/performance_cache.py

"""
Performance-Focused Redis Caching

This module implements strategic Redis caching for the most performance-critical
database queries in the application. It focuses on caching expensive operations
that are frequently accessed but change infrequently.

Key areas:
- Team standings and statistics  
- Player statistics aggregations
- League and season data
- Match results and summaries
"""

import json
import logging
from functools import wraps
from typing import Dict, List, Any, Optional
from flask import g
from app.utils.redis_manager import get_redis_connection
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)

def get_cache_client():
    """Get Redis client instance."""
    try:
        return get_redis_connection()
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        return None

def cache_team_stats(ttl=600):  # 10 minutes
    """Cache team statistics queries."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cache_client = get_cache_client()
            if not cache_client:
                return f(*args, **kwargs)
            
            # Create cache key from function name and arguments
            cache_key = f"team_stats:{f.__name__}:{hash(str(args) + str(sorted(kwargs.items())))}"
            
            try:
                # Try cache first
                cached = cache_client.get(cache_key)
                if cached:
                    logger.debug(f"Team stats cache hit: {cache_key}")
                    return json.loads(cached)
                
                # Execute and cache
                result = f(*args, **kwargs)
                if result:
                    cache_client.setex(cache_key, ttl, json.dumps(result, default=str))
                    logger.debug(f"Team stats cached: {cache_key}")
                
                return result
                
            except Exception as e:
                logger.warning(f"Team stats cache error: {e}")
                return f(*args, **kwargs)
        
        return wrapper
    return decorator

def cache_standings_data(league_id=None, ttl=300):  # 5 minutes
    """Cache standings data which is expensive to calculate."""
    cache_client = get_cache_client()
    if not cache_client:
        return None
    
    cache_key = f"standings:league:{league_id}" if league_id else "standings:all"
    
    try:
        cached = cache_client.get(cache_key)
        if cached:
            logger.debug(f"Standings cache hit: {cache_key}")
            return json.loads(cached)
        return None
    except Exception as e:
        logger.warning(f"Standings cache read error: {e}")
        return None

def set_standings_cache(data, league_id=None, ttl=300):
    """Store standings data in cache."""
    cache_client = get_cache_client()
    if not cache_client:
        return
    
    cache_key = f"standings:league:{league_id}" if league_id else "standings:all"
    
    try:
        cache_client.setex(cache_key, ttl, json.dumps(data, default=str))
        logger.debug(f"Standings cached: {cache_key}")
    except Exception as e:
        logger.warning(f"Standings cache write error: {e}")

def cache_player_stats_summary(player_id, season_id=None, ttl=900):  # 15 minutes
    """Cache player statistics summary."""
    cache_client = get_cache_client()
    if not cache_client:
        return None
    
    cache_key = f"player_stats:{player_id}:season:{season_id or 'current'}"
    
    try:
        cached = cache_client.get(cache_key)
        if cached:
            logger.debug(f"Player stats cache hit: {cache_key}")
            return json.loads(cached)
        return None
    except Exception as e:
        logger.warning(f"Player stats cache error: {e}")
        return None

def set_player_stats_cache(player_id, data, season_id=None, ttl=900):
    """Store player statistics in cache."""
    cache_client = get_cache_client()
    if not cache_client:
        return
    
    cache_key = f"player_stats:{player_id}:season:{season_id or 'current'}"
    
    try:
        cache_client.setex(cache_key, ttl, json.dumps(data, default=str))
        logger.debug(f"Player stats cached: {cache_key}")
    except Exception as e:
        logger.warning(f"Player stats cache write error: {e}")

def cache_match_results(league_id=None, season_id=None, ttl=1800):  # 30 minutes
    """Cache match results which don't change often."""
    cache_client = get_cache_client()
    if not cache_client:
        return None
    
    cache_key = f"matches:league:{league_id}:season:{season_id}"
    
    try:
        cached = cache_client.get(cache_key)
        if cached:
            logger.debug(f"Match results cache hit: {cache_key}")
            return json.loads(cached)
        return None
    except Exception as e:
        logger.warning(f"Match results cache error: {e}")
        return None

def set_match_results_cache(data, league_id=None, season_id=None, ttl=1800):
    """Store match results in cache."""
    cache_client = get_cache_client()
    if not cache_client:
        return
    
    cache_key = f"matches:league:{league_id}:season:{season_id}"
    
    try:
        cache_client.setex(cache_key, ttl, json.dumps(data, default=str))
        logger.debug(f"Match results cached: {cache_key}")
    except Exception as e:
        logger.warning(f"Match results cache write error: {e}")

def invalidate_team_cache(team_id):
    """Invalidate all cache entries related to a specific team."""
    cache_client = get_cache_client()
    if not cache_client:
        return
    
    try:
        # Get all keys that contain this team
        patterns = [
            f"team_stats:*:{team_id}:*",
            f"standings:*",  # Standings affect all teams
            f"matches:*"     # Match results affect standings
        ]
        
        for pattern in patterns:
            keys = cache_client.keys(pattern)
            if keys:
                cache_client.delete(*keys)
                logger.debug(f"Invalidated {len(keys)} cache entries for team {team_id}")
    
    except Exception as e:
        logger.warning(f"Cache invalidation error for team {team_id}: {e}")

def invalidate_player_cache(player_id):
    """Invalidate cache entries for a specific player."""
    cache_client = get_cache_client()
    if not cache_client:
        return
    
    try:
        pattern = f"player_stats:{player_id}:*"
        keys = cache_client.keys(pattern)
        if keys:
            cache_client.delete(*keys)
            logger.debug(f"Invalidated {len(keys)} cache entries for player {player_id}")
    
    except Exception as e:
        logger.warning(f"Cache invalidation error for player {player_id}: {e}")

def warm_critical_caches():
    """Pre-populate the most critical caches during low-traffic periods."""
    logger.info("Starting cache warming process...")
    
    try:
        with managed_session() as session:
            from app.models import Team, League, Season
            
            # Get current season
            current_season = session.query(Season).filter_by(is_current=True).first()
            if not current_season:
                logger.warning("No current season found for cache warming")
                return
            
            # Warm team stats cache
            teams = session.query(Team).filter_by(league_id=current_season.leagues[0].id if current_season.leagues else None).limit(20).all()
            logger.info(f"Warming cache for {len(teams)} teams...")
            
            # This would trigger our optimized bulk loading
            from app.team_performance_helpers import bulk_load_team_stats
            team_ids = [team.id for team in teams]
            stats = bulk_load_team_stats(team_ids, session)
            
            # Cache the results
            for team_id, team_stats in stats.items():
                cache_key = f"team_stats:bulk:{team_id}"
                set_standings_cache(team_stats, team_id, ttl=1200)  # 20 minutes
            
            logger.info("Cache warming completed successfully")
    
    except Exception as e:
        logger.error(f"Cache warming failed: {e}", exc_info=True)

def get_cache_stats():
    """Get Redis cache statistics for monitoring."""
    cache_client = get_cache_client()
    if not cache_client:
        return {"error": "Redis not available"}
    
    try:
        info = cache_client.info()
        
        # Count keys by prefix
        key_counts = {}
        for prefix in ['team_stats:', 'standings:', 'player_stats:', 'matches:']:
            keys = cache_client.keys(f"{prefix}*")
            key_counts[prefix.rstrip(':')] = len(keys)
        
        return {
            "connected_clients": info.get('connected_clients', 0),
            "used_memory_human": info.get('used_memory_human', 'N/A'),
            "keyspace_hits": info.get('keyspace_hits', 0),
            "keyspace_misses": info.get('keyspace_misses', 0),
            "cache_hit_ratio": round(
                info.get('keyspace_hits', 0) / 
                max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0), 1) * 100, 2
            ),
            "key_counts": key_counts
        }
    
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {"error": str(e)}