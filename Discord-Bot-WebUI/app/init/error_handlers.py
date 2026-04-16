# app/init/error_handlers.py

"""
Error Handlers

HTTP error handlers and exception handling.
Provides secure error responses that don't leak sensitive information.
"""

import logging

from flask import request, redirect, url_for, render_template, session as flask_session, jsonify
from werkzeug.routing import BuildError
from werkzeug.routing.exceptions import WebsocketMismatch
from werkzeug.exceptions import HTTPException
from flask_limiter.errors import RateLimitExceeded

from app.alert_helpers import show_error

logger = logging.getLogger(__name__)

# Safe error messages for production (don't leak internal details)
SAFE_ERROR_MESSAGES = {
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    408: 'Request Timeout',
    409: 'Conflict',
    413: 'Request Too Large',
    415: 'Unsupported Media Type',
    422: 'Unprocessable Entity',
    429: 'Too Many Requests',
    500: 'Internal Server Error',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
}


def _is_api_request():
    """Check if the current request expects a JSON response."""
    return (
        request.path.startswith('/api/') or
        request.path.startswith('/admin-panel/api/') or
        request.path.startswith('/mobile-api/') or
        request.path.startswith('/external-api/') or
        request.headers.get('Accept', '').startswith('application/json') or
        request.content_type == 'application/json' or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


def _get_safe_error_message(status_code, default='An error occurred'):
    """Get a safe error message that doesn't expose internal details."""
    return SAFE_ERROR_MESSAGES.get(status_code, default)


def _compute_retry_after(error) -> int:
    """Extract Retry-After seconds from a Flask-Limiter exception, fallback to 60.

    ``RateLimitExceeded.limit`` wraps a ``limits.RateLimitItem`` whose
    ``get_expiry()`` returns the window length in seconds — the worst-case
    wait under the fixed-window strategy. Matches what Flask-Limiter itself
    emits in its ``Retry-After`` header.
    """
    try:
        if isinstance(error, RateLimitExceeded) and getattr(error, 'limit', None):
            item = error.limit.limit  # limits.RateLimitItem
            seconds = int(item.get_expiry())
            if seconds > 0:
                return seconds
    except Exception:
        pass
    # Werkzeug TooManyRequests may populate .retry_after on some versions.
    retry = getattr(error, 'retry_after', None)
    if isinstance(retry, (int, float)) and retry > 0:
        return int(retry)
    return 60


def install_error_handlers(app):
    """
    Install custom error handlers with the Flask application.

    Args:
        app: The Flask application instance.
    """

    @app.errorhandler(WebsocketMismatch)
    def handle_websocket_mismatch(error):
        """Handle WebSocket mismatch errors."""
        app.logger.warning(f"WebSocket mismatch for {request.path} - this should be rare now")
        return None

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        """Handle 405 errors with detailed logging for debugging."""
        app.logger.error(
            f"405 Method Not Allowed: {request.method} {request.url} | "
            f"Valid methods: {error.valid_methods} | "
            f"User-Agent: {request.headers.get('User-Agent', 'unknown')[:100]}"
        )
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Method Not Allowed',
                'detail': f'{request.method} is not allowed for {request.path}',
                'allowed_methods': list(error.valid_methods or []),
                'status_code': 405
            }), 405
        return render_template("500_flowbite.html"), 405

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Handle unexpected exceptions with secure error messages."""
        # Log the full error internally (not exposed to user)
        app.logger.error(
            f"Unhandled Exception: {error} | "
            f"{request.method} {request.url}",
            exc_info=True
        )

        # Determine status code
        if isinstance(error, HTTPException):
            status_code = error.code
        else:
            status_code = 500

        # Return JSON for API requests
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': _get_safe_error_message(status_code),
                'status_code': status_code
            }), status_code

        # Return HTML for browser requests
        # Try to render template, fallback to plain text if session unavailable (Redis down)
        try:
            template = f"{status_code}_flowbite.html" if status_code in [403, 404, 500] else "500_flowbite.html"
            return render_template(template), status_code
        except Exception:
            # Fallback to simple error page if specific template fails
            try:
                return render_template("500_flowbite.html"), status_code
            except Exception:
                # Session unavailable (Redis down) - return minimal response
                return _get_safe_error_message(status_code), status_code, {'Content-Type': 'text/plain'}

    @app.errorhandler(401)
    def unauthorized(error):
        """Handle unauthorized access."""
        next_url = request.path
        if next_url != '/':
            flask_session['next'] = next_url
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def forbidden(error):
        """Handle 403 forbidden — used for banned IPs. Minimal response, no logging."""
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Forbidden',
                'status_code': 403
            }), 403
        return '', 403

    # Paths that 404 so often they drown real 404s: browser auto-requests for
    # favicons/apple-touch-icons and the known stale mobile-client prefix
    # /api/v1/v1/... (client-side bug, real fix lives in the RN app).
    QUIET_404_PATHS = (
        '/favicon.ico',
        '/apple-touch-icon.png',
        '/apple-touch-icon-precomposed.png',
        '/apple-touch-icon-120x120.png',
        '/apple-touch-icon-120x120-precomposed.png',
        '/api/v1/v1/',
    )

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 not found errors."""
        path = request.path
        if any(path == p or path.startswith(p) for p in QUIET_404_PATHS):
            logger.debug(f"404 (suppressed): {path}")
        else:
            logger.warning(f"404 error: {path}")

        # Return JSON for API requests
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Not Found',
                'status_code': 404
            }), 404

        return render_template("404_flowbite.html"), 404

    @app.errorhandler(429)
    def handle_too_many_requests(error):
        """Handle 429 with Retry-After derived from the tripped Flask-Limiter rule."""
        retry_after = _compute_retry_after(error)

        if _is_api_request():
            response = jsonify({
                'success': False,
                'error': 'Too Many Requests',
                'message': 'Rate limit exceeded. Please wait before retrying.',
                'retry_after_seconds': retry_after,
                'status_code': 429,
            })
        else:
            try:
                response = app.make_response(render_template("500_flowbite.html"))
            except Exception:
                response = app.make_response(('Too Many Requests', 429))

        response.status_code = 429
        response.headers['Retry-After'] = str(retry_after)

        # Preserve Flask-Limiter's X-RateLimit-* headers from the exception.
        if isinstance(error, RateLimitExceeded):
            try:
                for k, v in (error.get_headers() or []):
                    if k.lower() == 'retry-after':
                        continue  # don't clobber our own computed value
                    response.headers.setdefault(k, v)
            except Exception:
                pass

        return response

    @app.errorhandler(BuildError)
    def handle_url_build_error(error):
        """Handle URL build errors."""
        logger.error(f"URL build error: {str(error)}")
        if 'main.index' in str(error):
            try:
                return redirect(url_for('main.index'))
            except:
                return redirect('/')
        show_error('An error occurred while redirecting. You have been returned to the home page.')
        return redirect('/')
