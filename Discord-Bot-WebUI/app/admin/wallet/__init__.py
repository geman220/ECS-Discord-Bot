# app/admin/wallet/__init__.py

"""
Wallet Admin Package

This package organizes all wallet administration functionality into logical modules:

- config/: Pass configuration (certificates, assets, templates, design)
- management/: Pass lifecycle management (issue, void, view passes)
- locations/: Partner location management
- sponsors/: Sponsor management
- subgroups/: ECS subgroup management
- studio/: Unified Pass Studio for non-technical pass editing

Each module contains its own routes that are registered to the main blueprints.
"""

import logging
from flask import Blueprint, redirect, request

logger = logging.getLogger(__name__)

# Create the main blueprints — wallet admin lives inside the admin panel shell.
wallet_config_bp = Blueprint('wallet_config', __name__, url_prefix='/admin-panel/wallet/config')
wallet_admin_bp = Blueprint('wallet_admin', __name__, url_prefix='/admin-panel/wallet')

# Legacy /admin/wallet/* URLs (bookmarks, old links) — 308 preserves method+body
# so old POSTing clients keep working too.
wallet_legacy_bp = Blueprint('wallet_legacy', __name__, url_prefix='/admin/wallet')


@wallet_legacy_bp.route('/', defaults={'subpath': ''},
                        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
@wallet_legacy_bp.route('/<path:subpath>',
                        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
def legacy_redirect(subpath):
    target = f"/admin-panel/wallet/{subpath}"
    if request.query_string:
        target = f"{target}?{request.query_string.decode('utf-8', 'ignore')}"
    return redirect(target, code=308)

# Import the Pass Studio blueprint FIRST (it has fewer dependencies)
# This is a separate blueprint for the unified pass editing experience
try:
    from .studio_routes import pass_studio_bp
except ImportError as e:
    logger.warning(f"Could not import pass_studio_bp: {e}")
    # Create a placeholder blueprint if import fails
    pass_studio_bp = Blueprint('pass_studio', __name__, url_prefix='/admin-panel/wallet/studio')

# Import and register route modules
# These imports must come after blueprint creation to avoid circular imports
from . import config_routes
from . import management_routes
from . import location_routes
from . import sponsor_routes
from . import design_routes


def init_app(app):
    """Initialize wallet admin blueprints with the Flask app"""
    app.register_blueprint(wallet_config_bp)
    app.register_blueprint(wallet_admin_bp)
    app.register_blueprint(pass_studio_bp)
    app.register_blueprint(wallet_legacy_bp)
