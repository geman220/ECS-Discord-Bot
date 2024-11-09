# celery_beat.py
import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import celery, db
from app.utils.redis_manager import RedisManager
from app.config.celery_config import CeleryConfig
from celery.apps.beat import Beat
from celery.signals import beat_init
import logging
import os
import pytz
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app instance globally
flask_app = create_app()
celery.flask_app = flask_app

def initialize_celery(app):
    """Initialize Celery with app configuration"""
    try:
        app.config.from_object(CeleryConfig)
        celery.conf.update(app.config)
        return celery
    except Exception as e:
        logger.error(f"Failed to initialize Celery: {e}")
        raise

@beat_init.connect
def beat_init_handler(**kwargs):
    """Initialize Flask context for beat scheduler."""
    try:
        logger.info("Initializing beat scheduler with Flask context")
        flask_app.app_context().push()
        
        # Ensure clean database state
        if hasattr(db, 'engine'):
            db.engine.dispose()
        db.session.remove()
    except Exception as e:
        logger.error(f"Beat initialization failed: {e}")
        raise

def verify_redis():
    """Verify Redis connection is working"""
    with flask_app.app_context():
        redis_manager = RedisManager()
        try:
            if not redis_manager.client.ping():
                logger.error("Failed to connect to Redis")
                return False
            logger.info("Redis connection verified")
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
        os.chmod(beat_dir, 0o755)
        return True
    except Exception as e:
        logger.error(f"Failed to create beat directory: {str(e)}")
        return False

def start_beat(app):
    """Start the Celery beat scheduler"""
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
    try:
        logger.info("Initializing Celery beat scheduler")
        
        # Initialize Celery
        celery = initialize_celery(flask_app)
        
        # Initialize app context for main process
        flask_app.app_context().push()
        
        # Verify Redis connection
        if not verify_redis():
            logger.error("Redis verification failed. Exiting.")
            sys.exit(1)
        
        # Setup beat directory
        if not setup_beat_directory():
            logger.error("Beat directory setup failed. Exiting.")
            sys.exit(1)
        
        # Start beat scheduler
        start_beat(flask_app)
    except Exception as e:
        logger.error(f"Beat scheduler failed: {str(e)}")
        sys.exit(1)
        
    finally:
        # Cleanup on exit
        try:
            if hasattr(db, 'engine'):
                db.engine.dispose()
            db.session.remove()
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")