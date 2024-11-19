# celery_worker_base.py

from eventlet import monkey_patch
from eventlet.green import threading
monkey_patch(thread=True)

from app import create_app
from app.core import celery as celery_app
from app.core import db
from app.config.celery_config import CeleryConfig
from celery.signals import worker_init
from flask import current_app
import logging
import os
import time
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Configure Celery
for key, value in vars(CeleryConfig).items():
    if not key.startswith('_'):
        celery_app.conf[key] = value

# Create Flask app instance
flask_app = create_app()

# Update Celery with Flask config
celery_app.conf.update(flask_app.config)
celery_app.flask_app = flask_app

# Export the celery app for workers to import
__all__ = ['flask_app', 'celery_app', 'logger']

@worker_init.connect
def init_worker(**kwargs):
    """Initialize worker with configuration."""
    with flask_app.app_context():
        try:
            # Set threading module for Celery
            import celery.utils.threads as celery_threads
            celery_threads.Threading = threading

            # Set timezone
            logger.info("Initializing worker with America/Los_Angeles timezone")
            os.environ['TZ'] = 'America/Los_Angeles'
            if hasattr(time, 'tzset'):
                time.tzset()

            # Override Celery's timezone setting
            celery_app.conf.timezone = 'America/Los_Angeles'

            # Log important configurations
            broker_url = celery_app.conf.get('broker_url', 'Not configured')
            logger.info(f"- Broker URL: {broker_url}")
            db_url = flask_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
            logger.info(f"- Database URL: {db_url}")
            concurrency = celery_app.conf.get('worker_concurrency', 'Not configured')
            logger.info(f"- Concurrency: {concurrency}")
            timezone = celery_app.conf.get('timezone', 'Not configured')
            logger.info(f"- Timezone: {timezone}")

            # Clean database connections
            try:
                if hasattr(db, 'get_engine'):
                    engine = db.get_engine(flask_app)
                    if engine:
                        engine.dispose()
                        logger.info("Successfully cleaned database connections")
            except Exception as db_error:
                logger.warning(f"Error cleaning database connections: {db_error}")

        except Exception as e:
            logger.error(f"Worker initialization failed: {e}", exc_info=True)
            sys.exit(1)

# Clean up function for worker shutdown
@celery_app.on_after_finalize.connect
def cleanup_app_context(*args, **kwargs):
    """Clean up the application context on worker shutdown"""
    try:
        app_context = flask_app.app_context()
        app_context.pop()
    except Exception as e:
        logger.error(f"Error cleaning up app context: {e}")
