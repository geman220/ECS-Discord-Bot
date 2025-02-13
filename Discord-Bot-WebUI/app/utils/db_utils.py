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

    Commits the current Flask‑SQLAlchemy db.session on success and rolls back
    on error. The session is automatically removed at the end of the request.
    
    Args:
        f: The function to be wrapped.

    Returns:
        The wrapped function with transaction management.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            db.session.commit()
            return result
        except Exception as e:
            db.session.rollback()
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