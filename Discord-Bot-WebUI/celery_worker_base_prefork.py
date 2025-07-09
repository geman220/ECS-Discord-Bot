# celery_worker_base_prefork.py

"""
Celery Worker Base (Prefork) Module

This module initializes the Flask application and updates the Celery
configuration for a worker that uses the prefork pool. It exports the
Flask app, the Celery app, and a logger for use by worker scripts.
"""

import logging
from app import create_app
from app.core import celery as celery_app
from app.config.celery_config import CeleryConfig  # Imported for configuration reference

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Create the Flask application instance
flask_app = create_app()

# Update Celery configuration using Flask app settings
celery_app.conf.update(flask_app.config)
# Apply the CeleryConfig class configuration including imports
celery_app.config_from_object(CeleryConfig)
celery_app.flask_app = flask_app

# Export the necessary components for worker scripts
__all__ = ['flask_app', 'celery_app', 'logger']