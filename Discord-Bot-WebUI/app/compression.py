# app/compression.py

"""
Compression and Static File Configuration

This module handles:
1. Gzip compression for HTTP responses (Flask-Compress)
2. Static file cache headers (1 year max-age)
3. Asset production mode detection

Extracted from assets.py as part of Flask-Assets deprecation.
"""

import os
import logging
import re

from flask import request
from flask_compress import Compress

# Vite emits content-hashed names (vite-dist/js/main-mE06ZOsi.js) — exactly 8 hash
# chars. Only those may be cached `immutable`: a rebuild gives them a NEW url, so the
# bytes at this url genuinely never change. Anchored to vite-dist/ and to exactly 8
# chars on purpose — a looser pattern would match a hand-named file like
# js/some-verylongname.js and pin it in every browser cache for a year.
_HASHED_ASSET_RE = re.compile(r'/static/vite-dist/.*-[A-Za-z0-9_-]{8}\.(?:js|css)$')

_LONG_LIVED_SUFFIXES = ('.woff', '.woff2', '.ttf', '.eot',
                        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp')

logger = logging.getLogger(__name__)


def init_compression(app):
    """
    Initialize compression and static file caching.

    Args:
        app: Flask application instance
    """
    # Gzip is done by TRAEFIK now (the `gzip-compress` middleware on the webui-secure
    # router), not here.
    #
    # Flask-Compress gzipped every response — including the multi-MB JS bundle for
    # every cold client — INSIDE the gevent worker. CPU does not yield under gevent, so
    # that compression froze every other greenlet in the process for its whole
    # duration. Traefik does the same job in Go, in its own process, and never stalls a
    # Python request.
    #
    # Set COMPRESS_IN_FLASK=true to fall back to in-process compression (e.g. if you
    # ever run this without Traefik in front). Verify after deploying with:
    #   curl -sI -H 'Accept-Encoding: gzip' https://portal.ecsfc.com/ | grep -i encoding
    if os.getenv('COMPRESS_IN_FLASK', 'false').lower() in ('true', '1', 'yes'):
        logger.info("Flask-Compress ENABLED (COMPRESS_IN_FLASK=true)")
        Compress(app)
    else:
        logger.info("Flask-Compress disabled — gzip is handled by Traefik")

    # Static caching.
    #
    # This used to be a flat `SEND_FILE_MAX_AGE_DEFAULT = 31536000` — a ONE YEAR
    # max-age on EVERY static file. That is only safe for content-hashed filenames,
    # where a rebuild produces a new URL. It was also being applied to fixed names
    # like vite-dist/css/tailwind.css, css/template-styles.css and the raw js/*.js —
    # so a returning visitor's browser held the OLD stylesheet for a year and simply
    # never saw a CSS or JS deploy.
    #
    # None => Werkzeug sends ETag/Last-Modified and `no-cache`, i.e. revalidate.
    # The hook below then re-grants long caching to the files that have earned it.
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = None

    @app.after_request
    def _static_cache_control(response):
        path = request.path or ''
        if not path.startswith('/static/'):
            return response

        if _HASHED_ASSET_RE.search(path):
            # Vite content-hashed: the bytes at this URL can never change.
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        elif path.endswith(_LONG_LIVED_SUFFIXES):
            # Fonts/images: change rarely and are normally renamed when they do.
            response.headers['Cache-Control'] = 'public, max-age=2592000'
        else:
            # Unhashed css/js: cache briefly so one page-load burst doesn't
            # revalidate 30 times, but let a deploy actually land.
            response.headers['Cache-Control'] = 'public, max-age=300'
        return response

    # Determine asset production mode
    # This is used by templates for fallback logic
    flask_env = os.getenv('FLASK_ENV', 'development')
    flask_debug = os.getenv('FLASK_DEBUG', str(app.debug)).lower() in ('true', '1', 'yes')
    use_prod_assets = os.getenv('USE_PRODUCTION_ASSETS', '').lower() in ('true', '1', 'yes')

    # Check if pre-built production bundle exists (legacy check)
    production_bundle_path = os.path.join(app.static_folder, 'gen', 'production.min.css')
    has_production_bundle = os.path.exists(production_bundle_path)

    # Determine production mode:
    # 1. FLASK_DEBUG=1 → ALWAYS dev mode
    # 2. USE_PRODUCTION_ASSETS=true → force production mode
    # 3. FLASK_ENV=production + bundle exists → production mode
    # 4. Otherwise → dev mode
    if flask_debug:
        is_production = False
    elif use_prod_assets:
        is_production = True
    elif flask_env == 'production' and has_production_bundle:
        is_production = True
    else:
        is_production = False

    # Store in app config for template access
    # NOTE: Templates should prefer vite_production_mode() over this flag
    # This is maintained for backward compatibility only
    app.config['ASSETS_PRODUCTION_MODE'] = is_production

    logger.info(f"[Compression] Initialized: gzip enabled, cache 1yr, production_mode={is_production}")

    return is_production
