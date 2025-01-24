# app/core/session_manager.py

from flask import g, current_app
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
    """Global session manager for consistent transaction handling"""
    if hasattr(g, 'db_session'):
        session = g.db_session
    else:
        session = current_app.SessionLocal()

    try:
        session.execute(text("SET LOCAL statement_timeout = '10s'"))
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Session error: {e}")
        session.rollback()
        raise
    finally:
        if not hasattr(g, 'db_session'):
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
