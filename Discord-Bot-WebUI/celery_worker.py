# celery_worker.py

"""
Celery Worker

This script starts the main Celery worker using an Eventlet pool with the 'celery'
queue. It configures high concurrency and prefetch settings, and also applies
resource limits such as maximum tasks per child and time limits.
"""

import sys
from celery_worker_base import celery_app as celery, logger

if __name__ == '__main__':
    try:
        logger.info("Starting Celery worker")

        # Start the Celery worker with the specified options.
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'celery',
            '--pool=eventlet',
            '--concurrency=8',
            '--prefetch-multiplier=4',
            '--max-tasks-per-child=100',
            '--time-limit=1800',
            '--soft-time-limit=1500',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
