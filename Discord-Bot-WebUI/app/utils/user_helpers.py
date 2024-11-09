# app/utils/user_helpers.py
from flask_login import current_user
from werkzeug.local import LocalProxy
from sqlalchemy.orm.exc import DetachedInstanceError
from app.extensions import db
from app.db_management import db_manager
import logging

logger = logging.getLogger(__name__)

def _get_safe_user():
    """Retrieve current_user, attaching to session if detached."""
    from app.models import User
    try:
        with db_manager.session_scope(nested=True):  # Use nested since this might be called within another session
            # Use current_user directly to avoid recursion
            return db.session.merge(current_user) if db.session.is_active else None
    except DetachedInstanceError:
        logger.warning("current_user is detached. Re-fetching.")
        with db_manager.session_scope(nested=True):
            return User.query.get(current_user.id) if current_user.is_authenticated else None

# Create a LocalProxy for safe current user access
safe_current_user = LocalProxy(_get_safe_user)