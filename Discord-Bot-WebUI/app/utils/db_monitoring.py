# app/utils/db_monitoring.py

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List
from flask import current_app
from prometheus_client import Counter, Histogram, Gauge

logger = logging.getLogger(__name__)

# Prometheus metrics
DB_CONNECTIONS = Gauge('db_connections_active', 'Number of active database connections')
DB_OPERATIONS = Counter('db_operations_total', 'Total database operations', ['operation_type'])
DB_OPERATION_DURATION = Histogram('db_operation_duration_seconds', 'Duration of database operations', ['operation_type'])
DB_ERRORS = Counter('db_errors_total', 'Total database errors', ['error_type'])

class DatabaseMetrics:
    def __init__(self):
        self.session_starts: Dict[int, float] = {}
        self.long_queries: List[Dict] = []
        self.error_counts: Dict[str, int] = {}
        
    def start_session(self, session_id: int):
        """Record the start of a database session"""
        self.session_starts[session_id] = time.time()
        DB_CONNECTIONS.inc()
        
    def end_session(self, session_id: int):
        """Record the end of a database session"""
        if session_id in self.session_starts:
            duration = time.time() - self.session_starts[session_id]
            DB_CONNECTIONS.dec()
            DB_OPERATION_DURATION.labels('session').observe(duration)
            del self.session_starts[session_id]
            
    def record_operation(self, operation_type: str, duration: float):
        """Record a database operation"""
        DB_OPERATIONS.labels(operation_type).inc()
        DB_OPERATION_DURATION.labels(operation_type).observe(duration)
        
        if duration > current_app.config.get('DB_SLOW_QUERY_THRESHOLD', 1.0):
            self.long_queries.append({
                'type': operation_type,
                'duration': duration,
                'timestamp': datetime.utcnow()
            })
            
    def record_error(self, error_type: str):
        """Record a database error"""
        DB_ERRORS.labels(error_type).inc()
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
    def get_metrics(self) -> Dict:
        """Get current database metrics"""
        return {
            'active_connections': len(self.session_starts),
            'long_queries': [q for q in self.long_queries 
                           if q['timestamp'] > datetime.utcnow() - timedelta(hours=1)],
            'error_counts': self.error_counts
        }
        
    def cleanup_old_data(self):
        """Clean up old metrics data"""
        cutoff = datetime.utcnow() - timedelta(hours=1)
        self.long_queries = [q for q in self.long_queries if q['timestamp'] > cutoff]
        
        # Clean up any orphaned session starts
        current_time = time.time()
        orphaned_sessions = [
            session_id for session_id, start_time in self.session_starts.items()
            if current_time - start_time > 3600  # 1 hour
        ]
        for session_id in orphaned_sessions:
            logger.warning(f"Cleaning up orphaned session {session_id}")
            del self.session_starts[session_id]
            DB_CONNECTIONS.dec()

# Create global instance
db_metrics = DatabaseMetrics()