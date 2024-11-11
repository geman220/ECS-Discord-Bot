from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional
from sqlalchemy import text
from flask import current_app
from contextlib import contextmanager
from app.core import db

logger = logging.getLogger(__name__)

class DBConnectionMonitor:
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app"""
        self.app = app
        # Base timeout for normal web requests
        app.config.setdefault('DB_CONNECTION_TIMEOUT', 30)  # seconds
        # Timeout for active queries
        app.config.setdefault('DB_QUERY_TIMEOUT', 300)  # 5 minutes
        # Maximum age for any connection
        app.config.setdefault('DB_MAX_CONNECTION_AGE', 900)  # 15 minutes
        # Timeout for idle-in-transaction
        app.config.setdefault('DB_IDLE_TRANSACTION_TIMEOUT', 60)  # 1 minute
        app.config.setdefault('DB_MONITOR_ENABLED', True)
        app.teardown_appcontext(self.cleanup_connections)

    def get_long_running_connections(self, threshold_seconds: Optional[int] = None) -> List[Dict]:
        """Get all database connections running longer than threshold"""
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
        """Terminate connections that have been running longer than threshold"""
        if not self.app.config['DB_MONITOR_ENABLED']:
            return 0

        if age_threshold_seconds is None:
            age_threshold_seconds = self.app.config['DB_QUERY_TIMEOUT']

        connections = self.get_long_running_connections(age_threshold_seconds)
        terminated = 0

        for conn in connections:
            # Skip admin connections and connections without queries
            if (conn['application_name'] and 'admin' in conn['application_name'].lower()) or not conn['query']:
                continue
                
            # Skip active queries that aren't extremely old
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
        """Cleanup function to be called at the end of each request"""
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

    @contextmanager
    def monitor_transaction(self, name: str, timeout: int = None):
        """Context manager to monitor transaction duration"""
        start_time = datetime.now()
        
        if timeout is None:
            timeout = self.app.config['DB_CONNECTION_TIMEOUT']

        try:
            yield
        finally:
            duration = datetime.now() - start_time
            if duration > timedelta(seconds=timeout):
                logger.warning(
                    f"Long running transaction detected:\n"
                    f"Name: {name}\n"
                    f"Duration: {duration.total_seconds():.1f}s"
                )
