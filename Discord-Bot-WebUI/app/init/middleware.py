# app/init/middleware.py

"""
Middleware Configuration

Apply ProxyFix, security middleware, rate limiting, session persistence, and debug middleware.
"""

import logging
from flask import request
from werkzeug.middleware.proxy_fix import ProxyFix

logger = logging.getLogger(__name__)


class SessionPersistenceMiddleware:
    """Middleware to ensure session persistence."""

    def __init__(self, app, flask_app):
        self.app = app
        self.flask_app = flask_app
        self.logger = logging.getLogger(__name__)

    def __call__(self, environ, start_response):
        def session_aware_start_response(status, headers, exc_info=None):
            # Process the session before sending the response
            if hasattr(self.flask_app, 'session_interface') and 'flask.session' in environ:
                session = environ['flask.session']
                if session and session.modified:
                    self.logger.debug(
                        f"Ensuring session is persisted in middleware: "
                        f"{session.sid if hasattr(session, 'sid') else 'unknown'}"
                    )
                    session.permanent = True
            return start_response(status, headers, exc_info)

        return self.app(environ, session_aware_start_response)


class DebugMiddleware:
    """Middleware for debug logging in development mode."""

    def __init__(self, wsgi_app, app):
        self.wsgi_app = wsgi_app
        self.flask_app = app

    def __call__(self, environ, start_response):
        with self.flask_app.app_context():
            with self.flask_app.request_context(environ):
                # Only log critical path information at INFO level
                path = environ.get('PATH_INFO')
                if not path.startswith('/static/') and not path.startswith('/test/status/'):
                    logger.info(f"{environ.get('REQUEST_METHOD')} {path}")

                def debug_start_response(status, headers, exc_info=None):
                    # Only log non-200 responses
                    if not status.startswith('200'):
                        logger.info(f"Response Status: {status} for {environ.get('PATH_INFO')}")
                    return start_response(status, headers, exc_info)

                try:
                    response = self.wsgi_app(environ, debug_start_response)
                    return response
                except Exception as e:
                    logger.error(f"Error in request: {str(e)}", exc_info=True)
                    raise


def apply_middleware(app):
    """
    Apply all middleware to the Flask application.

    Args:
        app: The Flask application instance.
    """
    # Apply ProxyFix to handle reverse proxy headers
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Add security middleware (non-breaking implementation)
    from app.security_middleware import SecurityMiddleware
    security_middleware = SecurityMiddleware(app)

    # Add rate limiting (with Redis backend)
    _init_rate_limiting(app)

    # Apply session persistence middleware
    app.wsgi_app = SessionPersistenceMiddleware(app.wsgi_app, app)

    # Add basic security headers
    _add_security_headers(app)

    # Add API request logging for analytics
    _init_api_logger(app)

    # Apply DebugMiddleware in debug mode
    if app.debug:
        app.wsgi_app = DebugMiddleware(app.wsgi_app, app)
        logger.info("Debug mode enabled with request logging")


def _init_rate_limiting(app):
    """Initialize rate limiting with Redis backend."""
    try:
        from flask_limiter import Limiter

        def get_client_ip():
            """
            Get real client IP, with security considerations.

            IMPORTANT: This relies on the reverse proxy (Traefik/nginx) being
            configured to set X-Forwarded-For correctly and strip any client-provided
            X-Forwarded-For headers. ProxyFix is applied in apply_middleware().
            """
            if request.headers.get('X-Forwarded-For'):
                # First IP in chain is the original client (set by trusted proxy)
                client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
            elif request.headers.get('X-Real-IP'):
                client_ip = request.headers.get('X-Real-IP')
            elif request.headers.get('CF-Connecting-IP'):
                client_ip = request.headers.get('CF-Connecting-IP')
            else:
                client_ip = request.remote_addr or 'unknown'
            return client_ip

        def is_internal_request():
            """
            Check if request is internal (container-to-container, not through proxy).

            Logic:
            - External requests come through reverse proxy (Traefik) which sets
              X-Forwarded-For header with the real client IP
            - Internal container-to-container calls don't go through proxy,
              so they won't have X-Forwarded-For set by the proxy

            Security model:
            - If X-Forwarded-For exists → came through proxy → external → rate limit
            - If no X-Forwarded-For AND remote_addr is Docker network → internal → exempt
            - Localhost always exempt (health checks, CLI tools)
            """
            peer_ip = request.remote_addr or ''

            # Localhost is always internal (health checks, CLI)
            if peer_ip in ('127.0.0.1', '::1'):
                return True

            # If request has X-Forwarded-For, it came through the reverse proxy
            # This means it's external traffic (user → Traefik → app)
            if request.headers.get('X-Forwarded-For'):
                return False

            # No X-Forwarded-For + private network IP = internal/local call
            # (e.g., Celery worker, local dev machine, another microservice)
            # RFC 1918 private ranges: 10.x, 172.16-31.x, 192.168.x
            if (peer_ip.startswith('172.') or
                peer_ip.startswith('10.') or
                peer_ip.startswith('192.168.')):
                return True

            return False

        redis_url = app.config.get('REDIS_URL', 'redis://redis:6379/0')

        limiter = Limiter(
            app=app,
            key_func=get_client_ip,
            storage_uri=redis_url,
            default_limits=["5000 per day", "2000 per hour", "200 per minute"],
            headers_enabled=True,
            strategy="fixed-window"
        )

        # Exempt truly internal traffic (Docker containers, localhost)
        # External traffic through reverse proxy will still be rate limited
        @limiter.request_filter
        def skip_internal_traffic():
            return is_internal_request()

        # Exempt background polling endpoints from rate limiting
        # These are legitimate automated requests that run on every page, not abuse
        @limiter.request_filter
        def skip_polling_endpoints():
            exempt_paths = [
                # Health checks
                '/api/health/',

                # Socket.IO - makes rapid requests during connection/messaging
                # Rate limiting Socket.IO causes 429 errors and connection failures
                '/socket.io/',

                # Presence/online status (polls every 30-120s on every page)
                '/api/notifications/presence/',

                # Notification counts (polls every 60s on every page)
                '/api/notifications/count',

                # Message unread counts (polls every 60s on every page)
                '/api/messages/unread-count',

                # Admin dashboard polling endpoints (polls every 30-60s for admin users)
                # These are authenticated admin-only endpoints, not abuse vectors
                '/security/status',
                '/security/events',
                '/security/logs',
                '/bot/admin/get_all_match_statuses',

                # Email broadcast progress polling (polls every 5s during send)
                '/admin-panel/api/email-broadcasts/',
            ]
            return any(request.path.startswith(path) for path in exempt_paths)

        app.limiter = limiter
        logger.info("Rate limiting initialized with Redis backend")

    except Exception as e:
        logger.warning(f"Rate limiting initialization failed: {e}")


def _add_security_headers(app):
    """Add security headers to all responses."""

    @app.after_request
    def add_security_headers(response):
        """Add basic security headers to all responses."""
        if not request.path.startswith('/static/'):
            response.headers.update({
                'X-Content-Type-Options': 'nosniff',
                'X-Frame-Options': 'SAMEORIGIN',
                'X-XSS-Protection': '1; mode=block',
                'Referrer-Policy': 'strict-origin-when-cross-origin',
                'Server': 'ECS Portal'
            })

            # Add HSTS for HTTPS connections
            if request.is_secure:
                response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        return response


def _init_api_logger(app):
    """Initialize API request logging for analytics."""
    try:
        from app.middleware.api_logger import init_api_logger
        init_api_logger(app)
    except Exception as e:
        logger.warning(f"API logger initialization failed: {e}")
