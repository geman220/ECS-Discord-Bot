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
from flask import current_app, url_for, Markup


def init_app(app):
    """Initialize Vite integration with Flask app."""

    # Default configuration
    app.config.setdefault('VITE_DEV_MODE', app.debug)
    app.config.setdefault('VITE_DEV_SERVER_URL', 'http://localhost:5173')
    app.config.setdefault('VITE_MANIFEST_PATH', 'dist/.vite/manifest.json')

    # Register template context processor
    @app.context_processor
    def vite_context():
        return {
            'vite_asset': vite_asset,
            'vite_dev_mode': lambda: current_app.config.get('VITE_DEV_MODE', False),
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
        alt_path = os.path.join(current_app.static_folder, 'dist', 'manifest.json')
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
            tags.append(f'<script type="module" src="{url_for("static", filename=f"dist/{file_path}")}"></script>')
        elif entry_point.endswith('.css'):
            tags.append(f'<link rel="stylesheet" href="{url_for("static", filename=f"dist/{file_path}")}">')

    # Add CSS files imported by JS
    for css_file in entry.get('css', []):
        tags.append(f'<link rel="stylesheet" href="{url_for("static", filename=f"dist/{css_file}")}">')

    # Add preload hints for imports
    for import_file in entry.get('imports', []):
        if import_file in manifest:
            import_entry = manifest[import_file]
            import_path = import_entry.get('file', '')
            if import_path:
                tags.append(f'<link rel="modulepreload" href="{url_for("static", filename=f"dist/{import_path}")}">')

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
