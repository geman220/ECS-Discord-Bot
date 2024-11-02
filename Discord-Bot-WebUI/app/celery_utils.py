# celery_utils.py
from celery import Celery
from flask import Flask

def create_celery_app(app: Flask) -> Celery:
    """Create and configure Celery with Flask application context."""
    celery_app = Celery(
        app.import_name,
        broker=app.config['CELERY_BROKER_URL'],
        backend=app.config['CELERY_RESULT_BACKEND']
    )

    # Update Celery config from Flask config
    celery_app.conf.update(
        broker_url=app.config['CELERY_BROKER_URL'],
        result_backend=app.config['CELERY_RESULT_BACKEND'],
        accept_content=['json'],
        task_serializer='json',
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_time_limit=30 * 60,  # 30 minutes
        task_soft_time_limit=15 * 60,  # 15 minutes
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1
    )

    class ContextTask(celery_app.Task):
        """Ensures tasks run within Flask app context"""
        abstract = True
        
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app.Task = ContextTask
    return celery_app