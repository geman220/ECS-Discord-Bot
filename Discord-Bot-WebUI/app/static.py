# app/static.py

"""
Static File Serving Module

This module configures custom static file serving for the Flask application.
It provides secure path handling, ETag caching, and proper content type and
cache-control headers when serving static files.
"""

import logging
import mimetypes
from pathlib import Path

from flask import current_app, request, send_from_directory
from werkzeug.utils import safe_join
from app.database.cache import cache_static_file

logger = logging.getLogger(__name__)


def configure_static_serving(app):
    """
    Configure custom static file serving for the given Flask application.

    Sets up a route to serve static files with enhanced security,
    caching headers, and correct content types.
    """
    static_folder = Path(app.static_folder)

    @app.route('/static/<path:filename>')
    @cache_static_file()
    def serve_static(filename):
        """
        Serve a static file with security and caching enhancements.

        - Securely joins the file path.
        - Returns a 404 page if the file does not exist.
        - Handles ETag caching (returns 304 if appropriate).
        - Sets proper content type and security headers.
        - Returns a 500 page if an error occurs.

        Args:
            filename (str): The requested file name.

        Returns:
            A Flask response object.
        """
        try:
            # Securely join the requested filename to the static folder path.
            file_path = safe_join(static_folder, filename)
            if not file_path or not Path(file_path).exists():
                return app.send_static_file('404.html'), 404

            # ETag handling: if the client's ETag matches and not in debug mode, return 304.
            if request.if_none_match and not current_app.config.get('DEBUG', False):
                response = current_app.make_response("")
                response.status_code = 304
                return response

            # Serve the file from the static directory.
            response = send_from_directory(static_folder, filename)

            # Determine and set the correct content type.
            content_type = mimetypes.guess_type(filename)[0]
            if content_type:
                response.headers['Content-Type'] = content_type

            # Set additional headers for caching and security.
            # Add immutable flag for static assets that won't change
            is_immutable = filename.endswith(('.js', '.css', '.woff', '.woff2', '.ttf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico'))
            response.headers.update({
                'Cache-Control': f'public, max-age=31536000{", immutable" if is_immutable else ""}',
                'X-Content-Type-Options': 'nosniff',
                'Access-Control-Allow-Origin': '*'
            })
            return response

        except Exception as e:
            logger.error(f"Static file error: {e}")
            return app.send_static_file('500.html'), 500