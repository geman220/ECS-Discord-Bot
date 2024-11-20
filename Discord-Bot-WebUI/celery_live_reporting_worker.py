# celery_live_reporting_worker.py

from celery_worker_base import flask_app, celery_app as celery, logger
import sys

if __name__ == '__main__':
    try:
        logger.info("Starting Live Reporting Celery worker")

        # Start Celery worker with Eventlet pool
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'live_reporting',
            '--pool=eventlet',
            '--concurrency=1000',
            '--prefetch-multiplier=1000',
            '--max-tasks-per-child=50',
            '--time-limit=1800',
            '--soft-time-limit=1500',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
