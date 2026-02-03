# app/utils/user_locking.py

"""
User Locking Utilities Module

This module provides utilities for acquiring row-level locks on User records
during role modifications to prevent lock contention and race conditions.

Key features:
- Pessimistic locking with SELECT FOR UPDATE
- Context manager for automatic lock release
- Support for NOWAIT to fail fast when lock is unavailable
- Proper integration with Flask's g.db_session and db.session patterns

Note: We intentionally do NOT use joinedload with FOR UPDATE because PostgreSQL
does not support FOR UPDATE on the nullable side of LEFT OUTER JOINs. Instead,
we lock the user row first, then trigger lazy loading of relationships.
"""

import logging
from contextlib import contextmanager

from flask import g, has_request_context
from sqlalchemy.exc import OperationalError

from app.core import db
from app.models import User

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """
    Raised when a lock cannot be acquired on a user record.

    This typically occurs when:
    - Another request is already modifying the user's roles
    - The user record does not exist
    - A database timeout occurred while waiting for the lock
    """
    pass


def get_session():
    """
    Get the appropriate database session for the current context.

    Returns g.db_session if available (Flask request context),
    otherwise falls back to db.session.
    """
    if has_request_context() and hasattr(g, 'db_session') and g.db_session:
        return g.db_session
    return db.session


@contextmanager
def lock_user_for_role_update(user_id, session=None, nowait=True, timeout=None):
    """
    Context manager to acquire a row-level lock on a User for role modifications.

    This ensures that concurrent requests modifying the same user's roles are
    serialized, preventing lock contention on the user_roles table.

    Args:
        user_id: The ID of the user to lock.
        session: Optional database session to use. Defaults to g.db_session or db.session.
        nowait: If True (default), fail immediately if lock is unavailable.
                If False, wait for the lock (potentially blocking).
        timeout: Optional timeout in seconds when nowait=False. Not all databases
                 support this (PostgreSQL does via statement_timeout).

    Yields:
        User: The locked User object with player and roles relationships loaded.

    Raises:
        LockAcquisitionError: If the lock cannot be acquired (user not found,
                              lock unavailable, or timeout).

    Example:
        try:
            with lock_user_for_role_update(user_id, session=db_session) as user:
                user.roles.remove(old_role)
                user.roles.append(new_role)
                db_session.flush()
        except LockAcquisitionError:
            return jsonify({'success': False, 'message': 'User is being modified'}), 409
    """
    if session is None:
        session = get_session()

    try:
        # IMPORTANT: Do NOT use joinedload with FOR UPDATE!
        # PostgreSQL does not support FOR UPDATE on LEFT OUTER JOINs
        # (which joinedload creates for nullable relationships like User.player)
        #
        # Instead, we lock the user row first, then access relationships after.
        # SQLAlchemy will lazy-load them within the same transaction.
        query = session.query(User).filter(User.id == user_id)

        # Apply the FOR UPDATE lock
        # nowait=True: Fail immediately if another transaction holds the lock
        # nowait=False: Wait for the lock to be released
        query = query.with_for_update(nowait=nowait)

        user = query.first()

        if user is None:
            raise LockAcquisitionError(f"User {user_id} not found")

        # Explicitly load the relationships we need within the lock
        # This triggers lazy loading but keeps it within the transaction
        _ = user.roles  # Load roles collection
        _ = user.player  # Load player (may be None)

        logger.debug(f"Acquired lock on user {user_id}")

        yield user

        logger.debug(f"Released lock on user {user_id}")

    except OperationalError as e:
        error_str = str(e).lower()
        # PostgreSQL error messages for lock failures
        if any(pattern in error_str for pattern in [
            'could not obtain lock',
            'lock not available',
            'nowait is set',
            'lock timeout',
            'canceling statement due to lock timeout',
        ]):
            logger.warning(f"Lock acquisition failed for user {user_id}: {e}")
            raise LockAcquisitionError(
                f"User {user_id} is currently being modified by another request"
            ) from e
        # Re-raise other operational errors
        raise


@contextmanager
def lock_users_for_role_update(user_ids, session=None, nowait=True):
    """
    Context manager to acquire row-level locks on multiple Users.

    Locks are acquired in a consistent order (sorted by user_id) to prevent
    deadlocks when multiple requests try to lock overlapping sets of users.

    Args:
        user_ids: List of user IDs to lock.
        session: Optional database session. Defaults to g.db_session or db.session.
        nowait: If True (default), fail immediately if any lock is unavailable.

    Yields:
        dict: Mapping of user_id to locked User object.

    Raises:
        LockAcquisitionError: If any lock cannot be acquired.

    Example:
        try:
            with lock_users_for_role_update([1, 2, 3]) as locked_users:
                for user_id, user in locked_users.items():
                    user.approval_status = 'approved'
        except LockAcquisitionError as e:
            # Handle lock failure - some users couldn't be locked
            pass
    """
    if session is None:
        session = get_session()

    # Sort user IDs to ensure consistent lock ordering across requests
    # This prevents deadlocks when multiple requests lock overlapping user sets
    sorted_ids = sorted(set(user_ids))

    if not sorted_ids:
        yield {}
        return

    try:
        # Query all users with FOR UPDATE, locked in order
        # IMPORTANT: Do NOT use joinedload - PostgreSQL doesn't support
        # FOR UPDATE on LEFT OUTER JOINs
        users = session.query(User).filter(
            User.id.in_(sorted_ids)
        ).order_by(
            User.id
        ).with_for_update(nowait=nowait).all()

        # Build the result dictionary
        locked_users = {user.id: user for user in users}

        # Check if all requested users were found
        missing_ids = set(sorted_ids) - set(locked_users.keys())
        if missing_ids:
            raise LockAcquisitionError(
                f"Users not found: {sorted(missing_ids)}"
            )

        # Load relationships for all locked users within the transaction
        for user in users:
            _ = user.roles  # Trigger lazy load
            _ = user.player  # Trigger lazy load

        logger.debug(f"Acquired locks on {len(locked_users)} users")

        yield locked_users

        logger.debug(f"Released locks on {len(locked_users)} users")

    except OperationalError as e:
        error_str = str(e).lower()
        if any(pattern in error_str for pattern in [
            'could not obtain lock',
            'lock not available',
            'nowait is set',
            'lock timeout',
        ]):
            logger.warning(f"Lock acquisition failed for users {sorted_ids}: {e}")
            raise LockAcquisitionError(
                f"One or more users are currently being modified by another request"
            ) from e
        raise
