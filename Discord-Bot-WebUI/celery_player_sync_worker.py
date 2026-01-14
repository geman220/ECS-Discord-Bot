# celery_player_sync_worker.py

"""
Celery Player Sync Worker

This script starts a dedicated Celery worker for player synchronization tasks,
using a prefork pool and a dedicated 'player_sync' queue.
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
        logger.info("Starting Player Sync Celery Worker")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '--hostname=player-sync-worker@%h',
            '-Q', 'player_sync',
            '--pool=prefork',
            '--concurrency=2',
            '--prefetch-multiplier=1',
            '--max-tasks-per-child=500',  # Increased from 100 to reduce restart overhead
            '--time-limit=1800',
            '--soft-time-limit=1500',
            '--max-memory-per-child=250000'
        ])
    except Exception as e:
        logger.error(f"Failed to start player sync worker: {e}", exc_info=True)
        sys.exit(1)