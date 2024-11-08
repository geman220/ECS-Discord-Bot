# app/extensions.py
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from celery import Celery
import eventlet
eventlet.monkey_patch()

# Initialize extensions
db = SQLAlchemy()
socketio = SocketIO(
    async_mode='eventlet',
    engineio_logger=True,
    logger=True,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
)

def create_celery(app=None):
    """Create Celery instance with proper configuration"""
    _celery = Celery(
        'app',
        broker='redis://redis:6379/0',
        backend='redis://redis:6379/0',
    )

    # Update Celery config
    _celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=30 * 60,
        task_soft_time_limit=15 * 60
    )

    class FlaskTask(_celery.Task):
        """Celery Task that wraps task execution in Flask application context"""
        abstract = True
        
        def __call__(self, *args, **kwargs):
            if app is None:
                # Look for an application context
                from flask import current_app
                if current_app:
                    flask_app = current_app
                else:
                    # Create new app if no context
                    from app import create_app
                    flask_app = create_app()
            else:
                flask_app = app
                
            with flask_app.app_context():
                return self.run(*args, **kwargs)

    _celery.Task = FlaskTask
    
    if app:
        # Update celery config from app
        _celery.conf.update(app.config)
        
    return _celery

# Create the base celery instance
celery = create_celery()
