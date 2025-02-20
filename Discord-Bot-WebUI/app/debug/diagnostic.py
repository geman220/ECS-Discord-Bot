"""
Diagnostic utilities for the Flask application.

This module provides middleware and functions to monitor the request lifecycle,
and to run basic connectivity checks for the database and Redis.
"""

import threading
import eventlet
import logging
import sys
from sqlalchemy import text
from flask import request, has_app_context, g, current_app
from app.core import db as core_db

# Configure logging at INFO level; detailed exception info will log at DEBUG.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def diagnostic_middleware(app):
    """
    Middleware to track the request lifecycle and detect request timeouts.
    """
    @app.before_request
    def before_request():
        # Warn if required extensions are missing.
        if not (hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions):
            logger.warning("SQLAlchemy not initialized in diagnostic middleware")
            return
        if not hasattr(current_app, 'redis'):
            logger.warning("Redis not initialized in diagnostic middleware")
            return

        # Schedule a timeout handler to run after 30 seconds.
        g._request_timeout = eventlet.spawn_after(30, timeout_handler)
        logger.info("Request started")

    @app.after_request
    def after_request(response):
        # Cancel the scheduled timeout handler if it exists.
        if hasattr(g, '_request_timeout'):
            try:
                g._request_timeout.cancel()
            except Exception:
                logger.error("Error cancelling timeout handler")
        logger.info("Request completed")
        return response


def timeout_handler():
    """
    Handler called when a request exceeds its allowed processing time.
    """
    logger.error("Request timeout detected")


def check_db_connection(db=None):
    """
    Verify database connectivity by executing a simple query.
    Sensitive details (like full DB credentials) are not logged.
    Returns True if the connection is successful; False otherwise.
    """
    if not has_app_context():
        logger.warning("No application context available for DB check")
        return False

    try:
        if db is None:
            db = core_db
            if not (hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions):
                logger.warning("SQLAlchemy not initialized yet")
                return False

        logger.info("Attempting to connect to the database")
        with db.engine.connect() as conn:
            # Execute a simple query.
            conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            return True

    except Exception as e:
        logger.error("Database connection failed")
        logger.debug("Exception details", exc_info=True)
        return False


def check_db_initialization(app):
    """
    Check the database configuration and initialization status.
    Logs only high-level configuration info.
    """
    logger.info("Checking database initialization")
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if db_uri:
        logger.info("Database URI is configured")
    else:
        logger.info("Database URI not set")

    if hasattr(app, 'extensions') and 'sqlalchemy' in app.extensions:
        logger.info("SQLAlchemy extension is initialized")
    else:
        logger.info("SQLAlchemy extension not initialized")


def check_redis_connection(redis_client=None):
    """
    Verify Redis connectivity by sending a ping command.
    Returns True if Redis responds; False otherwise.
    """
    if not has_app_context():
        logger.warning("No application context available for Redis check")
        return False

    try:
        if redis_client is None:
            if not hasattr(current_app, 'redis'):
                logger.warning("Redis not initialized")
                return False
            redis_client = current_app.redis

        if redis_client.ping():
            logger.info("Redis connection successful")
            return True
        else:
            logger.error("Redis ping failed")
            return False
    except Exception as e:
        logger.error("Redis connection failed")
        logger.debug("Exception details", exc_info=True)
        return False


def run_diagnostics(app):
    """
    Run basic diagnostics for the application.
    Logs minimal configuration and connectivity statuses.
    """
    logger.info("Running diagnostics")
    with app.app_context():
        if hasattr(app, 'extensions') and 'sqlalchemy' in app.extensions:
            db_status = check_db_connection(core_db)
            logger.info(f"Database connection: {'OK' if db_status else 'FAILED'}")
        else:
            logger.info("SQLAlchemy not initialized; skipping database check")

        if hasattr(app, 'redis'):
            redis_status = check_redis_connection()
            logger.info(f"Redis connection: {'OK' if redis_status else 'FAILED'}")
        else:
            logger.info("Redis not initialized; skipping Redis check")


def run_final_diagnostics(app):
    """
    Run final diagnostics after all extensions are initialized.
    """
    logger.info("Running final diagnostics")
    with app.app_context():
        db_status = check_db_connection()
        redis_status = check_redis_connection()
        logger.info(f"Final Database connection: {'OK' if db_status else 'FAILED'}")
        logger.info(f"Final Redis connection: {'OK' if redis_status else 'FAILED'}")


def install_error_handlers(app):
    """
    Install an error handler to capture unhandled exceptions.
    Logs only minimal request details to avoid leaking sensitive information.
    """
    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.error("Unhandled exception occurred", exc_info=True)
        try:
            if has_app_context():
                logger.error(f"Request URL: {request.url}")
                logger.error(f"Request Method: {request.method}")
        except Exception:
            logger.error("Error during diagnostic checks", exc_info=True)
        # Re-raise the exception for further handling.
        raise e