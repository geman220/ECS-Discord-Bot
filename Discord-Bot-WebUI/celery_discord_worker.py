# celery_discord_worker.py

"""
Celery Discord Worker

This module starts the Discord-specific Celery worker using a prefork pool.
It uses celery.worker_main with defined options to launch the worker.
"""

import sys
from celery_worker_base_prefork import celery_app as celery, logger

if __name__ == '__main__':
    try:
        logger.info("Starting Discord Celery worker")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '-Q', 'discord',
            '--pool=prefork',
            '--concurrency=4',
            '--max-tasks-per-child=100',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)