# app/debug/diagnostic.py

"""
Diagnostic utilities for the Flask application.

This module provides middleware and functions to monitor the request lifecycle,
check database and Redis connectivity, and run comprehensive diagnostics. It also
installs a global error handler for enhanced debugging.
"""

import threading
import eventlet
import logging
import sys
from sqlalchemy import text
from flask import request, has_app_context, g, current_app
from app.core import db as core_db

# Configure logging for diagnostics
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def diagnostic_middleware(app):
    """
    Middleware to track the request lifecycle and detect potential deadlocks.
    
    It spawns a timeout handler if a request takes longer than 30 seconds and
    logs the current thread information both at the start and completion of a request.
    """
    @app.before_request
    def before_request():
        # Check for SQLAlchemy and Redis initialization
        if not hasattr(current_app, 'extensions') or 'sqlalchemy' not in current_app.extensions:
            logger.warning("SQLAlchemy not initialized in diagnostic middleware")
            return

        if not hasattr(current_app, 'redis'):
            logger.warning("Redis not initialized in diagnostic middleware")
            return

        # Schedule a timeout handler to run after 30 seconds
        g._request_start_time = eventlet.spawn_after(30, timeout_handler)
        g._request_thread = threading.current_thread().ident
        logger.debug(f"Request started on thread {g._request_thread}")

    @app.after_request
    def after_request(response):
        # Cancel the scheduled timeout handler if it exists
        if hasattr(g, '_request_start_time'):
            try:
                g._request_start_time.cancel()
            except Exception as e:
                logger.error(f"Error cancelling timeout handler: {e}")
        logger.debug(f"Request completed on thread {threading.current_thread().ident}")
        return response


def timeout_handler():
    """
    Handler called when a request exceeds its allowed processing time.
    
    Logs an error message along with a list of all running threads.
    """
    thread_id = threading.current_thread().ident
    logger.error(f"Request timeout detected on thread {thread_id}")
    for thread in threading.enumerate():
        logger.error(f"Thread {thread.ident}: {thread.name}")


def check_db_connection(db=None):
    """
    Verify database connectivity by executing a simple query.
    
    If no database instance is provided, the core_db is used. Logs detailed
    connection information and returns True if successful, False otherwise.
    
    :param db: Optional SQLAlchemy database instance.
    :return: True if the connection is successful; False otherwise.
    """
    if not has_app_context():
        logger.warning("No application context available for DB check")
        return False

    try:
        if db is None:
            db = core_db
            if not hasattr(current_app, 'extensions') or 'sqlalchemy' not in current_app.extensions:
                logger.warning("SQLAlchemy not initialized yet")
                logger.info(f"Available extensions: {list(getattr(current_app, 'extensions', {}).keys())}")
                return False

        logger.info(f"Database object type: {type(db)}")
        logger.info(f"Extensions available: {list(current_app.extensions.keys())}")
        logger.info(f"SQLAlchemy config: {current_app.config.get('SQLALCHEMY_DATABASE_URI')}")

        db_url = str(db.engine.url)
        # Mask the user credentials in the URL for safe logging
        safe_url = db_url.replace(db_url.split('@')[0], '***:***')
        logger.info(f"Attempting to connect to database: {safe_url}")

        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT current_database(), current_user, version()"))
            info = result.fetchone()
            logger.info(f"Connected to database: {info[0]} as user: {info[1]}")
            logger.info(f"Database version: {info[2]}")
            return True

    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        if hasattr(e, 'orig'):
            logger.error(f"Original error: {str(e.orig)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False


def check_db_initialization(app):
    """
    Check the database configuration and initialization status.
    
    Logs the database URL and available Flask extensions. If SQLAlchemy is
    initialized, logs additional details about its configuration.
    
    :param app: The Flask application instance.
    """
    logger.info("Checking database initialization...")
    logger.info(f"Database URL from config: {app.config.get('SQLALCHEMY_DATABASE_URI', 'Not set')}")
    logger.info(f"Available extensions: {list(app.extensions.keys()) if hasattr(app, 'extensions') else 'No extensions'}")

    if hasattr(app, 'extensions') and 'sqlalchemy' in app.extensions:
        sqlalchemy_ext = app.extensions['sqlalchemy']
        logger.info(f"SQLAlchemy extension type: {type(sqlalchemy_ext)}")
        logger.info(f"SQLAlchemy extension attributes: {dir(sqlalchemy_ext)}")


def check_redis_connection(redis_client=None):
    """
    Verify Redis connectivity by sending a ping command.
    
    If no Redis client is provided, the one attached to current_app is used.
    
    :param redis_client: Optional Redis client instance.
    :return: True if Redis responds to the ping; False otherwise.
    """
    if not has_app_context():
        logger.warning("No application context available for Redis check")
        return False

    try:
        if redis_client is None:
            if not hasattr(current_app, 'redis'):
                logger.warning("Redis not initialized yet")
                return False
            redis_client = current_app.redis

        return redis_client.ping()
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return False


def run_diagnostics(app):
    """
    Run comprehensive diagnostics for the application.
    
    Logs configuration details, loaded modules, and checks both database and
    Redis connectivity within the app context.
    
    :param app: The Flask application instance.
    """
    logger.info("Starting diagnostics...")

    logger.info(f"Core DB object type: {type(core_db)}")
    logger.info(f"Core DB initialized: {getattr(core_db, '_is_initialized', False)}")

    logger.info("Flask app configuration:")
    logger.info(f"Debug mode: {app.debug}")
    logger.info(f"Testing mode: {app.testing}")
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'Not set')
    if db_uri != 'Not set' and '@' in db_uri:
        logger.info(f"Database URL: {db_uri.split('@')[1]}")
    else:
        logger.info("Database URL: Not set")

    modules = [m for m in sys.modules if 'app' in m]
    logger.info("Loaded modules:")
    for module in modules:
        logger.info(f"  - {module}")

    with app.app_context():
        logger.info("Checking database in app context...")
        if hasattr(app, 'extensions') and 'sqlalchemy' in app.extensions:
            logger.info("SQLAlchemy extension found")
            db_status = check_db_connection(core_db)
            logger.info(f"Database connection: {'OK' if db_status else 'FAILED'}")
        else:
            logger.info("Database not initialized yet - skipping check")
            logger.info(f"Available extensions: {list(getattr(app, 'extensions', {}).keys())}")

        if hasattr(app, 'redis'):
            redis_status = check_redis_connection()
            logger.info(f"Redis connection: {'OK' if redis_status else 'FAILED'}")
        else:
            logger.info("Redis not initialized yet - skipping check")

        logger.info("Session config:")
        for key in ['SESSION_TYPE', 'SESSION_REDIS', 'PERMANENT_SESSION_LIFETIME']:
            logger.info(f"  - {key}: {app.config.get(key)}")

        logger.info("Eventlet status:")
        logger.info(f"  - Threading: {threading.current_thread().__class__.__module__}")
        logger.info(f"  - Socket patched: {'socket' in eventlet.patcher.already_patched}")


def run_final_diagnostics(app):
    """
    Run final diagnostics after all extensions are initialized.
    
    Checks and logs the final status of the database and Redis connections.
    
    :param app: The Flask application instance.
    """
    logger.info("Running final diagnostics...")
    with app.app_context():
        db_status = check_db_connection()
        redis_status = check_redis_connection()
        logger.info(f"Final Database connection: {'OK' if db_status else 'FAILED'}")
        logger.info(f"Final Redis connection: {'OK' if redis_status else 'FAILED'}")


def install_error_handlers(app):
    """
    Install enhanced error handlers to capture and log unhandled exceptions.
    
    The error handler logs detailed request information, attempts additional
    diagnostic checks, and re-raises the exception.
    
    :param app: The Flask application instance.
    """
    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        thread_id = threading.current_thread().ident
        logger.error(f"Exception occurred in thread {thread_id}")

        try:
            if has_app_context():
                logger.error(f"Request URL: {request.url}")
                logger.error(f"Request Method: {request.method}")
                logger.error(f"Request Headers: {dict(request.headers)}")

                if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                    check_db_connection()

                if hasattr(current_app, 'redis'):
                    check_redis_connection()

        except Exception as check_error:
            logger.error(f"Error during diagnostic checks: {check_error}")

        # Re-raise the exception after logging for further handling
        raise