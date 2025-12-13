# app/__init__.py

"""
Flask Application Factory

This module provides the create_app function to initialize and configure the Flask
application. The initialization has been modularized into the app/init/ package.

To rollback to the monolithic version:
1. Rename this file to __init__new.py
2. Rename __init__legacy.py to __init__.py
"""

# Fix eventlet database connection handling
try:
    import eventlet.debug
    eventlet.debug.hub_prevent_multiple_readers(False)
except ImportError:
    pass

import logging
from flask import Flask

from app.assets import init_assets
from app.core import db

logger = logging.getLogger(__name__)


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

    # Phase 1: Core setup
    init_logging(app)
    redis_manager = init_redis(app)
    init_database(app, db)

    # Phase 2: Extensions
    login_manager, mail, csrf, migrate = init_extensions(app, db)

    # Phase 3: Real-time communication
    init_socketio(app)

    # Phase 4: Authentication & Security
    init_jwt(app)
    init_request_handlers(app, csrf)

    # Phase 5: Blueprints and routes
    init_blueprints(app, csrf)
    init_context_processors(app)
    init_template_helpers(app)
    install_error_handlers(app)

    # Phase 6: Middleware and session
    apply_middleware(app)
    init_session(app, redis_manager)

    # Phase 7: Services and CLI
    init_services(app)
    init_cli_commands(app)

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
