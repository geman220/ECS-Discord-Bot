# celery_worker.py
from celery_worker_base import flask_app, celery_app as celery, logger
import sys

if __name__ == '__main__':
    try:
        logger.info("Starting Celery worker")

        # Get configuration from celery instance
        task_routes = celery.conf.get('task_routes', {})
        timezone = celery.conf.get('timezone', 'America/Los_Angeles')

        logger.info(f"Task Routes: {task_routes}")
        logger.info(f"Timezone: {timezone}")

        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'celery,default',
            '--pool=eventlet',
            '--concurrency=4',
            '--max-tasks-per-child=50',
            '--prefetch-multiplier=1',
            '-Ofair',
            '--time-limit=1800',
            '--soft-time-limit=1500',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
