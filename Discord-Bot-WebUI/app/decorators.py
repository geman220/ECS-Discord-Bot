# app/decorators.py
from functools import wraps
from datetime import datetime
from flask import flash, redirect, url_for, abort, jsonify, Flask, current_app, has_app_context, g
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from contextlib import contextmanager, asynccontextmanager
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy import text
from app.utils.user_helpers import safe_current_user
from app.db_management import db_manager
from typing import Any, Callable
import logging
import inspect
import threading
from celery import shared_task

# Import extensions but only db since we need it directly
from app.extensions import db, celery

logger = logging.getLogger(__name__)

def is_flask_view_function(f):
    """Helper to detect Flask view functions"""
    return (hasattr(f, 'view_function') or 
            hasattr(f, '_is_view') or 
            hasattr(f, '__blueprinted__') or 
            hasattr(f, '_blueprint_name') or
            hasattr(f, 'endpoint'))

def handle_db_operation(nested=False, transaction_name=None):
    """Decorator for database operations with session handling."""
    def db_operation_decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            with db_manager.session_scope(nested=nested, transaction_name=transaction_name):
                return f(*args, **kwargs)
        return wrapper
    return db_operation_decorator

def log_context_state(location: str):
    """Helper to log detailed context state"""
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

def register_template_context_processor(app):
    """Register template context processor for safe DB access"""
    @app.context_processor
    def inject_db_handler():
        def safe_db_load(callable_func):
            try:
                with db_manager.session_scope():
                    return callable_func()
            except Exception as e:
                logger.error(f"Template DB access error: {e}")
                return None
        return dict(safe_db_load=safe_db_load)

def role_required(roles):
    """Ensure the current user has one of the required roles."""
    if isinstance(roles, str):
        roles = [roles]

    def role_required_decorator(f):
        # Skip if already decorated
        if hasattr(f, 'role_decorated'):
            return f
            
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = safe_current_user
            if not user or not user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            user_roles = [role.name for role in user.roles]
            if not any(role in user_roles for role in roles):
                flash(f'Access denied: One of the following roles required: {", ".join(roles)}', 'danger')
                return redirect(url_for('auth.login'))

            return f(*args, **kwargs)
            
        decorated_function.role_decorated = True  # Mark as decorated
        return decorated_function
    return role_required_decorator

def permission_required(permission_name):
    """Ensure the current user has the required permission."""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = safe_current_user  # Use safe_current_user
            if not user or not user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            if not user.has_permission(permission_name):
                flash(f'Access denied: {permission_name} permission required.', 'danger')
                return redirect(url_for('auth.login'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def admin_or_owner_required(func):
    from app.models import Player
    """
    Decorator to ensure that the current user is either an admin or the owner of the profile.
    """
    @wraps(func)
    def decorated_function(*args, **kwargs):
        player_id = kwargs.get('player_id')
        if not player_id:
            flash('Invalid access.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player_id))
        
        player = Player.query.get(player_id)
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player_id))
        
        # Define admin roles
        admin_roles = ['Global Admin', 'Pub League Admin']
        
        # Extract user's role names
        user_roles = [role.name for role in safe_current_user.roles]
        
        # Check if the user has any admin role
        is_admin = any(role in admin_roles for role in user_roles)
        
        # Check if the user is the owner of the profile
        is_owner = safe_current_user.id == player.user_id
        
        if not (is_admin or is_owner):
            flash('Access denied: You do not have permission to perform this action.', 'danger')
            return redirect(url_for('auth.login'))
        
        return func(*args, **kwargs)
    
    return decorated_function

def jwt_role_required(roles):
    from app.models import User
    """
    Ensure the current user has one of the required roles for API access.
    :param roles: A list of roles (strings) or a single role (string).
    """
    if isinstance(roles, str):
        roles = [roles]
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            verify_jwt_in_request()
            current_user_id = get_jwt_identity()
            user = User.query.get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404
            user_roles = [role.name for role in user.roles]
            if not any(role in user_roles for role in roles):
                return jsonify({"msg": f"Access denied: One of the following roles required: {', '.join(roles)}"}), 403
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def jwt_permission_required(permission_name):
    from app.models import User
    """
    Ensure the current user has the required permission for API access.
    :param permission_name: The name of the required permission (string).
    """
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            verify_jwt_in_request()
            current_user_id = get_jwt_identity()
            user = User.query.get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404
            if not user.has_permission(permission_name):
                return jsonify({"msg": f"Access denied: {permission_name} permission required"}), 403
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def jwt_admin_or_owner_required(func):
    from app.models import User, Player
    """
    Decorator to ensure that the current user is either an admin or the owner of the profile for API access.
    """
    @wraps(func)
    def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player_id = kwargs.get('player_id')
        if not player_id:
            return jsonify({"msg": "Invalid access"}), 400
        
        player = Player.query.get(player_id)
        if not player:
            return jsonify({"msg": "Player not found"}), 404
        
        admin_roles = ['Global Admin', 'Pub League Admin']
        user_roles = [role.name for role in user.roles]
        is_admin = any(role in admin_roles for role in user_roles)
        is_owner = user.id == player.user_id
        
        if not (is_admin or is_owner):
            return jsonify({"msg": "Access denied: You do not have permission to perform this action"}), 403
        
        return func(*args, **kwargs)
    
    return decorated_function

def query_operation(f):
    """Query operation decorator with improved view function detection"""
    # Skip if already decorated or is a view function
    if hasattr(f, 'query_decorated') or is_flask_view_function(f):
        return f
        
    @wraps(f)
    def wrapper(*args, **kwargs):
        with db_manager.session_scope(nested=True):
            return f(*args, **kwargs)
            
    wrapper.query_decorated = True  # Mark as decorated
    return wrapper

@contextmanager
def session_timeout_context(timeout_seconds: int = 30):
    """Context manager to enforce session timeout"""
    start_time = datetime.utcnow()
    
    def check_timeout():
        duration = (datetime.utcnow() - start_time).total_seconds()
        if duration > timeout_seconds:
            raise Exception(f"Session timeout after {duration}s")
    
    try:
        yield check_timeout
    finally:
        check_timeout()

@asynccontextmanager
async def async_session_context():
    """Update async session context to use db_manager"""
    session_id = f"session-{datetime.utcnow().timestamp()}"
    logger.debug(f"Starting new async session context: {session_id}")
    try:
        # Note: This still uses db.session directly as db_manager doesn't have async support yet
        yield db.session
        if db.session.is_active:
            db.session.commit()
            logger.debug(f"Committed session: {session_id}")
    except Exception as e:
        logger.error(f"Error in async session {session_id}: {str(e)}")
        if db.session.is_active:
            db.session.rollback()
            logger.debug(f"Rolled back session: {session_id}")
        raise
    finally:
        db.session.remove()
        logger.debug(f"Removed session: {session_id}")

def celery_task(**task_kwargs):
    """Update celery task to use db_manager with better connection handling"""
    def celery_task_decorator(f):
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        base_task = celery.task(name=task_name, **task_kwargs)(f)
        
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app import create_app
            app = create_app()
            
            logger.debug(f"[CELERY TASK START] {task_name}")
            
            try:
                with app.app_context():
                    # Use transaction name to track celery task connections
                    with db_manager.session_scope(transaction_name=f"celery_{task_name}") as session:
                        # Explicitly close any lingering transactions
                        session.execute(text("ROLLBACK"))
                        session.execute(text("SET idle_in_transaction_session_timeout = '30s'"))
                        
                        result = base_task(*args, **kwargs)
                        return result
                        
            except Exception as e:
                logger.error(f"Task {task_name} failed: {str(e)}", exc_info=True)
                raise
            finally:
                # Force cleanup after task completion
                db_manager.cleanup_pool()
                if hasattr(db, 'session'):
                    db.session.remove()
                
        wrapped.delay = base_task.delay
        wrapped.apply_async = base_task.apply_async
        return wrapped
    return celery_task_decorator

def async_task(**task_kwargs):
    """Decorator for async Celery tasks with better connection handling"""
    def async_task_decorator(f):
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        base_task = celery.task(name=task_name, **task_kwargs)(f)
        
        @wraps(f)
        async def wrapped(*args, **kwargs):
            try:
                return await base_task(*args, **kwargs)
            except Exception as e:
                logger.error(f"Async task {task_name} failed: {str(e)}", exc_info=True)
                raise
            finally:
                # Ensure connections are cleaned up
                db_manager.cleanup_pool()
                if hasattr(db, 'session'):
                    db.session.remove()
                
        wrapped.delay = base_task.delay
        wrapped.apply_async = base_task.apply_async
        return wrapped
    return async_task_decorator
