# app/sockets/session.py

"""
Session management for WebSocket interactions.

This module provides a context manager to create and manage a SQLAlchemy session
bound to a given engine specifically for WebSocket-related operations. It sets
a local statement timeout, commits the session on successful completion, and
rolls back in case of errors.
"""

from contextlib import contextmanager
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

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
        # Set a local statement timeout of 5 seconds.
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()