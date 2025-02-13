# celery_worker_base.py

"""
Celery Worker Base Module

This module initializes the Flask application, applies Eventlet monkey patching
for asynchronous support, and updates the Celery configuration using the Flask
app's configuration. It exports the Flask app, the Celery app, and a logger
for use by worker scripts.
"""

import eventlet
eventlet.monkey_patch()  # Apply monkey patching for async support

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
celery_app.flask_app = flask_app

# Export the necessary components for worker scripts
__all__ = ['flask_app', 'celery_app', 'logger']
