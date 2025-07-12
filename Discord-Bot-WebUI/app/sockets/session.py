# app/sockets/session.py

"""
Session management for WebSocket interactions.

This module provides a context manager to create and manage a SQLAlchemy session
bound to a given engine specifically for WebSocket-related operations. It sets
a local statement timeout, commits the session on successful completion, and
rolls back in case of errors.
"""

import logging
from contextlib import contextmanager
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.utils.pgbouncer_utils import set_session_timeout

logger = logging.getLogger(__name__)

# Create a session factory that prevents expiration of objects on commit.
SessionLocal = sessionmaker(expire_on_commit=False)

@contextmanager
def socket_session(engine):
    """
    Provide a transactional scope for WebSocket operations.

    This context manager creates a session bound to the specified engine, sets a local
    statement timeout to 5 seconds to prevent hanging queries, yields the session for
    database operations, and commits the transaction if successful. If an error occurs,
    it rolls back the transaction and re-raises the exception. The session is closed
    in all cases.

    :param engine: The SQLAlchemy engine to which the session should be bound.
    :yield: A SQLAlchemy session.
    """
    session = SessionLocal(bind=engine)
    try:
        # Increased timeouts for 2 CPU / 4GB RAM environment
        # Automatically skipped for PgBouncer connections
        set_session_timeout(session, statement_timeout_seconds=10, idle_timeout_seconds=15)
        yield session
        try:
            session.commit()
        except Exception as commit_error:
            logger.warning(f"Error committing session in socket_session: {commit_error}")
            try:
                session.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")
            raise
    except Exception:
        try:
            session.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {rollback_error}")
        raise
    finally:
        try:
            if session:
                session.close()
        except Exception as close_error:
            logger.error(f"Error closing session: {close_error}")