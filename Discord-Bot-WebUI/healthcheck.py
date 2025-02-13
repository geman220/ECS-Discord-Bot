# healthcheck.py

"""
Healthcheck Script

This script checks the health of the Redis server by attempting to ping it.
If the check passes, the script exits with a status code of 0; otherwise, it exits with 1.
"""

import os
import sys
from redis import Redis


def check_redis_health():
    """
    Check the health of the Redis server.

    Returns:
        bool: True if Redis responds to a ping, False otherwise.
    """
    try:
        redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
        redis_client = Redis.from_url(redis_url, socket_timeout=2)
        return redis_client.ping()
    except Exception as e:
        print(f"Redis healthcheck failed: {str(e)}")
        return False


if __name__ == "__main__":
    if check_redis_health():
        sys.exit(0)
    sys.exit(1)