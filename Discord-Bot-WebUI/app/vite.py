"""
Flask Vite Integration
======================

Provides helper functions for integrating Vite-bundled assets with Flask templates.

In development mode:
- Assets are served from Vite dev server (http://localhost:5173)
- Hot Module Replacement (HMR) is enabled

In production mode:
- Assets are served from the dist/ directory
- Uses manifest.json for cache-busted filenames

Usage in templates:
    {{ vite_asset('js/main-entry.js') }}
    {{ vite_asset('css/main-entry.css') }}

Configuration:
    VITE_DEV_MODE: Set to True to use Vite dev server (default: based on FLASK_DEBUG)
    VITE_DEV_SERVER_URL: URL of Vite dev server (default: http://localhost:5173)
"""

import json
import os
from functools import lru_cache
from flask import current_app, url_for
from markupsafe import Markup


def init_app(app):
    """Initialize Vite integration with Flask app."""

    # Default configuration
    # VITE_DEV_MODE is opt-in only - enables HMR via Vite dev server
    # Default: Use built Vite assets (with source maps in dev for debugging)
    vite_dev_mode = os.getenv('VITE_DEV_MODE', '').lower() in ('true', '1', 'yes')
    app.config.setdefault('VITE_DEV_MODE', vite_dev_mode)
    app.config.setdefault('VITE_DEV_SERVER_URL', 'http://localhost:5173')
    app.config.setdefault('VITE_MANIFEST_PATH', 'vite-dist/.vite/manifest.json')

    # Check if Vite production assets exist
    vite_manifest_path = os.path.join(app.static_folder, 'vite-dist/.vite/manifest.json')
    vite_assets_exist = os.path.exists(vite_manifest_path)

    # Use Vite bundled assets if:
    # 1. Vite assets exist (manifest found)
    # 2. Not explicitly using Vite dev server
    # This enables using built assets even in debug mode (with source maps for debugging)
    use_vite = os.getenv('USE_VITE_ASSETS', '').lower() in ('true', '1', 'yes')
    vite_production_mode = (vite_assets_exist and not vite_dev_mode) or use_vite

    app.config['VITE_PRODUCTION_MODE'] = vite_production_mode

    # Determine which mode we're actually in
    if vite_production_mode:
        mode = "VITE BUNDLED ASSETS (from vite-dist/)"
    elif vite_dev_mode:
        mode = "VITE DEV SERVER (HMR from localhost:5173)"
    else:
        mode = "FALLBACK (no Vite assets found - run 'npm run build')"

    app.logger.info(f"[VITE] Asset loading: {mode}")
    app.logger.info(f"  Vite manifest exists: {vite_assets_exist}")
    app.logger.info(f"  Use source maps? Set BUILD_MODE=dev before 'npm run build'")

    # Register template context processor
    @app.context_processor
    def vite_context():
        return {
            'vite_asset': vite_asset,
            'vite_asset_url': vite_asset_url,
            'vite_dev_mode': lambda: current_app.config.get('VITE_DEV_MODE', False),
            'vite_production_mode': lambda: current_app.config.get('VITE_PRODUCTION_MODE', False),
        }

    # Clear manifest cache on each request in debug mode
    if app.debug:
        @app.before_request
        def clear_vite_cache():
            get_manifest.cache_clear()


@lru_cache(maxsize=1)
def get_manifest():
    """Load and cache the Vite manifest file."""
    manifest_path = os.path.join(
        current_app.static_folder,
        current_app.config.get('VITE_MANIFEST_PATH', 'dist/.vite/manifest.json')
    )

    if not os.path.exists(manifest_path):
        # Try alternative manifest location
        alt_path = os.path.join(current_app.static_folder, 'vite-dist', 'manifest.json')
        if os.path.exists(alt_path):
            manifest_path = alt_path
        else:
            current_app.logger.warning(f'Vite manifest not found at {manifest_path}')
            return {}

    try:
        with open(manifest_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        current_app.logger.error(f'Error loading Vite manifest: {e}')
        return {}


def vite_asset(entry_point: str) -> Markup:
    """
    Generate HTML tags for a Vite entry point.

    In development mode, returns script/link tags pointing to Vite dev server.
    In production mode, returns tags pointing to built assets with hashed filenames.

    Args:
        entry_point: The entry point path (e.g., 'js/main-entry.js')

    Returns:
        Markup object containing HTML tags
    """
    dev_mode = current_app.config.get('VITE_DEV_MODE', False)

    if dev_mode:
        return _vite_dev_asset(entry_point)
    else:
        return _vite_prod_asset(entry_point)


def vite_asset_url(entry_point: str) -> str:
    """
    Get the URL for a Vite asset (without HTML tags).

    Useful for preload hints, modulepreload, etc.

    Args:
        entry_point: The entry point path (e.g., 'js/main-entry.js')

    Returns:
        URL string for the asset
    """
    dev_mode = current_app.config.get('VITE_DEV_MODE', False)

    if dev_mode:
        dev_url = current_app.config.get('VITE_DEV_SERVER_URL', 'http://localhost:5173')
        return f"{dev_url}/static/{entry_point}"

    # Production mode - look up in manifest
    manifest = get_manifest()
    if not manifest:
        return url_for('static', filename=entry_point)

    entry_key = entry_point
    if entry_key not in manifest:
        entry_key = f'static/{entry_point}'

    if entry_key not in manifest:
        return url_for('static', filename=entry_point)

    entry = manifest[entry_key]
    file_path = entry.get('file', '')
    if file_path:
        return url_for('static', filename=f'vite-dist/{file_path}')

    return url_for('static', filename=entry_point)


def _vite_dev_asset(entry_point: str) -> Markup:
    """Generate asset tags for Vite development mode."""
    dev_url = current_app.config.get('VITE_DEV_SERVER_URL', 'http://localhost:5173')

    tags = []

    # Always include Vite client for HMR
    tags.append(f'<script type="module" src="{dev_url}/@vite/client"></script>')

    if entry_point.endswith('.js'):
        tags.append(f'<script type="module" src="{dev_url}/static/{entry_point}"></script>')
    elif entry_point.endswith('.css'):
        # In dev mode, CSS is injected by the JS module
        # But we can still include it directly
        tags.append(f'<link rel="stylesheet" href="{dev_url}/static/{entry_point}">')

    return Markup('\n'.join(tags))


def _vite_prod_asset(entry_point: str) -> Markup:
    """Generate asset tags for Vite production mode."""
    manifest = get_manifest()

    if not manifest:
        # Fallback to direct file path if no manifest
        return _fallback_asset(entry_point)

    # Look up the entry point in the manifest
    entry_key = entry_point
    if entry_key not in manifest:
        # Try with 'static/' prefix
        entry_key = f'static/{entry_point}'

    if entry_key not in manifest:
        current_app.logger.warning(f'Entry point {entry_point} not found in Vite manifest')
        return _fallback_asset(entry_point)

    entry = manifest[entry_key]
    tags = []

    # Add the main file
    file_path = entry.get('file', '')
    if file_path:
        if entry_point.endswith('.js'):
            tags.append(f'<script type="module" src="{url_for("static", filename=f"vite-dist/{file_path}")}"></script>')
        elif entry_point.endswith('.css'):
            tags.append(f'<link rel="stylesheet" href="{url_for("static", filename=f"vite-dist/{file_path}")}">')

    # Add CSS files imported by JS
    for css_file in entry.get('css', []):
        tags.append(f'<link rel="stylesheet" href="{url_for("static", filename=f"vite-dist/{css_file}")}">')

    # Add preload hints for imports
    for import_file in entry.get('imports', []):
        if import_file in manifest:
            import_entry = manifest[import_file]
            import_path = import_entry.get('file', '')
            if import_path:
                tags.append(f'<link rel="modulepreload" href="{url_for("static", filename=f"vite-dist/{import_path}")}">')

    return Markup('\n'.join(tags))


def _fallback_asset(entry_point: str) -> Markup:
    """Fallback to Flask-Assets style paths when Vite manifest is not available."""
    # Try to use the gen/ directory from Flask-Assets
    if entry_point.endswith('.js'):
        # Check if production.min.js exists
        gen_path = 'gen/production.min.js'
        full_path = os.path.join(current_app.static_folder, gen_path)
        if os.path.exists(full_path):
            return Markup(f'<script src="{url_for("static", filename=gen_path)}"></script>')
        return Markup(f'<script type="module" src="{url_for("static", filename=entry_point)}"></script>')

    elif entry_point.endswith('.css'):
        # Check if production.min.css exists
        gen_path = 'gen/production.min.css'
        full_path = os.path.join(current_app.static_folder, gen_path)
        if os.path.exists(full_path):
            return Markup(f'<link rel="stylesheet" href="{url_for("static", filename=gen_path)}">')
        return Markup(f'<link rel="stylesheet" href="{url_for("static", filename=entry_point)}">')

    return Markup('')


def vite_react_refresh() -> Markup:
    """
    Add React Refresh script for HMR in development.
    Only needed if using React.
    """
    if not current_app.config.get('VITE_DEV_MODE', False):
        return Markup('')

    dev_url = current_app.config.get('VITE_DEV_SERVER_URL', 'http://localhost:5173')

    return Markup(f'''
<script type="module">
  import RefreshRuntime from "{dev_url}/@react-refresh"
  RefreshRuntime.injectIntoGlobalHook(window)
  window.$RefreshReg$ = () => {{}}
  window.$RefreshSig$ = () => (type) => type
  window.__vite_plugin_react_preamble_installed__ = true
</script>
''')
