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
            """Get real client IP from proxy headers."""
            if request.headers.get('X-Forwarded-For'):
                client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
            elif request.headers.get('X-Real-IP'):
                client_ip = request.headers.get('X-Real-IP')
            elif request.headers.get('CF-Connecting-IP'):
                client_ip = request.headers.get('CF-Connecting-IP')
            else:
                client_ip = request.remote_addr or 'unknown'

            # Exempt local and Docker network traffic from rate limiting
            local_networks = ['127.0.0.1', '172.18.0.1', 'host.docker.internal']

            if (client_ip.startswith('172.') or
                client_ip.startswith('192.168.') or
                client_ip.startswith('10.') or
                client_ip in local_networks):
                return 'local_exempted'

            return client_ip

        redis_url = app.config.get('REDIS_URL', 'redis://redis:6379/0')

        limiter = Limiter(
            app=app,
            key_func=get_client_ip,
            storage_uri=redis_url,
            default_limits=["5000 per day", "2000 per hour", "200 per minute"],
            headers_enabled=True,
            strategy="fixed-window"
        )

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
