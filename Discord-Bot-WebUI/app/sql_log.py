from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine
import logging
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('sqlalchemy')

@event.listens_for(Session, 'after_commit')
def after_commit(session):
    logger.info(f"Session {session} committed.")
    logger.debug(''.join(traceback.format_stack()))

@event.listens_for(Session, 'after_rollback')
def after_rollback(session):
    logger.info(f"Session {session} rolled back.")
    logger.debug(''.join(traceback.format_stack()))

@event.listens_for(Session, 'after_flush')
def after_flush(session, flush_context):
    logger.info(f"Session {session} flushed.")
    logger.debug(''.join(traceback.format_stack()))

@event.listens_for(Engine, 'before_cursor_execute')
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    logger.info(f"Running SQL: {statement}")
    logger.debug(f"Parameters: {parameters}")
    logger.debug(''.join(traceback.format_stack()))

@event.listens_for(Session, 'after_transaction_end')
def after_transaction_end(session, transaction):
    logger.info(f"Transaction ended for session {session}.")
    logger.debug(''.join(traceback.format_stack()))
