# app/core/session_manager.py

from flask import g, current_app, has_request_context
from contextlib import contextmanager
import logging
# Import the text function from SQLAlchemy
from sqlalchemy import text
from app.core import db

logger = logging.getLogger(__name__)

# Expose SQLAlchemy components
Table = db.Table
Column = db.Column
ForeignKey = db.ForeignKey
relationship = db.relationship

@contextmanager
def managed_session():
    """Global session manager for consistent transaction handling."""
    if has_request_context() and hasattr(g, 'db_session'):
        session = g.db_session
        use_global = True
    else:
        session = current_app.SessionLocal()
        use_global = False

    try:
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
    if hasattr(g, 'db_session'):
        try:
            if exception:
                g.db_session.rollback()
            else:
                g.db_session.commit()
        finally:
            g.db_session.close()
            delattr(g, 'db_session')
