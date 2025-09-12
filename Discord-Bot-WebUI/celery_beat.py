# celery_beat.py

"""
Celery Beat Scheduler Script

This script initializes the Celery beat scheduler after verifying the Redis
connection and ensuring the beat schedule directory is set up. It uses Eventlet
to monkey-patch the standard library for asynchronous operations.
"""

import eventlet
eventlet.monkey_patch(thread=False)

import os
import sys

from celery.apps.beat import Beat

from celery_worker_base import flask_app, celery_app as celery, logger
from app.utils.safe_redis import get_safe_redis
from app.config.celery_config import CeleryConfig


def verify_redis():
    """Verify that the Redis connection is working."""
    with flask_app.app_context():
        redis_client = get_safe_redis()
        try:
            if not redis_client.ping():
                logger.error("Failed to connect to Redis")
                return False
            logger.info("Redis connection verified")
            return True
        except Exception as e:
            logger.error(f"Redis connection error: {str(e)}")
            return False


def setup_beat_directory():
    """Create the directory for Celery beat schedule files."""
    try:
        beat_dir = '/tmp/celerybeat'
        os.makedirs(beat_dir, exist_ok=True)
        logger.info(f"Created beat directory: {beat_dir}")
        os.chmod(beat_dir, 0o755)
        return True
    except Exception as e:
        logger.error(f"Failed to create beat directory: {str(e)}")
        return False


def start_beat():
    """Start the Celery beat scheduler."""
    try:
        schedule_file = '/tmp/celerybeat/celerybeat-schedule'
        pid_file = '/tmp/celerybeat/celerybeat.pid'
        
        beat = Beat(
            app=celery,
            loglevel='INFO',
            schedule=schedule_file,
            pidfile=pid_file,
            max_interval=300,
            scheduler_cls='celery.beat.PersistentScheduler',
            working_directory='/tmp/celerybeat'
        )
        
        logger.info("Starting beat scheduler...")
        beat.run()
        
    except Exception as e:
        logger.error(f"Failed to start beat scheduler: {str(e)}")
        raise


if __name__ == '__main__':
    try:
        logger.info("Initializing Celery beat scheduler")
        
        # Verify Redis connection
        if not verify_redis():
            logger.error("Redis verification failed. Exiting.")
            sys.exit(1)
        
        # Setup beat schedule directory
        if not setup_beat_directory():
            logger.error("Beat directory setup failed. Exiting.")
            sys.exit(1)
        
        # Start the beat scheduler
        start_beat()
        
    except Exception as e:
        logger.error(f"Beat scheduler failed: {str(e)}")
        sys.exit(1)