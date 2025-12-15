# app/assets.py

"""
Asset Management Module

This module initializes and registers asset bundles (CSS and JS) for the
Flask application. It also enables gzip compression and sets caching
headers for static files.
"""

import logging

from flask_assets import Environment, Bundle
from flask_compress import Compress

logger = logging.getLogger(__name__)


def init_assets(app):
    logger.debug("Initializing assets...")

    # Enable gzip compression for responses.
    Compress(app)

    # Set cache duration for static files (1 year).
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

    # Initialize the Flask-Assets environment.
    assets = Environment(app)
    assets.debug = app.debug
    
    # Skip compilation if bundles already exist (faster boot)
    assets.auto_build = app.debug

    # Explicitly set the assets directory and load path to match the static folder.
    assets.directory = app.static_folder
    assets.url = app.static_url_path
    assets.load_path = [app.static_folder]

    logger.debug("Creating asset bundles...")

    # Define your bundles.
    # Phase 3A: Consolidated CSS Architecture (14 files → 6 files)
    
    # Foundation Bundle - Bootstrap + ECS Core + Z-Index System  
    foundation_css = Bundle(
        'css/foundation.css',            # Consolidated: core.css + ecs-core.css + z-index-system.css
        filters='cssmin',
        output='dist/foundation.css'
    )
    
    # Components Bundle - Theme + Layout + Components
    components_css = Bundle(
        'css/components.css',            # Consolidated: theme-default.css + layout-system.css + ecs-components.css
        filters='cssmin',
        output='dist/components.css'
    )
    
    # Vendor Bundle - Third-party libraries + overrides (Tabler Icons loaded separately in base.html)
    vendor_css = Bundle(
        'vendor/fonts/fontawesome.css',          # FontAwesome (separate to preserve font paths)
        'vendor/libs/node-waves/node-waves.css', # Node Waves
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.css', # Perfect Scrollbar
        filters='cssmin',
        output='dist/vendor.css'
    )
    
    # Demo/Development CSS Bundle - Non-critical assets
    demo_css = Bundle(
        'assets/css/demo.css',
        filters='cssmin',
        output='dist/demo.css'
    )
    vendor_js_essential = Bundle(
        'vendor/libs/jquery/jquery.js',
        'vendor/libs/popper/popper.js',
        'vendor/js/bootstrap.js',
        filters='jsmin',
        output='dist/vendor-essential.js'
    )
    vendor_js = Bundle(
        'vendor/libs/node-waves/node-waves.js',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
        'vendor/libs/hammer/hammer.js',
        'vendor/js/menu.js',
        'vendor/js/helpers.js',
        filters='jsmin',
        output='dist/vendor.js'
    )
    custom_js = Bundle(
        'assets/js/main.js',
        'custom_js/tour.js',
        'custom_js/report_match.js',
        'custom_js/rsvp.js',
        filters='jsmin',
        output='dist/custom.js'
    )

    logger.debug("Registering asset bundles...")
    assets.register('foundation_css', foundation_css)
    assets.register('components_css', components_css)
    assets.register('vendor_css', vendor_css)
    assets.register('demo_css', demo_css)
    assets.register('vendor_js_essential', vendor_js_essential)
    assets.register('vendor_js', vendor_js)
    assets.register('custom_js', custom_js)

    # Register the assets environment in app.extensions.
    app.extensions = getattr(app, 'extensions', {})
    app.extensions['assets'] = assets

    return assets