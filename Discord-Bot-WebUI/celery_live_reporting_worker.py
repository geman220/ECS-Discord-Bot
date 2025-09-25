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
            '--concurrency=4',  # Reduced from 16 to prevent overload
            '--prefetch-multiplier=1',  # Reduced from 4 to limit task prefetch
            '--max-tasks-per-child=50',  # Reduced from 100 for more frequent restarts
            '--time-limit=300',  # Reduced from 1800 (30min to 5min) - live updates should be quick
            '--soft-time-limit=240',  # Reduced from 1500 (25min to 4min)
            '--max-memory-per-child=100000'  # Reduced from 150MB to 100MB
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
