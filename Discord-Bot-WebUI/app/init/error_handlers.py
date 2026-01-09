# app/init/error_handlers.py

"""
Error Handlers

HTTP error handlers and exception handling.
"""

import logging

from flask import request, redirect, url_for, render_template, session as flask_session
from werkzeug.routing import BuildError
from werkzeug.routing.exceptions import WebsocketMismatch

from app.alert_helpers import show_error

logger = logging.getLogger(__name__)


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
        """Handle unexpected exceptions."""
        app.logger.error(f"Unhandled Exception: {error}", exc_info=True)
        return render_template("500_flowbite.html"), 500

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
