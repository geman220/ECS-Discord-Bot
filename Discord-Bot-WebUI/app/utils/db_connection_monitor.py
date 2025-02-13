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
from typing import List, Dict, Optional
from sqlalchemy import text
from app.core import db

logger = logging.getLogger(__name__)


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
        app.config.setdefault('DB_MAX_CONNECTION_AGE', 900)       # Maximum age for any connection (seconds)
        app.config.setdefault('DB_IDLE_TRANSACTION_TIMEOUT', 60)  # Timeout for idle-in-transaction (seconds)
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
        except Exception as e:
            logger.error(f"Error in connection cleanup: {e}")