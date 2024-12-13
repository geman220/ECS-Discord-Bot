# app/tasks/monitoring_tasks.py

from app import create_app
from app.core import celery
from app.database.db_models import DBMonitoringSnapshot
from datetime import datetime
import logging
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
        session = app.SessionLocal()
        try:
            # Test database connection
            session.execute(text('SELECT 1'))
            logger.info("Database connection successful")

            # Retrieve in-memory detailed stats from db_manager
            # Assuming `db_manager` is globally imported or accessible
            from app.db_management import db_manager
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

            session.add(snapshot)
            session.commit()
            logger.info("Database stats collected and saved successfully")

        except SQLAlchemyError as e:
            logger.error(f"Database error collecting DB stats: {e}", exc_info=True)
            session.rollback()
            raise
        except Exception as e:
            logger.error(f"Error collecting DB stats: {e}", exc_info=True)
            session.rollback()
            raise
        finally:
            session.close()
