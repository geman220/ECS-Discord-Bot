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
        # Changed from eventlet to prefork due to eventlet deadlocking issue
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '--hostname=live-reporting-worker@%h',  # Explicit hostname
            '-Q', 'live_reporting',
            '--pool=prefork',  # Changed from eventlet - eventlet was deadlocking
            '--concurrency=2',  # Reduced for prefork
            '--prefetch-multiplier=1',
            '--max-tasks-per-child=50',
            '--time-limit=300',
            '--soft-time-limit=240',
            '--max-memory-per-child=250000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
