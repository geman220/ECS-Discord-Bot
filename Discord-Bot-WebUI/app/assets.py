# app/assets.py

"""
Asset Management Module (Simplified)

This module has been simplified as part of the Vite migration.
Flask-Assets bundle definitions have been removed - Vite is now the
primary build system (npm run build → vite-dist/).

This module now only:
1. Initializes compression and caching (via compression.py)
2. Sets ASSETS_PRODUCTION_MODE for template backward compatibility
3. Registers Flask-Assets extension for {% assets %} tag compatibility

For asset bundling, use Vite:
- Development: npm run dev
- Production: npm run build
"""

import os
import logging
from flask_assets import Environment, Bundle
from app.compression import init_compression

logger = logging.getLogger(__name__)


def init_assets(app):
    """
    Initialize asset configuration.

    This function is maintained for backward compatibility.
    It registers Flask-Assets so the {% assets %} Jinja tag works,
    but Vite is the primary build system.

    Args:
        app: Flask application instance

    Returns:
        Flask-Assets Environment (for backward compatibility)
    """
    logger.debug("Initializing assets (Vite is primary build system)...")

    # Initialize compression and production mode detection
    is_production = init_compression(app)

    # Initialize Flask-Assets for template {% assets %} tag compatibility
    # This is needed even though Vite builds the assets, because templates
    # may still use {% assets %} in fallback blocks
    assets = Environment(app)
    assets.debug = app.debug
    assets.auto_build = not is_production
    assets.url = app.static_url_path
    assets.directory = app.static_folder

    # Register minimal bundles for fallback compatibility
    # These are only used when Vite assets are NOT available
    _register_fallback_bundles(assets, app.static_folder)

    logger.info(
        f"[Assets] Initialized: compression enabled, "
        f"ASSETS_PRODUCTION_MODE={is_production}, "
        f"primary build system: Vite, Flask-Assets fallback: enabled"
    )

    return assets


def _register_fallback_bundles(assets, static_folder):
    """
    Register minimal CSS bundles for fallback when Vite assets aren't available.
    These load individual CSS files directly (no minification).
    """
    # Core design tokens
    assets.register('core_tokens', Bundle(
        'css/tokens/colors.css',
        'css/tokens/typography.css',
        'css/tokens/spacing.css',
        'css/tokens/shadows.css',
        'css/tokens/borders.css',
        'css/tokens/animations.css',
        'css/core/variables.css',
        'css/core/z-index.css',
        output='gen/core_tokens.css'
    ))

    # Foundation styles
    assets.register('foundation_css', Bundle(
        'css/core/bootstrap-theming.css',
        'css/bootstrap-minimal.css',
        'css/core/component-aliases.css',
        output='gen/foundation.css'
    ))

    # Components
    assets.register('components_css', Bundle(
        'css/components/c-btn.css',
        'css/components/forms-modern.css',
        'css/components/cards-modern.css',
        'css/components/modals.css',
        'css/components/c-modal.css',
        'css/components/c-dropdown.css',
        'css/components/dropdowns.css',
        'css/components/tables-modern.css',
        'css/components/badges.css',
        'css/components/alerts.css',
        'css/components/navigation.css',
        output='gen/components.css'
    ))

    # Mobile styles
    assets.register('mobile_css', Bundle(
        'css/mobile/index.css',
        output='gen/mobile.css'
    ))

    # Layout styles
    assets.register('layout_css', Bundle(
        'css/layout/base-layout.css',
        'css/layout/navbar.css',
        'css/layout/sidebar-modern.css',
        output='gen/layout.css'
    ))

    # Utilities
    assets.register('utilities_css', Bundle(
        'css/utilities/display-utils.css',
        'css/utilities/layout-utils.css',
        'css/utilities/sizing-utils.css',
        output='gen/utilities.css'
    ))

    # Features
    assets.register('features_css', Bundle(
        'css/features/draft.css',
        'css/features/player-profile.css',
        output='gen/features.css'
    ))

    # Pages
    assets.register('pages_css', Bundle(
        'css/pages/home.css',
        output='gen/pages.css'
    ))

    # Theme
    assets.register('theme_modern', Bundle(
        'css/themes/modern/modern-components.css',
        'css/themes/modern/modern-light.css',
        'css/themes/modern/modern-dark.css',
        output='gen/theme_modern.css'
    ))
