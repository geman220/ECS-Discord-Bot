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
    Check Redis health using a very simple approach that uses minimal resources.
    
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
        # Use the redis-cli command to check Redis health with minimal overhead
        # This avoids loading the entire Redis Python library
        import subprocess
        
        # Get Redis host and port from environment or use defaults
        redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
        
        # Parse the Redis URL (simple parsing)
        if redis_url.startswith('redis://'):
            parts = redis_url[8:].split('/')
            host_port = parts[0].split(':')
            host = host_port[0] or 'redis'
            port = host_port[1] if len(host_port) > 1 else '6379'
        else:
            host = 'redis'
            port = '6379'
        
        # Use timeout to ensure the command completes quickly
        process = subprocess.Popen(
            ["timeout", "1", "redis-cli", "-h", host, "-p", port, "ping"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for the process to complete with a timeout
        stdout, stderr = process.communicate(timeout=1)
        
        # Check if the output contains "PONG"
        result = stdout.strip().lower() == b'pong'
        
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