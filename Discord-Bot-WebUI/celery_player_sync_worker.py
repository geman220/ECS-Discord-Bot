# celery_player_sync_worker.py

"""
Celery Player Sync Worker

This script starts a dedicated Celery worker for player synchronization tasks,
using an Eventlet pool and a dedicated 'player_sync' queue.
"""

import sys
from celery_worker_base import celery_app as celery, logger

if __name__ == '__main__':
    try:
        logger.info("Starting Player Sync Celery Worker")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'player_sync',
            '--pool=eventlet',
            '--concurrency=4',
            '--prefetch-multiplier=1',
            '--max-tasks-per-child=100',
            '--time-limit=1800',
            '--soft-time-limit=1500',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start player sync worker: {e}", exc_info=True)
        sys.exit(1)