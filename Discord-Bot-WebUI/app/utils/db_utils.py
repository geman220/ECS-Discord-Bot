# app/utils/db_utils.py

from functools import wraps
from flask import g, current_app
from app.core import celery
import logging

logger = logging.getLogger(__name__)

def transactional(f):
    """
    Decorator to manage database transactions in request context.
    Relies on g.db_session being set in request context.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        session = getattr(g, 'db_session', None)
        if session is None:
            # If no db_session is available, raise an error or handle gracefully.
            # This decorator is meant for request-bound functions.
            raise RuntimeError("No database session available. Ensure this code runs within a request context.")

        try:
            result = f(*args, **kwargs)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            logger.error(f"Error in transactional function {f.__name__}: {e}", exc_info=True)
            raise
    return wrapped

def celery_transactional_task(**task_kwargs):
    """
    Decorator to manage database transactions in Celery tasks.
    Creates a new session from app.SessionLocal for each task run.
    """
    def decorator(f):
        @celery.task(**task_kwargs)
        @wraps(f)
        def wrapped(*args, **kwargs):
            app = celery.flask_app
            with app.app_context():
                session = app.SessionLocal()
                try:
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
