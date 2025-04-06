# app/core/helpers.py

"""
Core Helper Utilities.

This module provides helper functions that are used across the application:
- get_match: Retrieves MLSMatch instances using either internal ID or ESPN match_id
- find_orphaned_sessions: Identifies potentially leaked database sessions
- terminate_orphaned_session: Safely terminates specific orphaned sessions
- cleanup_orphaned_sessions: Automatically detects and cleans up orphaned sessions

These utilities help maintain database integrity and prevent resource leaks.

Example:
    from app.core.helpers import get_match, cleanup_orphaned_sessions
    match = get_match(session, identifier)
    cleanup_results = cleanup_orphaned_sessions(session)
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import or_, text
from sqlalchemy.exc import SQLAlchemyError
from flask import current_app

from app.models import MLSMatch

logger = logging.getLogger(__name__)

def get_match(session, identifier) -> MLSMatch:
    """
    Retrieve an MLSMatch using either the internal id (if identifier is numeric)
    or the ESPN match_id (always stored as a string).

    This helper function attempts to convert the provided identifier to an integer.
    If successful, it adds a filter to check if the internal primary key (id) matches.
    It also always checks whether the ESPN match_id (stored as a string) matches
    the string representation of the identifier. This dual filtering ensures that
    the function works regardless of which unique identifier is provided.

    :param session: The SQLAlchemy session object used for querying the database.
    :param identifier: A unique identifier for the match, which can be either the
                       internal primary key (integer) or the ESPN match_id (string).
    :return: An instance of MLSMatch if found; otherwise, None.
    """
    try:
        numeric_id = int(identifier)
    except (ValueError, TypeError):
        numeric_id = None

    filters = []
    if numeric_id is not None:
        filters.append(MLSMatch.id == numeric_id)
    # Always check match_id as a string.
    filters.append(MLSMatch.match_id == str(identifier))
    
    return session.query(MLSMatch).filter(or_(*filters)).first()


def find_orphaned_sessions(session, minutes=30):
    """
    Find database sessions that have been idle for too long and might be orphaned.
    
    Args:
        session: Database session to use for the query.
        minutes: Time threshold in minutes for considering a session orphaned.
        
    Returns:
        A list of session information dictionaries.
    """
    try:
        # Query for idle sessions that have been open for longer than the threshold
        query = text("""
            SELECT 
                pid, 
                usename,
                application_name,
                client_addr,
                backend_start,
                xact_start,
                query_start,
                state_change,
                state,
                EXTRACT(EPOCH FROM (NOW() - state_change)) as idle_seconds,
                query
            FROM 
                pg_stat_activity 
            WHERE 
                state = 'idle in transaction'
                AND state_change < NOW() - INTERVAL :minutes MINUTE
            ORDER BY 
                idle_seconds DESC;
        """)
        
        results = []
        for row in session.execute(query, {"minutes": minutes}).mappings():
            results.append(dict(row))
        
        logger.info(f"Found {len(results)} potentially orphaned database sessions")
        return results
    except Exception as e:
        logger.error(f"Error finding orphaned sessions: {e}", exc_info=True)
        return []


def terminate_orphaned_session(session, pid):
    """
    Terminate a specific database session by its process ID.
    
    Args:
        session: Database session to use for the termination.
        pid: Process ID of the session to terminate.
        
    Returns:
        Boolean indicating success or failure.
    """
    try:
        result = session.execute(
            text("SELECT pg_terminate_backend(:pid)"),
            {"pid": pid}
        ).scalar()
        
        session.commit()
        
        if result:
            logger.info(f"Successfully terminated database session {pid}")
        else:
            logger.warning(f"Failed to terminate database session {pid}")
        
        return result
    except Exception as e:
        logger.error(f"Error terminating database session {pid}: {e}", exc_info=True)
        session.rollback()
        return False


def cleanup_orphaned_sessions(session=None, minutes=60):
    """
    Find and terminate database sessions that appear to be orphaned.
    
    Args:
        session: Database session to use. If None, creates a new one.
        minutes: Time threshold in minutes for considering a session orphaned.
        
    Returns:
        Dictionary with cleanup results.
    """
    new_session = False
    try:
        if session is None:
            app = current_app._get_current_object()
            session = app.SessionLocal()
            new_session = True
        
        orphaned_sessions = find_orphaned_sessions(session, minutes)
        terminated_count = 0
        
        for orphan in orphaned_sessions:
            pid = orphan["pid"]
            idle_time = orphan["idle_seconds"] / 60
            
            if idle_time > minutes:
                logger.warning(
                    f"Terminating orphaned session: PID={pid}, "
                    f"Idle time={idle_time:.1f} minutes, "
                    f"Query: {orphan['query'][:100]}"
                )
                
                if terminate_orphaned_session(session, pid):
                    terminated_count += 1
        
        result = {
            "found": len(orphaned_sessions),
            "terminated": terminated_count,
            "threshold_minutes": minutes
        }
        
        if new_session:
            session.commit()
        
        return result
    except Exception as e:
        logger.error(f"Error cleaning up orphaned sessions: {e}", exc_info=True)
        if new_session and session:
            session.rollback()
        return {
            "error": str(e),
            "found": 0,
            "terminated": 0
        }
    finally:
        if new_session and session:
            session.close()
