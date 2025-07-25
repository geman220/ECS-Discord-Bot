"""
Cache Management System for Mobile API
Handles long-term caching with smart invalidation for match data.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from flask import current_app
from app.performance_cache import cache_match_results, set_match_results_cache
import logging

logger = logging.getLogger(__name__)

class MobileCacheManager:
    """
    Manages long-term caching for mobile API with selective invalidation.
    
    Cache Strategy:
    - Match schedules: 7 days (rarely change)
    - Team rosters: 3 days (changes when players join/leave)
    - Player stats: 1 day (updated after matches)
    - User profiles: 1 hour (can change more frequently)
    """
    
    # Cache TTL configuration (in minutes)
    CACHE_TTL = {
        'match_schedule': 10080,    # 7 days - schedules rarely change
        'match_list': 10080,        # 7 days - match lists rarely change  
        'team_roster': 4320,        # 3 days - roster changes are uncommon
        'team_stats': 1440,         # 1 day - stats update after matches
        'player_profile': 60,       # 1 hour - profiles can change
        'team_list': 4320,          # 3 days - team list rarely changes
    }
    
    @staticmethod
    def get_cache_key(endpoint: str, params: Dict[str, Any]) -> str:
        """Generate consistent cache key for endpoint and parameters."""
        # Sort params for consistent key generation
        param_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
        cache_data = f"{endpoint}_{param_string}"
        return hashlib.md5(cache_data.encode()).hexdigest()
    
    @staticmethod
    def get_cached_data(cache_type: str, cache_key: str) -> Optional[Any]:
        """Retrieve cached data if available and valid."""
        try:
            full_key = f"{cache_type}_{cache_key}"
            cached_data = cache_match_results(league_id=full_key)
            if cached_data:
                logger.debug(f"Cache HIT for {cache_type}:{cache_key}")
                return cached_data
            logger.debug(f"Cache MISS for {cache_type}:{cache_key}")
            return None
        except Exception as e:
            logger.warning(f"Cache retrieval failed for {cache_type}:{cache_key}: {e}")
            return None
    
    @staticmethod
    def set_cached_data(cache_type: str, cache_key: str, data: Any) -> bool:
        """Store data in cache with appropriate TTL."""
        try:
            ttl_minutes = MobileCacheManager.CACHE_TTL.get(cache_type, 60)
            full_key = f"{cache_type}_{cache_key}"
            set_match_results_cache(league_id=full_key, results=data, ttl_minutes=ttl_minutes)
            logger.debug(f"Cache SET for {cache_type}:{cache_key} (TTL: {ttl_minutes}m)")
            return True
        except Exception as e:
            logger.warning(f"Cache storage failed for {cache_type}:{cache_key}: {e}")
            return False
    
    @staticmethod
    def invalidate_cache_pattern(pattern: str) -> int:
        """
        Invalidate all cache entries matching a pattern.
        Returns number of entries invalidated.
        """
        try:
            # This would need to be implemented based on your Redis setup
            # For now, log the invalidation request
            logger.info(f"Cache invalidation requested for pattern: {pattern}")
            
            # You would implement actual Redis pattern deletion here
            # Example: redis_client.delete(*redis_client.keys(f"*{pattern}*"))
            
            return 0  # Return actual count when implemented
        except Exception as e:
            logger.error(f"Cache invalidation failed for pattern {pattern}: {e}")
            return 0
    
    @staticmethod
    def invalidate_match_caches():
        """Invalidate all match-related caches when schedule changes."""
        patterns = [
            "match_schedule_",
            "match_list_",
        ]
        total_invalidated = 0
        for pattern in patterns:
            total_invalidated += MobileCacheManager.invalidate_cache_pattern(pattern)
        
        logger.info(f"Invalidated {total_invalidated} match cache entries")
        return total_invalidated
    
    @staticmethod
    def invalidate_team_caches(team_id: Optional[int] = None):
        """Invalidate team-related caches when roster or stats change."""
        if team_id:
            patterns = [
                f"team_roster_{team_id}",
                f"team_stats_{team_id}",
                f"match_schedule_.*team_id.*{team_id}",
                f"match_list_.*team_id.*{team_id}",
            ]
        else:
            patterns = [
                "team_roster_",
                "team_stats_",
                "team_list_",
            ]
        
        total_invalidated = 0
        for pattern in patterns:
            total_invalidated += MobileCacheManager.invalidate_cache_pattern(pattern)
        
        logger.info(f"Invalidated {total_invalidated} team cache entries for team {team_id or 'all'}")
        return total_invalidated

# Cache invalidation endpoints for admin use
def create_cache_admin_routes(app):
    """Create admin routes for manual cache management."""
    
    @app.route('/admin/cache/invalidate/matches', methods=['POST'])
    def invalidate_match_caches():
        """Admin endpoint to invalidate match caches."""
        # Add admin authentication here
        count = MobileCacheManager.invalidate_match_caches()
        return {"success": True, "invalidated": count, "message": "Match caches invalidated"}
    
    @app.route('/admin/cache/invalidate/teams', methods=['POST'])
    @app.route('/admin/cache/invalidate/teams/<int:team_id>', methods=['POST'])
    def invalidate_team_caches(team_id=None):
        """Admin endpoint to invalidate team caches."""
        # Add admin authentication here
        count = MobileCacheManager.invalidate_team_caches(team_id)
        return {"success": True, "invalidated": count, "message": f"Team caches invalidated for team {team_id or 'all'}"}

# Webhook handlers for automatic cache invalidation
class CacheInvalidationHooks:
    """Hooks to automatically invalidate caches when data changes."""
    
    @staticmethod
    def on_match_created_or_updated(match_id: int):
        """Called when a match is created or updated."""
        MobileCacheManager.invalidate_match_caches()
        logger.info(f"Auto-invalidated match caches due to match {match_id} change")
    
    @staticmethod
    def on_team_roster_changed(team_id: int):
        """Called when team roster changes (player added/removed)."""
        MobileCacheManager.invalidate_team_caches(team_id)
        logger.info(f"Auto-invalidated team caches due to roster change for team {team_id}")
    
    @staticmethod
    def on_player_stats_updated(player_id: int, team_id: int):
        """Called when player stats are updated."""
        MobileCacheManager.invalidate_team_caches(team_id)
        logger.info(f"Auto-invalidated team caches due to stats update for player {player_id}")

# Response headers for mobile app cache control
def add_cache_headers(response, cache_type: str, max_age_hours: int = 24):
    """
    Add appropriate cache headers for mobile app.
    
    This tells the mobile app how long it can cache the response locally.
    """
    max_age_seconds = max_age_hours * 3600
    
    # Cache headers for mobile app
    response.headers['Cache-Control'] = f'public, max-age={max_age_seconds}'
    response.headers['ETag'] = hashlib.md5(response.get_data()).hexdigest()
    
    # Custom header to indicate cache type
    response.headers['X-Cache-Type'] = cache_type
    response.headers['X-Cache-Max-Age-Hours'] = str(max_age_hours)
    
    return response

# Cache usage examples for mobile API endpoints
"""
Example usage in mobile API endpoints:

@mobile_api.route('/matches/schedule', methods=['GET'])
@jwt_required()
def get_match_schedule():
    # Generate cache key based on user role and parameters
    cache_params = {
        'endpoint': 'match_schedule',
        'team_id': request.args.get('team_id'),
        'limit': get_user_appropriate_limit(),
        'upcoming': request.args.get('upcoming', 'true')
    }
    cache_key = MobileCacheManager.get_cache_key('match_schedule', cache_params)
    
    # Try cache first (only for non-personalized data)
    if not request.args.get('include_availability'):
        cached_data = MobileCacheManager.get_cached_data('match_schedule', cache_key)
        if cached_data:
            response = jsonify(cached_data)
            return add_cache_headers(response, 'match_schedule', 168)  # 7 days
    
    # Generate fresh data
    data = generate_match_schedule_data()
    
    # Cache the result
    if not request.args.get('include_availability'):
        MobileCacheManager.set_cached_data('match_schedule', cache_key, data)
    
    response = jsonify(data)
    return add_cache_headers(response, 'match_schedule', 168)  # 7 days
"""