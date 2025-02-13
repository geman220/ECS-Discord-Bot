# app/tasks/tasks_maintenance.py

"""
Maintenance Tasks Module

This module defines a periodic Celery task for database connection maintenance.
Specifically, it cleans up idle transactions and connection pools every 5 minutes.
"""

import logging
from app.core import celery
from app.db_management import db_manager

logger = logging.getLogger(__name__)


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    Configure periodic tasks after Celery is set up.

    Schedules the cleanup_database_connections task to run every 5 minutes.
    """
    sender.add_periodic_task(
        300.0,  # 300 seconds = 5 minutes
        cleanup_database_connections.s(),
        name='cleanup-database-connections'
    )


@celery.task
def cleanup_database_connections():
    """
    Periodic task to clean up database connections.

    This task terminates idle transactions and cleans up connection pools via the
    db_manager. It logs the result and returns a status dictionary.
    
    Returns:
        A dictionary indicating success or error with an optional message.
    """
    logger.info("Running scheduled database connection cleanup")
    try:
        db_manager.terminate_idle_transactions()
        db_manager.cleanup_connections()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in database cleanup task: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}