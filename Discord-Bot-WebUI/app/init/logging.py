# app/init/logging.py

"""
Logging Configuration

Configure logging using dictConfig for production or simple console logging for testing.
"""

import logging
import logging.config


def init_logging(app):
    """
    Initialize logging configuration for the Flask application.

    Args:
        app: The Flask application instance.
    """
    # Use simplified logging for testing to avoid file permission issues
    if app.config.get('TESTING'):
        # Simple console-only logging for tests
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
        ))

        # Configure root logger for tests
        root_logger = logging.getLogger()
        root_logger.handlers = [console_handler]
        root_logger.setLevel(logging.WARNING)

        # Configure app logger
        app.logger.handlers = [console_handler]
        app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    else:
        # Use full logging configuration for production
        from app.log_config.logging_config import LOGGING_CONFIG
        logging.config.dictConfig(LOGGING_CONFIG)
        app.logger.setLevel(logging.INFO if app.debug else logging.WARNING)
        if app.debug:
            logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
