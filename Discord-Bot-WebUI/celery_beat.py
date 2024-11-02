# celery_beat.py
import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import celery, init_celery
from app.utils.redis_manager import RedisManager
from app.config.celery_config import CeleryConfig
from celery.apps.beat import Beat
import logging
import os
import pytz

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def create_celery_app():
    """Create and configure Celery application"""
    # Create Flask app instance
    flask_app = create_app()
    
    # Apply Celery configuration
    flask_app.config.from_object(CeleryConfig)
    
    # Initialize Celery with Flask context
    init_celery(flask_app)
    
    return flask_app, celery

def verify_redis():
    """Verify Redis connection is working"""
    redis_manager = RedisManager()
    try:
        if not redis_manager.client.ping():
            logger.error("Failed to connect to Redis")
            return False
        logger.info("Redis connection verified")
        # List all Redis keys for debugging
        keys = redis_manager.client.keys('*')
        decoded_keys = [k.decode() if isinstance(k, bytes) else k for k in keys]
        logger.info(f"Current Redis keys: {decoded_keys}")
        return True
    except Exception as e:
        logger.error(f"Redis connection error: {str(e)}")
        return False

def setup_beat_directory():
    """Create directory for beat schedule files"""
    try:
        beat_dir = '/tmp/celerybeat'
        os.makedirs(beat_dir, exist_ok=True)
        logger.info(f"Created beat directory: {beat_dir}")
        # Set proper permissions
        os.chmod(beat_dir, 0o755)
        return True
    except Exception as e:
        logger.error(f"Failed to create beat directory: {str(e)}")
        return False

def start_beat(app, celery_app):
    """Start the Celery beat scheduler"""
    try:
        schedule_file = '/tmp/celerybeat/celerybeat-schedule'
        pid_file = '/tmp/celerybeat/celerybeat.pid'
        
        beat = Beat(
            app=celery_app,
            loglevel='INFO',
            schedule=schedule_file,
            pidfile=pid_file,
            max_interval=300,
            scheduler_cls='celery.beat.PersistentScheduler',
            working_directory='/tmp/celerybeat'
        )
        
        # Log configuration
        logger.info("Beat Configuration:")
        logger.info(f"Schedule file: {beat.schedule}")
        logger.info(f"Max interval: {beat.max_interval}s")
        logger.info(f"Scheduler class: {beat.scheduler_cls}")
        logger.info(f"Timezone: {CeleryConfig.timezone}")
        logger.info("Tasks to be scheduled:")
        
        for task_name, task_config in CeleryConfig.beat_schedule.items():
            schedule = task_config['schedule']
            queue = task_config.get('options', {}).get('queue', 'default')
            logger.info(f"  - {task_name}:")
            logger.info(f"    Schedule: {schedule}")
            logger.info(f"    Queue: {queue}")
        
        logger.info("Starting beat scheduler...")
        beat.run()
        
    except Exception as e:
        logger.error(f"Failed to start beat scheduler: {str(e)}")
        raise

if __name__ == '__main__':
    logger.info("Initializing Celery beat scheduler")
    
    # Create and configure app
    flask_app, celery_app = create_celery_app()
    
    # Verify Redis connection
    if not verify_redis():
        logger.error("Redis verification failed. Exiting.")
        exit(1)
    
    # Setup beat directory
    if not setup_beat_directory():
        logger.error("Beat directory setup failed. Exiting.")
        exit(1)
    
    try:
        # Start beat scheduler
        start_beat(flask_app, celery_app)
    except Exception as e:
        logger.error(f"Beat scheduler failed: {str(e)}")
        exit(1)