# healthcheck.py

"""
Healthcheck Script

This script checks the health of the Redis server by attempting to ping it.
If the check passes, the script exits with a status code of 0; otherwise, it exits with 1.

Highly optimized version to reduce CPU usage with minimal dependencies.
"""

import os
import sys
import time

# Shared cache between process invocations (via file system)
CACHE_FILE = "/tmp/redis_health_status"
CACHE_TTL = 15  # Cache result for 15 seconds


def check_redis_health():
    """
    Check Redis health using the Redis Python library.
    
    Returns:
        bool: True if Redis responds to a ping, False otherwise.
    """
    # Try to use cached result first to avoid repeated checks
    try:
        if os.path.exists(CACHE_FILE):
            mtime = os.path.getmtime(CACHE_FILE)
            if time.time() - mtime < CACHE_TTL:
                with open(CACHE_FILE, 'r') as f:
                    cached_status = f.read().strip()
                    return cached_status == "OK"
    except:
        # Ignore any errors with the cache file
        pass
    
    try:
        # Use shared Redis connection manager to prevent connection leaks
        from app.utils.redis_manager import get_redis_connection
        
        # Get Redis connection using the singleton manager
        r = get_redis_connection()
        
        # Ping Redis to check if it's responsive
        result = r.ping()
        
        # Cache the result
        try:
            with open(CACHE_FILE, 'w') as f:
                f.write("OK" if result else "FAIL")
        except:
            pass
            
        return result
    except Exception as e:
        try:
            # Cache the failure
            with open(CACHE_FILE, 'w') as f:
                f.write("FAIL")
        except:
            pass
        return False


if __name__ == "__main__":
    if check_redis_health():
        sys.exit(0)
    sys.exit(1)