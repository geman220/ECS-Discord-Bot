# app/sql_log.py

"""
SQL Log Module

This module sets up SQLAlchemy event listeners to log important session and
engine events, such as commits, rollbacks, flushes, SQL execution, and transaction endings.
This is useful for debugging and monitoring database operations.
"""

import logging
import traceback

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

# Configure logging for SQL events.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('sqlalchemy')


@event.listens_for(Session, 'after_commit')
def after_commit(session):
    """
    Log a message after a session commit.
    """
    logger.info(f"Session {session} committed.")
    logger.debug(''.join(traceback.format_stack()))


@event.listens_for(Session, 'after_rollback')
def after_rollback(session):
    """
    Log a message after a session rollback.
    """
    logger.info(f"Session {session} rolled back.")
    logger.debug(''.join(traceback.format_stack()))


@event.listens_for(Session, 'after_flush')
def after_flush(session, flush_context):
    """
    Log a message after a session flush.
    """
    logger.info(f"Session {session} flushed.")
    logger.debug(''.join(traceback.format_stack()))


@event.listens_for(Engine, 'before_cursor_execute')
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """
    Log the SQL statement and its parameters before execution.
    """
    logger.info(f"Running SQL: {statement}")
    logger.debug(f"Parameters: {parameters}")
    logger.debug(''.join(traceback.format_stack()))


@event.listens_for(Session, 'after_transaction_end')
def after_transaction_end(session, transaction):
    """
    Log a message after a transaction ends for a session.
    """
    logger.info(f"Transaction ended for session {session}.")
    logger.debug(''.join(traceback.format_stack()))