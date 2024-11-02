from redis import Redis
import sys
import os

def check_redis_health():
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