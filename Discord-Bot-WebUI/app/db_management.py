"""
Database Management Module

This module defines a DatabaseManager class that enhances monitoring of
database connections. It tracks connection events (checkout/checkin),
maintains a history of connection events, and provides pool statistics.
Optional periodic maintenance (e.g., metadata cleanup) can be scheduled.

This updated version also captures the full Python stack trace when a
transaction begins (both at the engine level and via a global fallback),
and now tracks COMMIT and ROLLBACK events. This provides detailed information
to diagnose long-running, idle, or leaked connections.
"""

import logging
import collections
from datetime import datetime
import time
import eventlet
import traceback
import threading

from sqlalchemy import event, text
from sqlalchemy.orm import Session
from flask import request

from app.core import db

logger = logging.getLogger(__name__)

# Global semaphore for synchronizing critical sections (if needed)
lock = eventlet.semaphore.Semaphore()

# Global dictionary to hold transaction metadata (e.g. stack traces), keyed by backend PID.
transaction_metadata = {}

def get_backend_pid(conn):
    """
    Retrieve the backend PID from the raw DB connection (works for psycopg2).
    Accepts either a raw connection or an object with a .connection attribute.
    """
    try:
        if hasattr(conn, 'connection'):
            return conn.connection.get_backend_pid()
        else:
            return conn.get_backend_pid()
    except Exception as e:
        logger.error(f"Unable to get backend PID: {e}", exc_info=True)
        return None

def get_transaction_details(pid):
    """
    Retrieve the stored transaction details (including full stack trace) for the given PID.
    """
    return transaction_metadata.get(pid)

def clear_transaction_details(pid):
    """
    Clear stored transaction details for a given PID.
    """
    if pid in transaction_metadata:
        del transaction_metadata[pid]

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
        #if self.initialized:
        #    return

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
            logger.info("Running scheduled metadata cleanup")
            now = time.time()
            stale_pids = [pid for pid, meta in transaction_metadata.items()
                          if (now - meta.get('start_time', now).timestamp()) > 3600]
            for pid in stale_pids:
                clear_transaction_details(pid)
                logger.debug(f"Cleared stale transaction metadata for PID {pid}")

        eventlet.spawn_after(300, cleanup)

    def check_for_leaked_connections(self):
        """
        Check active connections for leaks (connections checked out for over 60 seconds).
        Updates the pool statistics accordingly.
        """
        current_time = time.time()
        for pid, meta in list(transaction_metadata.items()):
            age = (datetime.utcnow() - meta.get('start_time')).total_seconds()
            if age > 60:
                logger.error(
                    f"Leaked transaction for PID {pid} (open for {age:.1f} seconds). Origin:\n{meta.get('stack_trace')}"
                )
                self.pool_stats['leaked_connections'] += 1
                clear_transaction_details(pid)

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
        Set up SQLAlchemy engine event listeners to monitor connection usage,
        transaction beginnings, commits, rollbacks, and query performance.
        """
        if not self._engine:
            return

        @event.listens_for(self._engine, 'checkout')
        def on_checkout(dbapi_conn, connection_record, connection_proxy):
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
                logger.error(f"Connection checkout failed: {e}", exc_info=True)
                raise
            # Fallback: capture a stack trace on checkout if none exists.
            pid = get_backend_pid(connection_record)
            if pid and pid not in transaction_metadata:
                stack_summary = traceback.extract_stack()
                filtered = [frame for frame in stack_summary if "site-packages" not in frame.filename]
                summary_text = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered)
                transaction_metadata[pid] = {
                    'stack_trace': summary_text,
                    'full_stack_trace': ''.join(traceback.format_stack()),
                    'start_time': datetime.utcnow()
                }
                logger.debug(f"Captured fallback stack trace for PID {pid} on checkout:\n{summary_text}")

        @event.listens_for(self._engine, 'checkin')
        def on_checkin(dbapi_conn, connection_record):
            conn_id = str(id(connection_record))
            self._active_connections.pop(conn_id, None)
            self.pool_stats['checkins'] += 1

        # Listener for transaction begin at the engine level.
        @event.listens_for(self._engine, "begin")
        def capture_transaction_begin(conn):
            pid = get_backend_pid(conn)
            if pid:
                stack_summary = traceback.extract_stack()
                filtered = [frame for frame in stack_summary if "site-packages" not in frame.filename]
                summary_text = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered)
                try:
                    req_info = f"Endpoint: {request.endpoint}, URL: {request.url}"
                except Exception:
                    req_info = "No request context available"
                transaction_metadata[pid] = {
                    'stack_trace': summary_text,
                    'full_stack_trace': ''.join(traceback.format_stack()),
                    'start_time': datetime.utcnow(),
                    'request_info': req_info
                }
                logger.debug(f"Transaction started (engine event) from:\n{summary_text}\n{req_info}")
            else:
                logger.warning("Transaction begin: Unable to capture backend PID (engine event).")

        # Listener for transaction begin at the Session level.
        def capture_session_after_begin(session, transaction, connection):
            pid = get_backend_pid(connection)
            if pid:
                stack_summary = traceback.extract_stack()
                filtered = [frame for frame in stack_summary if "site-packages" not in frame.filename]
                summary_text = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered)
                try:
                    req_info = f"Endpoint: {request.endpoint}, URL: {request.url}"
                except Exception:
                    req_info = "No request context available"
                transaction_metadata[pid] = {
                    'stack_trace': summary_text,
                    'full_stack_trace': ''.join(traceback.format_stack()),
                    'start_time': datetime.utcnow(),
                    'request_info': req_info
                }
                logger.debug(f"Transaction started (Session.after_begin) from:\n{summary_text}\n{req_info}")
            else:
                logger.warning("Session.after_begin: Unable to capture backend PID.")

        # Attach the session-level event.
        event.listen(Session, "after_begin", capture_session_after_begin)

        @event.listens_for(self._engine, 'before_cursor_execute')
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self._local.query_start = time.time()
            pid = get_backend_pid(conn)
            if pid:
                stack_summary = traceback.extract_stack()
                filtered = [frame for frame in stack_summary if "site-packages" not in frame.filename]
                summary_text = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered)
                transaction_metadata[pid] = {
                    'stack_trace': summary_text,
                    'full_stack_trace': ''.join(traceback.format_stack()),
                    'start_time': datetime.utcnow()
                }
                logger.debug(f"Updated fallback stack trace for PID {pid} during query execution:\n{summary_text}")

        @event.listens_for(self._engine, 'after_cursor_execute')
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            duration = time.time() - getattr(self._local, 'query_start', time.time())
            if duration > 1.0:
                logger.warning(f"Query took {duration:.2f}s: {statement}")

        # Listener for transaction COMMIT event.
        @event.listens_for(self._engine, "commit")
        def capture_commit(conn):
            pid = get_backend_pid(conn)
            if not pid:
                logger.warning("Commit event: Unable to capture backend PID.")
                return
            # If no transaction metadata exists, log a warning and capture fallback.
            if pid not in transaction_metadata:
                logger.warning(f"Commit event for PID {pid} with no prior transaction metadata. Capturing fallback now.")
                transaction_metadata[pid] = {
                    'stack_trace': "Fallback: No transaction begin captured.",
                    'full_stack_trace': ''.join(traceback.format_stack()),
                    'start_time': datetime.utcnow()
                }
            stack_summary = traceback.extract_stack()
            filtered = [frame for frame in stack_summary if "site-packages" not in frame.filename]
            summary_text = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered)
            try:
                req_info = f"Endpoint: {request.endpoint}, URL: {request.url}"
            except Exception:
                req_info = "No request context available"
            logger.debug(f"COMMIT executed for PID {pid}.\nCommit stack trace:\n{summary_text}\n{req_info}")
            transaction_metadata[pid].update({
                'commit_stack_trace': summary_text,
                'commit_time': datetime.utcnow(),
                'commit_request_info': req_info
            })
            # Once committed, clear the stored metadata.
            clear_transaction_details(pid)

        # Listener for transaction ROLLBACK event.
        @event.listens_for(self._engine, "rollback")
        def capture_rollback(conn):
            pid = get_backend_pid(conn)
            if not pid:
                logger.warning("Rollback event: Unable to capture backend PID.")
                return
            # If no metadata exists, capture fallback.
            if pid not in transaction_metadata:
                logger.warning(f"Rollback event for PID {pid} with no prior transaction metadata. Capturing fallback now.")
                transaction_metadata[pid] = {
                    'stack_trace': "Fallback: No transaction begin captured.",
                    'full_stack_trace': ''.join(traceback.format_stack()),
                    'start_time': datetime.utcnow()
                }
            stack_summary = traceback.extract_stack()
            filtered = [frame for frame in stack_summary if "site-packages" not in frame.filename]
            summary_text = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered)
            try:
                req_info = f"Endpoint: {request.endpoint}, URL: {request.url}"
            except Exception:
                req_info = "No request context available"
            logger.debug(f"ROLLBACK executed for PID {pid}.\nRollback stack trace:\n{summary_text}\n{req_info}")
            transaction_metadata[pid].update({
                'rollback_stack_trace': summary_text,
                'rollback_time': datetime.utcnow(),
                'rollback_request_info': req_info
            })
            # Once rolled back, clear the stored metadata.
            clear_transaction_details(pid)

    def get_transaction_details(self, pid):
        return get_transaction_details(pid)

# Create a global DatabaseManager instance
db_manager = DatabaseManager(db)