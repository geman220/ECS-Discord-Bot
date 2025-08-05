# app/database/config.py

"""
Database configuration utilities.

This module provides functions to set up detailed logging for SQLAlchemy and to
configure database settings for the Flask application using engine options.
"""

import logging
from app.database.pool import ENGINE_OPTIONS

logger = logging.getLogger(__name__)

def setup_db_logging(testing=False):
    """
    Configure detailed logging for SQLAlchemy engine and connection pool.

    Sets the log level for the SQLAlchemy engine and pool loggers, attaches a
    FileHandler with a specific formatter, and disables propagation to prevent
    duplicate logging.
    
    :param testing: If True, skip file logging to avoid permission issues
    """
    db_logger = logging.getLogger('sqlalchemy.engine')
    db_logger.setLevel(logging.INFO)

    pool_logger = logging.getLogger('sqlalchemy.pool')
    pool_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
    )

    # Iterate over the loggers and set up the handler for each.
    for logger_instance in (db_logger, pool_logger):
        # Clear existing handlers.
        logger_instance.handlers = []
        
        if testing:
            # Use console handler for testing to avoid file permission issues
            handler = logging.StreamHandler()
        else:
            # Use file handler for production with logs directory
            handler = logging.FileHandler('logs/sql_detailed.log')
            
        handler.setFormatter(formatter)
        logger_instance.addHandler(handler)
        # Disable propagation to avoid duplicate logs.
        logger_instance.propagate = False

def configure_db_settings(app):
    """
    Configure the Flask application's database settings with enhanced options.

    This function updates the engine options by adding an 'application_name'
    parameter to the connection arguments, applies the configuration to the app,
    sets up detailed SQLAlchemy logging, and logs the current pool settings.

    :param app: The Flask application instance.
    :return: True if the configuration is applied successfully.
    :raises Exception: Re-raises any exception encountered during configuration.
    """
    try:
        is_testing = app.config.get('TESTING', False)
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_sqlite = 'sqlite' in db_uri.lower()
        
        if is_testing and is_sqlite:
            # For SQLite testing, use minimal engine options
            engine_options = {
                'pool_pre_ping': False,  # Not needed for SQLite
                'echo': False
            }
            logger.info("Using SQLite engine options for testing")
        else:
            # Use full PostgreSQL engine options for production
            engine_options = ENGINE_OPTIONS.copy()

            # Update connection arguments to include an application name for tracking.
            engine_options.update({
                'connect_args': {
                    **ENGINE_OPTIONS.get('connect_args', {}),
                    'application_name': 'flask_app'
                }
            })
            logger.info("Using PostgreSQL engine options for production")

        # Apply SQLAlchemy settings to the Flask app configuration.
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

        # Set up detailed logging for database operations.
        setup_db_logging(testing=is_testing)

        # Log current database pool settings for debugging purposes.
        if not is_testing or not is_sqlite:
            logger.info("Database settings configured with:")
            logger.info(f"Pool size: {engine_options.get('pool_size')}")
            logger.info(f"Max overflow: {engine_options.get('max_overflow')}")
            logger.info(f"Pool timeout: {engine_options.get('pool_timeout')}")
            logger.info(f"Pool recycle: {engine_options.get('pool_recycle')}")

    except Exception as e:
        logger.error(f"Error configuring database settings: {e}", exc_info=True)
        raise

    return True