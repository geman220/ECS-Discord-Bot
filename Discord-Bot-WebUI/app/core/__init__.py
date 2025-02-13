# app/core/__init__.py

"""
Core Application Module

This module initializes the core components of the application, including:
  - SQLAlchemy for ORM
  - SocketIO for real-time communication
  - Celery for asynchronous task processing

It also provides a function to configure Celery with the Flask application context.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from celery import Celery

# Initialize core components
db = SQLAlchemy()
socketio = SocketIO()
celery = Celery('app')


def configure_celery(app):
    """
    Configure Celery to work with the Flask application context.

    This function updates the Celery configuration using the Flask app's configuration,
    attaches the Flask app to the Celery instance, and defines a custom Task base class
    to ensure that tasks run within the Flask application context.

    Args:
        app (Flask): The Flask application instance.

    Returns:
        Celery: The configured Celery instance.
    """
    celery.conf.update(
        broker_url=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        result_backend=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=30 * 60,
        task_soft_time_limit=15 * 60,
        worker_max_tasks_per_child=50,
        worker_max_memory_per_child=150000
    )

    # Attach the Flask app to the Celery instance
    celery.flask_app = app

    # Define a custom Task base class to ensure tasks run within the Flask app context
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    # Set the base Task class to the custom ContextTask
    celery.Task = ContextTask

    return celery