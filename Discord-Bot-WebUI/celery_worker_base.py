# celery_worker_base.py

import eventlet
eventlet.monkey_patch()

import logging
from app import create_app
from app.core import celery as celery_app
from app.config.celery_config import CeleryConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app instance
flask_app = create_app()

# Update Celery with Flask config
celery_app.conf.update(flask_app.config)
celery_app.flask_app = flask_app

# Export the celery app for workers to import
__all__ = ['flask_app', 'celery_app', 'logger']
