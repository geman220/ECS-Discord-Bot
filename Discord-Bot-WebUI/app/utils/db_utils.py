# app/utils/db_utils.py

from functools import wraps
from app.core import celery
from flask import has_app_context
from app.db_management import db_manager
import logging

logger = logging.getLogger(__name__)

def transactional(f):
    """Decorator to manage database transactions."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        with db_manager.session_scope(transaction_name="transactional"):
            return f(*args, **kwargs)
    return wrapped

def celery_transactional_task(**task_kwargs):
    """Decorator to manage database transactions in Celery tasks with app context."""
    def decorator(f):
        @celery.task(**task_kwargs)
        @wraps(f)
        def wrapped(*args, **kwargs):
            app = celery.flask_app
            with app.app_context():
                with db_manager.session_scope(transaction_name="celery_transactional"):
                    return f(*args, **kwargs)
        return wrapped
    return decorator