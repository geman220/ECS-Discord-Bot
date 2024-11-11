# app/utils/db_utils.py

from functools import wraps
from app.core import db, celery
import logging

logger = logging.getLogger(__name__)

def transactional(f):
    """Decorator to manage database transactions."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            db.session.commit()
            return result
        except Exception as e:
            db.session.rollback()
            logger.error(f"Database transaction failed in {f.__name__}: {e}", exc_info=True)
            # Optionally, re-raise the exception or handle it as needed
            raise
    return wrapped

def celery_transactional_task(**task_kwargs):
    """Decorator to manage database transactions in Celery tasks."""
    def decorator(f):
        @celery.task(**task_kwargs)
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                result = f(*args, **kwargs)
                db.session.commit()  # Commit the transaction
                return result
            except Exception as e:
                db.session.rollback()  # Rollback on exception
                logger.error(f"Celery task '{f.__name__}' failed: {e}", exc_info=True)
                raise
            finally:
                db.session.remove()  # Remove the session to avoid leaks
        return wrapped
    return decorator