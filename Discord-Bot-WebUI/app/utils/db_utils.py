# app/utils/db_utils.py

"""
Database Utilities Module

This module provides helper decorators for managing database transactions
within Flask request contexts and Celery tasks. The 'transactional' decorator
is designed for use within Flask views, while the 'celery_transactional_task'
decorator creates a new session for each Celery task execution.
"""

import time
import random
from functools import wraps
from flask import g, current_app
from sqlalchemy.exc import OperationalError, InterfaceError
from app.core import celery, db
import logging

logger = logging.getLogger(__name__)

# Error patterns that indicate transient/retryable database errors
RETRYABLE_PATTERNS = [
    'server closed the connection',
    'connection reset',
    'could not obtain lock',
    'lock timeout',
    'deadlock detected',
    'connection timed out',
    'connection refused',
    'ssl connection has been closed',
    'terminating connection',
]


def is_retryable_error(exception):
    """
    Check if an exception is a transient database error that should be retried.

    Args:
        exception: The exception to check

    Returns:
        bool: True if the error is transient and should be retried
    """
    if not isinstance(exception, (OperationalError, InterfaceError)):
        return False
    error_str = str(exception).lower()
    return any(pattern in error_str for pattern in RETRYABLE_PATTERNS)


def _safe_rollback():
    """Safely rollback both session patterns without raising exceptions."""
    if hasattr(g, 'db_session') and g.db_session:
        try:
            g.db_session.rollback()
        except Exception:
            pass  # Session may already be invalidated
    try:
        db.session.rollback()
    except Exception:
        pass  # Session may already be invalidated


def _invalidate_connection_if_needed(exception):
    """
    Invalidate the database connection if the error indicates a broken connection.

    This forces SQLAlchemy to get a fresh connection from the pool on the next
    attempt rather than reusing a potentially broken connection.
    """
    error_str = str(exception).lower()
    broken_connection_patterns = [
        'server closed the connection',
        'connection reset',
        'ssl connection has been closed',
        'terminating connection',
    ]
    if any(pattern in error_str for pattern in broken_connection_patterns):
        try:
            # Invalidate the connection so the pool will create a new one
            if hasattr(g, 'db_session') and g.db_session:
                connection = g.db_session.get_bind().connect()
                connection.invalidate()
        except Exception:
            pass
        try:
            connection = db.session.get_bind().connect()
            connection.invalidate()
        except Exception:
            pass


def transactional(f=None, max_retries=3, base_delay=0.5):
    """
    Decorator to manage database transactions for Flask routes or functions.

    Commits both g.db_session (per-request session) and db.session (Flask-SQLAlchemy
    scoped session) on success, and rolls back both on error. This ensures transaction
    integrity regardless of which session pattern routes use.

    Includes retry logic with exponential backoff for transient database errors
    such as connection resets, lock timeouts, and deadlocks.

    Can be used with or without parentheses:
        @transactional
        def my_route(): ...

        @transactional(max_retries=5, base_delay=1.0)
        def my_route(): ...

    Args:
        f: The function to be wrapped (when used without parentheses).
        max_retries: Maximum number of retry attempts for transient errors (default: 3).
        base_delay: Base delay in seconds for exponential backoff (default: 0.5).

    Returns:
        The wrapped function with transaction management and retry logic.
    """
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    # Commit both session patterns to ensure all changes are persisted
                    # Routes may use either g.db_session or db.session inconsistently
                    if hasattr(g, 'db_session') and g.db_session:
                        g.db_session.commit()
                    # Also commit Flask-SQLAlchemy's scoped session
                    db.session.commit()
                    return result

                except (OperationalError, InterfaceError) as e:
                    last_exception = e
                    _safe_rollback()

                    # Check if this is a retryable error and we have retries left
                    if not is_retryable_error(e) or attempt >= max_retries:
                        current_app.logger.exception(
                            "Non-retryable database error in %s after %d attempts",
                            func.__name__, attempt + 1
                        )
                        raise

                    # Invalidate connection if it appears broken
                    _invalidate_connection_if_needed(e)

                    # Calculate delay with exponential backoff and jitter
                    delay = base_delay * (2 ** attempt) * (0.5 + random.random())
                    logger.warning(
                        "Retrying %s after %.2fs (attempt %d/%d) due to: %s",
                        func.__name__, delay, attempt + 1, max_retries, str(e)[:100]
                    )
                    time.sleep(delay)

                except Exception as e:
                    _safe_rollback()
                    current_app.logger.exception("Error in transactional function %s", func.__name__)
                    raise

            # Should not reach here, but if we do, raise the last exception
            if last_exception:
                raise last_exception

        return wrapped

    # Support both @transactional and @transactional() and @transactional(max_retries=5)
    if f is not None:
        # Called without parentheses: @transactional
        return decorator(f)
    else:
        # Called with parentheses: @transactional() or @transactional(max_retries=5)
        return decorator


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