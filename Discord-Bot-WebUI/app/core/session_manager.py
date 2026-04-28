# app/core/session_manager.py

from flask import g, current_app, has_request_context
from contextlib import contextmanager
import logging
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from app.core import db
from app.utils.pgbouncer_utils import set_session_timeout

try:
    from celery.exceptions import Retry as CeleryRetry
except ImportError:
    CeleryRetry = ()

logger = logging.getLogger(__name__)

# Expose frequently used SQLAlchemy components from our DB instance
Table = db.Table
Column = db.Column
ForeignKey = db.ForeignKey
relationship = db.relationship


_TRANSIENT_DB_ERROR_STRINGS = (
    'server closed the connection',
    'PGRES_TUPLES_OK and no message',
    'SSL connection has been closed',
    'Connection refused',
    'could not translate host name',
    'Name or service not known',
    'could not connect to server',
)


def is_transient_db_disconnect(exc) -> bool:
    """
    Return True if `exc` looks like a transient DB connection drop
    (pool will recover on next checkout via pre_ping).

    Used to downgrade ERROR-level traceback spam to WARNING when the
    underlying cause is a brief network/DNS blip rather than a real bug.
    """
    if not isinstance(exc, (OperationalError, DBAPIError)):
        return False
    if getattr(exc, 'connection_invalidated', False):
        return True
    msg = str(exc)
    return any(s in msg for s in _TRANSIENT_DB_ERROR_STRINGS)


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
        # Automatically skipped for PgBouncer connections
        set_session_timeout(session, statement_timeout_seconds=10)
        yield session
        session.commit()
    except Exception as e:
        # Celery's Retry is a control-flow signal, not a DB error. Roll back
        # and re-raise silently so the task can be rescheduled.
        if CeleryRetry and isinstance(e, CeleryRetry):
            try:
                session.rollback()
            except Exception:
                pass
            raise
        # Downgrade transient connection drops to WARNING — the pool's
        # pre_ping + invalidation handles recovery on the next checkout,
        # and ERROR-level spam here masks real problems.
        if is_transient_db_disconnect(e):
            logger.warning(f"Transient DB connection drop: {e.__class__.__name__}")
            try:
                # Force SQLAlchemy to discard this connection from the pool
                session.invalidate()
            except Exception:
                pass
        else:
            logger.error(f"Session error: {e}")
        try:
            session.rollback()
        except Exception as rollback_error:
            # If rollback fails (e.g., due to PGBouncer DISCARD ALL error),
            # just log and continue - the session will be closed anyway
            logger.warning(f"Rollback failed (non-critical): {rollback_error}")
        raise
    finally:
        if not use_global:
            try:
                # Force close the connection to prevent leaks
                session.close()
                # DO NOT dispose the engine/connection pool - this destroys the entire pool!
                # session.bind.dispose() was causing massive memory issues
            except Exception as e:
                logger.error(f"Error closing session: {e}")


def cleanup_request(exception=None):
    """
    Clean up the database session after a request is finished.
    
    This function commits the session if no exception occurred, otherwise it rolls back
    the session. Finally, it closes the session and removes it from the request context.
    
    :param exception: An optional exception that occurred during the request.
    """
    # Skip cleanup if session creation failed (degraded mode)
    if hasattr(g, '_session_creation_failed') and g._session_creation_failed:
        logger.debug("Skipping session cleanup - request was in degraded mode (no session created)")
        return
        
    if hasattr(g, 'db_session') and g.db_session is not None:
        # Generate a session ID for logging
        session_id = str(id(g.db_session))
        
        # Get the request details for logging
        from flask import request
        endpoint = getattr(request, 'endpoint', 'unknown')
        url = getattr(request, 'url', 'unknown')
        
        # Import session monitor
        from app.utils.session_monitor import get_session_monitor
        monitor = get_session_monitor()
        
        # Track if we're doing cleanup in an error state
        status = 'normal'
        if exception:
            status = 'exception'
        
        try:
            logger.debug(f"Cleaning up request session {session_id} for {endpoint} (URL: {url})")
            
            if exception:
                logger.debug(f"Rolling back session {session_id} due to exception: {exception}")
                g.db_session.rollback()
                monitor.register_session_rollback(session_id)
            else:
                logger.debug(f"Committing session {session_id}")
                g.db_session.commit()
                monitor.register_session_commit(session_id)
                
        except Exception as e:
            status = 'cleanup-error'
            logger.error(f"Error during session cleanup for {session_id}: {e}", exc_info=True)
            # Try to roll back in case commit failed
            try:
                g.db_session.rollback()
                monitor.register_session_rollback(session_id)
            except:
                pass
        finally:
            try:
                # Close the session without trying to access the connection
                # The pool's checkin event handler will handle connection cleanup
                logger.debug(f"Closing session {session_id} (status: {status})")
                g.db_session.close()
                monitor.register_session_close(session_id)
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {e}", exc_info=True)
            finally:
                delattr(g, 'db_session')
