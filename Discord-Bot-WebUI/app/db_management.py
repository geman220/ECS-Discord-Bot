# app/db_management.py

import logging
import threading
import time
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
        self._active_connections: Set[int] = set()  # Track active connection IDs
        self._connection_times: Dict[int, float] = {}  # Track connection timestamps
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
        
        # Configure SQLAlchemy engine options
        engine_options = {
            'pool_size': app.config.get('SQLALCHEMY_POOL_SIZE', 10),
            'max_overflow': app.config.get('SQLALCHEMY_MAX_OVERFLOW', 20),
            'pool_timeout': app.config.get('SQLALCHEMY_POOL_TIMEOUT', 30),
            'pool_recycle': app.config.get('SQLALCHEMY_POOL_RECYCLE', 1800),  # 30 minutes
            'pool_pre_ping': True,
            'pool_use_lifo': True,
            'pool_reset_on_return': 'rollback',
            'echo_pool': app.config.get('SQLALCHEMY_ECHO_POOL', False),
            'poolclass': QueuePool,
            'connect_args': {
                'connect_timeout': 10,
                'application_name': f"{app.name}_app",
                'options': '-c statement_timeout=30000'  # 30 second query timeout
            }
        }
        
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
        
        # Register teardown handlers
        app.teardown_appcontext(self.teardown_session)
        app.teardown_request(self.teardown_request)
        app.teardown_appcontext(self.cleanup_pool)

        # Add periodic cleanup
        if not app.debug:
            @app.before_request
            def check_for_leaks():
                self.check_for_leaked_connections()

        # Set up engine after registration
        with app.app_context():
            self._setup_engine()

        self.initialized = True

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

    def check_for_leaked_connections(self):
        """Check for and cleanup leaked connections"""
        current_time = time.time()
        leaked = []

        for conn_id, checkout_time in self._connection_times.items():
            age = current_time - checkout_time
            if age > 600:  # 10 minutes
                leaked.append(conn_id)
                logger.error(f"Found leaked connection {conn_id}, age: {age:.1f}s")
                self.pool_stats['leaked_connections'] += 1

        # Cleanup leaked connections
        for conn_id in leaked:
            self._active_connections.discard(conn_id)
            self._connection_times.pop(conn_id, None)

        # Log pool status
        if leaked:
            logger.warning(
                f"Pool status: Size={len(self._active_connections)}, "
                f"Leaks={self.pool_stats['leaked_connections']}, "
                f"Created={self.pool_stats['connections_created']}"
            )

    @contextmanager
    def session_scope(self, nested=False, transaction_name=None):
        """Session context manager with enhanced connection tracking"""
        session = None
        is_nested = False
        app_ctx = None
        
        try:
            # Push app context if needed
            if not has_app_context() and self.app:
                app_ctx = self.app.app_context()
                app_ctx.push()

            if has_app_context():
                if hasattr(g, 'db_session'):
                    session = g.db_session
                    is_nested = True
                else:
                    session = self.db.session
                    g.db_session = session
            else:
                session = self.db.session

            # Set session timeout
            if not is_nested:
                session.execute(text("SET LOCAL statement_timeout = '30s'"))

            yield session

            if not nested and not is_nested and session.is_active:
                try:
                    session.commit()
                except SQLAlchemyError as e:
                    logger.error(f"Error committing session: {e}")
                    session.rollback()
                    raise
                
        except Exception:
            if session and session.is_active:
                session.rollback()
            raise
            
        finally:
            if session and not nested and not is_nested:
                session.close()
                session.remove()
            if app_ctx is not None:
                app_ctx.pop()

    def cleanup_pool(self, exception=None):
        """Enhanced cleanup of connection pool"""
        try:
            # Check for leaked connections
            self.check_for_leaked_connections()
            
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
                session.remove()
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
            self.db.session.remove()

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