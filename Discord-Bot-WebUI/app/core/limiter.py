# app/core/limiter.py

"""
Module-level Flask-Limiter singleton and key helpers.

Imported by blueprint modules at load time so ``@limiter.limit(...)`` decorators
can be applied before the Flask app is fully constructed. The real storage
backend and request filters are bound later via ``limiter.init_app(app)`` from
``app/init/middleware.py::_init_rate_limiting``.
"""

import logging

from flask import request, current_app
from flask_limiter import Limiter

logger = logging.getLogger(__name__)


def get_client_ip() -> str:
    """Return the real client IP, honoring trusted proxy headers."""
    xff = request.headers.get('X-Forwarded-For')
    if xff:
        return xff.split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    if request.headers.get('CF-Connecting-IP'):
        return request.headers.get('CF-Connecting-IP')
    return request.remote_addr or 'unknown'


def is_internal_request() -> bool:
    """True if the request came from localhost or an RFC1918 peer without a proxy hop."""
    peer_ip = request.remote_addr or ''

    # Localhost is always internal (health checks, CLI).
    if peer_ip in ('127.0.0.1', '::1'):
        return True

    # If X-Forwarded-For is set, the request came through the reverse proxy
    # (user -> Traefik -> app), which means it's external traffic.
    if request.headers.get('X-Forwarded-For'):
        return False

    # No XFF + private-network peer = container-to-container or local dev call.
    if (peer_ip.startswith('172.')
            or peer_ip.startswith('10.')
            or peer_ip.startswith('192.168.')):
        return True

    return False


def is_allowlisted_ip() -> bool:
    """True if the current request's IP appears in RATE_LIMIT_ALLOWLIST."""
    try:
        allow = current_app.config.get('RATE_LIMIT_ALLOWLIST') or ()
        if not allow:
            return False
        return get_client_ip() in allow
    except Exception:
        return False


def jwt_or_ip_key() -> str:
    """
    Return ``"user:<uid>"`` if a valid JWT is present, else ``"ip:<addr>"``.

    Uses ``verify_jwt_in_request(optional=True)`` so it's safe to call in key
    funcs that run before ``@jwt_required()`` has executed. Any parse failure
    falls back to IP.
    """
    try:
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        verify_jwt_in_request(optional=True)
        uid = get_jwt_identity()
        if uid is not None:
            return f"user:{uid}"
    except Exception:
        pass
    return f"ip:{get_client_ip()}"


# Module-level singleton. ``storage_uri`` is a safe in-memory fallback that
# gets overridden by ``limiter.init_app(app)`` reading ``RATELIMIT_STORAGE_URL``
# from ``app.config`` inside ``_init_rate_limiting``.
limiter = Limiter(
    key_func=get_client_ip,
    default_limits=["5000 per day", "2000 per hour", "200 per minute"],
    headers_enabled=True,
    strategy="fixed-window",
    storage_uri="memory://",
)
