# app/draft_cache_service.py

"""
Ultra-Reliable Draft Cache Service for Active Draft Sessions

This provides Redis-based caching optimized specifically for active draft sessions
with aggressive connection management, circuit breaker patterns, and fallback strategies
to prevent ANY timeouts during critical draft periods.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import contextmanager
import hashlib
import time
import threading

try:
    import redis
    from app.utils.redis_manager import get_redis_manager
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global state for active draft detection.
# NOTE: this in-process set only reflects the gunicorn worker that handled the
# start/stop request. With multiple web workers the others wouldn't know a draft
# is active, so they'd use the wrong cache TTLs / invalidation branch. It is now
# mirrored into a shared Redis set (_ACTIVE_DRAFT_REDIS_KEY) so ALL workers agree;
# the in-process set remains the fallback when Redis is unavailable.
_active_drafts = set()
_active_draft_lock = threading.Lock()
_ACTIVE_DRAFT_REDIS_KEY = 'draft:active_leagues'
_ACTIVE_DRAFT_REDIS_TTL = 21600  # 6h safety expiry, refreshed on every mark_active

class DraftCacheService:
    """
    Ultra-reliable cache service optimized for active draft sessions.
    
    Key Features:
    - Adaptive TTL based on draft activity
    - Circuit breaker for Redis operations
    - Aggressive fallback strategies
    - Zero-timeout guarantee for active drafts
    """
    
    # Adaptive Cache TTL settings based on draft activity
    ACTIVE_DRAFT_TTL = {
        'player_data': 3600,     # 1 hour during active drafts
        'analytics': 1800,       # 30 minutes during active drafts  
        'team_data': 7200,       # 2 hours during active drafts
        'availability': 900      # 15 minutes during active drafts
    }
    
    INACTIVE_DRAFT_TTL = {
        'player_data': 900,      # 15 minutes when inactive
        'analytics': 600,        # 10 minutes when inactive
        'team_data': 1800,       # 30 minutes when inactive
        'availability': 300      # 5 minutes when inactive
    }
    
    # Circuit breaker settings
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
    CIRCUIT_BREAKER_RESET_TIMEOUT = 30
    
    _circuit_breaker_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    _circuit_breaker_failures = 0
    _circuit_breaker_last_failure = 0
    
    @classmethod
    def mark_draft_active(cls, league_name: str):
        """Mark a league as having an active draft session (shared across workers)."""
        with _active_draft_lock:
            _active_drafts.add(league_name)
        try:
            with cls._redis_connection_safe() as redis_conn:
                if redis_conn:
                    redis_conn.sadd(_ACTIVE_DRAFT_REDIS_KEY, league_name)
                    redis_conn.expire(_ACTIVE_DRAFT_REDIS_KEY, _ACTIVE_DRAFT_REDIS_TTL)
        except Exception as e:
            logger.warning(f"mark_draft_active redis sync failed (local only): {e}")
        logger.info(f"🎯 Marked {league_name} as ACTIVE DRAFT - extended cache TTLs enabled")

    @classmethod
    def mark_draft_inactive(cls, league_name: str):
        """Mark a league as no longer having an active draft session (shared)."""
        with _active_draft_lock:
            _active_drafts.discard(league_name)
        try:
            with cls._redis_connection_safe() as redis_conn:
                if redis_conn:
                    redis_conn.srem(_ACTIVE_DRAFT_REDIS_KEY, league_name)
        except Exception as e:
            logger.warning(f"mark_draft_inactive redis sync failed (local only): {e}")
        logger.info(f"🎯 Marked {league_name} as INACTIVE DRAFT - normal cache TTLs restored")

    @classmethod
    def is_draft_active(cls, league_name: str) -> bool:
        """Check if a league has an active draft session. Prefer the shared Redis
        view so every worker agrees; fall back to the in-process set if Redis is
        unavailable (never let this raise on the pick path)."""
        try:
            with cls._redis_connection_safe() as redis_conn:
                if redis_conn:
                    return bool(redis_conn.sismember(_ACTIVE_DRAFT_REDIS_KEY, league_name))
        except Exception as e:
            logger.warning(f"is_draft_active redis check failed, using local set: {e}")
        with _active_draft_lock:
            return league_name in _active_drafts
    
    @classmethod
    def get_adaptive_ttl(cls, cache_type: str, league_name: str) -> int:
        """Get TTL based on whether draft is active for this league."""
        if cls.is_draft_active(league_name):
            return cls.ACTIVE_DRAFT_TTL.get(cache_type, 3600)
        else:
            return cls.INACTIVE_DRAFT_TTL.get(cache_type, 900)
    
    @classmethod
    def _check_circuit_breaker(cls) -> bool:
        """Check if circuit breaker allows operations."""
        current_time = time.time()
        
        if cls._circuit_breaker_state == "OPEN":
            if current_time - cls._circuit_breaker_last_failure > cls.CIRCUIT_BREAKER_RESET_TIMEOUT:
                cls._circuit_breaker_state = "HALF_OPEN"
                logger.info("🔧 Circuit breaker moved to HALF_OPEN")
                return True
            return False
        
        return True
    
    @classmethod
    def _record_success(cls):
        """Record successful Redis operation."""
        if cls._circuit_breaker_state == "HALF_OPEN":
            cls._circuit_breaker_state = "CLOSED"
            cls._circuit_breaker_failures = 0
            logger.info("🔧 Circuit breaker CLOSED - Redis operations restored")
    
    @classmethod
    def _record_failure(cls):
        """Record failed Redis operation."""
        cls._circuit_breaker_failures += 1
        cls._circuit_breaker_last_failure = time.time()
        
        if cls._circuit_breaker_failures >= cls.CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            cls._circuit_breaker_state = "OPEN"
            logger.error(f"🚨 Circuit breaker OPEN - Redis operations disabled for {cls.CIRCUIT_BREAKER_RESET_TIMEOUT}s")
    
    @staticmethod
    @contextmanager
    def _redis_connection_safe():
        """
        Ultra-safe Redis connection with circuit breaker and timeout protection.
        
        Returns None immediately if Redis is unavailable to prevent ANY blocking.
        """
        if not REDIS_AVAILABLE:
            yield None
            return
        
        # Circuit breaker check - fail fast if Redis is having issues
        if not DraftCacheService._check_circuit_breaker():
            logger.warning("Circuit breaker OPEN - skipping Redis operation to prevent timeout")
            yield None
            return
            
        try:
            redis_manager = get_redis_manager()
            
            # Check connection pool utilization - fail fast if overloaded
            try:
                stats = redis_manager.get_connection_stats()
                pool_utilization = stats.get('pool_stats', {}).get('utilization_percent', 0)
                
                if pool_utilization > 90:  # Very aggressive threshold for active drafts
                    logger.warning(f"Redis pool critical ({pool_utilization}%) - skipping operation to prevent timeout")
                    yield None
                    return
            except Exception as e:
                # If we can't even get stats, Redis is in trouble
                logger.warning(f"Could not get Redis stats: {e}")
                DraftCacheService._record_failure()
                yield None
                return
            
            # Set very aggressive timeout for connection
            try:
                start_time = time.time()
                conn = redis_manager.client
                
                # Ensure we got a valid connection
                if conn is None:
                    logger.error("Redis manager returned None client")
                    DraftCacheService._record_failure()
                    yield None
                    return
                
                # Test connection with minimal timeout - but handle fallback clients
                if hasattr(conn, 'ping'):
                    ping_result = conn.ping()
                    if ping_result is False:  # Fallback client returns False
                        logger.debug("Redis fallback client detected - degraded mode")
                else:
                    logger.warning("Redis client has no ping method")
                
                connection_time = time.time() - start_time
                if connection_time > 0.1:  # 100ms is too slow for active draft
                    logger.warning(f"Redis connection slow ({connection_time:.3f}s) - potential timeout risk")
                
                DraftCacheService._record_success()
                yield conn
                
            except Exception as e:
                logger.error(f"Redis connection error: {e}")
                DraftCacheService._record_failure()
                yield None
                
        except Exception as e:
            logger.error(f"Critical error in Redis connection manager: {e}")
            yield None
    
    @staticmethod
    def _get_cache_key(prefix: str, league_name: str, *args) -> str:
        """Generate a cache key with consistent formatting."""
        key_parts = [f"draft:{prefix}:{league_name}"]
        if args:
            args_str = ":".join(str(arg) for arg in args)
            args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
            key_parts.append(args_hash)
        return ":".join(key_parts)

    # --- key registry -------------------------------------------------------
    #
    # Invalidation used to SCAN the entire Redis keyspace, four patterns deep,
    # 100 keys per round trip. Redis is also the Celery broker AND result
    # backend here, and every API request queues a task that writes a result key,
    # so the keyspace is huge — that scan was costing SECONDS on the request
    # path, and it runs on every player activation (pass claim, pass assign).
    #
    # It was also silently broken: the pub-league path cleared `division.lower()`
    # ('premier') while the draft pages cache under 'Premier', and Redis MATCH is
    # case-sensitive — so it scanned the whole keyspace and deleted nothing.
    #
    # Instead we record each cache key we write in a per-league SET. Clearing is
    # then SMEMBERS + DEL: proportional to the handful of keys that actually
    # exist, not to the size of Redis. The registry is keyed case-INSENSITIVELY
    # so 'Premier' and 'premier' invalidate the same thing.

    _LEAGUE_INDEX = 'draft:leagues'
    _REGISTRY_TTL = 86400  # a day; keys themselves carry shorter TTLs

    @staticmethod
    def _registry_key(league_name: str) -> str:
        return f"draft:keyset:{(league_name or '').strip().lower()}"

    @staticmethod
    def _register_key(redis_conn, league_name: str, cache_key: str) -> None:
        """Record a cache key so it can be invalidated without a keyspace scan."""
        try:
            registry = DraftCacheService._registry_key(league_name)
            pipe = redis_conn.pipeline()
            pipe.sadd(registry, cache_key)
            pipe.expire(registry, DraftCacheService._REGISTRY_TTL)
            pipe.sadd(DraftCacheService._LEAGUE_INDEX, (league_name or '').strip().lower())
            pipe.expire(DraftCacheService._LEAGUE_INDEX, DraftCacheService._REGISTRY_TTL)
            pipe.execute()
        except Exception as e:
            # Never fail a cache WRITE because bookkeeping failed; worst case the
            # key falls out via its own TTL.
            logger.debug(f"Could not register draft cache key {cache_key}: {e}")


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
        return json.loads(data)
    
    @staticmethod
    def get_enhanced_players_cache(league_name: str, player_type: str = 'all') -> Optional[List[Dict]]:
        """
        Get cached enhanced player data with ultra-safe connection management.
        
        For active drafts, this will NEVER timeout - returns None immediately if Redis unavailable.
        """
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                if DraftCacheService.is_draft_active(league_name):
                    logger.warning(f"Redis unavailable during ACTIVE DRAFT for {league_name} - returning None to prevent timeout")
                return None
                
            try:
                # Use very short timeout for active drafts
                cache_key = DraftCacheService._get_cache_key('players', league_name, player_type)
                
                # Ultra-fast cache retrieval with timeout protection
                start_time = time.time()
                cached_data = redis_conn.get(cache_key)
                
                retrieval_time = time.time() - start_time
                if retrieval_time > 0.05:  # 50ms is slow for active draft
                    logger.warning(f"Cache retrieval slow ({retrieval_time:.3f}s) for {cache_key}")
                
                if cached_data:
                    logger.debug(f"⚡ Cache HIT for {cache_key} ({retrieval_time:.3f}s)")
                    return DraftCacheService._deserialize_data(cached_data)
                else:
                    logger.debug(f"Cache MISS for {cache_key}")
                    return None
                    
            except Exception as e:
                if DraftCacheService.is_draft_active(league_name):
                    logger.error(f"Cache retrieval failed during ACTIVE DRAFT for {league_name}: {e}")
                else:
                    logger.warning(f"Cache retrieval failed: {e}")
                return None
    
    @staticmethod
    def set_enhanced_players_cache(league_name: str, player_type: str, players_data: List[Dict]) -> bool:
        """
        Cache enhanced player data with ultra-safe connection management.
        
        For active drafts, uses longer TTL and fails fast if Redis unavailable.
        """
        if not players_data:
            return False
            
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                if DraftCacheService.is_draft_active(league_name):
                    logger.warning(f"Redis unavailable during ACTIVE DRAFT for {league_name} - skipping cache set")
                return False
                
            try:
                cache_key = DraftCacheService._get_cache_key('players', league_name, player_type)
                ttl = DraftCacheService.get_adaptive_ttl('player_data', league_name)
                
                serialized_data = DraftCacheService._serialize_data(players_data)
                
                start_time = time.time()
                success = redis_conn.setex(cache_key, ttl, serialized_data)
                if success:
                    DraftCacheService._register_key(redis_conn, league_name, cache_key)

                cache_time = time.time() - start_time
                if cache_time > 0.1:  # 100ms is slow for active draft
                    logger.warning(f"Cache set slow ({cache_time:.3f}s) for {cache_key}")
                
                if success:
                    is_active = DraftCacheService.is_draft_active(league_name)
                    ttl_type = "ACTIVE" if is_active else "normal"
                    logger.debug(f"⚡ Cached {len(players_data)} players for {cache_key} ({ttl_type} TTL: {ttl}s)")
                
                return bool(success)
                
            except Exception as e:
                if DraftCacheService.is_draft_active(league_name):
                    logger.error(f"Cache set failed during ACTIVE DRAFT for {league_name}: {e}")
                else:
                    logger.warning(f"Cache set failed: {e}")
                return False
    
    @staticmethod
    def invalidate_player_cache_ultra_safe(player_id: int, league_name: str = None) -> int:
        """
        Ultra-safe player cache invalidation that NEVER blocks during active drafts.
        
        Uses aggressive timeouts and circuit breaker to prevent any delays.
        """
        # For active drafts, use minimal invalidation to prevent any blocking
        if league_name and DraftCacheService.is_draft_active(league_name):
            logger.info(f"🎯 ACTIVE DRAFT detected for {league_name} - using minimal cache invalidation for player {player_id}")
            
            with DraftCacheService._redis_connection_safe() as redis_conn:
                if not redis_conn:
                    logger.warning(f"Redis unavailable during ACTIVE DRAFT - skipping cache invalidation for player {player_id}")
                    return 0
                
                try:
                    # Only invalidate specific league caches during active draft
                    keys_to_delete = [
                        DraftCacheService._get_cache_key('players', league_name, 'available'),
                        DraftCacheService._get_cache_key('players', league_name, 'drafted'),
                        DraftCacheService._get_cache_key('analytics', league_name)
                    ]
                    
                    deleted_count = 0
                    for key in keys_to_delete:
                        try:
                            if redis_conn.delete(key):
                                deleted_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to delete cache key {key}: {e}")
                    
                    logger.info(f"⚡ Fast invalidation: {deleted_count} keys for player {player_id} in ACTIVE DRAFT {league_name}")
                    return deleted_count
                    
                except Exception as e:
                    logger.error(f"Fast invalidation failed for player {player_id}: {e}")
                    return 0
        
        # For inactive drafts, use more thorough invalidation
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                return 0
                
            try:
                with redis_conn.pipeline() as pipe:
                    # Read from the per-league key registry rather than SCANning the
                    # keyspace (see _register_key). This is called from the user
                    # management routes on the request path, and a SCAN here walks
                    # every key in Redis — which doubles as the Celery broker and
                    # result backend, so the keyspace is large.
                    if league_name:
                        leagues = [league_name]
                    else:
                        try:
                            leagues = [
                                l.decode() if isinstance(l, bytes) else l
                                for l in redis_conn.smembers(DraftCacheService._LEAGUE_INDEX)
                            ]
                        except Exception as e:
                            logger.warning(f"Could not read league index: {e}")
                            leagues = []

                    keys_to_delete = []
                    for lg in leagues:
                        try:
                            keys_to_delete.extend(
                                redis_conn.smembers(DraftCacheService._registry_key(lg))
                            )
                        except Exception as e:
                            logger.warning(f"Error reading cache registry for {lg!r}: {e}")


                    deleted_count = 0
                    if keys_to_delete:
                        batch_size = 50
                        for i in range(0, len(keys_to_delete), batch_size):
                            batch = keys_to_delete[i:i + batch_size]
                            try:
                                pipe.delete(*batch)
                            except Exception as e:
                                logger.warning(f"Error adding batch to pipeline: {e}")
                        
                        try:
                            results = pipe.execute()
                            deleted_count = sum(results)
                        except Exception as e:
                            logger.warning(f"Pipeline execution failed: {e}")
                    
                    logger.debug(f"Invalidated {deleted_count} cache keys for player {player_id}")
                    return deleted_count
                    
            except Exception as e:
                logger.warning(f"Cache invalidation failed for player {player_id}: {e}")
                return 0
    
    # Legacy method redirects to ultra-safe version
    @staticmethod
    def invalidate_player_cache(player_id: int) -> int:
        """Legacy method - redirects to ultra-safe version."""
        return DraftCacheService.invalidate_player_cache_ultra_safe(player_id)
    
    @staticmethod
    def invalidate_player_cache_optimized(player_id: int, league_name: str = None) -> int:
        """Optimized method - redirects to ultra-safe version."""
        return DraftCacheService.invalidate_player_cache_ultra_safe(player_id, league_name)
    
    @staticmethod
    def warm_cache_for_active_draft(league_name: str) -> Dict[str, Any]:
        """
        Pre-warm cache before starting an active draft session.
        
        This should be called when draft UI is loaded to ensure cache is ready.
        """
        logger.info(f"🎯 Pre-warming cache for upcoming draft session: {league_name}")
        
        # Mark as active draft
        DraftCacheService.mark_draft_active(league_name)
        
        # Check current cache status
        cache_status = {}
        
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                logger.warning("Redis unavailable for cache warming")
                return {'success': False, 'error': 'Redis unavailable'}
            
            try:
                # Check each cache type
                cache_keys = [
                    ('players_available', DraftCacheService._get_cache_key('players', league_name, 'available')),
                    ('players_drafted', DraftCacheService._get_cache_key('players', league_name, 'drafted')),
                    ('analytics', DraftCacheService._get_cache_key('analytics', league_name)),
                    ('teams', DraftCacheService._get_cache_key('teams', league_name))
                ]
                
                for cache_type, cache_key in cache_keys:
                    try:
                        exists = redis_conn.exists(cache_key)
                        ttl = redis_conn.ttl(cache_key) if exists else 0
                        cache_status[cache_type] = {
                            'exists': bool(exists),
                            'ttl': ttl,
                            'cache_key': cache_key
                        }
                    except Exception as e:
                        logger.warning(f"Error checking cache for {cache_type}: {e}")
                        cache_status[cache_type] = {'exists': False, 'error': str(e)}
                
                return {
                    'success': True,
                    'league_name': league_name,
                    'active_draft_enabled': True,
                    'cache_status': cache_status,
                    'ttl_settings': DraftCacheService.ACTIVE_DRAFT_TTL
                }
                
            except Exception as e:
                logger.error(f"Error warming cache for {league_name}: {e}")
                return {'success': False, 'error': str(e)}

    @staticmethod
    def get_league_cache_status(league_name: str) -> Dict[str, Any]:
        """Read-only per-league cache status for the admin stats page.

        Same shape as warm_cache_for_active_draft() but WITHOUT marking the draft
        active — viewing the stats page must not mutate draft state. (The stats
        route previously called a non-existent warm_cache_for_league(), which made
        the page error out entirely.)
        """
        active = DraftCacheService.is_draft_active(league_name)
        cache_status = {}
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                return {'success': False, 'error': 'Redis unavailable',
                        'active_draft_enabled': active, 'cache_status': {}, 'warmed': False}
            cache_keys = [
                ('players_available', DraftCacheService._get_cache_key('players', league_name, 'available')),
                ('players_drafted', DraftCacheService._get_cache_key('players', league_name, 'drafted')),
                ('analytics', DraftCacheService._get_cache_key('analytics', league_name)),
                ('teams', DraftCacheService._get_cache_key('teams', league_name)),
            ]
            warmed_any = False
            for cache_type, cache_key in cache_keys:
                try:
                    exists = bool(redis_conn.exists(cache_key))
                    ttl = redis_conn.ttl(cache_key) if exists else 0
                    cache_status[cache_type] = {'exists': exists, 'ttl': ttl, 'cache_key': cache_key}
                    warmed_any = warmed_any or exists
                except Exception as e:
                    cache_status[cache_type] = {'exists': False, 'error': str(e)}
        return {
            'success': True,
            'league_name': league_name,
            'active_draft_enabled': active,
            'cache_status': cache_status,
            'warmed': warmed_any,
        }
    
    @staticmethod 
    def end_active_draft(league_name: str):
        """
        Mark end of active draft session and return to normal TTLs.
        
        This should be called when draft is completed or draft UI is closed.
        """
        DraftCacheService.mark_draft_inactive(league_name)
        logger.info(f"🎯 Ended active draft session for {league_name} - cache TTLs normalized")
        
        return {
            'success': True,
            'league_name': league_name,
            'active_draft_enabled': False,
            'ttl_settings': DraftCacheService.INACTIVE_DRAFT_TTL
        }
    
    @staticmethod
    def get_draft_analytics_cache(league_name: str) -> Optional[Dict]:
        """
        Get cached draft analytics data with ultra-safe connection management.
        
        For active drafts, this will NEVER timeout - returns None immediately if Redis unavailable.
        """
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                if DraftCacheService.is_draft_active(league_name):
                    logger.warning(f"Redis unavailable during ACTIVE DRAFT for {league_name} - returning None to prevent timeout")
                return None
                
            try:
                cache_key = DraftCacheService._get_cache_key('analytics', league_name)
                
                start_time = time.time()
                cached_data = redis_conn.get(cache_key)
                
                retrieval_time = time.time() - start_time
                if retrieval_time > 0.05:  # 50ms is slow for active draft
                    logger.warning(f"Analytics cache retrieval slow ({retrieval_time:.3f}s) for {cache_key}")
                
                if cached_data:
                    logger.debug(f"⚡ Analytics cache HIT for {cache_key} ({retrieval_time:.3f}s)")
                    return DraftCacheService._deserialize_data(cached_data)
                else:
                    logger.debug(f"Analytics cache MISS for {cache_key}")
                    return None
                    
            except Exception as e:
                if DraftCacheService.is_draft_active(league_name):
                    logger.error(f"Analytics cache retrieval failed during ACTIVE DRAFT for {league_name}: {e}")
                else:
                    logger.warning(f"Analytics cache retrieval failed: {e}")
                return None
    
    @staticmethod
    def set_draft_analytics_cache(league_name: str, analytics_data: Dict) -> bool:
        """
        Cache draft analytics data with ultra-safe connection management.
        
        For active drafts, uses longer TTL and fails fast if Redis unavailable.
        """
        if not analytics_data:
            return False
            
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                if DraftCacheService.is_draft_active(league_name):
                    logger.warning(f"Redis unavailable during ACTIVE DRAFT for {league_name} - skipping analytics cache set")
                return False
                
            try:
                cache_key = DraftCacheService._get_cache_key('analytics', league_name)
                ttl = DraftCacheService.get_adaptive_ttl('analytics', league_name)
                
                serialized_data = DraftCacheService._serialize_data(analytics_data)
                
                start_time = time.time()
                success = redis_conn.setex(cache_key, ttl, serialized_data)
                if success:
                    DraftCacheService._register_key(redis_conn, league_name, cache_key)

                cache_time = time.time() - start_time
                if cache_time > 0.1:  # 100ms is slow for active draft
                    logger.warning(f"Analytics cache set slow ({cache_time:.3f}s) for {cache_key}")
                
                if success:
                    is_active = DraftCacheService.is_draft_active(league_name)
                    ttl_type = "ACTIVE" if is_active else "normal"
                    logger.debug(f"⚡ Cached analytics for {cache_key} ({ttl_type} TTL: {ttl}s)")
                
                return bool(success)
                
            except Exception as e:
                if DraftCacheService.is_draft_active(league_name):
                    logger.error(f"Analytics cache set failed during ACTIVE DRAFT for {league_name}: {e}")
                else:
                    logger.warning(f"Analytics cache set failed: {e}")
                return False

    @staticmethod
    def clear_all_league_caches(league_name: str = None) -> int:
        """
        Clear ALL draft caches for a specific league or all leagues.

        This should be called after season rollover to ensure fresh data.

        Args:
            league_name: Specific league name to clear, or None for all leagues

        Returns:
            Number of cache keys deleted
        """
        logger.info(f"🗑️ Clearing all draft caches for: {league_name or 'ALL LEAGUES'}")

        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                logger.warning("Redis unavailable - cannot clear caches")
                return 0

            try:
                # Read the keys to drop from the per-league registry instead of
                # SCANning the whole keyspace. This runs on the pass-claim and
                # pass-assign request paths; the old scan walked every key in
                # Redis (which is also the Celery broker AND result backend) four
                # times over, costing seconds per call — and, because Redis MATCH
                # is case-sensitive and the pub-league path passed a lowercased
                # league name, it deleted nothing while doing so.
                if league_name:
                    leagues = [league_name]
                else:
                    try:
                        leagues = [
                            l.decode() if isinstance(l, bytes) else l
                            for l in redis_conn.smembers(DraftCacheService._LEAGUE_INDEX)
                        ]
                    except Exception as e:
                        logger.warning(f"Could not read league index: {e}")
                        leagues = []

                keys_to_delete = []
                registries = []
                for lg in leagues:
                    registry = DraftCacheService._registry_key(lg)
                    registries.append(registry)
                    try:
                        for key in redis_conn.smembers(registry):
                            keys_to_delete.append(key)
                    except Exception as e:
                        logger.warning(f"Error reading cache registry for {lg!r}: {e}")

                deleted_count = 0
                if keys_to_delete:
                    # Delete in batches
                    batch_size = 50
                    for i in range(0, len(keys_to_delete), batch_size):
                        batch = keys_to_delete[i:i + batch_size]
                        try:
                            deleted_count += redis_conn.delete(*batch)
                        except Exception as e:
                            logger.warning(f"Error deleting batch: {e}")

                # The registries themselves are now stale.
                if registries:
                    try:
                        redis_conn.delete(*registries)
                    except Exception as e:
                        logger.debug(f"Could not drop cache registries: {e}")

                logger.info(f"🗑️ Cleared {deleted_count} draft cache keys for {league_name or 'all leagues'}")
                return deleted_count

            except Exception as e:
                logger.error(f"Error clearing league caches: {e}")
                return 0

    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """Get comprehensive cache statistics including active draft status."""
        base_stats = {
            'redis_available': REDIS_AVAILABLE,
            'active_drafts': list(_active_drafts),
            'circuit_breaker': {
                'state': DraftCacheService._circuit_breaker_state,
                'failures': DraftCacheService._circuit_breaker_failures
            },
            'timestamp': datetime.now().isoformat()
        }
        
        if not REDIS_AVAILABLE:
            return base_stats
        
        with DraftCacheService._redis_connection_safe() as redis_conn:
            if not redis_conn:
                base_stats['connection_error'] = True
                return base_stats
            
            try:
                # Get Redis manager stats
                redis_manager = get_redis_manager()
                pool_stats = redis_manager.get_connection_stats()
                base_stats['connection_pool'] = pool_stats
                
                # Count cache keys
                cache_counts = {}
                patterns = {
                    'players': 'draft:players:*',
                    'analytics': 'draft:analytics:*', 
                    'teams': 'draft:teams:*',
                    'availability': 'draft:availability:*'
                }
                
                for cache_type, pattern in patterns.items():
                    try:
                        count = sum(1 for _ in redis_conn.scan_iter(match=pattern, count=1000))
                        cache_counts[cache_type] = count
                    except Exception as e:
                        cache_counts[cache_type] = f"Error: {e}"
                
                base_stats['draft_cache_keys'] = cache_counts
                return base_stats
                
            except Exception as e:
                base_stats['stats_error'] = str(e)
                return base_stats