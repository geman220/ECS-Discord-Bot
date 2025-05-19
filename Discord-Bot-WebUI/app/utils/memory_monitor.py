# app/utils/memory_monitor.py

"""
Memory Monitor Module

This module provides utilities for monitoring application memory usage,
detecting potential memory leaks, and taking proactive actions to prevent
out-of-memory conditions. It's designed for environments with limited resources.
"""

import logging
import time
import gc
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MemoryMonitor:
    """
    A utility class for monitoring memory usage of the application.
    
    This class provides methods to check current memory usage,
    log warnings when usage exceeds thresholds, and trigger garbage
    collection when necessary.
    """
    
    def __init__(self, app=None):
        """
        Initialize the MemoryMonitor.
        
        Args:
            app: Optional Flask application instance.
        """
        self.app = app
        self.memory_history = []
        self.last_check = time.time()
        self.check_interval = 300  # Check every 5 minutes by default
        self.threshold_mb = 3000   # 3GB threshold for 4GB environment
        self.critical_threshold_mb = 3500  # 3.5GB threshold for critical warning
        
        # Initialize with Flask app if provided
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """
        Configure with Flask application.
        
        Args:
            app: Flask application instance.
        """
        self.app = app
        
        # Set configuration from Flask app
        self.threshold_mb = app.config.get('MEMORY_WARNING_THRESHOLD_MB', 3000)
        self.critical_threshold_mb = app.config.get('MEMORY_CRITICAL_THRESHOLD_MB', 3500)
        self.check_interval = app.config.get('MEMORY_CHECK_INTERVAL', 300)
        
        # Register teardown handler
        app.teardown_appcontext(self.check_memory)
    
    def check_memory(self, exception=None):
        """
        Check current memory usage and take action if thresholds are exceeded.
        
        This method should be called periodically, possibly at the end of 
        web requests or during idle periods in background workers.
        
        Args:
            exception: Optional exception that occurred during request.
        """
        current_time = time.time()
        
        # Only check periodically to reduce overhead
        if current_time - self.last_check < self.check_interval:
            return
            
        self.last_check = current_time
        
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            # Convert to MB for easier reading
            memory_mb = memory_info.rss / (1024 * 1024)
            
            # Record in history (keep last 24 data points = 2 hours at 5 min intervals)
            self.memory_history.append({
                'timestamp': datetime.now(),
                'memory_mb': memory_mb
            })
            
            # Trim history to last 24 points
            if len(self.memory_history) > 24:
                self.memory_history = self.memory_history[-24:]
            
            # Check if memory usage is increasing over time (possible leak)
            self._check_memory_trend()
            
            # Take action based on memory usage
            if memory_mb > self.critical_threshold_mb:
                logger.warning(f"CRITICAL: Memory usage very high at {memory_mb:.1f}MB!")
                self._take_emergency_action()
            elif memory_mb > self.threshold_mb:
                logger.warning(f"High memory usage: {memory_mb:.1f}MB")
                # Force garbage collection
                collected = gc.collect()
                logger.info(f"Garbage collection freed {collected} objects")
                
            return {
                'memory_mb': memory_mb,
                'threshold_mb': self.threshold_mb,
                'critical_threshold_mb': self.critical_threshold_mb
            }
        
        except ImportError:
            logger.warning("Cannot monitor memory: psutil library not available")
            return None
        except Exception as e:
            logger.error(f"Error checking memory: {e}")
            return None
    
    def _check_memory_trend(self):
        """
        Analyze memory usage history to detect potential leaks.
        
        Checks if memory usage has been continuously increasing over
        the recorded history, which might indicate a memory leak.
        """
        if len(self.memory_history) < 6:
            return  # Need more data points for trend analysis
            
        # Check if memory has been increasing in the last 6 checks
        increasing = True
        for i in range(len(self.memory_history) - 1, len(self.memory_history) - 6, -1):
            if self.memory_history[i]['memory_mb'] <= self.memory_history[i-1]['memory_mb']:
                increasing = False
                break
                
        if increasing:
            # Calculate growth rate
            first = self.memory_history[-6]['memory_mb']
            last = self.memory_history[-1]['memory_mb']
            growth_mb = last - first
            growth_percent = (growth_mb / first) * 100 if first > 0 else 0
            
            if growth_percent > 10:  # More than 10% growth in 30 minutes
                logger.warning(
                    f"Potential memory leak detected! "
                    f"Memory increased by {growth_mb:.1f}MB ({growth_percent:.1f}%) in 30 minutes"
                )
    
    def _take_emergency_action(self):
        """
        Take emergency actions when memory usage is critically high.
        
        This method performs aggressive cleanup to try to prevent an OOM (Out Of Memory) error.
        """
        logger.warning("Taking emergency actions to reduce memory usage")
        
        # 1. Aggressive garbage collection
        gc.collect(2)  # Full collection
        
        # 2. Clear any module caches if possible
        try:
            from app.database.cache import cache
            if hasattr(cache, 'clear'):
                cache.clear()
                logger.info("Cleared Flask-Caching cache")
        except (ImportError, AttributeError):
            pass
            
        # 3. Clear in-memory static file versioning cache
        try:
            from app.extensions import file_versioning
            if hasattr(file_versioning, 'version_cache'):
                file_versioning.version_cache.clear()
                logger.info("Cleared static file versioning cache")
        except (ImportError, AttributeError):
            pass

# Create a global instance
memory_monitor = MemoryMonitor()

def check_memory_usage():
    """
    Convenience function to check memory usage.
    
    Can be called from anywhere in the application.
    
    Returns:
        Dict containing memory usage information or None if check failed.
    """
    return memory_monitor.check_memory()

def get_memory_stats():
    """
    Get detailed memory statistics.
    
    Returns:
        Dict containing memory usage statistics.
    """
    try:
        import psutil
        process = psutil.Process()
        
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)
        
        # System memory info
        system_memory = psutil.virtual_memory()
        system_memory_used_percent = system_memory.percent
        
        # Get current trend if available
        trend = "stable"
        if memory_monitor.memory_history and len(memory_monitor.memory_history) > 1:
            first = memory_monitor.memory_history[0]['memory_mb']
            last = memory_monitor.memory_history[-1]['memory_mb']
            if last > first * 1.1:  # 10% increase
                trend = "increasing"
            elif last < first * 0.9:  # 10% decrease
                trend = "decreasing"
        
        return {
            'process_memory_mb': memory_mb,
            'system_memory_used_percent': system_memory_used_percent,
            'memory_trend': trend,
            'history_points': len(memory_monitor.memory_history),
            'threshold_mb': memory_monitor.threshold_mb,
            'critical_threshold_mb': memory_monitor.critical_threshold_mb
        }
    except Exception as e:
        logger.error(f"Error getting memory stats: {e}")
        return {
            'error': str(e)
        }