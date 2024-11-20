# app/tasks/monitoring_tasks.py

from app import create_app
from app.core import celery, db
from app.db_management import db_manager
from app.database.db_models import DBMonitoringSnapshot
from datetime import datetime
import logging
from sqlalchemy import text

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()  # Or FileHandler('worker.log') to log to a file
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

@celery.task(name='app.tasks.monitoring_tasks.collect_db_stats')
def collect_db_stats():
    logger.info("Starting collect_db_stats task")
    app = celery.flask_app
    logger.info("Created Flask app")
    with app.app_context():
        logger.info("Entered app context")
        try:
            # Test database connection using text()
            db.session.execute(text('SELECT 1'))
            logger.info("Database connection successful")

            stats = db_manager.get_detailed_stats()
            logger.info("Collected database stats")

            snapshot = DBMonitoringSnapshot(
                timestamp=datetime.utcnow(),
                pool_stats=stats.get('pool_stats'),
                active_connections=stats.get('active_connections'),
                long_running_transactions=stats.get('long_running_transactions'),
                recent_events=stats.get('recent_events'),
                session_monitor=stats.get('session_monitor')
            )
            logger.info("Created DBMonitoringSnapshot instance")

            db.session.add(snapshot)
            db.session.commit()
            logger.info("Database stats collected and saved successfully")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error collecting DB stats: {e}", exc_info=True)
            raise