# app/db_management.py

# Import Eventlet's green modules
from eventlet.green import threading, time
import logging
import sys
import uuid
import collections
from datetime import datetime, timedelta
from contextlib import contextmanager
from flask import g, has_app_context, current_app
from sqlalchemy import event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, SQLAlchemyError, DisconnectionError
from typing import Optional, Dict, Set, Any
from app.core import db
from app.lifecycle import request_lifecycle
import eventlet

logger = logging.getLogger(__name__)

# Use Eventlet's Semaphore
lock = eventlet.semaphore.Semaphore()

class DatabaseManager:
    def __init__(self, db):
        """Initialize database manager with enhanced monitoring"""
        self._cleanup_lock = threading.RLock()
        self.db = db
        self._engine = None
        self.app = None
        self.initialized = False
        self._active_connections = {}
        self._connection_timeouts = {}
        self._long_running_transactions = collections.defaultdict(float)
        self.connection_history = collections.deque(maxlen=100)
        self.pool_stats = {
            'checkouts': 0,
            'checkins': 0,
            'connections_created': 0,
            'leaked_connections': 0,
            'failed_connections': 0,
            'long_transactions': 0
        }
        self._transaction_times = collections.defaultdict(list)
        self._session_monitor = collections.defaultdict(dict)

    def init_app(self, app):
        """Initialize with Flask app and setup event handlers"""
        if self.initialized:
            return

        try:
            self.app = app

            self._engine = self.db.engine

            # Ensure app context for engine access
            ctx = None
            try:
                if not has_app_context():
                    ctx = app.app_context()
                    ctx.push()

                # Get existing engine from SQLAlchemy
                self._engine = self.db.get_engine(app, bind=None)
                if not self._engine:
                    raise RuntimeError("Database engine not properly initialized")

                logger.debug("Successfully acquired database engine")

                # Setup engine events
                self._setup_engine_events()

                # Register lifecycle handlers
                request_lifecycle.register_cleanup(self._cleanup_request)
                request_lifecycle.register_before_request(self._check_connections)
                app.teardown_appcontext(self._cleanup_app_context)

                # Initialize monitoring structures
                self._active_connections.clear()
                self._long_running_transactions.clear()
                self._session_monitor.clear()
                self.connection_history.clear()

                # Reset stats
                self.pool_stats = {
                    'checkouts': 0,
                    'checkins': 0,
                    'connections_created': 0,
                    'leaked_connections': 0,
                    'failed_connections': 0,
                    'long_transactions': 0
                }

                self.initialized = True
                logger.info("Database manager initialized successfully")

            finally:
                if ctx is not None:
                    ctx.pop()

        except Exception as e:
            logger.error(f"Failed to initialize database manager: {e}", exc_info=True)
            self.initialized = False
            raise

    def get_pool_stats(self):
        """
        Get comprehensive connection pool statistics
    
        Returns:
            dict: Dictionary containing pool statistics and metrics
        """
        try:
            if not self._engine:
                logger.warning("Database engine not initialized")
                return {}
            
            # Get current pool state
            pool = self._engine.pool
            current_connections = len(self._active_connections)
        
            # Calculate pool utilization metrics
            pool_size = pool.size() if hasattr(pool, 'size') else 0
            max_overflow = pool._max_overflow if hasattr(pool, '_max_overflow') else 0
            total_capacity = pool_size + max_overflow
            utilization = (current_connections / total_capacity * 100) if total_capacity > 0 else 0
        
            # Combine with tracked statistics
            stats = {
                # Current pool state
                'current_size': pool_size,
                'max_size': total_capacity, 
                'active_connections': current_connections,
                'available_connections': max(0, total_capacity - current_connections),
                'utilization_percentage': round(utilization, 2),
            
                # Lifetime statistics from self.pool_stats
                'total_checkouts': self.pool_stats['checkouts'],
                'total_checkins': self.pool_stats['checkins'],
                'connections_created': self.pool_stats['connections_created'],
                'leaked_connections': self.pool_stats['leaked_connections'],
                'failed_connections': self.pool_stats['failed_connections'],
                'long_transactions': self.pool_stats['long_transactions'],
            
                # Additional metrics
                'checkout_pending': pool._overflow if hasattr(pool, '_overflow') else 0,
                'checkedin': pool.checkedin() if hasattr(pool, 'checkedin') else 0
            }
        
            # Add timing statistics if available
            if hasattr(self, '_transaction_times') and self._transaction_times:
                times = [t for sublist in self._transaction_times.values() for t in sublist]
                if times:
                    stats.update({
                        'avg_transaction_time': sum(times) / len(times),
                        'max_transaction_time': max(times),
                        'min_transaction_time': min(times)
                    })
                
            return stats
        
        except Exception as e:
            logger.error(f"Error getting pool stats: {e}", exc_info=True)
            return {
                'error': str(e),
                'checkouts': self.pool_stats['checkouts'],
                'checkins': self.pool_stats['checkins']
            }

    def cleanup_connections(self, exception=None):
        """Clean up database connections with proper error handling"""
        try:
            with self._cleanup_lock:
                self.check_for_leaked_connections()
                self.terminate_idle_transactions()
                if self._engine:
                    self._engine.dispose()
        except Exception as e:
            logger.error(f"Error during connection cleanup: {e}")
        finally:
            self._active_connections.clear()

    def _cleanup_request(self, exception=None):
        """Consolidated request cleanup"""
        try:
            if has_app_context() and hasattr(g, 'db_session'):
                session = g.db_session
                try:
                    if exception is not None:
                        session.rollback()
                    elif session.is_active:
                        session.commit()
                finally:
                    session.close()
                    if hasattr(session, 'remove'):
                        session.remove()
                    delattr(g, 'db_session')
        except Exception as e:
            logger.error(f"Error during request cleanup: {e}")

    def _cleanup_app_context(self, exception=None):
        """App context cleanup"""
        try:
            self.check_for_leaked_connections()
            self.terminate_idle_transactions()
            if self._engine:
                self._engine.dispose()
        except Exception as e:
            logger.error(f"App context cleanup error: {e}")
        finally:
            self._active_connections.clear()

    def _check_connections(self):
        """Combined connection check handler"""
        if not self.app.debug:
            self.check_for_leaked_connections()
            self.terminate_idle_transactions()

    def terminate_idle_transactions(self):
        """Aggressively terminate idle transactions"""
        with self._cleanup_lock:
            try:
                with self.session_scope(transaction_name='terminate_idle') as session:
                    # Kill idle transactions
                    session.execute(text("""
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity 
                        WHERE state = 'idle in transaction'
                        AND pid != pg_backend_pid()
                        AND (now() - state_change) > interval '15 seconds'
                    """))

                    # Kill idle connections
                    session.execute(text("""
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity 
                        WHERE state = 'idle'
                        AND pid != pg_backend_pid()
                        AND (now() - state_change) > interval '30 seconds'
                        AND application_name LIKE 'app_app%'
                    """))
            except Exception as e:
                logger.error(f"Error terminating connections: {str(e)}")

    def check_for_leaked_connections(self):
        """Identify and cleanup leaked connections"""
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

        if leaked:
            self.terminate_idle_transactions()

    def _log_connection_event(self, event_type: str, connection_id: str,
                              duration: Optional[float] = None,
                              extra: Optional[Dict[str, Any]] = None):
        """Enhanced connection event logging"""
        event = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'connection_id': connection_id,
            'thread_id': threading.get_ident(),
            'duration': duration,
            **(extra or {})
        }
        self.connection_history.append(event)

        if duration and duration > 1.0:  # Log slow operations
            logger.warning(f"Slow database operation: {event_type} took {duration:.2f}s")

    def _monitor_session(self, session_id: str, action: str):
        """Track session lifecycle"""
        self._session_monitor[session_id].update({
            'last_action': action,
            'timestamp': time.time(),
            'thread_id': threading.get_ident()
        })

    def _setup_engine_events(self):
        """Enhanced engine event configuration"""
        @event.listens_for(self._engine, 'checkout')
        def on_checkout(dbapi_conn, connection_record, connection_proxy):
            conn_id = str(uuid.uuid4())
            self._active_connections[conn_id] = time.time()
            self.pool_stats['checkouts'] += 1

            try:
                cursor = dbapi_conn.cursor()
                # Set stricter timeouts
                cursor.execute("""
                    SET LOCAL statement_timeout = '10s';
                    SET LOCAL idle_in_transaction_session_timeout = '10s';
                    SET LOCAL lock_timeout = '5s';
                """)
                cursor.close()
                self._log_connection_event('checkout', conn_id)
            except Exception as e:
                self.pool_stats['failed_connections'] += 1
                logger.error(f"Connection checkout failed: {e}")
                raise

        @event.listens_for(self._engine, 'checkin')
        def on_checkin(dbapi_conn, connection_record):
            conn_id = id(connection_record)
            if conn_id in self._active_connections:
                checkout_time = self._active_connections.pop(conn_id)
                duration = time.time() - checkout_time
                self._log_connection_event('checkin', str(conn_id), duration)

                if duration > 30:
                    self.pool_stats['long_transactions'] += 1
                    logger.warning(f"Long-lived connection detected: {duration:.1f}s")
            self.pool_stats['checkins'] += 1

        @event.listens_for(self._engine, 'connect')
        def on_connect(dbapi_conn, connection_record):
            self.pool_stats['connections_created'] += 1
            conn_id = str(uuid.uuid4())
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("""
                    SET SESSION statement_timeout = '10s';
                    SET SESSION idle_in_transaction_session_timeout = '10s';
                    SET SESSION lock_timeout = '5s';
                """)
                cursor.close()
                self._log_connection_event('connect', conn_id)
            except Exception as e:
                logger.error(f"Connection initialization failed: {e}")
                raise

        @event.listens_for(self._engine, 'reset')
        def on_reset(dbapi_conn, connection_record):
            conn_id = str(uuid.uuid4())
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("ROLLBACK")
                cursor.execute("""
                    SET SESSION statement_timeout = '10s';
                    SET SESSION idle_in_transaction_session_timeout = '10s';
                    SET SESSION lock_timeout = '5s';
                """)
                cursor.close()
                self._log_connection_event('reset', conn_id)
            except Exception as e:
                logger.error(f"Connection reset failed: {e}")
                raise

        @event.listens_for(self._engine, 'invalidate')
        def on_invalidate(dbapi_conn, connection_record, exception):
            conn_id = str(uuid.uuid4())
            logger.error(f"Connection invalidated due to: {exception}")
            self._log_connection_event('invalidate', conn_id, extra={'error': str(exception)})

    @contextmanager
    def session_scope(self, nested=False, transaction_name=None):
        """Enhanced session management with detailed logging"""
        session = None
        session_id = str(uuid.uuid4())
        start_time = time.time()

        logger.info(f"Starting session {session_id} for {transaction_name}",
                    extra={'session_id': session_id, 'transaction': transaction_name})

        try:
            # Reuse existing session if available
            if has_app_context() and hasattr(g, 'db_session'):
                session = g.db_session
                if nested:
                    logger.debug(f"Starting nested transaction in session {session_id}")
                    with session.begin_nested():
                        yield session
                    return
                yield session
                return

            # Create new session
            Session = sessionmaker(
                bind=self.db.engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )
            session = Session()

            if has_app_context():
                g.db_session = session
                logger.debug(f"Created new session {session_id} in request context")

            # Configure session
            try:
                session.execute(text("""
                    SET LOCAL statement_timeout = '30s';
                    SET LOCAL idle_in_transaction_session_timeout = '30s';
                    SET LOCAL lock_timeout = '10s';
                """))
            except Exception as e:
                logger.warning(f"Failed to set session parameters: {e}")

            yield session

            # Commit if active
            if session.is_active:
                try:
                    session.commit()
                    logger.debug(f"Committed session {session_id}")
                except Exception as e:
                    logger.error(f"Commit failed for session {session_id}: {e}")
                    session.rollback()
                    raise

        except Exception as e:
            logger.error(f"Session {session_id} failed: {e}",
                         extra={'session_id': session_id, 'error': str(e)})
            if session and session.is_active:
                try:
                    session.rollback()
                    logger.info(f"Rolled back session {session_id}")
                except Exception as rollback_error:
                    logger.error(f"Rollback failed for session {session_id}: {rollback_error}")
            raise

        finally:
            duration = time.time() - start_time

            # Log operation timing
            request_lifecycle.log_db_operation(
                operation=transaction_name or 'unnamed_transaction',
                duration=duration
            )

            # Cleanup
            if session and not has_app_context():
                try:
                    session.close()
                    logger.debug(f"Closed session {session_id}")
                except Exception as e:
                    logger.error(f"Error closing session {session_id}: {e}")

            if has_app_context() and hasattr(g, 'db_session') and duration > 5:
                logger.warning(f"Long running session detected: {duration:.2f}s",
                               extra={
                                   'session_id': session_id,
                                   'duration': duration,
                                   'transaction': transaction_name
                               })

            logger.info(f"Session {session_id} completed in {duration:.2f}s",
                        extra={
                            'session_id': session_id,
                            'duration': duration,
                            'transaction': transaction_name
                        })

    def get_long_running_queries(self):
        """Get information about long-running queries"""
        try:
            with self.session_scope(transaction_name='get_long_running_queries') as session:
                result = session.execute(text("""
                    SELECT pid, now() - query_start as duration, query
                    FROM pg_stat_activity
                    WHERE state = 'active'
                    AND now() - query_start > interval '5 seconds'
                    AND pid != pg_backend_pid()
                """))
                return {row.pid: {'duration': row.duration, 'query': row.query}
                        for row in result}
        except Exception as e:
            logger.error(f"Error getting long running queries: {e}")
            return {}

    def get_detailed_stats(self):
        """Get detailed database statistics"""
        return {
            'pool_stats': self.pool_stats,
            'active_connections': {
                'count': len(self._active_connections),
                'ages': {conn_id: time.time() - checkout_time
                         for conn_id, checkout_time in self._active_connections.items()}
            },
            'long_running_transactions': dict(self._long_running_transactions),
            'recent_events': list(self.connection_history),
            'session_monitor': dict(self._session_monitor)
        }

# Create global instance
db_manager = DatabaseManager(db)
