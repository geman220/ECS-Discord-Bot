# celery_player_sync_worker.py

import sys
import logging
from celery_worker_base import flask_app, celery_app as celery, logger

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
            '--max-tasks-per-child=50',
            '--time-limit=1800',
            '--soft-time-limit=1500'
        ])
    except Exception as e:
        logger.error(f"Failed to start player sync worker: {e}", exc_info=True)
        sys.exit(1)