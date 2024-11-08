# app/celery_utils.py

from celery import Celery
from flask import Flask, current_app
from typing import Any, Callable
from functools import wraps
import logging

logger = logging.getLogger(__name__)

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

    class FlaskTask(celery_app.Task):
        """Celery task that ensures Flask application context."""
        abstract = True

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            task_id = self.request.id if hasattr(self, 'request') else 'Unknown'
            thread_id = threading.get_ident()
        
            logger.info(
                f"[TASK CALL START] ID: {task_id}\n"
                f"Task Name: {self.name}\n"
                f"Thread ID: {thread_id}\n"
                f"Has App Context: {has_app_context()}"
            )
        
            try:
                from app import create_app
                flask_app = create_app()
            
                logger.info(
                    f"[APP CREATED] Task ID: {task_id}\n"
                    f"App Import Path: {flask_app.__module__}"
                )
            
                with flask_app.app_context():
                    log_context_state("Inside FlaskTask app context")
                    return self.run(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"[TASK ERROR] ID: {task_id}\n"
                    f"Error: {str(e)}\n"
                    f"Has App Context: {has_app_context()}\n"
                    f"Stack Trace: {traceback.format_exc()}"
                )
                raise

    celery_app.Task = FlaskTask
    celery_app.flask_app = app
    
    return celery_app

def async_task_with_context(f: Callable) -> Callable:
    """Decorator for async functions that need Flask context."""
    @wraps(f)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            from app import create_app
            flask_app = create_app()
            
            with flask_app.app_context():
                return await f(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Async task failed: {str(e)}")
            raise
    return wrapped