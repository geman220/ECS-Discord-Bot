# app/static.py

"""
Static File Serving Module

!! NOT WIRED UP. `configure_static_serving()` is never called anywhere — static files
are served by Flask's own built-in /static route. The live cache-control policy lives
in app/compression.py::init_compression (which IS called, via app/assets.py). Change it
there, not here.

Two things to fix BEFORE ever enabling this module:
  1. `@cache_static_file()` is `cache.memoize(timeout=86400)` keyed only on the
     filename — it is request-insensitive, so it would replay a memoized 200-with-body
     for 24h and never emit a 304.
  2. Confirm the Cache-Control policy below still matches compression.py's.

Kept because it has the correct secure path-traversal handling, and someone clearly
intended to use it.
"""

import logging
import mimetypes
import os
import re
from pathlib import Path

from flask import current_app, request, send_from_directory
from app.database.cache import cache_static_file

# Vite emits content-hashed names like vite-dist/js/main-BRZkLLqg.js — exactly 8
# hash chars. ONLY those may be cached `immutable`, because a rebuild gives them a
# new URL, so the bytes at this URL genuinely never change. Deliberately anchored to
# vite-dist/ and to exactly 8 chars: a looser pattern would falsely match a hand-named
# file like `js/some-verylongname.js` and pin it in every browser cache for a year.
_HASHED_ASSET_RE = re.compile(r'^vite-dist/.*-[A-Za-z0-9_-]{8}\.(?:js|css)$')

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
            # Werkzeug 3.0 removed safe_join, use manual path traversal prevention
            file_path = Path(os.path.normpath(os.path.join(static_folder, filename)))

            # Ensure the resolved path is within the static folder (prevent path traversal)
            try:
                file_path.resolve().relative_to(static_folder.resolve())
            except ValueError:
                logger.warning(f"Path traversal attempt blocked: {filename}")
                return app.send_static_file('404.html'), 404

            if not file_path.exists():
                return app.send_static_file('404.html'), 404

            # Serve the file. send_from_directory sets a real ETag/Last-Modified from
            # the file itself and handles conditional GET properly.
            #
            # This used to short-circuit to 304 whenever the client merely SENT an
            # If-None-Match header, without ever comparing it to the file's actual
            # ETag. Any browser holding a stale copy was told "not modified" forever,
            # no matter what the file now contained — so shipping a CSS or JS change
            # simply never reached returning users.
            response = send_from_directory(static_folder, filename)

            # Determine and set the correct content type.
            content_type = mimetypes.guess_type(filename)[0]
            if content_type:
                response.headers['Content-Type'] = content_type

            # `immutable` promises the bytes at this URL can NEVER change, so it is
            # only safe on content-hashed filenames (main-BRZkLLqg.js), where a new
            # build yields a new URL. Applying it to a fixed name like tailwind.css
            # pins every returning visitor to the old stylesheet for a year.
            is_hashed = bool(_HASHED_ASSET_RE.search(filename))
            if is_hashed:
                cache_control = 'public, max-age=31536000, immutable'
            else:
                # Unhashed: let the browser cache, but make it revalidate so a deploy
                # actually lands. The 304 costs a round trip, not a download.
                cache_control = 'public, max-age=0, must-revalidate'

            response.headers.update({
                'Cache-Control': cache_control,
                'X-Content-Type-Options': 'nosniff',
                'Access-Control-Allow-Origin': '*'
            })
            return response

        except Exception as e:
            logger.error(f"Static file error: {e}")
            return app.send_static_file('500.html'), 500