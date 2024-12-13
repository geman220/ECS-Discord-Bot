from flask_assets import Environment, Bundle
from flask_compress import Compress
import logging

logger = logging.getLogger(__name__)

def init_assets(app):
    logging.info("Initializing assets...")
    # Enable gzip compression
    Compress(app)
    
    # Set cache duration for static files
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1 year
    
    assets = Environment(app)
    assets.debug = app.debug
    logging.info("Creating asset bundles...")

    # Vendor CSS bundles
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
    
    # Custom CSS bundle
    custom_css = Bundle(
        'assets/css/demo.css',
        filters='cssmin',
        output='dist/custom.css'
    )
    
    # Essential vendor JS bundle
    vendor_js_essential = Bundle(
        'vendor/libs/jquery/jquery.js',
        'vendor/libs/popper/popper.js',
        'vendor/js/bootstrap.js',
        filters='jsmin',
        output='dist/vendor-essential.js'
    )
    
    # Main vendor JS bundle
    vendor_js = Bundle(
        'vendor/libs/node-waves/node-waves.js',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
        'vendor/libs/hammer/hammer.js',
        'vendor/js/menu.js',
        'vendor/js/helpers.js',
        filters='jsmin',
        output='dist/vendor.js'
    )
    
    # Custom JS bundle
    custom_js = Bundle(
        'assets/js/main.js',
        'custom_js/tour.js',
        'custom_js/report_match.js',
        'custom_js/rsvp.js',
        filters='jsmin',
        output='dist/custom.js'
    )

    logging.info("Registering asset bundles...")
    assets.register('vendor_css', vendor_css)
    assets.register('custom_css', custom_css)
    assets.register('vendor_js_essential', vendor_js_essential)
    assets.register('vendor_js', vendor_js)
    assets.register('custom_js', custom_js)
    
    return assets