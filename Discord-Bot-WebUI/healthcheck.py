# healthcheck.py

"""
Healthcheck Script

This script checks the health of the webui service by making an HTTP request
to the health endpoint. This avoids potential threading issues with Redis connections.
"""

import sys


def check_webui_health():
    """
    Check webui health by hitting the HTTP health endpoint.

    Returns:
        bool: True if the health endpoint responds with 200, False otherwise.
    """
    try:
        import requests
        resp = requests.get("http://localhost:5000/api/health/", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    if check_webui_health():
        sys.exit(0)
    sys.exit(1)