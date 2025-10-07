# healthcheck.py

"""
Universal Healthcheck Script

This script detects the service type and runs appropriate health checks:
- Webui: HTTP health endpoint
- Celery: Redis connectivity check
"""

import sys
import os


def check_webui_health():
    """Check webui health by hitting the HTTP health endpoint."""
    try:
        import requests
        resp = requests.get("http://localhost:5000/api/health/", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def check_celery_health():
    """Check celery health by testing if worker process is running and responding."""
    try:
        import redis
        import psutil
        import time

        # First check Redis connectivity
        r = redis.Redis(host="redis", port=6379, db=0, socket_timeout=3)
        r.ping()

        # Check if celery worker process exists and is running
        worker_found = False
        for proc in psutil.process_iter(['name', 'cmdline', 'status']):
            try:
                if proc.info['cmdline']:
                    cmdline = ' '.join(proc.info['cmdline'])
                    # Look for celery worker process
                    if 'celery' in cmdline and 'worker' in cmdline:
                        worker_found = True
                        # Check if process is not zombie/dead
                        if proc.info['status'] in ['zombie', 'dead']:
                            return False
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not worker_found:
            return False

        # Write heartbeat to Redis (worker-specific key)
        hostname = os.getenv('HOSTNAME', 'unknown')
        heartbeat_key = f"celery:worker_heartbeat:{hostname}"
        r.setex(heartbeat_key, 60, int(time.time()))

        return True
    except Exception:
        return False


def detect_service_type():
    """Detect what type of service this is based on environment or process."""
    # Check if this is likely a webui process (gunicorn running)
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'cmdline']):
            if proc.info['name'] in ['gunicorn', 'python'] and proc.info['cmdline']:
                cmdline = ' '.join(proc.info['cmdline'])
                if 'gunicorn' in cmdline or 'wsgi:application' in cmdline:
                    return 'webui'
    except:
        pass

    # Check environment variables
    if os.getenv('CELERY_WORKER') == '1':
        return 'celery'

    # Default to celery for safety (Redis check is simpler)
    return 'celery'


if __name__ == "__main__":
    service_type = detect_service_type()

    if service_type == 'webui':
        success = check_webui_health()
    else:
        success = check_celery_health()

    sys.exit(0 if success else 1)