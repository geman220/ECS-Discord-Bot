# app/cache/rsvp_cache.py

"""
Real-Time RSVP Cache

Google-level performance caching for RSVP state using Redis.
Provides instant reads and optimistic updates for sub-100ms responses.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)

class RSVPCache:
    """
    High-performance Redis cache for RSVP state.
    
    Provides:
    - Instant RSVP lookups (no database queries)
    - Optimistic updates for real-time UX
    - Automatic expiration and cleanup
    - Fallback to database if cache miss
    """
    
    def __init__(self):
        self.redis = get_safe_redis()
        self.cache_ttl = 3600  # 1 hour TTL for RSVP data
        self.match_prefix = "rsvp:match:"
        self.player_prefix = "rsvp:player:"
        self.summary_prefix = "rsvp:summary:"
    
    def get_match_rsvps(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Get cached RSVP data for a match.
        Returns None if not cached.
        """
        try:
            key = f"{self.match_prefix}{match_id}"
            data = self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Redis cache read failed for match {match_id}: {e}")
            return None
    
    def set_match_rsvps(self, match_id: int, rsvp_data: Dict[str, Any]):
        """
        Cache RSVP data for a match.
        """
        try:
            key = f"{self.match_prefix}{match_id}"
            data = {
                'match_id': match_id,
                'rsvps': rsvp_data,
                'cached_at': datetime.utcnow().isoformat(),
                'ttl': self.cache_ttl
            }
            self.redis.setex(key, self.cache_ttl, json.dumps(data, default=str))
            logger.debug(f"📦 Cached RSVP data for match {match_id}")
        except Exception as e:
            logger.warning(f"Redis cache write failed for match {match_id}: {e}")
    
    def update_player_rsvp(self, match_id: int, player_id: int, 
                          availability: str, player_name: str = None):
        """
        Optimistic cache update for a single player RSVP.
        Updates cached match data immediately without database query.
        """
        try:
            # Get current cached data
            cached_data = self.get_match_rsvps(match_id)
            if not cached_data:
                logger.debug(f"No cached data for match {match_id} - skipping optimistic update")
                return
            
            rsvps = cached_data.get('rsvps', {'yes': [], 'no': [], 'maybe': []})
            
            # Remove player from all existing lists
            for response_type in ['yes', 'no', 'maybe']:
                rsvps[response_type] = [
                    p for p in rsvps[response_type] 
                    if p.get('player_id') != player_id
                ]
            
            # Add player to new response list
            if availability in ['yes', 'no', 'maybe']:
                player_data = {
                    'player_id': player_id,
                    'player_name': player_name or f'Player_{player_id}',
                    'responded_at': datetime.utcnow().isoformat()
                }
                rsvps[availability].append(player_data)
            
            # Update cache with new data
            self.set_match_rsvps(match_id, rsvps)
            logger.debug(f"⚡ Optimistic cache update: match {match_id}, player {player_id} -> {availability}")
            
        except Exception as e:
            logger.warning(f"Optimistic cache update failed: {e}")
    
    def get_player_rsvp(self, match_id: int, player_id: int) -> Optional[str]:
        """
        Get a specific player's RSVP from cache.
        """
        try:
            cached_data = self.get_match_rsvps(match_id)
            if not cached_data:
                return None
            
            rsvps = cached_data.get('rsvps', {})
            for response_type, players in rsvps.items():
                for player in players:
                    if player.get('player_id') == player_id:
                        return response_type
            
            return 'no_response'
            
        except Exception as e:
            logger.warning(f"Failed to get player RSVP from cache: {e}")
            return None
    
    def invalidate_match(self, match_id: int):
        """
        Remove match data from cache to force fresh database read.
        """
        try:
            key = f"{self.match_prefix}{match_id}"
            self.redis.delete(key)
            logger.debug(f"🗑️ Invalidated cache for match {match_id}")
        except Exception as e:
            logger.warning(f"Cache invalidation failed for match {match_id}: {e}")
    
    def warm_cache(self, match_id: int, rsvp_data: Dict[str, Any]):
        """
        Pre-populate cache with fresh database data.
        Called after database updates to ensure cache consistency.
        """
        self.set_match_rsvps(match_id, rsvp_data)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        """
        try:
            info = self.redis.info()
            return {
                'connected': True,
                'hits': info.get('keyspace_hits', 0),
                'misses': info.get('keyspace_misses', 0),
                'memory_used': info.get('used_memory_human', 'unknown'),
                'uptime': info.get('uptime_in_seconds', 0)
            }
        except Exception as e:
            return {'connected': False, 'error': str(e)}

# Global cache instance
rsvp_cache = RSVPCache()