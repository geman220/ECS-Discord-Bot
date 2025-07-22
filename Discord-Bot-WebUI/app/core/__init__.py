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
from celery import signals

# Initialize core components
db = SQLAlchemy()
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    logger=True,
    engineio_logger=False
)
celery = Celery('app')

# Make signals accessible from celery object
celery.signals = signals


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
    # Configure Redis client with connection pool settings
    redis_socket_options = {
        'socket_timeout': 5,
        'socket_connect_timeout': 5,
        'retry_on_timeout': True,
        'health_check_interval': 30
    }
    
    celery.conf.update(
        broker_url=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        result_backend=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        redis_socket_timeout=5,
        redis_socket_connect_timeout=5,
        redis_retry_on_timeout=True,
        broker_transport_options={
            'visibility_timeout': 3600,  # 1 hour
            'socket_timeout': 5,
            'socket_connect_timeout': 5,
            'max_connections': 5  # Further reduced for unified architecture
        },
        result_backend_transport_options={
            'socket_timeout': 5,
            'socket_connect_timeout': 5
        },
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        worker_cancel_long_running_tasks_on_connection_loss=True,
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