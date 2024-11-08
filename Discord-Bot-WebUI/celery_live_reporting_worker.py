# celery_live_reporting_worker.py
import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import celery
import logging
import os
import time
from celery.signals import worker_init, worker_process_init, task_prerun
from flask import current_app

logger = logging.getLogger(__name__)

# Create Flask app instance
flask_app = create_app()
celery.flask_app = flask_app  # Store reference to app

@worker_init.connect
def init_worker(**kwargs):
    """Initialize worker with configuration."""
    logger.info("Initializing worker with America/Los_Angeles timezone")
    os.environ['TZ'] = 'America/Los_Angeles'
    if hasattr(time, 'tzset'):
        time.tzset()

@worker_process_init.connect
def init_worker_process(**kwargs):
    """Initialize Flask context for each worker process."""
    logger.info("Initializing worker process with Flask context")
    flask_app.app_context().push()
    
@task_prerun.connect
def task_prerun_handler(task, **kwargs):
    """Ensure Flask context is available before each task."""
    if not current_app:
        logger.info("Pushing new application context for task")
        flask_app.app_context().push()

if __name__ == '__main__':
    logger.info("Starting live reporting Celery worker")
    logger.info(f"Task Routes Configuration: {flask_app.config.get('task_routes')}")
    logger.info(f"Timezone: {flask_app.config.get('timezone')}")
    logger.info(f"Queues: live_reporting")

    # Initialize app context for main process
    flask_app.app_context().push()
    
    celery.worker_main([
        'worker',
        '--loglevel=INFO',
        '-Q', 'live_reporting',
        '--pool=eventlet',
        '--concurrency=4',
        '--max-tasks-per-child=10',
        '--prefetch-multiplier=1',
        '-Ofair'
    ])
