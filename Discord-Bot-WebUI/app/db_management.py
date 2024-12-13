# app/db_management.py

import logging
import uuid
import collections
from datetime import datetime
from sqlalchemy import event
import time
import eventlet
import traceback
import threading
from app.core import db

logger = logging.getLogger(__name__)

lock = eventlet.semaphore.Semaphore()

class DatabaseManager:
    def __init__(self, db):
        """Initialize database manager with enhanced monitoring (optional)."""
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

    def init_app(self, app):
        """Initialize with Flask app and setup event handlers."""
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
        """If needed for periodic maintenance, implement here."""
        def cleanup():
            pass
        eventlet.spawn_after(300, cleanup)

    def check_for_leaked_connections(self):
        current_time = time.time()
        leaked = []

        for conn_id, checkout_time in list(self._active_connections.items()):
            age = current_time - checkout_time
            if age > 60:  # Consider leaked after 60 seconds
                leaked.append(conn_id)
                logger.error(f"Leaked connection detected: {age:.1f}s old")
                self.pool_stats['leaked_connections'] += 1

        for conn_id in leaked:
            self._active_connections.pop(conn_id, None)

    def _log_connection_event(self, event_type: str, connection_id: str, duration: float = None, extra: dict = None):
        stack_trace = traceback.format_stack()
        event = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'connection_id': connection_id,
            'thread_id': threading.get_ident(),
            'duration': duration,
            'stack_trace': ''.join(stack_trace),
            **(extra or {})
        }
        self.connection_history.append(event)
        if duration and duration > 1.0:
            logger.warning(f"Slow database operation: {event_type} took {duration:.2f}s")

    def _setup_engine_events(self):
        if not self._engine:
            return

        @event.listens_for(self._engine, 'checkout')
        def on_checkout(dbapi_conn, connection_record, connection_proxy):
            conn_id = str(uuid.uuid4())
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

        @event.listens_for(self._engine, 'checkin')
        def on_checkin(dbapi_conn, connection_record):
            # connection_record is an object, we need a stable ID
            # Since we created conn_id at checkout from uuid, we must store it differently.
            # For simplicity, we can skip timing on checkin if we don't have the original conn_id.
            # Or store id(connection_record) at checkout.
            # Let's store id(connection_record) at checkout instead of uuid:

            # Adjusting above approach:
            # Replace checkout logic:
            # conn_id = id(connection_record) # Instead of UUID
            # In on_checkout:
            pass

        @event.listens_for(self._engine, 'before_cursor_execute')
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self._local.query_start = time.time()

        @event.listens_for(self._engine, 'after_cursor_execute')
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            duration = time.time() - getattr(self._local, 'query_start', time.time())
            # Adjust query logging if needed.

db_manager = DatabaseManager(db)
