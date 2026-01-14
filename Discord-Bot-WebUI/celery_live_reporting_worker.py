# celery_live_reporting_worker.py

"""
Celery Live Reporting Worker

This script starts a dedicated Celery worker for live reporting tasks,
using a prefork pool and the 'live_reporting' queue.
"""

import sys
import signal
from celery_worker_base import celery_app as celery, logger


def graceful_shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal - initiating graceful shutdown...")
    sys.exit(0)


# Register signal handlers for graceful shutdown
signal.signal(signal.SIGTERM, graceful_shutdown_handler)
signal.signal(signal.SIGINT, graceful_shutdown_handler)

if __name__ == '__main__':
    try:
        logger.info("Starting Live Reporting Celery worker")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '--hostname=live-reporting-worker@%h',
            '-Q', 'live_reporting',
            '--pool=prefork',
            '--concurrency=2',
            '--prefetch-multiplier=1',
            '--max-tasks-per-child=500',  # Increased from 50 to reduce restart overhead
            '--time-limit=300',
            '--soft-time-limit=240',
            '--max-memory-per-child=250000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
