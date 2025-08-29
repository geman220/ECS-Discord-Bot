# app/utils/task_status_helper.py

"""
Task Status Helper Module

Provides enhanced task status functionality that can be shared across
the application, including match management and monitoring pages.
"""

import json
import logging
import time
import redis
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)

# Simple in-memory cache to prevent concurrent requests to same match
_request_cache = {}
_CACHE_TTL = 30  # 30 seconds

# Redis connection pool for reliable connections
_redis_pool = None
_redis_connection_failures = 0
_max_redis_failures = 3  # Circuit breaker threshold
_redis_operation_metrics = {
    'total_requests': 0,
    'successful_requests': 0,
    'failed_requests': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'last_reset': time.time()
}


def _get_redis_connection() -> Optional[redis.Redis]:
    """Get a Redis connection with proper pooling and circuit breaker pattern."""
    global _redis_pool, _redis_connection_failures
    
    # Circuit breaker: if too many failures, don't attempt connections
    if _redis_connection_failures >= _max_redis_failures:
        logger.warning(f"Redis circuit breaker open: {_redis_connection_failures} failures")
        return None
    
    try:
        # Initialize connection pool on first use
        if _redis_pool is None:
            _redis_pool = redis.ConnectionPool(
                host='redis',
                port=6379,
                db=0,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                max_connections=10,
                retry_on_timeout=True,
                health_check_interval=30
            )
            logger.debug("Initialized Redis connection pool")
        
        # Get connection from pool
        redis_client = redis.Redis(connection_pool=_redis_pool)
        
        # Test connection with ping
        redis_client.ping()
        
        # Reset failure count on successful connection
        _redis_connection_failures = 0
        
        return redis_client
        
    except Exception as e:
        _redis_connection_failures += 1
        logger.error(f"Redis connection failed (attempt {_redis_connection_failures}/{_max_redis_failures}): {e}")
        
        # If we've hit the failure threshold, reset pool to force recreation
        if _redis_connection_failures >= _max_redis_failures:
            _redis_pool = None
            logger.warning("Resetting Redis pool due to connection failures")
        
        return None


def _safe_redis_operation(redis_client: redis.Redis, operation: str, *args, **kwargs):
    """Execute Redis operation with proper error handling and logging."""
    global _redis_operation_metrics
    
    try:
        method = getattr(redis_client, operation)
        result = method(*args, **kwargs)
        _redis_operation_metrics['successful_requests'] += 1
        return result
    except redis.ConnectionError as e:
        _redis_operation_metrics['failed_requests'] += 1
        logger.error(f"Redis connection error during {operation}: {e}")
        return None
    except redis.TimeoutError as e:
        _redis_operation_metrics['failed_requests'] += 1
        logger.error(f"Redis timeout during {operation}: {e}")
        return None
    except Exception as e:
        _redis_operation_metrics['failed_requests'] += 1
        logger.error(f"Redis error during {operation}: {e}")
        return None


def get_task_status_metrics() -> Dict[str, Any]:
    """Get comprehensive metrics about task status system health."""
    global _redis_operation_metrics, _redis_connection_failures, _request_cache
    
    current_time = time.time()
    uptime = current_time - _redis_operation_metrics['last_reset']
    
    # Calculate success rate
    total_ops = _redis_operation_metrics['successful_requests'] + _redis_operation_metrics['failed_requests']
    success_rate = (_redis_operation_metrics['successful_requests'] / total_ops * 100) if total_ops > 0 else 0
    
    # Cache statistics
    cache_total = _redis_operation_metrics['cache_hits'] + _redis_operation_metrics['cache_misses']
    cache_hit_rate = (_redis_operation_metrics['cache_hits'] / cache_total * 100) if cache_total > 0 else 0
    
    return {
        'redis_pool_status': {
            'pool_initialized': _redis_pool is not None,
            'connection_failures': _redis_connection_failures,
            'circuit_breaker_open': _redis_connection_failures >= _max_redis_failures,
            'max_connections': 10 if _redis_pool else None,
        },
        'operation_metrics': {
            'total_requests': _redis_operation_metrics['total_requests'],
            'successful_requests': _redis_operation_metrics['successful_requests'],
            'failed_requests': _redis_operation_metrics['failed_requests'],
            'success_rate_percent': round(success_rate, 2),
            'uptime_seconds': round(uptime, 2)
        },
        'cache_metrics': {
            'in_memory_cache_size': len(_request_cache),
            'cache_hits': _redis_operation_metrics['cache_hits'],
            'cache_misses': _redis_operation_metrics['cache_misses'],
            'cache_hit_rate_percent': round(cache_hit_rate, 2),
            'cache_ttl_seconds': _CACHE_TTL
        },
        'timestamp': current_time,
        'healthy': _redis_connection_failures < _max_redis_failures and success_rate > 80
    }


def get_enhanced_match_task_status(match_id: int, use_cache: bool = True) -> Dict[str, Any]:
    """
    Get enhanced task status for a match with cache-first approach and fallback logic.
    
    This function first tries to get data from the background cache for optimal performance.
    If cache miss or disabled, it falls back to real-time calculation.
    
    Args:
        match_id: The match ID to check
        use_cache: Whether to use cache-first approach (default: True)
        
    Returns:
        Dictionary with success flag, match_id, tasks dict, timestamp, and cache info
    """
    global _redis_operation_metrics
    
    # Track total requests
    _redis_operation_metrics['total_requests'] += 1
    
    # Check in-memory request cache first to prevent concurrent duplicate requests
    current_time = time.time()
    cache_key = f"task_status_{match_id}"
    
    if cache_key in _request_cache:
        cached_data, cached_time = _request_cache[cache_key]
        if current_time - cached_time < _CACHE_TTL:
            _redis_operation_metrics['cache_hits'] += 1
            logger.debug(f"Serving match {match_id} from in-memory cache")
            return cached_data
    
    # Track cache miss for in-memory cache
    _redis_operation_metrics['cache_misses'] += 1
    
    # Try cache first if enabled
    if use_cache:
        try:
            from app.services.task_status_cache import task_status_cache
            cached_result = task_status_cache.get_cached_status(match_id)
            
            if cached_result:
                logger.debug(f"Serving task status for match {match_id} from background cache")
                return cached_result
            
            logger.debug(f"Cache miss for match {match_id}, falling back to real-time calculation")
            
        except Exception as e:
            logger.warning(f"Cache lookup failed for match {match_id}: {e}, falling back to real-time")
    
    # Real-time calculation with robust Redis connection handling
    try:
        # Get Redis connection using connection pool
        redis_client = _get_redis_connection()
        
        # If Redis is unavailable, return graceful degradation
        if redis_client is None:
            logger.warning(f"Redis unavailable for match {match_id}, returning minimal status")
            return {
                'success': True,
                'match_id': match_id,
                'tasks': {},
                'timestamp': datetime.utcnow().isoformat(),
                'cached': False,
                'source': 'redis-unavailable',
                'message': 'Redis unavailable - task details not available'
            }
        
        # Helper function for decoding Redis data
        def safe_decode(data):
            if data is None:
                return None
            return data if isinstance(data, str) else data.decode('utf-8')
        
        tasks = {}
        
        # Get match details for fallback logic with proper session handling
        from app.core.helpers import get_match
        from app.core.session_manager import managed_session
        from app.models.external import MLSMatch
        match_data = None
        
        try:
            with managed_session() as session:
                # Use explicit query instead of get_match to avoid dependency issues
                match = session.query(MLSMatch).filter_by(id=match_id).first()
                if match:
                    # Extract ALL needed data while session is active to prevent lazy loading
                    match_data = {
                        'discord_thread_id': getattr(match, 'discord_thread_id', None),
                        'date_time': getattr(match, 'date_time', None),
                        'opponent': getattr(match, 'opponent', None),
                        'is_home_game': getattr(match, 'is_home_game', None)
                    }
                    # Force evaluation of any lazy-loaded attributes
                    session.flush()
        except Exception as e:
            logger.error(f"Error loading match {match_id}: {e}")
            match_data = None
        
        # Check for thread creation task
        thread_key = f"match_scheduler:{match_id}:thread"
        thread_data = _safe_redis_operation(redis_client, 'get', thread_key)
        thread_ttl = _safe_redis_operation(redis_client, 'ttl', thread_key)
        
        if thread_data:
            try:
                thread_json = json.loads(safe_decode(thread_data))
                task_id = thread_json.get('task_id')
                eta = thread_json.get('eta')
                
                # Get task status from Celery
                from celery.result import AsyncResult
                task_result = AsyncResult(task_id)
                
                tasks['thread'] = {
                    'task_id': task_id,
                    'eta': eta,
                    'ttl': thread_ttl,
                    'status': str(task_result.status),
                    'result': str(task_result.result) if task_result.result else None,
                    'redis_key': thread_key,
                    'type': 'Thread Creation'
                }
            except (json.JSONDecodeError, Exception) as e:
                tasks['thread'] = {
                    'error': f'Failed to parse thread task: {str(e)}',
                    'raw_data': safe_decode(thread_data)
                }
        else:
            # Fallback logic for thread creation
            if match_data and match_data.get('discord_thread_id'):
                # Thread exists, so task completed successfully
                tasks['thread'] = {
                    'task_id': 'unknown',
                    'eta': 'completed',
                    'status': 'SUCCESS',
                    'result': f'Thread created: {match_data["discord_thread_id"]}',
                    'type': 'Thread Creation',
                    'fallback': True,
                    'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} thread created'
                }
            elif match_data:
                # Check if thread creation should have happened by now
                import pytz
                utc_tz = pytz.UTC
                match_time = match_data['date_time'].replace(tzinfo=utc_tz) if match_data['date_time'] else None
                if match_time:
                    thread_time = match_time - timedelta(hours=48)  # 48 hours before
                    now = datetime.now(utc_tz)
                    if now > thread_time:
                        # Thread should have been created but wasn't
                        tasks['thread'] = {
                            'task_id': 'unknown',
                            'eta': thread_time.isoformat(),
                            'status': 'MISSING',
                            'result': 'Thread creation task should have run but no thread found',
                            'type': 'Thread Creation',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - thread creation overdue'
                        }
                    else:
                        # Thread not due yet
                        tasks['thread'] = {
                            'task_id': 'scheduled',
                            'eta': thread_time.isoformat(),
                            'status': 'PENDING',
                            'result': f'Scheduled for {thread_time.strftime("%Y-%m-%d %H:%M UTC")}',
                            'type': 'Thread Creation',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - thread scheduled'
                        }
        
        # Check for live reporting task
        reporting_key = f"match_scheduler:{match_id}:reporting"
        reporting_data = _safe_redis_operation(redis_client, 'get', reporting_key)
        reporting_ttl = _safe_redis_operation(redis_client, 'ttl', reporting_key)
        
        if reporting_data:
            try:
                reporting_json = json.loads(safe_decode(reporting_data))
                task_id = reporting_json.get('task_id')
                eta = reporting_json.get('eta')
                
                # Get task status from Celery
                from celery.result import AsyncResult
                task_result = AsyncResult(task_id)
                
                tasks['reporting'] = {
                    'task_id': task_id,
                    'eta': eta,
                    'ttl': reporting_ttl,
                    'status': str(task_result.status),
                    'result': str(task_result.result) if task_result.result else None,
                    'redis_key': reporting_key,
                    'type': 'Live Reporting'
                }
            except (json.JSONDecodeError, Exception) as e:
                tasks['reporting'] = {
                    'error': f'Failed to parse reporting task: {str(e)}',
                    'raw_data': safe_decode(reporting_data)
                }
        else:
            # Fallback logic for live reporting
            if match_data:
                import pytz
                utc_tz = pytz.UTC
                match_time = match_data['date_time'].replace(tzinfo=utc_tz) if match_data['date_time'] else None
                if match_time:
                    reporting_time = match_time - timedelta(minutes=5)  # 5 minutes before
                    now = datetime.now(utc_tz)
                    
                    if now > match_time:
                        # Match has already started/finished
                        tasks['reporting'] = {
                            'task_id': 'completed',
                            'eta': reporting_time.isoformat(),
                            'status': 'FINISHED',
                            'result': 'Match has ended',
                            'type': 'Live Reporting',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - match completed'
                        }
                    elif now > reporting_time:
                        # Reporting should have started
                        tasks['reporting'] = {
                            'task_id': 'active',
                            'eta': reporting_time.isoformat(),
                            'status': 'RUNNING',
                            'result': 'Live reporting should be active',
                            'type': 'Live Reporting',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - live reporting active'
                        }
                    else:
                        # Reporting not due yet
                        tasks['reporting'] = {
                            'task_id': 'scheduled',
                            'eta': reporting_time.isoformat(),
                            'status': 'PENDING',
                            'result': f'Scheduled for {reporting_time.strftime("%Y-%m-%d %H:%M UTC")}',
                            'type': 'Live Reporting',
                            'fallback': True,
                            'message': f'{"Sounders vs " + match_data["opponent"] if match_data["is_home_game"] else match_data["opponent"] + " vs Sounders"} - reporting scheduled'
                        }
        
        result = {
            'success': True,
            'match_id': match_id,
            'tasks': tasks,
            'timestamp': datetime.utcnow().isoformat(),
            'cached': False,
            'source': 'real-time'
        }
        
        # Cache the result to prevent duplicate requests
        _request_cache[cache_key] = (result, current_time)
        
        # Clean up old cache entries periodically
        if len(_request_cache) > 100:  # Simple cleanup when cache gets large
            cutoff_time = current_time - _CACHE_TTL
            keys_to_remove = [k for k, (_, cached_time) in _request_cache.items() 
                             if current_time - cached_time > _CACHE_TTL]
            for k in keys_to_remove:
                del _request_cache[k]
            logger.debug(f"Cleaned up {len(keys_to_remove)} expired cache entries")
            
        return result
        
    except Exception as e:
        logger.error(f"Error getting enhanced match tasks for {match_id}: {str(e)}", exc_info=True)
        error_result = {
            'success': False,
            'error': str(e),
            'match_id': match_id,
            'tasks': {},
            'cached': False,
            'source': 'error'
        }
        
        # Cache error results briefly to prevent repeated failures
        _request_cache[cache_key] = (error_result, current_time)
        
        return error_result