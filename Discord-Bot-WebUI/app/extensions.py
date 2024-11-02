# app/extensions.py

# Monkey patch must happen first
import eventlet
eventlet.monkey_patch()

from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from celery import Celery

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
celery = Celery()

def init_celery(app=None):
    """Initialize Celery with Flask application context."""
    if app is None:
        from flask import current_app
        app = current_app

    celery.conf.update(app.config)
    
    class ContextTask(celery.Task):
        """Ensures tasks run within Flask app context"""
        abstract = True
        
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery