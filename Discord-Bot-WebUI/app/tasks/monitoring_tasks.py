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
from app.utils.redis_manager import RedisManager
from app.utils.task_session_manager import task_session

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


@celery.task(name='app.tasks.monitoring_tasks.check_for_session_leaks')
def check_for_session_leaks():
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


@celery.task(name='app.tasks.monitoring_tasks.monitor_redis_connections')
def monitor_redis_connections():
    """
    Monitor Redis connection usage and detect potential leaks.
    
    This task:
    - Retrieves the current Redis connection pool statistics
    - Logs warnings if connection usage is approaching capacity
    - Returns detailed statistics for monitoring
    
    Returns:
        Dict with Redis connection pool statistics
    """
    logger.info("Starting Redis connection monitoring task")
    
    app = celery.flask_app
    
    with app.app_context():
        try:
            redis_manager = RedisManager()
            
            # Get connection pool stats
            stats = redis_manager.get_connection_stats()
            
            # Extract pool stats
            pool_stats = stats.get('pool_stats', {})
            
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
            
            return stats
            
        except Exception as e:
            logger.error(f"Error monitoring Redis connections: {e}", exc_info=True)
            raise