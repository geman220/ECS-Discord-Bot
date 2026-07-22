# app/tasks/tasks_maintenance.py

"""
Maintenance Tasks Module

This module defines a periodic Celery task for database connection maintenance.
Specifically, it cleans up idle transactions and connection pools every 5 minutes.
"""

import os
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


# setup_periodic_tasks REMOVED — it was an @celery.on_after_configure.connect handler
# that NEVER FIRED, so the six periodic tasks it registered were never scheduled.
#
# WHY IT NEVER FIRED: Celery sends on_after_configure when it finalizes its config,
# which happens the moment it READS conf.imports. This module is IN conf.imports
# (app/config/celery_config.py:57) — so by the time it gets imported, the signal has
# already been sent, and connecting a handler afterwards is too late.
#
# It was not a theory. player_attendance_stats was last computed 2026-06-03, 39 days
# stale, with 78 of 248 players still at season_matches_invited = 0 — which is exactly
# the condition that makes the coach dashboard recompute attendance live from raw RSVP
# rows on every single load. Substitute requests were never expiring either.
#
# The five WORKING tasks now live in the static CeleryConfig.beat_schedule
# (app/config/celery_config.py), where beat actually reads them.
#
# The sixth, cleanup_database_connections, is deliberately NOT scheduled: it calls
# db_manager.terminate_idle_transactions() and .cleanup_connections(), neither of which
# exists on DatabaseManager — it would raise AttributeError every 5 minutes. It is also
# obsolete; idle-in-transaction was fixed by the pgbouncer web/celery pool split and the
# commit-before-render hook. Left in place (unscheduled) rather than deleted, in case
# something calls it directly.


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
def expire_stale_substitute_pools(self, session, inactive_days=120):
    """Deactivate substitute-pool memberships that have gone stale.

    Keeps the "active sub pool" from filling up with people who signed up once and
    were never used again (or lingered across seasons). A membership is stale when
    it is still active but its most recent signal — last_active_at, else
    joined_pool_at, else created_at — is older than ``inactive_days``.

    Conservative on purpose: it only flips the pool row's ``is_active`` to False
    (the source of truth the sub-matcher filters on, so a deactivated person stops
    being offered matches) and drops ``player.is_sub`` when they have no active
    pools left. It does NOT strip Discord/Flask sub roles automatically — that
    destructive step is left to the admin "stale subs" review list, where a human
    confirms. Covers both the unified SubstitutePool and the legacy EcsFcSubPool.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func as sqlfunc
    from app.models.substitutes import SubstitutePool, EcsFcSubPool, log_pool_action
    from app.models import Player

    cutoff = datetime.utcnow() - timedelta(days=inactive_days)
    affected_player_ids = set()
    deactivated = 0

    try:
        pl_stale = session.query(SubstitutePool).filter(
            SubstitutePool.is_active == True,  # noqa: E712
            sqlfunc.coalesce(
                SubstitutePool.last_active_at,
                SubstitutePool.joined_pool_at,
                SubstitutePool.created_at,
            ) < cutoff
        ).all()
        for pool in pl_stale:
            pool.is_active = False
            affected_player_ids.add(pool.player_id)
            deactivated += 1
            try:
                log_pool_action(
                    player_id=pool.player_id, league_id=pool.league_id, action='REMOVED',
                    notes=f"Auto-expired from {pool.league_type} sub pool "
                          f"(inactive > {inactive_days}d)",
                    performed_by=None, pool_id=pool.id, session=session,
                )
            except Exception as e:
                logger.warning(f"Pool history log skipped for player {pool.player_id}: {e}")

        ecs_stale = session.query(EcsFcSubPool).filter(
            EcsFcSubPool.is_active == True,  # noqa: E712
            sqlfunc.coalesce(
                EcsFcSubPool.last_active_at,
                EcsFcSubPool.joined_pool_at,
            ) < cutoff
        ).all()
        for pool in ecs_stale:
            pool.is_active = False
            affected_player_ids.add(pool.player_id)
            deactivated += 1

        session.flush()

        # Drop the player-level is_sub flag for anyone with no active pools left.
        cleared_is_sub = 0
        for pid in affected_player_ids:
            has_active_pl = session.query(SubstitutePool.id).filter(
                SubstitutePool.player_id == pid, SubstitutePool.is_active == True  # noqa: E712
            ).first()
            has_active_ecs = session.query(EcsFcSubPool.id).filter(
                EcsFcSubPool.player_id == pid, EcsFcSubPool.is_active == True  # noqa: E712
            ).first()
            if not has_active_pl and not has_active_ecs:
                player = session.query(Player).get(pid)
                if player and player.is_sub:
                    player.is_sub = False
                    cleared_is_sub += 1

        # Phase-0 dual-write: reflect the deactivations in the league_membership spine
        # (their sub rows go active->resting) for each affected player.
        if affected_player_ids:
            from app.services.league_membership_sync import resync_player_memberships
            for _pid in affected_player_ids:
                resync_player_memberships(session, _pid)

        logger.info(f"Sub pool hygiene: deactivated {deactivated} stale membership(s) "
                    f"across {len(affected_player_ids)} player(s); cleared is_sub on {cleared_is_sub}")
        return {
            "status": "success",
            "deactivated": deactivated,
            "players_affected": len(affected_player_ids),
            "is_sub_cleared": cleared_is_sub,
            "inactive_days": inactive_days,
        }
    except Exception as e:
        logger.error(f"Error expiring stale substitute pools: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_task
def advance_season_phases(self, session):
    """Auto-advance the current Pub League season's lifecycle phase on schedule.

    preseason -> in_season once start_date is reached; in_season -> offseason once
    end_date has passed. ECS FC is exempt (pinned in_season, no rollover). Discord
    channels/roles are NEVER torn down here — that is the separate manual rollover
    process; this only flips the phase flag. See season_phase_service.auto_advance_phases.
    """
    try:
        from app.services.season_phase_service import auto_advance_phases
        changes = auto_advance_phases(session)
        if changes:
            logger.info("Season phase auto-advance: %s", "; ".join(changes))
        return {"status": "success", "changes": changes}
    except Exception as e:
        logger.error(f"Error advancing season phases: {e}", exc_info=True)
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


@celery_task(
    name='app.tasks.tasks_maintenance.recalculate_all_attendance_stats',
    bind=True,
    queue='celery',
    max_retries=0,
)
def recalculate_all_attendance_stats(self, session):
    """Recompute every PlayerAttendanceStats row (career + current-season) in the
    background.

    The admin "Recalculate Statistics" button used to do this inline in the web
    request — looping hundreds of players, each now doing several queries — which
    exceeded the request timeout and rolled the whole transaction back, so stored
    attendance stayed frozen (career showed the old buggy calc, season read 0%).
    Running it as a task with a per-player commit removes the timeout and lets
    partial progress persist; one bad player can't lose the rest.
    """
    from app.models.stats import PlayerAttendanceStats

    player_ids = [pid for (pid,) in session.query(PlayerAttendanceStats.player_id).all()]
    updated = 0
    errors = 0
    for pid in player_ids:
        try:
            stat = session.query(PlayerAttendanceStats).filter_by(player_id=pid).first()
            if stat is not None:
                stat.update_stats(session)
                session.commit()
                updated += 1
        except Exception as e:
            session.rollback()
            errors += 1
            logger.warning(f"recalculate_all_attendance_stats: player {pid} failed: {e}")
    logger.info(f"recalculate_all_attendance_stats: {updated} updated, {errors} errors, {len(player_ids)} total")
    return {'updated': updated, 'errors': errors, 'total': len(player_ids)}


@celery_task(
    name='app.tasks.tasks_maintenance.expire_past_match_sub_requests',
    bind=True,
    queue='celery',
    max_retries=1,
)
def expire_past_match_sub_requests(self, session):
    """Mark substitute requests EXPIRED once their match date has passed.

    Neither the Pub League (SubstituteRequest) nor the ECS FC (EcsFcSubRequest)
    system filtered by match date or had any auto-expiry, so OPEN requests for
    matches that already happened piled up in the Priority Fill Queue / sub-request
    boards forever (e.g. the ~19 stale items). This expires active requests whose
    match is in the past so the boards only show what's actually actionable. EXPIRED
    is terminal and excluded from the active/open views; rows are kept for history.
    """
    from app.models.substitutes import SubstituteRequest, EcsFcSubRequest
    from app.models.matches import Match
    from app.models.ecs_fc import EcsFcMatch
    from app.utils.substitute_helpers import ACTIVE_SUB_STATUSES, actionable_sub_cutoff_date

    # Expire only once a request is past the grace window the UI still shows it in,
    # so a request stays live through its ~24h retroactive-assignment window rather
    # than vanishing the morning after the match.
    cutoff = actionable_sub_cutoff_date()
    active = ACTIVE_SUB_STATUSES

    pl = (session.query(SubstituteRequest)
          .join(Match, SubstituteRequest.match_id == Match.id)
          .filter(SubstituteRequest.status.in_(active), Match.date < cutoff)
          .all())
    for req in pl:
        req.status = 'EXPIRED'

    ecs = (session.query(EcsFcSubRequest)
           .join(EcsFcMatch, EcsFcSubRequest.match_id == EcsFcMatch.id)
           .filter(EcsFcSubRequest.status.in_(active), EcsFcMatch.match_date < cutoff)
           .all())
    for req in ecs:
        req.status = 'EXPIRED'

    session.commit()
    logger.info(f"expire_past_match_sub_requests: expired {len(pl)} Pub League + {len(ecs)} ECS FC past-match requests")
    return {'pub_league_expired': len(pl), 'ecs_fc_expired': len(ecs)}

@celery_task(
    name='app.tasks.tasks_maintenance.cleanup_task_executions',
    bind=True,
    queue='celery',
    max_retries=1
)
def cleanup_task_executions(self, session):
    """Trim the task_executions table to a rolling retention window.

    Every @celery_task run INSERTs one row here (app/decorators.py::_record_task_execution)
    to power the admin Task History page, and NOTHING pruned it. High-frequency beat tasks
    make that unbounded: the draft clock alone runs every 15s = ~5,760 rows/day, and the
    live-reporting watchdog every 2 min adds ~720 more. Left alone this table grows by
    millions of rows a year on a 1-vCPU Postgres, and every INSERT is a pooled transaction.

    Task History only ever looks at recent runs, so keep a rolling window and delete the
    rest. Deleted in batches so we never hold a long transaction (a pgbouncer server slot is
    pinned for the whole transaction — see the transaction-budget notes).
    """
    from datetime import datetime, timedelta
    from app.models.api_logs import TaskExecution

    retention_days = int(os.getenv('TASK_EXECUTION_RETENTION_DAYS', '14'))
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    total = 0
    while True:
        ids = [
            r[0] for r in session.query(TaskExecution.id)
            .filter(TaskExecution.created_at < cutoff)
            .limit(5000).all()
        ]
        if not ids:
            break
        session.query(TaskExecution).filter(TaskExecution.id.in_(ids)).delete(
            synchronize_session=False
        )
        session.commit()
        total += len(ids)

    logger.info(f"cleanup_task_executions: deleted {total} rows older than {retention_days}d")
    return {'deleted': total, 'retention_days': retention_days}


@celery_task(
    name='app.tasks.tasks_maintenance.update_player_attendance',
    bind=True,
    queue='celery',
    max_retries=1,
)
def update_player_attendance(self, session, player_id, season_id=None):
    """Recompute ONE player's attendance stats after their RSVP changed.

    This used to run INLINE inside the RSVP task (tasks_rsvp.py), whose own comment already
    said "update attendance stats asynchronously to avoid blocking main RSVP flow" — but the
    call was synchronous. It also never actually ran: attendance_service used an unimported
    `g`, so every call raised NameError and the caller's `except Exception` ate it.

    Doing it inline is the wrong shape now that it works:
      * update_stats() is ~11 queries (it rescans the player's whole career match history),
        which is a lot to bolt onto a hot write path on a 1-vCPU Postgres;
      * the RSVP write is NOT yet committed when it runs, so it cannot share the RSVP task's
        session — a rollback in the retry loop would discard the RSVP itself — which means an
        inline call has to open a SECOND concurrent connection while the first is still open.
    As its own task it gets one session, one connection, and the RSVP task returns immediately.
    """
    from app.models.stats import PlayerAttendanceStats

    stat = PlayerAttendanceStats.get_or_create(player_id, season_id, session=session)
    stat.update_stats(session=session)
    session.commit()
    logger.debug(f"Recomputed attendance stats for player {player_id}")
    return {'player_id': player_id, 'season_id': season_id}
