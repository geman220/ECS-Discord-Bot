# celery_live_reporting_worker.py

"""
Celery Live Reporting Worker

This script starts a dedicated Celery worker for live reporting tasks,
using an Eventlet pool and the 'live_reporting' queue. It is configured with
high concurrency and prefetch settings, along with resource limits.
"""

import sys
from celery_worker_base import celery_app as celery, logger

if __name__ == '__main__':
    try:
        logger.info("Starting Live Reporting Celery worker")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'live_reporting',
            '--pool=eventlet',
            '--concurrency=16',
            '--prefetch-multiplier=4',
            '--max-tasks-per-child=50',
            '--time-limit=1800',
            '--soft-time-limit=1500',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
