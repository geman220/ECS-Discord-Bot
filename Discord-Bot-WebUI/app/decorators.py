# app/decorators.py

"""
Decorators Module

This module provides various decorators for enforcing role- and permission-based
access control for both standard Flask view functions and JWT-protected API endpoints.
It also includes utilities for logging context state and wrapping Celery tasks with
session management.
"""

import asyncio
import threading
import logging
import traceback
from functools import wraps
from contextlib import asynccontextmanager
from inspect import getouterframes, currentframe

from flask import (
    flash, redirect, url_for, abort, jsonify,
    current_app, has_app_context, g
)
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from app.core import celery
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helper / Utility Functions
# ------------------------------------------------------------------

def is_flask_view_function(f):
    """
    Check if a function is a Flask view function by looking for specific attributes.
    
    Args:
        f (callable): Function to check.
    
    Returns:
        bool: True if function appears to be a Flask view function, otherwise False.
    """
    return (
        hasattr(f, 'view_function')
        or hasattr(f, '_is_view')
        or hasattr(f, '__blueprinted__')
        or hasattr(f, '_blueprint_name')
        or hasattr(f, 'endpoint')
    )


def log_context_state(location: str):
    """
    Log detailed context state for debugging purposes.

    Args:
        location (str): A string indicating the location or context of the log.
    """
    has_context = has_app_context()
    frame = currentframe()
    caller = getouterframes(frame, 2)
    logger.debug(
        f"[CONTEXT CHECK] Location: {location}\n"
        f"Has App Context: {has_context}\n"
        f"Current App: {current_app._get_current_object() if has_context else 'None'}\n"
        f"Call Stack:\n{''.join(map(str, caller))}\n"
        f"Thread ID: {threading.get_ident()}"
    )


# ------------------------------------------------------------------
# Role-Based and Permission-Based Decorators for Flask Routes
# ------------------------------------------------------------------

def role_required(roles):
    """
    Decorator to ensure that the current user has one of the required roles.
    
    If not authenticated, redirects to the login page.
    If authenticated but lacking the required roles, returns a 403 error.

    Args:
        roles (str or list): Required role(s).

    Returns:
        function: Decorated view function.
    """
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

            # Merge user to refresh role data
            user = session.merge(user)
            user_roles = [role.name for role in user.roles]
            if not any(role in user_roles for role in roles):
                flash(f'Access denied: Required roles: {", ".join(roles)}', 'danger')
                return abort(403)

            return f(*args, **kwargs)

        decorated_function.role_decorated = True
        return decorated_function

    return role_required_decorator


def permission_required(permission_name):
    """
    Decorator to ensure that the current user has a required permission.
    
    If not authenticated, redirects to login.
    If authenticated but lacking the permission, returns a 403 error.

    Args:
        permission_name (str): Required permission name.

    Returns:
        function: Decorated view function.
    """
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
                return abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return wrapper


def admin_or_owner_required(func):
    """
    Decorator to ensure that the current user is either an admin or the owner of the player profile.
    
    If not authenticated, redirects to login.
    If authenticated but not admin or owner, returns a 403 error.
    
    Expects a 'player_id' parameter in the view function's keyword arguments.
    """
    from app.models import Player

    @wraps(func)
    def decorated_function(*args, **kwargs):
        user = safe_current_user
        if not user or not user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))

        player_id = kwargs.get('player_id')
        if not player_id:
            flash('Invalid access: player_id missing.', 'danger')
            return abort(400)

        session = getattr(g, 'db_session', None)
        if session is None:
            flash('Database session not available.', 'danger')
            return redirect(url_for('auth.login'))

        player = session.query(Player).get(player_id)
        if not player:
            flash('Player not found.', 'danger')
            return abort(404)

        admin_roles = ['Global Admin', 'Pub League Admin']
        user = session.merge(user)
        user_roles = [role.name for role in user.roles]

        is_admin = any(role in user_roles for role in admin_roles)
        is_owner = (user.id == player.user_id)

        if not (is_admin or is_owner):
            flash('Access denied: You do not have permission to perform this action.', 'danger')
            return abort(403)

        return func(*args, **kwargs)

    return decorated_function


# ------------------------------------------------------------------
# JWT-Based Decorators for API Endpoints
# ------------------------------------------------------------------

def jwt_role_required(roles):
    """
    Decorator to ensure that the current JWT-authenticated user has one of the required roles.
    
    Returns JSON with 403 if the user lacks the required roles.

    Args:
        roles (str or list): Required role(s).

    Returns:
        function: Decorated function.
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
                return jsonify({
                    "msg": f"Access denied: Required roles: {', '.join(roles)}"
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return wrapper


def jwt_permission_required(permission_name):
    """
    Decorator to ensure that the current JWT-authenticated user has the required permission.
    
    Returns JSON with 403 if the user lacks the permission.

    Args:
        permission_name (str): The required permission name.

    Returns:
        function: Decorated function.
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
                return jsonify({
                    "msg": f"Access denied: {permission_name} permission required"
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return wrapper


def jwt_admin_or_owner_required(func):
    """
    Decorator to ensure that the current JWT-authenticated user is either an admin or the owner of a player profile.
    
    Expects a 'player_id' parameter in the view's keyword arguments.
    Returns JSON 403 if access is denied.
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
            return jsonify({"msg": "Invalid access: player_id missing"}), 400

        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        admin_roles = ['Global Admin', 'Pub League Admin']
        user_roles = [role.name for role in user.roles]
        is_admin = any(role in user_roles for role in admin_roles)
        is_owner = (user.id == player.user_id)

        if not (is_admin or is_owner):
            return jsonify({"msg": "Access denied: You do not have permission"}), 403

        return func(*args, **kwargs)

    return decorated_function


@asynccontextmanager
async def async_session_context():
    """
    Asynchronous session context manager for async operations.

    If within a request context, uses g.db_session; otherwise, creates a new session.
    
    Yields:
        A database session.
    """
    app = current_app._get_current_object()
    session = getattr(g, 'db_session', None)
    new_session = False
    if session is None:
        session = app.SessionLocal()
        new_session = True

    try:
        yield session
    finally:
        if new_session:
            session.close()


def celery_task(**task_kwargs):
    """
    Decorator for wrapping functions as Celery tasks with session management.

    Handles both synchronous and asynchronous functions by creating a new
    database session from the Flask app context.

    Args:
        **task_kwargs: Keyword arguments for Celery task configuration.

    Returns:
        function: The decorated Celery task.
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
                    if asyncio.iscoroutinefunction(f):
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            result = loop.run_until_complete(f(self, session, *args, **kwargs))
                        finally:
                            loop.close()
                    else:
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
    Decorator for asynchronous Celery tasks with explicit session handling.

    Args:
        **task_kwargs: Keyword arguments for Celery task configuration.

    Returns:
        function: The decorated async Celery task.
    """
    def async_task_decorator(f):
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        base_task = celery.task(name=task_name, **task_kwargs)(f)

        @wraps(f)
        async def wrapped(*args, **kwargs):
            app = celery.flask_app
            async_session = app.SessionLocal()
            try:
                result = await f(async_session, *args, **kwargs)
                async_session.commit()
                return result
            except Exception as e:
                async_session.rollback()
                logger.error(f"Async task {task_name} failed: {str(e)}", exc_info=True)
                raise
            finally:
                async_session.close()

        # Expose the delay and apply_async methods from the base task.
        wrapped.delay = base_task.delay
        wrapped.apply_async = base_task.apply_async
        return wrapped
    return async_task_decorator