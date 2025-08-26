# app/utils/user_helpers.py

"""
User Helpers Module

This module provides helper functions and a wrapper class for safely accessing the current
user within a Flask application. It uses a UserWrapper to supply default values for user 
attributes and ensures that database sessions are coordinated via the request context.
A LocalProxy is used to lazily load the current user.
"""

import logging
from flask_login import current_user
from werkzeug.local import LocalProxy
from sqlalchemy.orm import joinedload, selectinload
from flask import has_app_context, g
from functools import wraps

from app.models import User, Role

logger = logging.getLogger(__name__)


class UserWrapper:
    """
    Wrapper class for user objects to ensure that common user attributes and methods are always available.

    When no user is provided, default values are returned for attributes such as authentication
    status, active state, and roles.
    """
    def __init__(self, user=None):
        self._user = user

    def __getattr__(self, name):
        # If no underlying user is set, return safe default values for common attributes.
        if self._user is None:
            if name == 'is_authenticated':
                return False
            if name == 'is_active':
                return False
            if name == 'is_anonymous':
                return True
            if name == 'has_completed_onboarding':
                return False
            if name == 'has_skipped_profile_creation':
                return False
            if name == 'roles':
                return []
            # Default method responses for permission checking.
            if name == 'has_permission':
                return lambda *args, **kwargs: False
            if name == 'has_role':
                return lambda *args, **kwargs: False
            return None
        # Otherwise, delegate attribute access to the underlying user object.
        return getattr(self._user, name)


def get_user():
    """
    Retrieve the current user with coordinated session handling.

    This function attempts to use a request-scoped database session (g.db_session) to 
    eagerly load additional relationships for the authenticated user. If no user is authenticated
    or if there is no session available, a UserWrapper with default values is returned.

    Returns:
        A UserWrapper instance wrapping the current user or providing safe defaults.
    """
    # If there's no application context, return a safe user wrapper.
    if not has_app_context():
        return UserWrapper()

    try:
        # Return cached safe user if available.
        if hasattr(g, '_safe_current_user'):
            return g._safe_current_user

        if not current_user.is_authenticated:
            user = UserWrapper()
        else:
            # Check if we're in degraded mode (no session due to pool exhaustion)
            if hasattr(g, '_session_creation_failed') and g._session_creation_failed:
                logger.debug("Using minimal user wrapper - in degraded mode due to database pool exhaustion")
                user = UserWrapper()
            else:
                session = getattr(g, 'db_session', None)
                if session is None:
                    logger.error("No database session available to load authenticated user.")
                    user = UserWrapper()
                else:
                    # Import user-related models; eager-load frequently used relationships.
                    from app.models import Player, Team
                    db_user = session.query(User).options(
                        selectinload(User.roles).selectinload(Role.permissions),
                        selectinload(User.player).selectinload(Player.teams)
                    ).get(current_user.id)
                    # Wrap the user; do not detach to allow lazy loading of additional attributes.
                    user = UserWrapper(db_user)
        g._safe_current_user = user
        return user
    except Exception as e:
        logger.error(f"Error getting safe user: {e}", exc_info=True)
        return UserWrapper()


# Create a LocalProxy for lazy loading of the safe current user.
safe_current_user = LocalProxy(get_user)


def cleanup_user_data():
    """
    Cleanup function to be called at the end of a request.

    This function removes the cached safe current user from the Flask 'g' object.
    """
    try:
        if hasattr(g, '_safe_current_user'):
            delattr(g, '_safe_current_user')
    except Exception as e:
        logger.error(f"Error cleaning up user data: {e}", exc_info=True)


def with_safe_user():
    """
    Decorator to ensure safe user access in Flask view functions.

    The decorator clears any cached user data before and after the view function executes,
    ensuring that each request starts with a fresh user context.

    Returns:
        A decorator that wraps a view function.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cleanup_user_data()  # Ensure a fresh user is loaded.
            try:
                return f(*args, **kwargs)
            finally:
                cleanup_user_data()  # Clean up after view execution.
        return decorated_function
    return decorator