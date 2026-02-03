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

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Handle unexpected exceptions with secure error messages."""
        # Log the full error internally (not exposed to user)
        app.logger.error(f"Unhandled Exception: {error}", exc_info=True)

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
            return render_template("500_flowbite.html"), 500
        except Exception:
            # Session unavailable (Redis down) - return minimal response
            return "Internal Server Error", 500, {'Content-Type': 'text/plain'}

    @app.errorhandler(401)
    def unauthorized(error):
        """Handle unauthorized access."""
        next_url = request.path
        if next_url != '/':
            flask_session['next'] = next_url
        return redirect(url_for('auth.login'))

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 not found errors."""
        logger.warning(f"404 error: {request.path}")

        # Return JSON for API requests
        if _is_api_request():
            return jsonify({
                'success': False,
                'error': 'Not Found',
                'status_code': 404
            }), 404

        return render_template("404_flowbite.html"), 404

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
