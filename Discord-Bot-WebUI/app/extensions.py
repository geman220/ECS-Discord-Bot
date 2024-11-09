# app/extensions.py
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown, task_prerun, task_postrun
import eventlet
import logging

eventlet.monkey_patch()

logger = logging.getLogger(__name__)

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
        task_soft_time_limit=15 * 60,
        worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
        worker_max_memory_per_child=150000  # Restart if memory exceeds 150MB
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
                try:
                    return self.run(*args, **kwargs)
                finally:
                    # Ensure database connections are cleaned up
                    try:
                        db.session.remove()
                        if hasattr(db, 'engine'):
                            db.engine.dispose()
                    except Exception as e:
                        logger.error(f"Error cleaning up database connection: {e}")

    _celery.Task = FlaskTask

    # Setup Celery signal handlers
    @worker_process_init.connect
    def init_worker(**kwargs):
        """Initialize worker process with clean database connection."""
        logger.info("Initializing Celery worker process")
        try:
            if hasattr(db, 'engine'):
                db.engine.dispose()
        except Exception as e:
            logger.error(f"Error disposing engine on worker init: {e}")

    @worker_process_shutdown.connect
    def shutdown_worker(**kwargs):
        """Cleanup database connections on worker shutdown."""
        logger.info("Shutting down Celery worker process")
        try:
            db.session.remove()
            if hasattr(db, 'engine'):
                db.engine.dispose()
        except Exception as e:
            logger.error(f"Error cleaning up on worker shutdown: {e}")

    @task_prerun.connect
    def task_prerun_handler(task_id, task, *args, **kwargs):
        """Setup fresh database connection before task."""
        logger.debug(f"Setting up database connection for task {task_id}")
        try:
            db.session.remove()
            if hasattr(db, 'engine'):
                db.engine.dispose()
        except Exception as e:
            logger.error(f"Error in task prerun cleanup: {e}")

    @task_postrun.connect
    def task_postrun_handler(task_id, task, *args, retval, state, **kwargs):
        """Cleanup database connections after task."""
        logger.debug(f"Cleaning up database connection for task {task_id} (state: {state})")
        try:
            db.session.remove()
            if hasattr(db, 'engine'):
                db.engine.dispose()
        except Exception as e:
            logger.error(f"Error in task postrun cleanup: {e}")
    
    if app:
        # Update celery config from app
        _celery.conf.update(app.config)
        
    return _celery

# Create the base celery instance
celery = create_celery()