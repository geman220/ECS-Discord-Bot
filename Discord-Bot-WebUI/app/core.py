# app/core.py

from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from celery import Celery

db = SQLAlchemy()
socketio = SocketIO()
celery = Celery('app')

def configure_celery(app):
    """Configure Celery with application context"""
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
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery.Task = ContextTask
    return celery