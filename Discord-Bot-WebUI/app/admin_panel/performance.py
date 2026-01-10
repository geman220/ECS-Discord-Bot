# app/admin_panel/performance.py

"""
Admin Panel Performance Optimization Module

This module provides performance optimization utilities for the admin panel:
- Response caching for expensive queries
- Database query optimization
- Memory usage monitoring
- Performance metrics collection
"""

import time
import logging
from functools import wraps
from datetime import datetime, timedelta
from flask import request, g, current_app
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Set up the module logger
logger = logging.getLogger(__name__)

# In-memory cache for admin panel data (simple implementation)
_admin_cache = {}
_cache_timestamps = {}
CACHE_TIMEOUT = 300  # 5 minutes

def cache_admin_data(key, timeout=CACHE_TIMEOUT):
    """
    Decorator to cache admin panel data in memory.
    
    Args:
        key: Cache key (function name will be appended)
        timeout: Cache timeout in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"admin_panel_{key}_{func.__name__}"
            
            # Check if we have cached data that's still valid
            if (cache_key in _admin_cache and 
                cache_key in _cache_timestamps and
                time.time() - _cache_timestamps[cache_key] < timeout):
                
                logger.debug(f"Cache hit for {cache_key}")
                return _admin_cache[cache_key]
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            _admin_cache[cache_key] = result
            _cache_timestamps[cache_key] = time.time()
            
            logger.debug(f"Cache miss for {cache_key}, cached result")
            return result
        return wrapper
    return decorator


def clear_admin_cache(pattern=None):
    """
    Clear admin panel cache entries.
    
    Args:
        pattern: If provided, only clear keys containing this pattern
    """
    global _admin_cache, _cache_timestamps
    
    if pattern:
        keys_to_remove = [k for k in _admin_cache.keys() if pattern in k]
        for key in keys_to_remove:
            _admin_cache.pop(key, None)
            _cache_timestamps.pop(key, None)
        logger.info(f"Cleared {len(keys_to_remove)} cache entries matching pattern: {pattern}")
    else:
        _admin_cache.clear()
        _cache_timestamps.clear()
        logger.info("Cleared entire admin panel cache")


def get_cache_stats():
    """Get current cache statistics."""
    current_time = time.time()
    active_entries = sum(1 for ts in _cache_timestamps.values() 
                        if current_time - ts < CACHE_TIMEOUT)
    
    return {
        'total_entries': len(_admin_cache),
        'active_entries': active_entries,
        'expired_entries': len(_admin_cache) - active_entries,
        'cache_size_mb': sum(len(str(v)) for v in _admin_cache.values()) / (1024 * 1024)
    }


# Database query performance monitoring
query_times = []
slow_query_threshold = 1.0  # seconds

@event.listens_for(Engine, "before_cursor_execute")
def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Record query start time."""
    context._query_start_time = time.time()


@event.listens_for(Engine, "after_cursor_execute")
def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Record query execution time and log slow queries."""
    total = time.time() - context._query_start_time
    query_times.append(total)
    
    # Keep only recent query times (last 100)
    if len(query_times) > 100:
        query_times.pop(0)
    
    # Log slow queries
    if total > slow_query_threshold:
        logger.warning(f"Slow query detected: {total:.3f}s - {statement[:200]}{'...' if len(statement) > 200 else ''}")


def get_database_performance_stats():
    """Get database performance statistics."""
    if not query_times:
        return {
            'avg_query_time': 0,
            'max_query_time': 0,
            'min_query_time': 0,
            'slow_queries': 0,
            'total_queries': 0
        }
    
    slow_queries = sum(1 for t in query_times if t > slow_query_threshold)
    
    return {
        'avg_query_time': sum(query_times) / len(query_times),
        'max_query_time': max(query_times),
        'min_query_time': min(query_times),
        'slow_queries': slow_queries,
        'total_queries': len(query_times)
    }


def optimize_admin_queries():
    """
    Performance optimization decorator for admin routes.
    
    This decorator:
    - Times route execution
    - Monitors memory usage
    - Provides performance warnings
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                # Log performance metrics
                if execution_time > 2.0:  # Slow route threshold
                    logger.warning(f"Slow admin route: {func.__name__} took {execution_time:.3f}s")
                else:
                    logger.debug(f"Admin route {func.__name__} executed in {execution_time:.3f}s")
                
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"Admin route {func.__name__} failed after {execution_time:.3f}s: {e}")
                raise
                
        return wrapper
    return decorator


# Precomputed statistics cache
class AdminStatsCache:
    """Cache for frequently accessed admin statistics."""
    
    def __init__(self):
        self._stats = {}
        self._last_update = {}
        self._update_interval = 60  # 1 minute
    
    def get_stats(self, stat_name, compute_func):
        """
        Get cached statistics or compute if expired.
        
        Args:
            stat_name: Name of the statistic
            compute_func: Function to compute the statistic
        """
        current_time = time.time()
        
        if (stat_name not in self._stats or 
            stat_name not in self._last_update or
            current_time - self._last_update[stat_name] > self._update_interval):
            
            try:
                self._stats[stat_name] = compute_func()
                self._last_update[stat_name] = current_time
                logger.debug(f"Updated cached stat: {stat_name}")
            except Exception as e:
                logger.error(f"Error computing stat {stat_name}: {e}")
                # Return cached value if available, otherwise default
                if stat_name not in self._stats:
                    self._stats[stat_name] = {}
        
        return self._stats[stat_name]
    
    def invalidate(self, stat_name=None):
        """Invalidate specific stat or all stats."""
        if stat_name:
            self._stats.pop(stat_name, None)
            self._last_update.pop(stat_name, None)
        else:
            self._stats.clear()
            self._last_update.clear()


# Global stats cache instance
admin_stats_cache = AdminStatsCache()


def preload_admin_data():
    """
    Preload commonly accessed admin data to improve response times.
    This should be called during application startup or periodically.
    """
    try:
        from app.models import User, Match, Team, Season
        from app.models.admin_config import AdminAuditLog
        
        # Preload user statistics
        admin_stats_cache.get_stats('user_stats', lambda: {
            'total_users': User.query.count(),
            'active_users': User.query.filter_by(is_active=True).count(),
            'pending_approvals': User.query.filter_by(approved=False).count()
        })
        
        # Preload match statistics
        admin_stats_cache.get_stats('match_stats', lambda: {
            'total_matches': Match.query.count(),
            'upcoming_matches': Match.query.filter(Match.date >= datetime.utcnow().date()).count(),
            'teams_count': Team.query.count()
        })
        
        # Preload recent activity
        admin_stats_cache.get_stats('recent_activity', lambda:
            AdminAuditLog.query.order_by(AdminAuditLog.timestamp.desc()).limit(10).all()
        )
        
        logger.info("Admin data preloading completed")
        
    except Exception as e:
        logger.error(f"Error preloading admin data: {e}")


def get_performance_report():
    """Generate a comprehensive performance report for the admin panel."""
    cache_stats = get_cache_stats()
    db_stats = get_database_performance_stats()
    
    return {
        'timestamp': datetime.utcnow().isoformat(),
        'cache': cache_stats,
        'database': db_stats,
        'recommendations': _generate_performance_recommendations(cache_stats, db_stats)
    }


def _generate_performance_recommendations(cache_stats, db_stats):
    """Generate performance improvement recommendations."""
    recommendations = []
    
    # Cache recommendations
    if cache_stats['cache_size_mb'] > 50:
        recommendations.append("Consider reducing cache size or implementing cache eviction")
    
    if cache_stats['expired_entries'] > cache_stats['active_entries']:
        recommendations.append("High cache miss ratio - consider increasing cache timeout")
    
    # Database recommendations
    if db_stats['slow_queries'] > 5:
        recommendations.append(f"High number of slow queries ({db_stats['slow_queries']}) - review query optimization")
    
    if db_stats['avg_query_time'] > 0.5:
        recommendations.append("Average query time is high - consider adding database indexes")
    
    return recommendations


# Cleanup function to be called periodically
def cleanup_performance_data():
    """Clean up old performance data to prevent memory leaks."""
    global query_times
    
    # Clean up expired cache entries
    current_time = time.time()
    expired_keys = [k for k, ts in _cache_timestamps.items() 
                   if current_time - ts > CACHE_TIMEOUT * 2]
    
    for key in expired_keys:
        _admin_cache.pop(key, None)
        _cache_timestamps.pop(key, None)
    
    # Keep only recent query times
    if len(query_times) > 200:
        query_times = query_times[-100:]
    
    logger.debug(f"Performance cleanup: removed {len(expired_keys)} expired cache entries")