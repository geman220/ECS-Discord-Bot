# app/database/config.py
import logging
from app.database.pool import RateLimitedPool, ENGINE_OPTIONS  # Import both

logger = logging.getLogger(__name__)

def setup_db_logging():
    """Configure detailed logging"""
    db_logger = logging.getLogger('sqlalchemy.engine')
    db_logger.setLevel(logging.INFO)
    
    # Add pool logging
    pool_logger = logging.getLogger('sqlalchemy.pool')
    pool_logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
    )
    
    # Clear existing handlers
    for logger in (db_logger, pool_logger):
        logger.handlers = []
        fh = logging.FileHandler('sql_detailed.log')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.propagate = False

def configure_db_settings(app):
    """Configure database settings with enhanced options"""
    try:
        # Start with base ENGINE_OPTIONS from pool.py
        engine_options = ENGINE_OPTIONS.copy()
        
        # Add Flask-specific configurations
        engine_options.update({
            'connect_args': {
                **ENGINE_OPTIONS['connect_args'],
                'application_name': 'flask_app'
            }
        })
        
        # Update app config
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Configure detailed logging
        setup_db_logging()
        
        # Log configuration summary
        logger.info("Database settings configured with:")
        logger.info(f"Pool size: {engine_options['pool_size']}")
        logger.info(f"Max overflow: {engine_options['max_overflow']}")
        logger.info(f"Pool timeout: {engine_options['pool_timeout']}")
        logger.info(f"Pool recycle: {engine_options['pool_recycle']}")
        
    except Exception as e:
        logger.error(f"Error configuring database settings: {e}", exc_info=True)
        raise

    return True