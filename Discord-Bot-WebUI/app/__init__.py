# app/__init__.py

"""
Flask Application Factory

This module provides the create_app function to initialize and configure the Flask
application. The initialization has been modularized into the app/init/ package.

To rollback to the monolithic version (if needed):
The legacy __init__legacy.py was removed but can be recovered from git history.

Build Mode:
Set SKIP_REDIS=true, SKIP_CELERY=true, SKIP_SOCKETIO=true to create a minimal app
for asset building without external service dependencies.
"""

import os
import logging
import mimetypes
from flask import Flask, request

from app.assets import init_assets
from app.core import db
from app import vite

logger = logging.getLogger(__name__)

# Ensure JS/CSS are served with correct Content-Type. In minimal containers the
# system mime database can map .js -> text/plain, which makes browsers BLOCK
# ES-module <script type="module"> loads (Vite chunks, admin-entry, main-entry).
# Registering explicitly here fixes module loading app-wide.
mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('text/javascript', '.mjs')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/json', '.json')
mimetypes.add_type('image/svg+xml', '.svg')


def create_app(config_object='web_config.Config'):
    """
    Application factory function for creating a Flask app instance.

    Loads configuration from the specified config object, initializes Flask extensions,
    sets up logging, Redis, SQLAlchemy, Celery, and other components, and registers
    blueprints, context processors, and error handlers.

    Args:
        config_object: The configuration object to load (default is 'web_config.Config').

    Returns:
        A configured Flask application instance.
    """
    app = Flask(__name__, static_folder="static")
    app.config.from_object(config_object)

    # SECRET_KEY is mandatory
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY must be set')

    # Initialize asset management
    app.config['FLASK_ASSETS_USE_CDN'] = False
    app.assets = init_assets(app)

    # Initialize Vite integration (modern asset pipeline)
    # Set VITE_DEV_MODE=True in .env to use Vite dev server
    vite.init_app(app)

    # Import initialization modules
    from app.init import (
        init_logging,
        init_redis,
        init_database,
        init_extensions,
        init_socketio,
        init_jwt,
        apply_middleware,
        init_cli_commands,
        init_session,
        init_services,
        init_blueprints,
        init_context_processors,
        install_error_handlers,
        init_request_handlers,
        init_template_helpers,
    )

    # Check for build mode (minimal initialization for asset building)
    skip_redis = os.environ.get('SKIP_REDIS', '').lower() in ('true', '1', 'yes')
    skip_socketio = os.environ.get('SKIP_SOCKETIO', '').lower() in ('true', '1', 'yes')
    skip_celery = os.environ.get('SKIP_CELERY', '').lower() in ('true', '1', 'yes')
    build_mode = skip_redis or skip_socketio or skip_celery

    if build_mode:
        logger.info("Running in BUILD MODE - skipping external service initialization")

    # Phase 1: Core setup
    init_logging(app)
    redis_manager = None
    if not skip_redis:
        redis_manager = init_redis(app)
    else:
        logger.info("Skipping Redis initialization (SKIP_REDIS=true)")
    init_database(app, db)

    # Opt-in per-request profiler (REQUEST_PROFILE=true). Inert otherwise.
    # Logs queries, connection checkouts, and CPU-vs-wall time per request — the
    # only numbers that distinguish "this request is waiting on the DB" (harmless
    # under gevent; it yields) from "this request is burning CPU" (freezes every
    # other greenlet in the worker). Registered before the extensions so its
    # before_request runs early.
    from app.request_profiler import init_request_profiler
    init_request_profiler(app)

    # Phase 2: Extensions
    login_manager, mail, csrf, migrate = init_extensions(app, db)

    # Phase 3: Real-time communication
    if not skip_socketio:
        init_socketio(app)
    else:
        logger.info("Skipping SocketIO initialization (SKIP_SOCKETIO=true)")

    # Phase 4: Authentication & Security
    init_jwt(app)
    init_request_handlers(app, csrf)

    # League access gating: confine pending/unpaid users to a safe allowlist.
    # Registered right after init_request_handlers so it runs AFTER the
    # db-session before_request (g.db_session + g._cached_user_roles available).
    from app.init.access_gating import register_access_gating
    register_access_gating(app)

    # Legacy WordPress → new-site 301 redirects (SEO). Host-gated to
    # ecspubleague.org, so this is dormant on portal.ecsfc.com until DNS cutover.
    from app.public_redirects import register_public_redirects
    register_public_redirects(app)

    # The mobile counterpart. access_gating exempts /api wholesale (the JSON API
    # is trusted to enforce its own state), and pending users now hold real JWTs
    # so they can link the pass they bought — this is what keeps them out of
    # everything else.
    from app.mobile_api.approval_gate import register_approval_gate
    register_approval_gate(app)

    # Phase 5: Blueprints and routes
    init_blueprints(app, csrf)
    init_context_processors(app)
    init_template_helpers(app)
    install_error_handlers(app)

    # Attach SQLAlchemy event listeners for account-approval FCM push.
    # The import itself binds the listeners (decorators run at module load);
    # the explicit register() call is a no-op safeguard so importers can't
    # tree-shake this away.
    from app.services.account_approval_push import register as _register_approval_push
    _register_approval_push()

    # Wallet pass auto-refresh listeners: bump + APNs push when a Player or
    # Match attribute that's baked into pass.json changes.
    from app.wallet_pass.services.auto_refresh import install_listeners as _install_wallet_auto_refresh
    _install_wallet_auto_refresh()

    # Phase 6: Middleware and session
    apply_middleware(app)
    if not skip_redis and redis_manager:
        init_session(app, redis_manager)
    else:
        logger.info("Skipping session initialization (requires Redis)")

    # Phase 7: Services and CLI
    if not skip_celery:
        init_services(app)
    else:
        logger.info("Skipping services initialization (SKIP_CELERY=true)")
    init_cli_commands(app)

    # Bulletproof JS/CSS content-type. Some container mime databases map .js ->
    # text/plain, which makes browsers BLOCK <script type="module"> (Vite chunks,
    # admin-entry, main-entry) — breaking JS app-wide. Force the correct type on
    # every static .js/.mjs/.css response regardless of the environment.
    @app.after_request
    def _force_static_mime(response):
        try:
            p = request.path or ''
            if p.endswith(('.js', '.mjs')):
                response.headers['Content-Type'] = 'text/javascript; charset=utf-8'
            elif p.endswith('.css'):
                response.headers['Content-Type'] = 'text/css; charset=utf-8'
        except Exception:
            pass
        return response

    return app


# Re-export commonly used items for backward compatibility
from app.core import db, socketio, celery
from app.init.extensions import login_manager, mail, csrf, migrate

__all__ = [
    'create_app',
    'db',
    'socketio',
    'celery',
    'login_manager',
    'mail',
    'csrf',
    'migrate',
]
