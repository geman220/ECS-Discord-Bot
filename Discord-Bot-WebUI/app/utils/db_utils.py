# app/utils/db_utils.py

"""
Database Utilities Module

This module provides helper decorators for managing database transactions
within Flask request contexts and Celery tasks. The 'transactional' decorator
is designed for use within Flask views, while the 'celery_transactional_task'
decorator creates a new session for each Celery task execution.
"""

from functools import wraps
from flask import g, current_app
from app.core import celery, db
import logging

logger = logging.getLogger(__name__)


def transactional(f):
    """
    Decorator to manage database transactions for Flask routes or functions.

    Commits both g.db_session (per-request session) and db.session (Flask-SQLAlchemy
    scoped session) on success, and rolls back both on error. This ensures transaction
    integrity regardless of which session pattern routes use.

    Args:
        f: The function to be wrapped.

    Returns:
        The wrapped function with transaction management.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            # Commit both session patterns to ensure all changes are persisted
            # Routes may use either g.db_session or db.session inconsistently
            if hasattr(g, 'db_session') and g.db_session:
                g.db_session.commit()
            # Also commit Flask-SQLAlchemy's scoped session
            db.session.commit()
            return result
        except Exception as e:
            # Rollback both sessions on error
            if hasattr(g, 'db_session') and g.db_session:
                try:
                    g.db_session.rollback()
                except Exception:
                    pass  # Session may already be invalidated
            try:
                db.session.rollback()
            except Exception:
                pass  # Session may already be invalidated
            current_app.logger.exception("Error in transactional function %s", f.__name__)
            raise
    return wrapped


def celery_transactional_task(**task_kwargs):
    """
    Decorator to manage database transactions within Celery tasks.

    For each task execution, it creates a new session from app.SessionLocal,
    commits on success, rolls back on error, and closes the session.
    
    Args:
        **task_kwargs: Keyword arguments to pass to celery.task.

    Returns:
        A decorator that wraps the task function with database transaction management.
    """
    def decorator(f):
        @celery.task(**task_kwargs)
        @wraps(f)
        def wrapped(*args, **kwargs):
            app = celery.flask_app
            # Ensure the task runs within the Flask application context.
            with app.app_context():
                session = app.SessionLocal()
                try:
                    # Pass the session to the task function.
                    result = f(*args, session=session, **kwargs)
                    session.commit()
                    return result
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error in celery transactional task {f.__name__}: {e}", exc_info=True)
                    raise
                finally:
                    session.close()
        return wrapped
    return decorator