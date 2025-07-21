"""
Redis Connection Pool Monitoring Utility

This module provides utilities to monitor Redis connection pool health
and automatically clean up connections when approaching limits.
"""

import logging
import threading
import time
from typing import Dict, Any, Optional
from flask import current_app

logger = logging.getLogger(__name__)


class RedisPoolMonitor:
    """Monitor Redis connection pools and provide health metrics."""
    
    def __init__(self, check_interval: int = 60):
        """
        Initialize Redis pool monitor.
        
        Args:
            check_interval: Seconds between health checks
        """
        self.check_interval = check_interval
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        
    def start_monitoring(self):
        """Start background monitoring of Redis connection pools."""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Redis pool monitoring started")
        
    def stop_monitoring(self):
        """Stop background monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Redis pool monitoring stopped")
        
    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._monitoring:
            try:
                self._check_pools()
            except Exception as e:
                logger.error(f"Error in Redis pool monitoring: {e}")
            
            time.sleep(self.check_interval)
            
    def _check_pools(self):
        """Check health of all Redis pools and log warnings if needed."""
        try:
            # Check main Redis pool
            if hasattr(current_app, 'redis_manager'):
                main_stats = current_app.redis_manager.get_connection_stats()
                self._log_pool_health('Main Redis', main_stats)
                
                # Auto-cleanup if utilization is high
                if main_stats.get('utilization_percent', 0) > 80:
                    logger.warning("Main Redis pool utilization > 80%, triggering cleanup")
                    current_app.redis_manager._cleanup_idle_connections()
            
            # Check session Redis pool
            if hasattr(current_app, 'session_redis'):
                session_stats = self._get_session_pool_stats()
                self._log_pool_health('Session Redis', session_stats)
                
        except Exception as e:
            logger.error(f"Error checking Redis pool health: {e}")
            
    def _get_session_pool_stats(self) -> Dict[str, Any]:
        """Get stats for the session Redis pool."""
        stats = {
            'connection_pool': False,
            'in_use': 0,
            'created': 0,
            'max': 0,
            'utilization_percent': 0
        }
        
        try:
            session_redis = current_app.session_redis
            if hasattr(session_redis, 'connection_pool'):
                pool = session_redis.connection_pool
                stats['connection_pool'] = True
                
                if hasattr(pool, '_in_use_connections') and hasattr(pool, '_available_connections'):
                    in_use = len(pool._in_use_connections)
                    created = len(pool._available_connections) + in_use
                    max_conn = pool.max_connections if hasattr(pool, 'max_connections') else 0
                    
                    stats.update({
                        'in_use': in_use,
                        'created': created,
                        'max': max_conn,
                        'utilization_percent': (in_use / max_conn * 100) if max_conn else 0
                    })
                    
        except Exception as e:
            logger.error(f"Error getting session pool stats: {e}")
            
        return stats
        
    def _log_pool_health(self, pool_name: str, stats: Dict[str, Any]):
        """Log pool health information."""
        if not stats.get('connection_pool'):
            return
            
        utilization = stats.get('utilization_percent', 0)
        in_use = stats.get('in_use', 0)
        max_conn = stats.get('max', 0)
        
        if utilization > 90:
            logger.error(f"{pool_name} pool CRITICAL: {in_use}/{max_conn} connections ({utilization:.1f}%)")
        elif utilization > 75:
            logger.warning(f"{pool_name} pool HIGH: {in_use}/{max_conn} connections ({utilization:.1f}%)")
        elif utilization > 50:
            logger.info(f"{pool_name} pool MODERATE: {in_use}/{max_conn} connections ({utilization:.1f}%)")
        else:
            logger.debug(f"{pool_name} pool OK: {in_use}/{max_conn} connections ({utilization:.1f}%)")


# Global monitor instance
_monitor: Optional[RedisPoolMonitor] = None


def get_monitor() -> RedisPoolMonitor:
    """Get the global Redis pool monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = RedisPoolMonitor()
    return _monitor


def start_monitoring():
    """Start Redis pool monitoring."""
    monitor = get_monitor()
    monitor.start_monitoring()


def stop_monitoring():
    """Stop Redis pool monitoring."""
    monitor = get_monitor()
    monitor.stop_monitoring()