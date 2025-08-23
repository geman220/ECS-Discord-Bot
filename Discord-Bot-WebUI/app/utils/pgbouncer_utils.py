"""
PgBouncer compatibility utilities.

This module provides utilities for detecting and handling PgBouncer connections,
which have limitations compared to direct PostgreSQL connections.
"""

import os
import logging
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def is_using_pgbouncer(engine_or_session):
    """
    Check if the connection is through PgBouncer.
    
    Args:
        engine_or_session: SQLAlchemy Engine or Session object
        
    Returns:
        bool: True if using PgBouncer, False otherwise
    """
    try:
        if isinstance(engine_or_session, Session):
            url = str(engine_or_session.bind.url)
        elif isinstance(engine_or_session, Engine):
            url = str(engine_or_session.url)
        else:
            # Check environment variable as fallback
            url = os.getenv('DATABASE_URL', '')
            
        return 'pgbouncer' in url.lower() or ':6432' in url
    except Exception as e:
        logger.warning(f"Error checking for PgBouncer: {e}")
        return False


def set_session_timeout(session, statement_timeout_seconds=None, idle_timeout_seconds=None):
    """
    Set session timeouts if not using PgBouncer.
    
    PgBouncer doesn't support SET LOCAL commands, so we skip them when detected.
    
    Args:
        session: SQLAlchemy Session object
        statement_timeout_seconds: Statement timeout in seconds
        idle_timeout_seconds: Idle in transaction timeout in seconds
    """
    if is_using_pgbouncer(session):
        # Session timeout configuration skipped for PgBouncer
        pass
        return
        
    try:
        if statement_timeout_seconds:
            session.execute(text(f"SET statement_timeout = '{statement_timeout_seconds}s'"))
            
        if idle_timeout_seconds:
            session.execute(text(f"SET idle_in_transaction_session_timeout = '{idle_timeout_seconds}s'"))
            
    except Exception as e:
        # Log but don't fail - connection might still be usable
        logger.warning(f"Could not set session timeouts: {e}")


def execute_with_pgbouncer_fallback(session, statement, fallback_statement=None):
    """
    Execute a statement with a fallback for PgBouncer compatibility.
    
    Args:
        session: SQLAlchemy Session object
        statement: Primary SQL statement to execute
        fallback_statement: Optional fallback statement for PgBouncer
        
    Returns:
        Result of the executed statement
    """
    try:
        return session.execute(statement)
    except Exception as e:
        if is_using_pgbouncer(session) and fallback_statement:
            # Using PgBouncer fallback statement
            pass
            return session.execute(fallback_statement)
        raise