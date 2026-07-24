# app/tasks/monitoring_tasks.py

"""
Monitoring Tasks

This module defines Celery tasks for monitoring system health, including:
- Collecting detailed database statistics
- Checking for potential database session leaks
- Monitoring Redis connection pool usage
"""

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core import celery
from app.database.db_models import DBMonitoringSnapshot
from app.utils.redis_manager import UnifiedRedisManager
from app.utils.task_session_manager import task_session
from app.services.redis_connection_service import get_redis_service

# Use standard logger - logging config should be centralized
logger = logging.getLogger(__name__)


@celery.task(
    name='app.tasks.monitoring_tasks.collect_db_stats',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def collect_db_stats(self):
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
        try:
            with task_session() as session:
                # Test the database connection.
                session.execute(text('SELECT 1'))
                logger.info("Database connection successful")

                # Import db_manager here to avoid circular dependencies.
                from app.db_management import db_manager
                
                # Collect detailed statistics from the database.
                stats = {}
                if hasattr(db_manager, 'get_detailed_stats'):
                    stats = db_manager.get_detailed_stats()
                else:
                    # Fallback if the method doesn't exist
                    logger.warning("db_manager.get_detailed_stats method not found, using basic stats")
                    stats = {
                        'pool_stats': db_manager.get_pool_stats() if hasattr(db_manager, 'get_pool_stats') else {},
                        'active_connections': 0,
                        'long_running_transactions': [],
                        'recent_events': [],
                        'session_monitor': {}
                    }
                    
                    # Collect basic connection stats
                    conn_stats = session.execute(text("""
                        SELECT COUNT(*) as total_connections,
                               COUNT(*) FILTER (WHERE state = 'active') as active_connections,
                               COUNT(*) FILTER (WHERE state = 'idle in transaction') as idle_transactions
                        FROM pg_stat_activity
                    """)).fetchone()
                    
                    if conn_stats:
                        stats['active_connections'] = conn_stats.active_connections
                        stats['pool_stats']['total_connections'] = conn_stats.total_connections
                        stats['pool_stats']['idle_transactions'] = conn_stats.idle_transactions
                
                logger.info("Collected database stats")

                # Create a snapshot instance with the collected stats.
                snapshot = DBMonitoringSnapshot(
                    timestamp=datetime.utcnow(),
                    pool_stats=stats.get('pool_stats', {}),
                    active_connections=stats.get('active_connections', 0),
                    long_running_transactions=stats.get('long_running_transactions', []),
                    recent_events=stats.get('recent_events', []),
                    session_monitor=stats.get('session_monitor', {})
                )
                logger.info("Created DBMonitoringSnapshot instance")

                # Save the snapshot to the database.
                session.add(snapshot)
                # Commit happens automatically in task_session
                logger.info("Database stats collected and saved successfully")

        except SQLAlchemyError as e:
            logger.error(f"Database error collecting DB stats: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error collecting DB stats: {e}", exc_info=True)
            raise


@celery.task(
    name='app.tasks.monitoring_tasks.snapshot_system_metrics',
    bind=True,
    max_retries=0,          # a missed sample just leaves a gap; never retry-storm
    ignore_result=True
)
def snapshot_system_metrics(self):
    """
    Record ONE row of key system-health metrics for the System Command Center
    trend sparklines, then prune rows older than 7 days.

    This is a cheap beat task (every ~5 min), entirely OFF the request path. Each
    sample is guarded INDEPENDENTLY: if one collector fails, its column is left
    NULL and the rest of the row is still written (the trend shows a gap there,
    never a fabricated value — all metric columns are nullable). The whole task is
    wrapped so it can never leave a broken session or crash beat.

    Samples & real collectors (mirrors the Overview read model):
      cpu/mem/disk .......... helpers._get_system_performance_metrics()  [psutil]
      active/queued/failed .. task_monitor.TaskMonitor().get_task_stats(86400)
      error_rate ............ failed/total * 100 (derived from those stats)
      services_up/total ..... system_center_service.get_services_board(force=True)
                              (healthy non-idle / probed non-idle)
      redis_mem_mb .......... redis INFO used_memory
    """
    logger.info("Starting snapshot_system_metrics task")

    app = celery.flask_app
    with app.app_context():
        try:
            from app.models.api_logs import SystemMetricSnapshot

            cpu_pct = memory_pct = disk_pct = None
            active_jobs = queued_jobs = failed_24h = None
            error_rate = None
            services_up = services_total = None
            redis_mem_mb = None

            # ---- CPU / memory / disk (psutil, host/container) ----
            try:
                from app.admin_panel.routes.helpers import _get_system_performance_metrics
                m = _get_system_performance_metrics() or {}
                cpu_pct = float(m.get('cpu_usage')) if m.get('cpu_usage') is not None else None
                memory_pct = float(m.get('memory_usage')) if m.get('memory_usage') is not None else None
                disk_pct = float(m.get('disk_usage')) if m.get('disk_usage') is not None else None
            except Exception:
                logger.warning("snapshot: perf metrics sample failed", exc_info=True)

            # ---- active / queued / failed jobs + error rate (24h task stats) ----
            try:
                from app.utils.task_monitor import TaskMonitor
                stats = TaskMonitor().get_task_stats(time_window=86400) or {}
                active_jobs = int(stats.get('running') or 0)
                queued_jobs = int(stats.get('pending') or 0)
                failed_24h = int(stats.get('failed') or 0)
                total = int(stats.get('total') or 0)
                error_rate = round((failed_24h / total * 100), 2) if total > 0 else 0.0
            except Exception:
                logger.warning("snapshot: task stats sample failed", exc_info=True)

            # ---- services up / total (healthy non-idle / probed non-idle) ----
            try:
                from app.services import system_center_service
                with task_session() as _s:
                    board = system_center_service.get_services_board(_s, force=True) or []
                probed = [svc for svc in board if svc.get('status') != 'idle']
                services_total = len(probed)
                services_up = sum(1 for svc in probed if svc.get('status') == 'healthy')
            except Exception:
                logger.warning("snapshot: services board sample failed", exc_info=True)

            # ---- Redis used memory (MB) ----
            try:
                from app.utils.redis_manager import get_redis_manager
                info = get_redis_manager().client.info() or {}
                used = info.get('used_memory')
                if used is not None:
                    redis_mem_mb = round(int(used) / (1024 * 1024), 1)
            except Exception:
                logger.warning("snapshot: redis info sample failed", exc_info=True)

            # ---- write ONE row + prune > 7 days, in a single committed session ----
            with task_session() as session:
                session.add(SystemMetricSnapshot(
                    created_at=datetime.utcnow(),
                    cpu_pct=cpu_pct,
                    memory_pct=memory_pct,
                    disk_pct=disk_pct,
                    active_jobs=active_jobs,
                    queued_jobs=queued_jobs,
                    failed_24h=failed_24h,
                    error_rate=error_rate,
                    services_up=services_up,
                    services_total=services_total,
                    redis_mem_mb=redis_mem_mb,
                ))
                # Bounded cleanup: drop anything older than 7 days each run.
                from datetime import timedelta
                cutoff = datetime.utcnow() - timedelta(days=7)
                deleted = session.query(SystemMetricSnapshot).filter(
                    SystemMetricSnapshot.created_at < cutoff
                ).delete(synchronize_session=False)
                # Commit happens automatically in task_session
                logger.info(
                    "snapshot_system_metrics: row written (cpu=%s mem=%s svc=%s/%s redis=%sMB), pruned %s old rows",
                    cpu_pct, memory_pct, services_up, services_total, redis_mem_mb, deleted
                )
        except Exception as e:
            # Never let a snapshot failure crash beat or poison anything downstream.
            logger.error(f"Error in snapshot_system_metrics: {e}", exc_info=True)


@celery.task(
    name='app.tasks.monitoring_tasks.check_for_session_leaks',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def check_for_session_leaks(self):
    """
    Check for potential database session leaks.
    
    This task:
    - Queries pg_stat_activity for 'idle in transaction' sessions
    - Identifies sessions that have been idle for too long
    - Terminates sessions that appear to be leaking resources
    - Logs information about potential leaks for investigation
    
    Returns:
        Dict with leak detection results
    """
    logger.info("Starting session leak detection task")
    
    app = celery.flask_app
    
    with app.app_context():
        try:
            with task_session() as session:
                # Find idle-in-transaction sessions
                query = text("""
                    SELECT 
                        pid, 
                        usename, 
                        application_name,
                        client_addr,
                        backend_start,
                        xact_start,
                        query_start,
                        state_change,
                        state,
                        EXTRACT(EPOCH FROM (NOW() - state_change)) as idle_seconds,
                        query
                    FROM 
                        pg_stat_activity 
                    WHERE 
                        pid <> pg_backend_pid() 
                        AND state = 'idle in transaction'
                        AND state_change < NOW() - interval '30 minutes'
                    ORDER BY 
                        idle_seconds DESC;
                """)
                
                potential_leaks = []
                for row in session.execute(query).mappings():
                    leak_data = dict(row)
                    potential_leaks.append(leak_data)
                
                logger.info(f"Found {len(potential_leaks)} potential session leaks")
                
                # Terminate sessions that have been idle for too long (likely leaked)
                terminated = 0
                for leak in potential_leaks:
                    try:
                        if leak.get('idle_seconds', 0) > 3600:  # Over 1 hour idle
                            session.execute(
                                text("SELECT pg_terminate_backend(:pid)"),
                                {"pid": leak['pid']}
                            )
                            terminated += 1
                            logger.warning(
                                f"Terminated leaked session: PID={leak['pid']}, "
                                f"Idle time={leak['idle_seconds']/60:.1f} minutes"
                            )
                    except Exception as e:
                        logger.error(f"Failed to terminate session {leak['pid']}: {e}")
                
                result = {
                    "potential_leaks": len(potential_leaks),
                    "terminated": terminated,
                    "details": [
                        {
                            "pid": leak['pid'],
                            "application": leak.get('application_name', 'Unknown'),
                            "idle_minutes": leak.get('idle_seconds', 0) / 60,
                            "query": leak.get('query', 'No query')[:100]
                        }
                        for leak in potential_leaks
                    ]
                }
                
                logger.info(f"Session leak check completed: {result['potential_leaks']} potential leaks, {result['terminated']} terminated")
                return result
                
        except Exception as e:
            logger.error(f"Error checking for session leaks: {e}", exc_info=True)
            raise


@celery.task(
    name='app.tasks.monitoring_tasks.monitor_redis_connections',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def monitor_redis_connections(self):
    """
    Monitor Redis connection usage and detect potential leaks.
    
    This task:
    - Retrieves the current Redis connection pool statistics from the centralized service
    - Logs warnings if connection usage is approaching capacity  
    - Returns detailed statistics for monitoring
    
    Returns:
        Dict with Redis connection pool statistics
    """
    logger.info("Starting Redis connection monitoring task")
    
    app = celery.flask_app
    
    with app.app_context():
        try:
            # Use centralized Redis service for consistent monitoring
            redis_service = get_redis_service()
            
            # Get comprehensive service metrics
            service_metrics = redis_service.get_metrics()
            
            # Also get UnifiedRedisManager stats for comparison/compatibility
            try:
                redis_manager = UnifiedRedisManager()
                legacy_stats = redis_manager.get_connection_stats()
            except Exception as e:
                logger.warning(f"Could not get unified Redis manager stats: {e}")
                legacy_stats = {}
            
            # Extract pool stats from centralized service
            pool_stats = service_metrics.get('connection_pool', {})
            
            # Log warning if connection pool usage is high
            max_conn = pool_stats.get('max_connections', 0)
            in_use = pool_stats.get('in_use_connections', 0)
            if max_conn > 0 and in_use > max_conn * 0.8:
                utilization = (in_use / max_conn) * 100
                logger.warning(
                    f"Redis connection pool nearing capacity: "
                    f"{in_use}/{max_conn} connections in use "
                    f"({utilization:.1f}%)"
                )
            
            # Log normal status
            logger.info(
                f"Redis connection pool stats: {in_use} in use, "
                f"{pool_stats.get('created_connections', 0)} created, {max_conn} max"
            )
            
            # Include circuit breaker status
            service_status = service_metrics.get('service_status', {})
            if service_status.get('circuit_state') != 'closed':
                logger.warning(f"Redis circuit breaker is {service_status.get('circuit_state')}")
            
            # Combine all stats for comprehensive monitoring
            combined_stats = {
                'centralized_service': service_metrics,
                'legacy_manager': legacy_stats,
                'monitoring_timestamp': datetime.utcnow().isoformat()
            }
            
            return combined_stats
            
        except Exception as e:
            logger.error(f"Error monitoring Redis connections: {e}", exc_info=True)
            raise


@celery.task(
    name='app.tasks.monitoring_tasks.monitor_queue_backlogs',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def monitor_queue_backlogs(self):
    """
    Monitor Celery queues for excessive backlogs and alert when thresholds are exceeded.
    
    This task checks key queue lengths and logs warnings/errors when queues become backed up.
    It also attempts to clear expired tasks from queues to prevent performance issues.
    
    Returns:
        dict: Queue statistics and any alerts generated
    """
    logger.info("Starting queue backlog monitoring task")
    
    try:
        redis_service = get_redis_service()
        if not redis_service.is_healthy():
            logger.warning("Redis service not healthy for queue monitoring")
            return {'success': False, 'message': 'Redis service unhealthy'}
        
        # Define queue thresholds
        QUEUE_THRESHOLDS = {
            'live_reporting': {'warning': 50, 'critical': 200},
            'discord': {'warning': 100, 'critical': 500},
            'celery': {'warning': 200, 'critical': 1000},
            'player_sync': {'warning': 20, 'critical': 100},
            'enterprise_rsvp': {'warning': 50, 'critical': 200}
        }
        
        queue_stats = {}
        alerts = []
        
        with redis_service.get_connection() as redis_client:
            for queue_name, thresholds in QUEUE_THRESHOLDS.items():
                try:
                    queue_length = redis_client.llen(queue_name)
                    queue_stats[queue_name] = queue_length
                    
                    if queue_length >= thresholds['critical']:
                        alert = f"CRITICAL: Queue '{queue_name}' has {queue_length} tasks (threshold: {thresholds['critical']})"
                        logger.error(alert)
                        alerts.append(alert)
                    elif queue_length >= thresholds['warning']:
                        alert = f"WARNING: Queue '{queue_name}' has {queue_length} tasks (threshold: {thresholds['warning']})"
                        logger.warning(alert)
                        alerts.append(alert)
                    else:
                        logger.info(f"Queue '{queue_name}': {queue_length} tasks (healthy)")
                        
                except Exception as e:
                    error = f"Error checking queue '{queue_name}': {e}"
                    logger.error(error)
                    alerts.append(error)
            
            # Special handling for live_reporting queue - clear expired process_all_active_sessions_v2 tasks
            if queue_stats.get('live_reporting', 0) > 100:
                try:
                    cleared_count = _clear_expired_live_reporting_tasks(redis_client)
                    if cleared_count > 0:
                        logger.info(f"Cleared {cleared_count} expired live_reporting tasks")
                        queue_stats['live_reporting_cleared'] = cleared_count
                except Exception as e:
                    logger.error(f"Error clearing expired live_reporting tasks: {e}")
        
        # Get Redis service metrics for enhanced monitoring
        redis_metrics = redis_service.get_metrics()
        
        result = {
            'success': True,
            'queue_stats': queue_stats,
            'alerts': alerts,
            'redis_metrics': redis_metrics,
            'timestamp': datetime.now().isoformat()
        }
        
        if alerts:
            logger.warning(f"Queue monitoring generated {len(alerts)} alerts: {alerts}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in queue backlog monitoring: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def _clear_expired_live_reporting_tasks(redis_client):
    """
    Helper function to clear expired process_all_active_sessions_v2 tasks from live_reporting queue.
    
    Args:
        redis_client: Redis client instance
        
    Returns:
        int: Number of tasks cleared
    """
    import json
    from datetime import datetime
    import pytz
    from dateutil import parser
    
    queue_name = 'live_reporting'
    current_time = datetime.now(pytz.UTC)
    
    # Get all tasks
    all_tasks = redis_client.lrange(queue_name, 0, -1)
    if not all_tasks:
        return 0
    
    valid_tasks = []
    expired_count = 0
    
    for task_json in all_tasks:
        try:
            task = json.loads(task_json)
            headers = task.get('headers', {})
            expires = headers.get('expires')
            task_name = headers.get('task', '')
            
            # Only clear process_all_active_sessions_v2 tasks that are expired
            if 'process_all_active_sessions_v2' in task_name and expires:
                try:
                    expires_dt = parser.parse(expires)
                    if expires_dt < current_time:
                        expired_count += 1
                        continue  # Skip this task (mark as expired)
                except:
                    # If we can't parse the expiration, assume it's expired
                    expired_count += 1
                    continue
            
            # Keep all other tasks
            valid_tasks.append(task_json)
            
        except:
            # Keep unparseable tasks
            valid_tasks.append(task_json)
    
    # Only clear if we have significant expired tasks to avoid unnecessary work
    if expired_count > 10:
        # Clear queue and re-add valid tasks
        redis_client.delete(queue_name)
        if valid_tasks:
            # Use the raw Redis client for rpush since SafeRedisClient may not have it
            raw_client = redis_client.client
            for task in valid_tasks:
                raw_client.rpush(queue_name, task)
        
        logger.info(f"Cleared {expired_count} expired tasks from {queue_name} queue")
        return expired_count
    
    return 0