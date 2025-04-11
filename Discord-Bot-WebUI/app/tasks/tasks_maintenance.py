# app/tasks/tasks_maintenance.py

"""
Maintenance Tasks Module

This module defines a periodic Celery task for database connection maintenance.
Specifically, it cleans up idle transactions and connection pools every 5 minutes.
"""

import logging
from datetime import datetime, timedelta
from app.core import celery, db
from app.db_management import db_manager
from app.models import TemporarySubAssignment, Match
from celery.schedules import crontab

logger = logging.getLogger(__name__)


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    Configure periodic tasks after Celery is set up.

    Schedules the following tasks:
    - cleanup_database_connections: Run every 5 minutes
    - cleanup_old_sub_assignments: Run every Monday at midnight
    """
    # Database connection cleanup - every 5 minutes
    sender.add_periodic_task(
        300.0,  # 300 seconds = 5 minutes
        cleanup_database_connections.s(),
        name='cleanup-database-connections'
    )
    
    # Sub assignment cleanup - every Monday at midnight
    sender.add_periodic_task(
        crontab(hour=0, minute=0, day_of_week=1),  # Monday at midnight
        cleanup_old_sub_assignments.s(),
        name='cleanup-old-sub-assignments'
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


@celery.task
def cleanup_old_sub_assignments():
    """
    Clean up temporary sub assignments for matches that have already occurred.
    This task runs every Monday to clean up the previous week's matches.
    
    Returns:
        A dictionary indicating success or error with count of removed assignments.
    """
    logger.info("Running scheduled cleanup of old temporary sub assignments")
    try:
        current_date = datetime.utcnow().date()
        
        # Find all assignments for matches that have already occurred
        with db.session.begin():
            old_assignments = db.session.query(TemporarySubAssignment).join(
                Match, TemporarySubAssignment.match_id == Match.id
            ).filter(
                Match.date < current_date
            ).all()
            
            assignment_count = len(old_assignments)
            if assignment_count > 0:
                for assignment in old_assignments:
                    db.session.delete(assignment)
                
                logger.info(f"Successfully deleted {assignment_count} old sub assignments for past matches")
                
        return {
            "status": "success",
            "message": f"Deleted {assignment_count} old sub assignments",
            "count": assignment_count
        }
    except Exception as e:
        logger.error(f"Error cleaning up old sub assignments: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}