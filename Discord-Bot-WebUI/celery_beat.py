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
    # Use persistent location instead of /tmp (which can be cleared on reboot)
    # Fall back to /tmp if persistent location is not writable
    beat_dirs = [
        '/app/data/celerybeat',  # Preferred: persistent volume in Docker
        '/var/lib/celerybeat',   # Alternative: standard Linux service data
        '/tmp/celerybeat'        # Fallback: temporary directory
    ]

    for beat_dir in beat_dirs:
        try:
            os.makedirs(beat_dir, exist_ok=True)
            # Test write access
            test_file = os.path.join(beat_dir, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            # Set appropriate permissions (owner read/write/execute)
            os.chmod(beat_dir, 0o700)
            logger.info(f"Using beat directory: {beat_dir}")
            return beat_dir
        except (OSError, PermissionError) as e:
            logger.warning(f"Cannot use beat directory {beat_dir}: {e}")
            continue

    logger.error("Failed to create any beat directory")
    return None


def start_beat():
    """Start the Celery beat scheduler."""
    beat_dir = setup_beat_directory()
    if not beat_dir:
        raise RuntimeError("No writable beat directory available")

    try:
        schedule_file = os.path.join(beat_dir, 'celerybeat-schedule')
        pid_file = os.path.join(beat_dir, 'celerybeat.pid')

        beat = Beat(
            app=celery,
            loglevel='INFO',
            schedule=schedule_file,
            pidfile=pid_file,
            max_interval=300,
            scheduler_cls='celery.beat.PersistentScheduler',
            working_directory=beat_dir
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

        # Start the beat scheduler (directory setup is handled internally)
        start_beat()

    except Exception as e:
        logger.error(f"Beat scheduler failed: {str(e)}")
        sys.exit(1)