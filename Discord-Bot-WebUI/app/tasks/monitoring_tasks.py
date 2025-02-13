# app/tasks/monitoring_tasks.py

"""
Monitoring Tasks

This module defines a Celery task to collect detailed database statistics,
create a DBMonitoringSnapshot instance from those statistics, and store it in the database.
"""

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core import celery
from app.database.db_models import DBMonitoringSnapshot

# Configure logger for this module.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)


@celery.task(name='app.tasks.monitoring_tasks.collect_db_stats')
def collect_db_stats():
    """
    Collect and store database statistics.

    This Celery task:
    - Enters the Flask app context.
    - Establishes a database session and verifies connectivity.
    - Collects detailed statistics via the db_manager.
    - Creates a DBMonitoringSnapshot instance with the collected stats.
    - Commits the snapshot to the database.

    Raises:
        SQLAlchemyError: If a database error occurs during stats collection or commit.
        Exception: For any other errors during stats collection.
    """
    logger.info("Starting collect_db_stats task")
    
    # Retrieve the Flask app from the Celery instance.
    app = celery.flask_app
    logger.info("Created Flask app")
    
    with app.app_context():
        logger.info("Entered app context")
        session = app.SessionLocal()
        try:
            # Test the database connection.
            session.execute(text('SELECT 1'))
            logger.info("Database connection successful")

            # Import db_manager here to avoid circular dependencies.
            from app.db_management import db_manager

            # Collect detailed statistics from the database.
            stats = db_manager.get_detailed_stats()
            logger.info("Collected database stats")

            # Create a snapshot instance with the collected stats.
            snapshot = DBMonitoringSnapshot(
                timestamp=datetime.utcnow(),
                pool_stats=stats.get('pool_stats'),
                active_connections=stats.get('active_connections'),
                long_running_transactions=stats.get('long_running_transactions'),
                recent_events=stats.get('recent_events'),
                session_monitor=stats.get('session_monitor')
            )
            logger.info("Created DBMonitoringSnapshot instance")

            # Save the snapshot to the database.
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