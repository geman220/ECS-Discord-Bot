# celery_discord_worker.py
import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import celery, init_celery
import logging
import pytz
import os
import time
from celery.signals import worker_init

logger = logging.getLogger(__name__)

@worker_init.connect
def init_worker(**kwargs):
    """Set timezone for worker at startup."""
    logger.info("Initializing worker with America/Los_Angeles timezone")
    # Set the timezone for the worker
    os.environ['TZ'] = 'America/Los_Angeles'
    if hasattr(time, 'tzset'):
        time.tzset()

# Create Flask app instance
app = create_app()

# Initialize Celery with Flask context
init_celery(app)

if __name__ == '__main__':
    logger.info("Starting Discord worker")
    logger.info(f"Task Routes Configuration: {app.config.get('task_routes')}")
    logger.info(f"Timezone: {app.config.get('timezone')}")
    logger.info(f"Queues: discord")
    
    celery.worker_main([
        'worker',
        '--loglevel=INFO',
        '-Q', 'discord',
        '--pool=eventlet',
        '--concurrency=8',
        '--max-tasks-per-child=50',
        '--prefetch-multiplier=1',
        '-Ofair'  # Added fair scheduling
    ])