# celery_discord_worker.py

from celery_worker_base_prefork import flask_app, celery_app as celery, logger
import sys

if __name__ == '__main__':
    try:
        logger.info("Starting Discord Celery worker")
        celery.worker_main([
            'worker',
            '--loglevel=DEBUG',
            '-Q', 'discord',
            '--pool=prefork',
            '--concurrency=4',
        ])
    except Exception as e:
        logger.error(f"Failed to start worker: {e}", exc_info=True)
        sys.exit(1)
