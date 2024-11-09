# app/db_management.py

import logging
import threading
import time
from datetime import datetime
from contextlib import contextmanager
from flask import g, has_app_context, current_app
from sqlalchemy import event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError
from typing import Optional, Dict
from app.extensions import db

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db):
        self.db = db
        self._engine = None
        self.app = None
        self.initialized = False
        self.pool_stats = {
            'checkouts': 0,
            'checkins': 0,
            'connections_created': 0
        }
        
    def init_app(self, app):
        """Initialize database manager with Flask app"""
        if self.initialized:
            return

        self.app = app
        
        # Configure SQLAlchemy engine options
        app.config.setdefault('SQLALCHEMY_ENGINE_OPTIONS', {
            'pool_size': 10,
            'max_overflow': 20,
            'pool_timeout': 30,
            'pool_recycle': 1800,
            'pool_pre_ping': True,
            'pool_use_lifo': True,
            'pool_reset_on_return': 'commit',
            'echo_pool': app.debug,
            'poolclass': QueuePool,
            'connect_args': {
                'connect_timeout': 10,
                'application_name': f"{app.name}_app"
            }
        })
        
        # Register teardown handlers
        app.teardown_appcontext(self.teardown_session)
        app.teardown_request(self.teardown_request)
        app.teardown_appcontext(self.cleanup_pool)

        # Set up engine after registration
        with app.app_context():
            self._setup_engine()

        self.initialized = True

    def _setup_engine(self):
        """Setup database engine and listeners"""
        if not self._engine:
            # Get engine from Flask-SQLAlchemy
            self._engine = self.db.engine
            self._setup_pool_listeners()

    def _setup_pool_listeners(self):
        """Setup connection pool monitoring"""
        if not self._engine:
            return

        @event.listens_for(self._engine, 'checkout')
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            self.pool_stats['checkouts'] += 1

        @event.listens_for(self._engine, 'checkin')
        def receive_checkin(dbapi_conn, connection_record):
            self.pool_stats['checkins'] += 1

        @event.listens_for(self._engine, 'connect')
        def receive_connect(dbapi_conn, connection_record):
            self.pool_stats['connections_created'] += 1

    @contextmanager
    def session_scope(self, nested=False, transaction_name=None):
        """Session context manager that works with existing sessions"""
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

            yield session

            if not nested and not is_nested and session.is_active:
                try:
                    session.commit()
                except Exception as e:
                    logger.error(f"Error committing session: {e}")
                    session.rollback()
                    raise
                
        except Exception:
            if session and session.is_active:
                session.rollback()
            raise
            
        finally:
            if session and not nested and not is_nested:
                session.remove()
            if app_ctx is not None:
                app_ctx.pop()

    def cleanup_pool(self, exception=None):
        """Cleanup connection pool on app context teardown"""
        if self._engine:
            self._engine.dispose()

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
            self.db.session.remove()

    def get_pool_stats(self):
        """Get current connection pool statistics"""
        return self.pool_stats.copy()

# Create global instance
db_manager = DatabaseManager(db)