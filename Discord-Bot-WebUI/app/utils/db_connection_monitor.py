# app/utils/db_connection_monitor.py

"""
Database Connection Monitor

This module provides a DBConnectionMonitor class for monitoring and managing 
PostgreSQL database connections. It can be initialized with a Flask app to 
configure default connection timeouts and is used to identify and terminate 
long-running or "stuck" connections. The cleanup_connections method is registered 
to run at the end of each request.
"""

import logging
import psycopg2
import gc
import threading
from typing import List, Dict, Optional, Any
from sqlalchemy import text
from app.core import db

logger = logging.getLogger(__name__)

# Global variables to track connections
_active_connections: Dict[int, Dict[str, Any]] = {}
_connection_lock = threading.RLock()


class DBConnectionMonitor:
    def __init__(self, app=None):
        """
        Initialize the DBConnectionMonitor.

        Optionally accepts a Flask app, in which case it automatically initializes
        the monitor using the app's configuration.
        """
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        Initialize the monitor with a Flask application.

        Sets default configuration values for database connection timeouts and
        registers the cleanup_connections method to be called when the application
        context tears down.

        Args:
            app: The Flask application instance.
        """
        self.app = app
        # Set default configuration values if not already set.
        app.config.setdefault('DB_CONNECTION_TIMEOUT', 30)      # Timeout for normal web requests (seconds)
        app.config.setdefault('DB_QUERY_TIMEOUT', 300)          # Timeout for active queries (seconds)
        app.config.setdefault('DB_MAX_CONNECTION_AGE', 300)       # Maximum age for any connection - reduced from 900 to 300 seconds (5 minutes)
        app.config.setdefault('DB_IDLE_TRANSACTION_TIMEOUT', 30)  # Timeout for idle-in-transaction - reduced from 60 to 30 seconds
        app.config.setdefault('DB_MONITOR_ENABLED', True)
        app.teardown_appcontext(self.cleanup_connections)

    def get_long_running_connections(self, threshold_seconds: Optional[int] = None) -> List[Dict]:
        """
        Retrieve database connections running longer than the specified threshold.

        If no threshold is provided, the default DB_CONNECTION_TIMEOUT is used.
        The method queries PostgreSQL's pg_stat_activity to find connections that 
        exceed thresholds for query duration, idle transaction time, or overall age.

        Args:
            threshold_seconds: Optional threshold (in seconds) for identifying long-running connections.

        Returns:
            A list of dictionaries representing problematic connections.
        """
        if not self.app.config['DB_MONITOR_ENABLED']:
            return []

        if threshold_seconds is None:
            threshold_seconds = self.app.config['DB_CONNECTION_TIMEOUT']

        query_timeout = self.app.config['DB_QUERY_TIMEOUT']
        max_age = self.app.config['DB_MAX_CONNECTION_AGE']
        idle_timeout = self.app.config['DB_IDLE_TRANSACTION_TIMEOUT']

        sql = text("""
            SELECT 
                pid,
                usename,
                application_name,
                client_addr,
                backend_start,
                xact_start,
                query_start,
                state,
                wait_event_type,
                wait_event,
                query,
                COALESCE(EXTRACT(EPOCH FROM (NOW() - query_start)), 0) as duration,
                EXTRACT(EPOCH FROM (NOW() - backend_start)) as connection_age,
                EXTRACT(EPOCH FROM (NOW() - xact_start)) as transaction_age
            FROM pg_stat_activity 
            WHERE pid != pg_backend_pid()
            AND (
                (state = 'active' AND query_start IS NOT NULL AND EXTRACT(EPOCH FROM (NOW() - query_start)) > :query_timeout)
                OR (state = 'idle in transaction' AND xact_start IS NOT NULL AND EXTRACT(EPOCH FROM (NOW() - xact_start)) > :idle_timeout)
                OR (backend_start IS NOT NULL AND EXTRACT(EPOCH FROM (NOW() - backend_start)) > :max_age)
                OR (state NOT IN ('idle', 'active') AND query_start IS NOT NULL AND EXTRACT(EPOCH FROM (NOW() - query_start)) > :threshold)
            )
            ORDER BY 
                CASE state
                    WHEN 'active' THEN 1
                    WHEN 'idle in transaction' THEN 2
                    ELSE 3
                END,
                duration DESC
        """)

        try:
            with db.engine.connect() as conn:
                result = conn.execute(sql, {
                    "threshold": threshold_seconds,
                    "query_timeout": query_timeout,
                    "max_age": max_age,
                    "idle_timeout": idle_timeout
                })
                # Convert each row to a dictionary.
                connections = [dict(zip(row._mapping.keys(), row._mapping.values())) for row in result]
        
                if connections:
                    logger.warning(
                        f"Found {len(connections)} problematic connections:\n" + 
                        "\n".join([
                            f"PID {c.get('pid', 'Unknown')}: State={c.get('state', 'Unknown')}, "
                            f"Duration={(c.get('duration', 0) if c.get('duration') is not None else 0):.1f}s, "
                            f"Age={(c.get('connection_age', 0) if c.get('connection_age') is not None else 0):.1f}s, "
                            f"Transaction Age={(c.get('transaction_age', 0) if c.get('transaction_age') is not None else 0):.1f}s - "
                            f"App: {c.get('application_name', 'Unknown')} - "
                            f"Query: {c.get('query', '')[:100]}..."
                            for c in connections
                        ])
                    )
                return connections
        except Exception as e:
            logger.error(f"Error checking connections: {e}", exc_info=True)
            return []

    def terminate_stuck_connections(self, age_threshold_seconds: int = None) -> int:
        """
        Terminate database connections running longer than the specified threshold.

        The method retrieves problematic connections and attempts to terminate them
        using PostgreSQL's pg_terminate_backend function.

        Args:
            age_threshold_seconds: Optional threshold (in seconds) for termination; if not provided,
                                   defaults to the DB_QUERY_TIMEOUT value.

        Returns:
            The number of connections terminated.
        """
        if not self.app.config['DB_MONITOR_ENABLED']:
            return 0

        if age_threshold_seconds is None:
            age_threshold_seconds = self.app.config['DB_QUERY_TIMEOUT']

        connections = self.get_long_running_connections(age_threshold_seconds)
        terminated = 0

        for conn in connections:
            # Skip admin connections and connections without any query.
            if (conn['application_name'] and 'admin' in conn['application_name'].lower()) or not conn['query']:
                continue
                
            # Skip active queries that haven't exceeded the maximum allowed age.
            if (conn['state'] == 'active' and 
                conn.get('connection_age', 0) < self.app.config['DB_MAX_CONNECTION_AGE']):
                continue

            try:
                with db.engine.connect() as connection:
                    connection.execute(
                        text("SELECT pg_terminate_backend(:pid)"),
                        {"pid": conn['pid']}
                    )
                terminated += 1
                logger.warning(
                    f"Terminated stuck connection:\n"
                    f"PID: {conn['pid']}\n"
                    f"State: {conn['state']}\n"
                    f"Duration: {conn['duration']:.1f}s\n"
                    f"Connection Age: {conn.get('connection_age', 0):.1f}s\n"
                    f"Transaction Age: {conn.get('transaction_age', 0):.1f}s\n"
                    f"Application: {conn['application_name'] or 'Unknown'}\n"
                    f"Query: {conn['query'][:200]}..."
                )
            except Exception as e:
                logger.error(f"Failed to terminate connection {conn['pid']}: {e}")
        return terminated

    def cleanup_connections(self, exception=None):
        """
        Cleanup database connections at the end of a request.

        If an exception occurred during the request, it logs the error. Then, if
        connection monitoring is enabled, it terminates stuck connections that have
        exceeded a threshold (set to DB_CONNECTION_TIMEOUT * 3).

        Args:
            exception: Optional exception that occurred during the request.
        """
        if exception:
            logger.error(f"Exception during request, checking for stuck connections: {exception}")
        
        if not self.app.config['DB_MONITOR_ENABLED']:
            return

        try:
            terminated = self.terminate_stuck_connections(
                self.app.config['DB_CONNECTION_TIMEOUT'] * 3
            )
            if terminated:
                logger.warning(f"Cleanup terminated {terminated} stuck connections")
                
            # Also perform garbage collection to clean up any lingering connections
            ensure_connections_cleanup()
        except Exception as e:
            logger.error(f"Error in connection cleanup: {e}")


def register_connection(conn_id: int, origin: str = None) -> None:
    """
    Register a new database connection for tracking.
    
    Args:
        conn_id: Unique identifier for the connection.
        origin: Information about where the connection was created.
    """
    with _connection_lock:
        import traceback
        stack = ''.join(traceback.format_stack())
        
        _active_connections[conn_id] = {
            'created_at': __import__('datetime').datetime.utcnow(),
            'origin': origin or 'unknown',
            'stack': stack,
            'thread_id': threading.get_ident()
        }
        
        logger.debug(
            f"Registered connection {conn_id} from {origin}. "
            f"Active connections: {len(_active_connections)}"
        )


def unregister_connection(conn_id: int) -> None:
    """
    Unregister a database connection that's no longer active.
    
    Args:
        conn_id: Unique identifier for the connection.
    """
    with _connection_lock:
        if conn_id in _active_connections:
            conn_info = _active_connections.pop(conn_id)
            logger.debug(
                f"Unregistered connection {conn_id} from {conn_info.get('origin')}. "
                f"Active connections: {len(_active_connections)}"
            )
        else:
            logger.warning(f"Attempted to unregister unknown connection {conn_id}")


def get_active_connections() -> List[Dict[str, Any]]:
    """
    Get a list of all currently active connections.
    
    Returns:
        A list of dictionaries containing information about active connections.
    """
    with _connection_lock:
        return [
            {
                'id': conn_id,
                'created_at': info['created_at'],
                'origin': info['origin'],
                'thread_id': info['thread_id'],
                'age_seconds': (
                    __import__('datetime').datetime.utcnow() - info['created_at']
                ).total_seconds()
            }
            for conn_id, info in _active_connections.items()
        ]


def find_leaked_connections(age_threshold_seconds: int = 300) -> List[Dict[str, Any]]:
    """
    Find potentially leaked connections that have been active for longer than the threshold.
    
    Args:
        age_threshold_seconds: Time in seconds after which a connection is considered leaked.
        
    Returns:
        A list of dictionaries containing information about leaked connections.
    """
    with _connection_lock:
        now = __import__('datetime').datetime.utcnow()
        return [
            {
                'id': conn_id,
                'created_at': info['created_at'],
                'origin': info['origin'],
                'thread_id': info['thread_id'],
                'age_seconds': (now - info['created_at']).total_seconds(),
                'stack': info['stack']
            }
            for conn_id, info in _active_connections.items()
            if (now - info['created_at']).total_seconds() > age_threshold_seconds
        ]


def close_leaked_connections(age_threshold_seconds: int = 300) -> int:
    """
    Attempt to close leaked connections.
    
    Args:
        age_threshold_seconds: Time in seconds after which a connection is considered leaked.
        
    Returns:
        The number of connections that were closed.
    """
    closed_count = 0
    
    # Search for connections in the garbage collector
    for obj in gc.get_objects():
        try:
            if isinstance(obj, psycopg2.extensions.connection):
                if not obj.closed:
                    conn_id = id(obj)
                    with _connection_lock:
                        if conn_id in _active_connections:
                            info = _active_connections[conn_id]
                            age = (
                                __import__('datetime').datetime.utcnow() - info['created_at']
                            ).total_seconds()
                            
                            if age > age_threshold_seconds:
                                try:
                                    logger.warning(
                                        f"Closing leaked connection {conn_id} from {info['origin']} "
                                        f"(age: {age:.1f}s)"
                                    )
                                    obj.close()
                                    unregister_connection(conn_id)
                                    closed_count += 1
                                except Exception as e:
                                    logger.error(f"Error closing leaked connection {conn_id}: {e}")
        except ReferenceError:
            # Object was garbage collected while we were looking at it
            continue
        except Exception:
            # Skip objects that can't be safely introspected
            continue
    
    return closed_count


def ensure_connections_cleanup() -> None:
    """
    Ensure proper cleanup of database connections.
    
    This function should be called periodically, especially in long-running
    processes or after worker tasks complete.
    """
    try:
        active_count = len(_active_connections)
        if active_count > 0:
            logger.info(f"Cleaning up {active_count} active database connections")
            closed = close_leaked_connections(age_threshold_seconds=60)
            logger.info(f"Closed {closed} leaked connections")
            
        # Force garbage collection to help clean up any lingering connections
        gc.collect()
    except Exception as e:
        logger.error(f"Error in ensure_connections_cleanup: {e}", exc_info=True)


def monitor_connections_background() -> None:
    """
    Monitor connections in a background thread.
    
    This function runs every minute to detect and clean up leaked connections.
    It's designed to be started as a daemon thread.
    """
    import time
    while True:
        try:
            # First, check for extreme long-running connections (zombie connections)
            # Look for anything older than 1 hour, which is far too long
            zombie_connections = find_leaked_connections(age_threshold_seconds=3600)
            if zombie_connections:
                logger.error(
                    f"CRITICAL: Found {len(zombie_connections)} zombie database connections (> 1 hour old)"
                )
                for conn in zombie_connections:
                    logger.error(
                        f"Zombie connection: id={conn['id']}, "
                        f"origin={conn['origin']}, "
                        f"age={conn['age_seconds']:.1f}s"
                    )
                    
                # Force terminate these extremely old connections
                try:
                    monitor = DBConnectionMonitor(current_app._get_current_object())
                    terminated = monitor.terminate_stuck_connections(age_threshold_seconds=3600)
                    logger.info(f"Terminated {terminated} zombie connections via database")
                except Exception as e:
                    logger.error(f"Failed to terminate zombie connections: {e}", exc_info=True)
            
            # Now check for normal leaked connections
            leaked_connections = find_leaked_connections()
            if leaked_connections:
                logger.warning(
                    f"Found {len(leaked_connections)} potentially leaked database connections"
                )
                for conn in leaked_connections:
                    logger.warning(
                        f"Leaked connection: id={conn['id']}, "
                        f"origin={conn['origin']}, "
                        f"age={conn['age_seconds']:.1f}s"
                    )
                
                # Close connections that have been leaked
                closed_count = close_leaked_connections()
                logger.info(f"Closed {closed_count} leaked connections")
            
            # Check the overall connection count
            active_count = len(_active_connections)
            if active_count > 5:  # Lowered from 10 to 5
                logger.warning(
                    f"High number of active database connections: {active_count}"
                )
                
            # Force garbage collection every cycle
            import gc
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error in monitor_connections_background: {e}", exc_info=True)
        
        # Sleep for 1 minute before the next check (reduced from 5 minutes)
        time.sleep(60)


def start_connection_monitor() -> threading.Thread:
    """
    Start the background connection monitoring thread.
    
    Returns:
        The started thread.
    """
    monitor_thread = threading.Thread(
        target=monitor_connections_background,
        name="DBConnectionMonitor",
        daemon=True
    )
    monitor_thread.start()
    logger.info("Started database connection monitoring thread")
    return monitor_thread


# Initialize the monitor thread when this module is imported
try:
    monitor_thread = start_connection_monitor()
except Exception as e:
    logger.error(f"Failed to start connection monitor: {e}", exc_info=True)