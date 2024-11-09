# app/db_management.py

import logging
import threading
import time
import sys
import weakref
from datetime import datetime
from contextlib import contextmanager
from flask import g, has_app_context, current_app
from sqlalchemy import event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import Optional, Dict, Set
from app.extensions import db

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db):
        self.db = db
        self._engine = None
        self.app = None
        self.initialized = False
        self._statement_timeout_set = threading.local()
        self._active_connections: Set[int] = set()
        self._connection_times: Dict[int, float] = {}
        self.pool_stats = {
            'checkouts': 0,
            'checkins': 0,
            'connections_created': 0,
            'leaked_connections': 0,
            'max_connection_age': 0
        }
        
    def init_app(self, app):
        """Initialize database manager with Flask app"""
        if self.initialized:
            return

        self.app = app
        
        # Initialize engine immediately using db.engine
        with app.app_context():
            self._engine = self.db.engine
            self._session = self.db.session
            
            # Setup pool listeners
            self._setup_pool_listeners()
        
        # Register teardown handlers
        app.teardown_appcontext(self.teardown_session)
        app.teardown_request(self.teardown_request)
        app.teardown_appcontext(self.cleanup_pool)
        
        self.initialized = True

    def _set_session_timeouts(self, session):
        """Set session timeouts only if not already set in this thread"""
        if not hasattr(self._statement_timeout_set, 'value') or not self._statement_timeout_set.value:
            try:
                session.execute(text("SET LOCAL statement_timeout = '30s'"))
                session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
                self._statement_timeout_set.value = True
            except Exception as e:
                logger.error(f"Failed to set session timeouts: {e}")

    def execute_with_retry(self, session, query, params=None, max_retries=3):
        """Execute queries with retry logic and proper transaction handling"""
        for attempt in range(max_retries):
            try:
                if not session.in_transaction():
                    with session.begin():
                        result = session.execute(query, params) if params else session.execute(query)
                        return result
                else:
                    result = session.execute(query, params) if params else session.execute(query)
                    return result
            except OperationalError as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Query attempt {attempt + 1} failed, retrying: {e}")
                time.sleep(0.1 * (attempt + 1))
                session.rollback()

    def _setup_engine(self):
        """Setup database engine and listeners"""
        if not self._engine:
            self._engine = self.db.engine
            self._setup_pool_listeners()

    def _setup_pool_listeners(self):
        """Setup connection pool monitoring"""
        if not self._engine:
            return

        @event.listens_for(self._engine, 'checkout')
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            """Track when connections are checked out"""
            conn_id = id(connection_proxy)
            self._active_connections.add(conn_id)
            self._connection_times[conn_id] = time.time()
            self.pool_stats['checkouts'] += 1
            
            # Log long-held connections
            for old_conn_id, checkout_time in self._connection_times.items():
                if old_conn_id != conn_id:
                    age = time.time() - checkout_time
                    if age > 300:  # 5 minutes
                        logger.warning(f"Connection {old_conn_id} has been checked out for {age:.1f} seconds")

        @event.listens_for(self._engine, 'checkin')
        def receive_checkin(dbapi_conn, connection_record):
            """Track when connections are checked in"""
            conn_id = id(connection_record)
            self._active_connections.discard(conn_id)
            if conn_id in self._connection_times:
                age = time.time() - self._connection_times.pop(conn_id)
                self.pool_stats['max_connection_age'] = max(
                    self.pool_stats['max_connection_age'], 
                    age
                )
            self.pool_stats['checkins'] += 1

        @event.listens_for(self._engine, 'connect')
        def receive_connect(dbapi_conn, connection_record):
            """Track new connections"""
            self.pool_stats['connections_created'] += 1

        @event.listens_for(self._engine, 'reset')
        def receive_reset(dbapi_conn, connection_record):
            """Handle connection resets"""
            # Cancel any running queries
            try:
                dbapi_conn.cancel()
            except:
                pass

    def monitor_celery_connections(self):
        """Monitor and cleanup Celery-specific connections"""
        with self.session_scope() as session:
            try:
                # Find and terminate very old Celery connections
                session.execute(text("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity 
                    WHERE application_name LIKE '%celery%'
                    AND state = 'idle in transaction'
                    AND (now() - state_change) > interval '30 seconds'
                """))
            
                # Log Celery connection stats
                result = session.execute(text("""
                    SELECT count(*), state 
                    FROM pg_stat_activity 
                    WHERE application_name LIKE '%celery%'
                    GROUP BY state
                """))
            
                for count, state in result:
                    logger.info(f"Celery connections in {state}: {count}")
                
            except Exception as e:
                logger.error(f"Error monitoring Celery connections: {e}")

    def terminate_idle_transactions(self):
        """Forcibly terminate idle transactions and stale Celery connections"""
        with self.session_scope() as session:
            try:
                # Terminate very old Celery connections
                session.execute(text("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity 
                    WHERE application_name LIKE '%celery%'
                    AND (
                        state = 'idle in transaction'
                        OR (state = 'active' AND query_start < NOW() - INTERVAL '5 minutes')
                        OR (backend_start < NOW() - INTERVAL '30 minutes')
                    )
                """))
            
                # Terminate any idle transactions
                session.execute(text("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE state = 'idle in transaction'
                    AND pid != pg_backend_pid()
                    AND (now() - state_change) > interval '30 seconds'
                """))
            
                # Log connection stats
                result = session.execute(text("""
                    SELECT state, count(*) as count, 
                        MAX(EXTRACT(EPOCH FROM (now() - state_change))) as max_duration
                    FROM pg_stat_activity 
                    WHERE application_name LIKE '%app%'
                    GROUP BY state
                """))
            
                for row in result:
                    logger.info(f"Connection state {row.state}: {row.count} connections, "
                              f"max duration: {row.max_duration:.1f}s")
                
            except Exception as e:
                logger.error(f"Error cleaning up connections: {e}")

    def check_for_leaked_connections(self):
        """Check for and cleanup leaked connections"""
        current_time = time.time()
        leaked = []

        for conn_id, checkout_time in list(self._connection_times.items()):
            age = current_time - checkout_time
            if age > 300:  # Reduced from 600 to 300 seconds (5 minutes)
                leaked.append(conn_id)
                logger.error(f"Found leaked connection {conn_id}, age: {age:.1f}s")
                self.pool_stats['leaked_connections'] += 1
            
                # Try to terminate the connection
                self.terminate_idle_transactions()

        # Cleanup leaked connections
        for conn_id in leaked:
            self._active_connections.discard(conn_id)
            self._connection_times.pop(conn_id, None)

        # Log pool status
        if leaked or len(self._active_connections) > 5:  # Log if there are leaks or too many connections
            logger.warning(
                f"Pool status: Active={len(self._active_connections)}, "
                f"Leaks={self.pool_stats['leaked_connections']}, "
                f"Created={self.pool_stats['connections_created']}"
            )

    @contextmanager
    def session_scope(self, nested=False, transaction_name=None):
        """Improved session scope with better transaction handling"""
        session = None
        is_nested = False
        app_ctx = None
        start_time = time.time()
    
        try:
            if not has_app_context() and self.app:
                app_ctx = self.app.app_context()
                app_ctx.push()

            if has_app_context():
                if hasattr(g, 'db_session'):
                    session = g.db_session
                    is_nested = True
                else:
                    session = self.db.session()  # Create new session
                    g.db_session = session
            else:
                session = self.db.session()  # Create new session

            if not is_nested:
                self._set_session_timeouts(session)
            
            yield session

            # Check transaction duration
            duration = time.time() - start_time
            if duration > 10:  # Log long transactions
                logger.warning(f"Long transaction detected: {duration:.2f}s {transaction_name or ''}")

            if not nested and not is_nested and session.is_active:
                try:
                    session.commit()
                except SQLAlchemyError as e:
                    logger.error(f"Error committing session: {e}")
                    session.rollback()
                    raise
            
        except Exception as e:
            logger.error(f"Session scope error: {e}")
            if session and session.is_active:
                session.rollback()
            raise
        
        finally:
            if not nested and not is_nested:
                if session:
                    session.close()
                    if hasattr(session, 'registry'):
                        session.registry.clear()  # Clear registry instead of remove()
                self._statement_timeout_set.value = False
            if app_ctx is not None:
                app_ctx.pop()

    def safe_count_query(self, model, filters=None):
        """Safe method for performing count queries"""
        with self.session_scope() as session:
            try:
                query = session.query(model)
                if filters:
                    query = query.filter(*filters)
                return self.execute_with_retry(session, query.statement.with_only_columns([func.count()]).order_by(None))
            except Exception as e:
                logger.error(f"Count query failed for {model.__name__}: {e}")
                raise

    def cleanup_pool(self, exception=None):
        """Enhanced cleanup of connection pool"""
        try:
            # Check for leaked connections
            self.check_for_leaked_connections()
        
            # Terminate idle transactions
            self.terminate_idle_transactions()
        
            # Dispose of the engine
            if self._engine:
                self._engine.dispose()
            
            # Clear tracking sets
            self._active_connections.clear()
            self._connection_times.clear()
        
        except Exception as e:
            logger.error(f"Error during pool cleanup: {e}")

    def teardown_session(self, exception=None):
        """Clean up session at the end of app context"""
        if has_app_context() and hasattr(g, 'db_session'):
            try:
                session = g.db_session
                if exception is not None:
                    session.rollback()
                elif session.is_active:
                    session.commit()
            except Exception:
                if session.is_active:
                    session.rollback()
                raise
            finally:
                session.close()
                # Remove session from registry instead of calling remove()
                if hasattr(session, 'registry'):
                    session.registry.clear()  # For scoped_session
                delattr(g, 'db_session')

    def teardown_request(self, exception=None):
        """Clean up at the end of each request"""
        try:
            if exception is not None:
                self.db.session.rollback()
            else:
                try:
                    if self.db.session.is_active:
                        self.db.session.commit()
                except Exception:
                    self.db.session.rollback()
                    raise
        finally:
            self.db.session.close()
            # Clear the session registry instead of remove()
            if hasattr(self.db.session, 'registry'):
                self.db.session.registry.clear()

    def get_pool_stats(self):
        """Get enhanced pool statistics"""
        stats = self.pool_stats.copy()
        stats.update({
            'active_connections': len(self._active_connections),
            'connection_ages': {
                conn_id: time.time() - checkout_time
                for conn_id, checkout_time in self._connection_times.items()
            }
        })
        return stats

# Create global instance
db_manager = DatabaseManager(db)