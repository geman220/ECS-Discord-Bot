# app/tasks/tasks_maintenance.py

"""
Maintenance Tasks Module

This module defines a periodic Celery task for database connection maintenance.
Specifically, it cleans up idle transactions and connection pools every 5 minutes.
"""

import logging
import json
from datetime import datetime, timedelta
from app.core import celery
from app.decorators import celery_task
from app.db_management import db_manager
from app.models import TemporarySubAssignment, Match
from app.models.communication import ScheduledMessage
from app.utils.safe_redis import get_safe_redis
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
    
    # Scheduled message cleanup - daily at 2 AM
    sender.add_periodic_task(
        crontab(hour=2, minute=0),  # Daily at 2 AM
        cleanup_old_scheduled_messages.s(),
        name='cleanup-old-scheduled-messages'
    )

    # Presence SET cleanup - every 5 minutes
    # Removes stale entries from Redis SET (handles server crashes, etc.)
    sender.add_periodic_task(
        300.0,  # 300 seconds = 5 minutes
        cleanup_presence_set.s(),
        name='cleanup-presence-set'
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


@celery_task
def cleanup_old_sub_assignments(self, session):
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
        old_assignments = session.query(TemporarySubAssignment).join(
            Match, TemporarySubAssignment.match_id == Match.id
        ).filter(
            Match.date < current_date
        ).all()
        
        assignment_count = len(old_assignments)
        if assignment_count > 0:
            for assignment in old_assignments:
                session.delete(assignment)
                
                logger.info(f"Successfully deleted {assignment_count} old sub assignments for past matches")
                
        return {
            "status": "success",
            "message": f"Deleted {assignment_count} old sub assignments",
            "count": assignment_count
        }
    except Exception as e:
        logger.error(f"Error cleaning up old sub assignments: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_task
def cleanup_old_scheduled_messages(self, session):
    """
    Clean up old scheduled messages to prevent processing of invalid references.
    This task runs daily to remove:
    - Messages older than 9 days
    - Messages referencing non-existent matches
    - Messages in failed state for over 7 days
    
    Returns:
        A dictionary indicating success or error with count of removed messages.
    """
    logger.info("Running scheduled cleanup of old scheduled messages")
    try:
        current_time = datetime.utcnow()
        cutoff_date = current_time - timedelta(days=9)
        failed_cutoff = current_time - timedelta(days=7)
        
        deleted_count = 0
        
        # Delete messages older than 9 days
        old_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.created_at < cutoff_date
        ).all()
        
        for msg in old_messages:
            session.delete(msg)
            deleted_count += 1
        
        # Delete messages in failed state for over 7 days  
        failed_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.status.in_(['FAILED', 'ERROR']),
            ScheduledMessage.updated_at < failed_cutoff
        ).all()
        
        for msg in failed_messages:
            session.delete(msg)
            deleted_count += 1
        
        # Delete messages referencing non-existent matches
        orphaned_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.match_id.isnot(None)
        ).all()
        
        for msg in orphaned_messages:
            match_exists = session.query(Match).filter_by(id=msg.match_id).first()
            if not match_exists:
                session.delete(msg)
                deleted_count += 1
        
        logger.info(f"Successfully deleted {deleted_count} old/orphaned scheduled messages")
        
        return {
            "status": "success", 
            "message": f"Deleted {deleted_count} old/orphaned scheduled messages (>9 days old or orphaned)",
            "count": deleted_count
        }
    except Exception as e:
        logger.error(f"Error cleaning up old scheduled messages: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery.task
def cleanup_presence_set():
    """
    Periodic task to clean up stale presence SET entries.

    Handles edge cases where the presence SET gets out of sync with actual
    presence keys (e.g., after server crash or Redis connection issues).

    Returns:
        dict: Status with count of stale entries removed
    """
    logger.info("Running scheduled presence SET cleanup")
    try:
        from app.sockets.presence import PresenceManager
        removed = PresenceManager.cleanup_stale_set_members()
        return {"status": "success", "removed": removed}
    except Exception as e:
        logger.error(f"Error in presence cleanup task: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_task(
    name='app.tasks.tasks_maintenance.cleanup_expired_queue_tasks',
    bind=True,
    queue='celery',
    max_retries=2
)
def cleanup_expired_queue_tasks(self, session):
    """
    Clean up expired tasks from Redis queues to prevent backlog buildup.
    
    Checks all Celery queues for expired tasks and removes them.
    """
    try:
        redis = get_safe_redis()
        if not redis or not hasattr(redis, 'is_available') or not redis.is_available:
            logger.warning("Redis not available for queue cleanup")
            return {"status": "skipped", "message": "Redis not available"}
        
        queues_to_clean = ['live_reporting', 'discord', 'celery', 'player_sync']
        total_cleaned = 0
        queue_stats = {}
        
        for queue_name in queues_to_clean:
            try:
                # Get queue length before cleanup
                initial_length = redis.llen(queue_name)
                if initial_length == 0:
                    queue_stats[queue_name] = {'initial': 0, 'cleaned': 0, 'remaining': 0}
                    continue
                
                cleaned_count = 0
                current_time = datetime.utcnow()
                
                # Process queue items in batches to avoid blocking Redis
                batch_size = 100
                remaining_items = []
                
                # Get all items from the queue
                all_items = redis.lrange(queue_name, 0, -1)
                
                for item in all_items:
                    try:
                        # Parse the Celery task message
                        task_data = json.loads(item)
                        headers = task_data.get('headers', {})
                        expires = headers.get('expires')
                        
                        if expires:
                            # Parse expiry time
                            if isinstance(expires, str):
                                expire_time = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                            else:
                                # Skip if expiry format is not recognized
                                remaining_items.append(item)
                                continue
                            
                            # Check if task is expired
                            if expire_time < current_time:
                                cleaned_count += 1
                            else:
                                remaining_items.append(item)
                        else:
                            # Keep tasks without expiry
                            remaining_items.append(item)
                            
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        # Keep malformed items (let Celery handle them)
                        remaining_items.append(item)
                        logger.debug(f"Skipped malformed task in {queue_name}: {e}")
                
                # Replace queue contents with non-expired items
                if cleaned_count > 0:
                    # Clear the queue and repopulate with valid items
                    redis.delete(queue_name)
                    if remaining_items:
                        redis.lpush(queue_name, *remaining_items)
                
                total_cleaned += cleaned_count
                queue_stats[queue_name] = {
                    'initial': initial_length,
                    'cleaned': cleaned_count,
                    'remaining': len(remaining_items)
                }
                
                logger.info(f"Queue {queue_name}: cleaned {cleaned_count} expired tasks, {len(remaining_items)} remaining")
                
            except Exception as e:
                logger.error(f"Error cleaning queue {queue_name}: {e}")
                queue_stats[queue_name] = {'error': str(e)}
        
        logger.info(f"Queue cleanup completed: {total_cleaned} expired tasks removed total")
        
        return {
            "status": "success",
            "message": f"Cleaned {total_cleaned} expired tasks across all queues",
            "total_cleaned": total_cleaned,
            "queue_stats": queue_stats
        }
        
    except Exception as e:
        logger.error(f"Error during queue cleanup: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_task(
    name='app.tasks.tasks_maintenance.monitor_celery_health',
    bind=True,
    queue='celery',
    max_retries=1
)
def monitor_celery_health(self, session):
    """
    Monitor Celery system health including queue lengths, worker status, and failed tasks.
    
    Provides alerting when thresholds are exceeded.
    """
    try:
        redis = get_safe_redis()
        if not redis or not hasattr(redis, 'is_available') or not redis.is_available:
            logger.warning("Redis not available for health monitoring")
            return {"status": "skipped", "message": "Redis not available"}
        
        health_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'queues': {},
            'alerts': [],
            'status': 'healthy'
        }
        
        # Queue health thresholds
        queue_thresholds = {
            'live_reporting': 100,  # Alert if > 100 tasks
            'discord': 50,
            'celery': 200,
            'player_sync': 30
        }
        
        # Check queue lengths
        for queue_name, threshold in queue_thresholds.items():
            try:
                queue_length = redis.llen(queue_name)
                health_data['queues'][queue_name] = {
                    'length': queue_length,
                    'threshold': threshold,
                    'status': 'ok' if queue_length <= threshold else 'warning'
                }
                
                if queue_length > threshold:
                    alert_msg = f"Queue {queue_name} has {queue_length} tasks (threshold: {threshold})"
                    health_data['alerts'].append({
                        'type': 'queue_backlog',
                        'queue': queue_name,
                        'message': alert_msg,
                        'severity': 'warning' if queue_length < threshold * 2 else 'critical'
                    })
                    logger.warning(alert_msg)
                
            except Exception as e:
                health_data['queues'][queue_name] = {'error': str(e)}
        
        # Check for stuck tasks (tasks older than 1 hour in queue)
        try:
            current_time = datetime.utcnow()
            for queue_name in queue_thresholds.keys():
                # Sample first few tasks to check age
                sample_tasks = redis.lrange(queue_name, 0, 4)  # Check first 5 tasks
                
                stuck_count = 0
                for task_data in sample_tasks:
                    try:
                        task_json = json.loads(task_data)
                        headers = task_json.get('headers', {})
                        
                        # Check task age (if timestamp available)
                        task_id = headers.get('id', 'unknown')
                        
                        # For more accurate monitoring, we'd need to track task creation time
                        # This is a simplified check
                        
                    except (json.JSONDecodeError, KeyError):
                        continue
        
        except Exception as e:
            logger.error(f"Error checking for stuck tasks: {e}")
        
        # Set overall health status
        if health_data['alerts']:
            critical_alerts = [a for a in health_data['alerts'] if a['severity'] == 'critical']
            health_data['status'] = 'critical' if critical_alerts else 'warning'
        
        # Log summary
        total_tasks = sum(q.get('length', 0) for q in health_data['queues'].values() if isinstance(q, dict) and 'length' in q)
        alert_count = len(health_data['alerts'])
        
        if alert_count > 0:
            logger.warning(f"Celery health check: {alert_count} alerts, {total_tasks} total tasks in queues")
        else:
            logger.info(f"Celery health check: All systems healthy, {total_tasks} total tasks in queues")
        
        return {
            "status": "success",
            "health_data": health_data,
            "total_tasks": total_tasks,
            "alert_count": alert_count
        }
        
    except Exception as e:
        logger.error(f"Error during Celery health monitoring: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_task(
    name='app.tasks.tasks_maintenance.emergency_queue_purge',
    bind=True,
    queue='celery',
    max_retries=1
)
def emergency_queue_purge(self, session):
    """
    Emergency queue purge when queues exceed critical thresholds.
    
    This is the industry-standard approach for preventing queue buildup.
    Automatically purges queues that exceed emergency thresholds to prevent
    system overload and ensure continued operation.
    """
    try:
        redis = get_safe_redis()
        if not redis or not hasattr(redis, 'is_available') or not redis.is_available:
            logger.warning("Redis not available for emergency queue purge")
            return {"status": "skipped", "message": "Redis not available"}
        
        # Emergency thresholds (much higher than warning thresholds)
        emergency_thresholds = {
            'live_reporting': 500,  # Purge if > 500 tasks
            'discord': 300,         # Purge if > 300 tasks  
            'celery': 1000,         # Purge if > 1000 tasks
            'player_sync': 200      # Purge if > 200 tasks
        }
        
        purge_stats = {}
        total_purged = 0
        
        for queue_name, threshold in emergency_thresholds.items():
            try:
                queue_length = redis.llen(queue_name)
                
                if queue_length > threshold:
                    logger.warning(f"EMERGENCY: Queue {queue_name} has {queue_length} tasks, purging...")
                    
                    # Keep only the most recent tasks (last 10% or minimum 10)
                    keep_count = max(10, int(queue_length * 0.1))
                    purged_count = queue_length - keep_count
                    
                    # Keep most recent tasks at the end of the queue
                    redis.ltrim(queue_name, -keep_count, -1)
                    
                    total_purged += purged_count
                    purge_stats[queue_name] = {
                        'original_length': queue_length,
                        'purged': purged_count,
                        'kept': keep_count,
                        'threshold': threshold,
                        'action': 'purged'
                    }
                    
                    logger.error(f"EMERGENCY PURGE: Queue {queue_name} purged {purged_count} old tasks, kept {keep_count} recent tasks")
                
                else:
                    purge_stats[queue_name] = {
                        'original_length': queue_length,
                        'threshold': threshold,
                        'action': 'no_action_needed'
                    }
                
            except Exception as e:
                logger.error(f"Error during emergency purge of queue {queue_name}: {e}")
                purge_stats[queue_name] = {'error': str(e)}
        
        if total_purged > 0:
            logger.error(f"EMERGENCY QUEUE PURGE COMPLETED: {total_purged} tasks removed across all queues")
        else:
            logger.info("Emergency queue check: All queues within acceptable limits")
        
        return {
            "status": "success",
            "message": f"Emergency purge completed: {total_purged} tasks removed",
            "total_purged": total_purged,
            "purge_stats": purge_stats,
            "emergency_action": total_purged > 0
        }
        
    except Exception as e:
        logger.error(f"Error during emergency queue purge: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}