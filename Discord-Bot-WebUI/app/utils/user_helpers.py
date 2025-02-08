# app/utils/user_helpers.py
from flask_login import current_user
from werkzeug.local import LocalProxy
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.orm import joinedload
from flask import has_app_context, g
from functools import wraps
import logging

logger = logging.getLogger(__name__)

class UserWrapper:
    """Wrapper to ensure user methods are always available"""
    def __init__(self, user=None):
        self._user = user
        
    def __getattr__(self, name):
        if self._user is None:
            # Default values for common attributes
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
            # Default method responses
            if name == 'has_permission':
                return lambda *args, **kwargs: False
            if name == 'has_role':
                return lambda *args, **kwargs: False
            return None
        return getattr(self._user, name)

def get_user():
    """
    Get current user with coordinated session handling.
    Uses the request-scoped session from g.db_session.
    """
    if not has_app_context():
        return UserWrapper()
        
    try:
        if hasattr(g, '_safe_current_user'):
            return g._safe_current_user

        if not current_user.is_authenticated:
            user = UserWrapper()
        else:
            session = getattr(g, 'db_session', None)
            if session is None:
                logger.error("No database session available to load authenticated user.")
                user = UserWrapper()
            else:
                from app.models import User, Role, Player
                # Eagerly load relationships that are frequently used.
                db_user = session.query(User).options(
                    joinedload(User.roles).joinedload(Role.permissions),
                    joinedload(User.player)
                ).get(current_user.id)
                # Do not detach so lazy-loading works if additional attributes are accessed.
                user = UserWrapper(db_user)
        g._safe_current_user = user
        return user
    except Exception as e:
        logger.error(f"Error getting safe user: {e}", exc_info=True)
        return UserWrapper()

# Create LocalProxy for lazy loading of user
safe_current_user = LocalProxy(get_user)

def cleanup_user_data():
    """Cleanup function to be called at end of request"""
    try:
        if hasattr(g, '_safe_current_user'):
            delattr(g, '_safe_current_user')
    except Exception as e:
        logger.error(f"Error cleaning up user data: {e}", exc_info=True)

def with_safe_user():
    """Decorator to ensure safe user access in views"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cleanup_user_data()  # Ensure fresh start
            try:
                return f(*args, **kwargs)
            finally:
                cleanup_user_data()  # Cleanup after view
        return decorated_function
    return decorator
