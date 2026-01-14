# celery_discord_worker.py

"""
Celery Discord Worker

This module starts the Discord-specific Celery worker using a prefork pool.
It uses celery.worker_main with defined options to launch the worker.
"""

import sys
import signal
from celery_worker_base_prefork import celery_app as celery, logger


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
        logger.info("Starting Discord Celery worker")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'discord',
            '--pool=prefork',
            '--concurrency=2',
            '--max-tasks-per-child=500',  # Increased from 50 to reduce restart overhead
            '--max-memory-per-child=250000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)