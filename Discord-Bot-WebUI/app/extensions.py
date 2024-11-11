# app/extensions.py

import logging
import time
import inspect
from flask import g, has_app_context, current_app
from contextlib import contextmanager
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker, scoped_session
from celery.signals import worker_process_init, worker_process_shutdown

# Import db and other core components
from app.core import db, socketio, celery

logger = logging.getLogger(__name__)

class ManagedSession:
    """Session manager that integrates with db_manager"""
    def __init__(self, db_manager, real_session):
        self._db_manager = db_manager
        self._real_session = real_session
        self._in_managed_context = False

    def _create_managed_session(self):
        """Create new managed session with caller tracking"""
        frame = inspect.currentframe()
        caller = frame.f_back
        location = f"{caller.f_code.co_filename}:{caller.f_lineno}"
        logger.info(f"Creating managed session from {location}")

        try:
            self._context = self._db_manager.session_scope(
                transaction_name=f"auto_managed_{location}"
            )
            session = self._context.__enter__()
            self._in_managed_context = True

            if has_app_context():
                # Register cleanup with request lifecycle
                from app.lifecycle import request_lifecycle
                request_lifecycle.register_cleanup(
                    lambda exc: self._cleanup_session(exc)
                )

            return session

        except Exception as e:
            logger.error(f"Failed to create managed session: {e}")
            return self._real_session()

    def _cleanup_session(self, exc):
        """Clean up managed session"""
        if self._in_managed_context:
            try:
                self._context.__exit__(exc, None, None)
            finally:
                self._in_managed_context = False

    def __call__(self):
        """Session factory implementation"""
        if has_app_context() and hasattr(g, 'db_session'):
            return g.db_session

        if not self._in_managed_context:
            return self._create_managed_session()

        return self._real_session()

    def __getattr__(self, name):
        """Handle attribute access with session management"""
        if name == 'remove':
            def remove_session():
                if has_app_context() and hasattr(g, 'db_session'):
                    try:
                        session = g.db_session
                        if session.is_active:
                            session.rollback()
                        session.close()
                        delattr(g, 'db_session')
                    except Exception as e:
                        logger.error(f"Error removing session: {e}")
            return remove_session

        if has_app_context():
            if not hasattr(g, 'db_session'):
                g.db_session = self._create_managed_session()
            return getattr(g.db_session, name)

        if not self._in_managed_context:
            self._session = self._create_managed_session()
            self._in_managed_context = True
        return getattr(self._session, name)

class ManagedSQLAlchemy:
    """Adds session management capabilities to SQLAlchemy"""
    @classmethod
    def init_db(cls, app):
        """Initialize database with management capabilities"""
        if not hasattr(db, '_session_setup_complete'):
            db._session_setup_complete = False

            @app.before_request
            def setup_managed_session():
                if not db._session_setup_complete:
                    from app.db_management import db_manager
                    if not hasattr(db, '_managed_session'):
                        db._managed_session = ManagedSession(db_manager, db.session)
                        db.session = db._managed_session
                    db._session_setup_complete = True

            @app.before_request
            def setup_session_cleanup():
                if not hasattr(g, 'db_cleanups'):
                    g.db_cleanups = []
                g.get_db_cleanup = lambda f: g.db_cleanups.append(f) or f

# Celery initialization function
def init_celery(app=None):
    """Initialize Celery with the application"""
    if app:
        celery.conf.update(app.config)

    class FlaskTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            if app is None:
                from flask import current_app
                from app.db_management import db_manager
                flask_app = current_app._get_current_object() if current_app else create_app()
            else:
                flask_app = app

            with flask_app.app_context():
                with db_manager.session_scope(
                    transaction_name=f'celery_task_{self.name}'
                ) as session:
                    self._session = session
                    try:
                        return self.run(*args, **kwargs)
                    finally:
                        if hasattr(self, '_session'):
                            delattr(self, '_session')

        @property
        def session(self):
            if not hasattr(self, '_session'):
                raise RuntimeError("No database session - task not in correct context")
            return self._session

    celery.Task = FlaskTask

    # Configure Celery
    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=30 * 60,
        task_soft_time_limit=15 * 60,
        worker_max_tasks_per_child=50,
        worker_max_memory_per_child=150000
    )

    return celery

# Setup worker process handlers
@worker_process_init.connect
def init_worker_process(**kwargs):
    """Initialize worker process with limited connections."""
    if hasattr(db, 'engine'):
        db.engine.dispose()

    # Access app context to get the engine options
    from flask import current_app
    app = current_app._get_current_object()
    engine_options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
    db.engine = db.create_engine(db.engine.url, **engine_options)

@worker_process_shutdown.connect
def cleanup_worker_process(**kwargs):
    """Cleanup database connections when worker process shuts down."""
    if hasattr(db, 'engine'):
        db.engine.dispose()
