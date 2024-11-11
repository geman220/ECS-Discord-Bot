# app/tasks/tasks_maintenance.py

from celery.schedules import crontab
from app.core import celery
from app.db_management import db_manager
import logging

logger = logging.getLogger(__name__)

@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Run database cleanup every 5 minutes
    sender.add_periodic_task(
        300.0,
        cleanup_database_connections.s(),
        name='cleanup-database-connections'
    )

@celery.task
def cleanup_database_connections():
    """Periodic task to clean up database connections"""
    logger.info("Running scheduled database connection cleanup")
    try:
        db_manager.terminate_idle_transactions()
        db_manager.cleanup_pool()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in database cleanup task: {e}")
        return {"status": "error", "message": str(e)}