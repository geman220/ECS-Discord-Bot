# app/db_management.py

"""
Database Management Module

This module defines a DatabaseManager class that enhances monitoring of
database connections. It tracks connection events (checkout/checkin),
maintains a history of connection events, and provides pool statistics.
Optional periodic maintenance (e.g., metadata cleanup) can be scheduled.
"""

import logging
import collections
from datetime import datetime
import time
import eventlet
import traceback
import threading

from sqlalchemy import event

from app.core import db

logger = logging.getLogger(__name__)

# Global semaphore for synchronizing critical sections (if needed)
lock = eventlet.semaphore.Semaphore()


class DatabaseManager:
    def __init__(self, db):
        """
        Initialize the DatabaseManager with enhanced monitoring.

        Args:
            db: The SQLAlchemy database object.
        """
        self.db = db
        self._engine = None
        self.app = None
        self.initialized = False

        self._active_connections = {}
        self.connection_history = collections.deque(maxlen=100)
        self.pool_stats = {
            'checkouts': 0,
            'checkins': 0,
            'connections_created': 0,
            'leaked_connections': 0,
            'failed_connections': 0,
            'long_transactions': 0
        }
        self._local = threading.local()

    def get_pool_stats(self):
        """
        Return the current pool statistics.

        Returns:
            dict: Dictionary containing pool statistics.
        """
        return self.pool_stats

    def init_app(self, app):
        """
        Initialize the database manager with the Flask app and set up event handlers.

        Args:
            app: The Flask application instance.
        """
        if self.initialized:
            return

        try:
            self.app = app
            self._engine = self.db.engine

            if not self._engine:
                raise RuntimeError("Database engine not properly initialized")

            self._setup_engine_events()
            self.schedule_metadata_cleanup()
            self.initialized = True
            logger.info("Database manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database manager: {e}", exc_info=True)
            self.initialized = False
            raise

    def schedule_metadata_cleanup(self):
        """
        Schedule periodic metadata cleanup (if needed for maintenance).
        """
        def cleanup():
            # Implement cleanup tasks here if needed.
            pass

        # Schedule cleanup to run 5 minutes (300 seconds) later.
        eventlet.spawn_after(300, cleanup)

    def check_for_leaked_connections(self):
        """
        Check active connections for leaks (connections checked out for over 60 seconds).
        Updates the pool statistics accordingly.
        """
        current_time = time.time()
        leaked = []

        for conn_id, checkout_time in list(self._active_connections.items()):
            age = current_time - checkout_time
            if age > 60:  # Consider connection leaked if checked out for more than 60 seconds
                leaked.append(conn_id)
                logger.error(f"Leaked connection detected: {age:.1f}s old")
                self.pool_stats['leaked_connections'] += 1

        for conn_id in leaked:
            self._active_connections.pop(conn_id, None)

    def _log_connection_event(self, event_type: str, connection_id: str, duration: float = None, extra: dict = None):
        """
        Log a database connection event with a stack trace.

        Args:
            event_type (str): Type of event (e.g., 'checkout', 'checkin').
            connection_id (str): Unique identifier for the connection.
            duration (float, optional): Duration of the event in seconds.
            extra (dict, optional): Additional data to include in the log.
        """
        stack_trace = traceback.format_stack()
        event_record = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'connection_id': connection_id,
            'thread_id': threading.get_ident(),
            'duration': duration,
            'stack_trace': ''.join(stack_trace),
            **(extra or {})
        }
        self.connection_history.append(event_record)
        if duration and duration > 1.0:
            logger.warning(f"Slow database operation: {event_type} took {duration:.2f}s")

    def _setup_engine_events(self):
        """
        Set up SQLAlchemy engine event listeners to monitor connection usage and query performance.
        """
        if not self._engine:
            return

        # Listener for connection checkout
        @event.listens_for(self._engine, 'checkout')
        def on_checkout(dbapi_conn, connection_record, connection_proxy):
            # Use the id of connection_record as the connection identifier
            conn_id = str(id(connection_record))
            self._active_connections[conn_id] = time.time()
            self.pool_stats['checkouts'] += 1
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("""
                    SET LOCAL statement_timeout = '30s';
                    SET LOCAL idle_in_transaction_session_timeout = '30s';
                    SET LOCAL lock_timeout = '10s';
                """)
                cursor.close()
            except Exception as e:
                self.pool_stats['failed_connections'] += 1
                logger.error(f"Connection checkout failed: {e}")
                raise

        # Listener for connection checkin
        @event.listens_for(self._engine, 'checkin')
        def on_checkin(dbapi_conn, connection_record):
            # Remove the connection using the id of connection_record
            conn_id = str(id(connection_record))
            self._active_connections.pop(conn_id, None)
            self.pool_stats['checkins'] += 1

        # Listeners for query execution timing
        @event.listens_for(self._engine, 'before_cursor_execute')
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self._local.query_start = time.time()

        @event.listens_for(self._engine, 'after_cursor_execute')
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            duration = time.time() - getattr(self._local, 'query_start', time.time())
            # Log slow queries if necessary
            if duration > 1.0:
                logger.warning(f"Query took {duration:.2f}s: {statement}")

# Create a global DatabaseManager instance
db_manager = DatabaseManager(db)