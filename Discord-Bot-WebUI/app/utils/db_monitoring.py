# app/utils/db_monitoring.py

"""
Database Monitoring Utilities

This module provides tools for tracking and reporting on PostgreSQL database
connections and operations using Prometheus metrics. It defines a DatabaseMetrics
class that can record session start/end times, monitor slow queries, and track errors.
It also includes a cleanup mechanism for orphaned sessions and outdated metric data.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List
from flask import current_app
from prometheus_client import Counter, Histogram, Gauge

logger = logging.getLogger(__name__)

# Prometheus metrics definitions.
DB_CONNECTIONS = Gauge('db_connections_active', 'Number of active database connections')
DB_OPERATIONS = Counter('db_operations_total', 'Total database operations', ['operation_type'])
DB_OPERATION_DURATION = Histogram('db_operation_duration_seconds', 'Duration of database operations', ['operation_type'])
DB_ERRORS = Counter('db_errors_total', 'Total database errors', ['error_type'])


class DatabaseMetrics:
    def __init__(self):
        """
        Initialize the DatabaseMetrics instance.

        Attributes:
            session_starts: Dictionary mapping session IDs to their start timestamps.
            long_queries: List of dictionaries recording long-running query details.
            error_counts: Dictionary mapping error types to their occurrence counts.
        """
        self.session_starts: Dict[int, float] = {}
        self.long_queries: List[Dict] = []
        self.error_counts: Dict[str, int] = {}
        
    def start_session(self, session_id: int):
        """
        Record the start of a database session.

        Increments the active connection gauge and stores the start time for the session.

        Args:
            session_id: Unique identifier for the database session.
        """
        self.session_starts[session_id] = time.time()
        DB_CONNECTIONS.inc()
        
    def end_session(self, session_id: int):
        """
        Record the end of a database session.

        Decrements the active connection gauge, observes the session duration in the histogram,
        and removes the session from tracking.

        Args:
            session_id: Unique identifier for the database session.
        """
        if session_id in self.session_starts:
            duration = time.time() - self.session_starts[session_id]
            DB_CONNECTIONS.dec()
            DB_OPERATION_DURATION.labels('session').observe(duration)
            del self.session_starts[session_id]
            
    def record_operation(self, operation_type: str, duration: float):
        """
        Record a database operation.

        Increments operation count and observes its duration in the histogram. If the duration
        exceeds the slow query threshold defined in the Flask configuration, logs the query as a
        long-running query.

        Args:
            operation_type: A string describing the type of operation.
            duration: Duration of the operation in seconds.
        """
        DB_OPERATIONS.labels(operation_type).inc()
        DB_OPERATION_DURATION.labels(operation_type).observe(duration)
        
        if duration > current_app.config.get('DB_SLOW_QUERY_THRESHOLD', 1.0):
            self.long_queries.append({
                'type': operation_type,
                'duration': duration,
                'timestamp': datetime.utcnow()
            })
            
    def record_error(self, error_type: str):
        """
        Record a database error.

        Increments the error counter for the given error type and updates the internal error count.

        Args:
            error_type: A string describing the error type.
        """
        DB_ERRORS.labels(error_type).inc()
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
    def get_metrics(self) -> Dict:
        """
        Retrieve current database metrics.

        Returns a dictionary containing the number of active sessions, details of long-running
        queries (within the last hour), and error counts.
        
        Returns:
            A dictionary with keys 'active_connections', 'long_queries', and 'error_counts'.
        """
        return {
            'active_connections': len(self.session_starts),
            'long_queries': [q for q in self.long_queries 
                             if q['timestamp'] > datetime.utcnow() - timedelta(hours=1)],
            'error_counts': self.error_counts
        }
        
    def cleanup_old_data(self):
        """
        Clean up outdated metrics data.

        Removes long query records older than one hour and cleans up any orphaned session start
        entries (i.e., sessions that have been active for more than one hour without being ended).
        """
        # Remove long queries older than one hour.
        cutoff = datetime.utcnow() - timedelta(hours=1)
        self.long_queries = [q for q in self.long_queries if q['timestamp'] > cutoff]
        
        # Identify orphaned sessions that have been active for more than 1 hour.
        current_time = time.time()
        orphaned_sessions = [
            session_id for session_id, start_time in self.session_starts.items()
            if current_time - start_time > 3600  # 1 hour threshold
        ]
        for session_id in orphaned_sessions:
            logger.warning(f"Cleaning up orphaned session {session_id}")
            del self.session_starts[session_id]
            DB_CONNECTIONS.dec()


# Create a global instance of the DatabaseMetrics class.
db_metrics = DatabaseMetrics()