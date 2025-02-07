# app/utils/db_utils.py

from functools import wraps
from flask import g, current_app
from app.core import celery, db
import logging

logger = logging.getLogger(__name__)

def transactional(f):
    """
    Decorator to manage database transactions.
    Commits on success and rolls back on error.
    Uses the Flask‑SQLAlchemy db.session, which is automatically
    removed at the end of the request.
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
