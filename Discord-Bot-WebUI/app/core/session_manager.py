# app/core/session_manager.py

from flask import g, current_app, has_request_context
from contextlib import contextmanager
import logging
from sqlalchemy import text
from app.core import db
from app.utils.pgbouncer_utils import set_session_timeout

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
        # Automatically skipped for PgBouncer connections
        set_session_timeout(session, statement_timeout_seconds=10)
        yield session
        session.commit()
    except Exception as e:
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
        
    if hasattr(g, 'db_session'):
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
