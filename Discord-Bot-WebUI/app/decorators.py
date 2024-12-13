# app/decorators.py
from functools import wraps
from datetime import datetime
from flask import flash, redirect, url_for, abort, jsonify, current_app, has_app_context, g
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from contextlib import contextmanager, asynccontextmanager
from sqlalchemy.exc import SQLAlchemyError
from app.utils.user_helpers import safe_current_user
from typing import Any, Callable
import logging
import inspect
import threading
import uuid
from celery import shared_task

from app.core import db, celery

logger = logging.getLogger(__name__)

def is_flask_view_function(f):
    """Helper to detect Flask view functions."""
    return (hasattr(f, 'view_function') or
            hasattr(f, '_is_view') or
            hasattr(f, '__blueprinted__') or
            hasattr(f, '_blueprint_name') or
            hasattr(f, 'endpoint'))

def log_context_state(location: str):
    """Helper to log detailed context state."""
    has_context = has_app_context()
    frame = inspect.currentframe()
    caller = inspect.getouterframes(frame, 2)
    logger.debug(
        f"[CONTEXT CHECK] Location: {location}\n"
        f"Has App Context: {has_context}\n"
        f"Current App: {current_app._get_current_object() if has_context else 'None'}\n"
        f"Call Stack:\n"
        f"{''.join(map(str, caller))}\n"
        f"Thread ID: {threading.get_ident()}"
    )

def role_required(roles):
    """Ensure the current user has one of the required roles."""
    if isinstance(roles, str):
        roles = [roles]

    def role_required_decorator(f):
        if hasattr(f, 'role_decorated'):
            return f

        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = safe_current_user
            if not user or not user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            session = getattr(g, 'db_session', None)
            if session is None:
                flash('Database session not available.', 'danger')
                return redirect(url_for('auth.login'))

            user = session.merge(user)
            user_roles = [role.name for role in user.roles]
            if not any(role in user_roles for role in roles):
                flash(f'Access denied: Required roles: {", ".join(roles)}', 'danger')
                return redirect(url_for('auth.login'))

            return f(*args, **kwargs)

        decorated_function.role_decorated = True
        return decorated_function
    return role_required_decorator

def permission_required(permission_name):
    """Ensure the current user has the required permission."""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = safe_current_user
            if not user or not user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            session = getattr(g, 'db_session', None)
            if session is None:
                flash('Database session not available.', 'danger')
                return redirect(url_for('auth.login'))

            user = session.merge(user)
            if not user.has_permission(permission_name):
                flash(f'Access denied: {permission_name} permission required.', 'danger')
                return redirect(url_for('auth.login'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def admin_or_owner_required(func):
    """
    Decorator to ensure that the current user is either an admin or the owner of the profile.
    """
    from functools import wraps
    from app.models import Player

    @wraps(func)
    def decorated_function(*args, **kwargs):
        player_id = kwargs.get('player_id')
        if not player_id:
            flash('Invalid access.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player_id))

        session = getattr(g, 'db_session', None)
        if session is None:
            flash('Database session not available.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player_id))

        player = session.query(Player).get(player_id)
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player_id))

        admin_roles = ['Global Admin', 'Pub League Admin']
        user_roles = [role.name for role in safe_current_user.roles]

        is_admin = any(role in admin_roles for role in user_roles)
        is_owner = safe_current_user.id == player.user_id

        if not (is_admin or is_owner):
            flash('Access denied: You do not have permission to perform this action.', 'danger')
            return redirect(url_for('auth.login'))

        return func(*args, **kwargs)

    return decorated_function

def jwt_role_required(roles):
    """
    Ensure the current user has one of the required roles for API access.
    """
    from app.models import User
    if isinstance(roles, str):
        roles = [roles]

    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            verify_jwt_in_request()
            current_user_id = get_jwt_identity()

            session = getattr(g, 'db_session', None)
            if session is None:
                return jsonify({"msg": "Database session not available"}), 500

            user = session.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404
            user_roles = [role.name for role in user.roles]
            if not any(role in user_roles for role in roles):
                return jsonify({"msg": f"Access denied: Required roles: {', '.join(roles)}"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def jwt_permission_required(permission_name):
    """
    Ensure the current user has the required permission for API access.
    """
    from app.models import User
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            verify_jwt_in_request()
            current_user_id = get_jwt_identity()

            session = getattr(g, 'db_session', None)
            if session is None:
                return jsonify({"msg": "Database session not available"}), 500

            user = session.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404
            if not user.has_permission(permission_name):
                return jsonify({"msg": f"Access denied: {permission_name} permission required"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def jwt_admin_or_owner_required(func):
    """
    Decorator to ensure that the current user is either an admin or the owner of the profile for API access.
    """
    from app.models import User, Player
    @wraps(func)
    def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()

        session = getattr(g, 'db_session', None)
        if session is None:
            return jsonify({"msg": "Database session not available"}), 500

        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player_id = kwargs.get('player_id')
        if not player_id:
            return jsonify({"msg": "Invalid access"}), 400

        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        admin_roles = ['Global Admin', 'Pub League Admin']
        user_roles = [role.name for role in user.roles]
        is_admin = any(role in user_roles for role in admin_roles)
        is_owner = user.id == player.user_id

        if not (is_admin or is_owner):
            return jsonify({"msg": "Access denied: You do not have permission"}), 403

        return func(*args, **kwargs)

    return decorated_function

@contextmanager 
def session_timeout_context(timeout_seconds: int = 30):
    """
    Session timeout context.
    Uses g.db_session if available.
    """
    start_time = datetime.utcnow()
    
    def check_timeout():
        duration = (datetime.utcnow() - start_time).total_seconds()
        if duration > timeout_seconds:
            sess = getattr(g, 'db_session', None)
            if sess:
                sess.rollback()
            raise Exception(f"Session timeout after {duration}s")
    
    try:
        yield check_timeout
    finally:
        check_timeout()

@asynccontextmanager
async def async_session_context():
    """
    Async session context for async operations.
    If used in a request context, g.db_session is available.
    If not, create a new session from app.SessionLocal().
    """
    app = current_app._get_current_object()
    session = getattr(g, 'db_session', None)
    if session is None:
        session = app.SessionLocal()
        new_session = True
    else:
        new_session = False

    try:
        yield session
    finally:
        if new_session:
            session.close()

def celery_task(**task_kwargs):
    """
    Decorator for Celery tasks.
    Creates and manages its own database session.
    """
    def celery_task_decorator(f):
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        task_kwargs.pop('bind', None)  # Remove bind if present

        @celery.task(name=task_name, bind=True, **task_kwargs)
        @wraps(f)
        def wrapped(self, *args, **kwargs):
            app = celery.flask_app
            with app.app_context():
                session = app.SessionLocal()
                try:
                    # Now f must accept session as a parameter if it needs DB access
                    result = f(self, session, *args, **kwargs)
                    session.commit()
                    return result
                except Exception as e:
                    session.rollback()
                    logger.error(f"Task {task_name} failed: {str(e)}", exc_info=True)
                    raise
                finally:
                    session.close()
        return wrapped
    return celery_task_decorator

def async_task(**task_kwargs):
    """
    Decorator for async Celery tasks with explicit session handling.
    """
    def async_task_decorator(f):
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        base_task = celery.task(name=task_name, **task_kwargs)(f)

        @wraps(f)
        async def wrapped(*args, **kwargs):
            app = celery.flask_app
            async_session = app.SessionLocal()  # Create a sync session (consider async if needed)
            try:
                # f should accept session if needed:
                result = await f(async_session, *args, **kwargs)
                async_session.commit()
                return result
            except Exception as e:
                async_session.rollback()
                logger.error(f"Async task {task_name} failed: {str(e)}", exc_info=True)
                raise
            finally:
                async_session.close()

        wrapped.delay = base_task.delay
        wrapped.apply_async = base_task.apply_async
        return wrapped
    return async_task_decorator
