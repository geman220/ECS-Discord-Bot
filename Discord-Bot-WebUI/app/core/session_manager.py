# app/core/session_manager.py

from flask import g, current_app, has_request_context
from contextlib import contextmanager
import logging
from sqlalchemy import text
from app.core import db

logger = logging.getLogger(__name__)

# Expose frequently used SQLAlchemy components from our DB instance
Table = db.Table
Column = db.Column
ForeignKey = db.ForeignKey
relationship = db.relationship


@contextmanager
def managed_session():
    """
    Context manager for a database session that ensures proper transaction handling.
    
    If a request context is active and a session already exists on `g`, that session
    is used. Otherwise, a new session is created from the application's SessionLocal.
    
    The session sets a local statement timeout of 10 seconds before yielding.
    On exit, the session is committed, or in case of an exception, rolled back.
    """
    if has_request_context() and hasattr(g, 'db_session'):
        session = g.db_session
        use_global = True
    else:
        session = current_app.SessionLocal()
        use_global = False

    try:
        # Set a local statement timeout of 10 seconds for this session.
        session.execute(text("SET LOCAL statement_timeout = '10s'"))
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Session error: {e}")
        session.rollback()
        raise
    finally:
        if not use_global:
            session.close()


def cleanup_request(exception=None):
    """
    Clean up the database session after a request is finished.
    
    This function commits the session if no exception occurred, otherwise it rolls back
    the session. Finally, it closes the session and removes it from the request context.
    
    :param exception: An optional exception that occurred during the request.
    """
    if hasattr(g, 'db_session'):
        try:
            if exception:
                g.db_session.rollback()
            else:
                g.db_session.commit()
        finally:
            g.db_session.close()
            delattr(g, 'db_session')
