# app/core/limiter.py

"""
Module-level Flask-Limiter singleton and key helpers.

Imported by blueprint modules at load time so ``@limiter.limit(...)`` decorators
can be applied before the Flask app is fully constructed. The real storage
backend and request filters are bound later via ``limiter.init_app(app)`` from
``app/init/middleware.py::_init_rate_limiting``.
"""

import logging
import os

from flask import request, current_app
from flask_limiter import Limiter

logger = logging.getLogger(__name__)


def get_client_ip() -> str:
    """Return the real client IP, reading only the parts of X-Forwarded-For we trust.

    SECURITY: this used to return ``xff.split(',')[0]`` — the LEFTMOST entry. XFF is
    built by each proxy APPENDING the peer it actually saw, so everything to the left
    of our own proxy's contribution was supplied by the client and is forgeable. An
    attacker could send a random ``X-Forwarded-For`` on every request and mint a fresh
    rate-limit bucket each time, defeating every IP-keyed limit in the app — including
    the login limit that exists to stop an unauthenticated scrypt CPU-DoS.

    With N trusted proxies in front of us, the client's real address is the Nth entry
    from the RIGHT. We run a single Traefik, so N defaults to 1 (the rightmost entry
    is the address Traefik itself observed). If you ever put Cloudflare in front of
    Traefik, set TRUSTED_PROXY_COUNT=2 — otherwise every user would collapse into one
    bucket keyed on Cloudflare's edge IP.

    X-Real-IP / CF-Connecting-IP are NOT consulted: nothing in this deployment sets
    them, so they are pure client input and equally forgeable.
    """
    try:
        trusted = int(os.getenv('TRUSTED_PROXY_COUNT', '1'))
    except (TypeError, ValueError):
        trusted = 1
    trusted = max(1, trusted)

    xff = request.headers.get('X-Forwarded-For')
    if xff:
        parts = [p.strip() for p in xff.split(',') if p.strip()]
        if parts:
            idx = len(parts) - trusted
            return parts[idx] if 0 <= idx < len(parts) else parts[0]

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
