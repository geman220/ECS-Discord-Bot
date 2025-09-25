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
    """Check celery health by testing Redis connectivity."""
    try:
        import redis
        r = redis.Redis(host="redis", port=6379, db=0, socket_timeout=3)
        r.ping()
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