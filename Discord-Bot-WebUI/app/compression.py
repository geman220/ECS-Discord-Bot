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

from flask_compress import Compress

logger = logging.getLogger(__name__)


def init_compression(app):
    """
    Initialize compression and static file caching.

    Args:
        app: Flask application instance
    """
    # Enable gzip compression for responses
    Compress(app)

    # Set cache duration for static files (1 year)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

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
