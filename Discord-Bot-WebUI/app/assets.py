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
    """
    Initialize asset management for the Flask application.

    This function sets up gzip compression, configures caching for static
    files, and registers asset bundles for vendor and custom CSS/JS files.

    Args:
        app: The Flask application instance.

    Returns:
        Environment: The Flask-Assets environment with the registered bundles.
    """
    logger.info("Initializing assets...")

    # Enable gzip compression for responses.
    Compress(app)

    # Set cache duration for static files (1 year).
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

    # Initialize the Flask-Assets environment.
    assets = Environment(app)
    assets.debug = app.debug
    logger.info("Creating asset bundles...")

    # Vendor CSS bundle: Includes third-party CSS files.
    vendor_css = Bundle(
        'vendor/css/rtl/core.css',
        'vendor/css/rtl/theme-default.css',
        'vendor/fonts/fontawesome/fontawesome.css',
        'vendor/fonts/tabler/tabler-icons.css',
        'vendor/libs/node-waves/node-waves.css',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.css',
        filters='cssmin',
        output='dist/vendor.css'
    )

    # Custom CSS bundle: Includes application-specific CSS.
    custom_css = Bundle(
        'assets/css/demo.css',
        filters='cssmin',
        output='dist/custom.css'
    )

    # Essential vendor JS bundle: Includes core libraries like jQuery and Popper.
    vendor_js_essential = Bundle(
        'vendor/libs/jquery/jquery.js',
        'vendor/libs/popper/popper.js',
        'vendor/js/bootstrap.js',
        filters='jsmin',
        output='dist/vendor-essential.js'
    )

    # Main vendor JS bundle: Includes additional vendor scripts.
    vendor_js = Bundle(
        'vendor/libs/node-waves/node-waves.js',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
        'vendor/libs/hammer/hammer.js',
        'vendor/js/menu.js',
        'vendor/js/helpers.js',
        filters='jsmin',
        output='dist/vendor.js'
    )

    # Custom JS bundle: Includes application-specific JavaScript files.
    custom_js = Bundle(
        'assets/js/main.js',
        'custom_js/tour.js',
        'custom_js/report_match.js',
        'custom_js/rsvp.js',
        filters='jsmin',
        output='dist/custom.js'
    )

    logger.info("Registering asset bundles...")
    assets.register('vendor_css', vendor_css)
    assets.register('custom_css', custom_css)
    assets.register('vendor_js_essential', vendor_js_essential)
    assets.register('vendor_js', vendor_js)
    assets.register('custom_js', custom_js)

    return assets