# celery_worker.py
import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import celery, db
from celery.signals import (
    worker_init, 
    worker_process_init,
    worker_process_shutdown,
    task_prerun,
    task_postrun,
    worker_shutting_down
)
from flask import current_app
import logging
import os
import time
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app instance
flask_app = create_app()
celery.flask_app = flask_app  # Store reference to app

@worker_init.connect
def init_worker(**kwargs):
    """Initialize worker with configuration."""
    try:
        logger.info("Initializing worker with America/Los_Angeles timezone")
        os.environ['TZ'] = 'America/Los_Angeles'
        if hasattr(time, 'tzset'):
            time.tzset()
            
        # Log important configurations
        logger.info(f"Broker URL: {celery.conf.broker_url}")
        logger.info(f"Database URL: {flask_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')}")
        logger.info(f"Concurrency: {celery.conf.worker_concurrency}")
    except Exception as e:
        logger.error(f"Worker initialization failed: {e}")
        sys.exit(1)

@worker_process_init.connect
def init_worker_process(**kwargs):
    """Initialize Flask context and database connections for each worker process."""
    try:
        logger.info("Initializing worker process")
        flask_app.app_context().push()
        
        # Ensure clean database state
        if hasattr(db, 'engine'):
            db.engine.dispose()
        db.session.remove()
        
        logger.info("Worker process initialized successfully")
    except Exception as e:
        logger.error(f"Worker process initialization failed: {e}")
        sys.exit(1)

@worker_process_shutdown.connect
def cleanup_worker_process(**kwargs):
    """Cleanup database connections when worker process shuts down."""
    try:
        logger.info("Cleaning up worker process")
        if hasattr(db, 'engine'):
            db.engine.dispose()
        db.session.remove()
        logger.info("Worker process cleanup completed")
    except Exception as e:
        logger.error(f"Worker process cleanup failed: {e}")

@task_prerun.connect
def task_prerun_handler(task, **kwargs):
    """Ensure Flask context and clean database state before each task."""
    try:
        if not current_app:
            logger.info("Pushing new application context for task")
            flask_app.app_context().push()
            
        # Ensure clean database session
        db.session.remove()
        if hasattr(db, 'engine'):
            db.engine.dispose()
            
        logger.debug(f"Task {task.name} setup completed")
    except Exception as e:
        logger.error(f"Task prerun setup failed: {e}")
        raise

@task_postrun.connect
def task_postrun_handler(task, state, **kwargs):
    """Cleanup after task completion."""
    try:
        logger.debug(f"Cleaning up after task {task.name} (state: {state})")
        db.session.remove()
        if hasattr(db, 'engine'):
            db.engine.dispose()
    except Exception as e:
        logger.error(f"Task postrun cleanup failed: {e}")

@worker_shutting_down.connect
def worker_shutdown_handler(**kwargs):
    """Handle graceful shutdown of worker."""
    try:
        logger.info("Worker shutting down - cleaning up resources")
        if hasattr(db, 'engine'):
            db.engine.dispose()
        db.session.remove()
    except Exception as e:
        logger.error(f"Worker shutdown cleanup failed: {e}")

if __name__ == '__main__':
    try:
        logger.info("Starting Celery worker")
        logger.info(f"Task Routes: {flask_app.config.get('CELERY_TASK_ROUTES')}")
        logger.info(f"Timezone: {flask_app.config.get('TIMEZONE', 'America/Los_Angeles')}")
        
        # Initialize app context for main process
        flask_app.app_context().push()
        
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'celery,default',
            '--pool=eventlet',
            '--concurrency=4',
            '--max-tasks-per-child=50',
            '--prefetch-multiplier=1',
            '-Ofair',
            '--time-limit=1800',  # 30 minute hard time limit
            '--soft-time-limit=1500',  # 25 minute soft time limit
            '--max-memory-per-child=150000'  # Restart worker if memory exceeds 150MB
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}")
        sys.exit(1)