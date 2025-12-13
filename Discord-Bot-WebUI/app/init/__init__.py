# app/init/__init__.py

"""
Application Initialization Package

This package contains modular initialization functions for the Flask application.
Each module handles a specific aspect of application setup.
"""

from app.init.logging import init_logging
from app.init.redis import init_redis
from app.init.database import init_database
from app.init.extensions import init_extensions
from app.init.socketio import init_socketio
from app.init.jwt import init_jwt
from app.init.middleware import apply_middleware
from app.init.cli import init_cli_commands
from app.init.session import init_session
from app.init.services import init_services
from app.init.blueprints import init_blueprints
from app.init.context_processors import init_context_processors
from app.init.error_handlers import install_error_handlers
from app.init.request_handlers import init_request_handlers
from app.init.template_helpers import init_template_helpers

__all__ = [
    'init_logging',
    'init_redis',
    'init_database',
    'init_extensions',
    'init_socketio',
    'init_jwt',
    'apply_middleware',
    'init_cli_commands',
    'init_session',
    'init_services',
    'init_blueprints',
    'init_context_processors',
    'install_error_handlers',
    'init_request_handlers',
    'init_template_helpers',
]
