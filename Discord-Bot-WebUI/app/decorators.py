# app/decorators.py
from functools import wraps
from datetime import datetime
from flask import flash, redirect, url_for, abort, jsonify, Flask, current_app, has_app_context
from flask_login import current_user
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Callable
import logging
import inspect
import threading
from celery import shared_task

# Import extensions but only db since we need it directly
from app.extensions import db, celery

logger = logging.getLogger(__name__)

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
                with session_context():
                    return callable_func()
            except Exception as e:
                logger.error(f"Template DB access error: {e}")
                return None
        return dict(safe_db_load=safe_db_load)

def role_required(roles):
    """
    Ensure the current user has one of the required roles.
    :param roles: A list of roles (strings) or a single role (string).
    """
    if isinstance(roles, str):
        roles = [roles]

    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            user_roles = [role.name for role in current_user.roles]

            if not any(role in user_roles for role in roles):
                flash(f'Access denied: One of the following roles required: {", ".join(roles)}', 'danger')
                return redirect(url_for('auth.login'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def permission_required(permission_name):
    """
    Ensure the current user has the required permission.
    :param permission_name: The name of the required permission (string).
    """
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            if not current_user.has_permission(permission_name):
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
        user_roles = [role.name for role in current_user.roles]
        
        # Check if the user has any admin role
        is_admin = any(role in admin_roles for role in user_roles)
        
        # Check if the user is the owner of the profile
        is_owner = current_user.id == player.user_id
        
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

def db_operation(f: Callable) -> Callable:
    """Enhanced db operation decorator with better session handling"""
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        thread_id = threading.get_ident()
        logger.debug(f"[DB OP START] Function: {f.__name__} Thread: {thread_id}")
        
        try:
            result = f(*args, **kwargs)
            
            # Handle tuple returns where first element is list of objects to process
            if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[0], (list, tuple)):
                objects_to_process, response = result[0], result[1]
                
                with db.session.no_autoflush:
                    for obj in objects_to_process:
                        if hasattr(obj, '_sa_instance_state'):
                            if getattr(obj, 'deleted', False):
                                logger.debug(f"Deleting object: {obj}")
                                db.session.delete(obj)
                            elif obj not in db.session:
                                logger.debug(f"Adding object: {obj}")
                                db.session.add(obj)
                
                db.session.flush()
                return response
            
            if db.session.is_active:
                db.session.flush()
            
            return result
            
        except Exception as e:
            if db.session.is_active:
                db.session.rollback()
            logger.error(f"Database operation error in {f.__name__}: {str(e)}")
            raise
        finally:
            logger.debug(f"[DB OP END] Function: {f.__name__} Thread: {thread_id}")
    return decorated

def query_operation(f: Callable) -> Callable:
    """Enhanced query operation decorator that ensures session cleanup after response"""
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        thread_id = threading.get_ident()
        logger.debug(f"[QUERY START] Function: {f.__name__} Thread: {thread_id}")
        
        try:
            # Run the original function
            result = f(*args, **kwargs)
            
            # If this is a template render response, ensure data is fully loaded
            if hasattr(result, '_render_template'):
                template_context = result._template_context
                # Eagerly load any SQLAlchemy relationships that might be accessed in template
                for key, value in template_context.items():
                    if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
                        try:
                            # Force loading of SQLAlchemy collections
                            list(value)
                        except:
                            pass
            
            return result
            
        except Exception as e:
            if db.session.is_active:
                db.session.rollback()
            logger.error(f"Query operation error in {f.__name__}: {str(e)}")
            raise
        finally:
            logger.debug(f"[QUERY END] Function: {f.__name__} Thread: {thread_id}")
    return decorated

@contextmanager
def session_context():
    """Enhanced session context manager with connection health check"""
    session_id = f"session-{datetime.utcnow().timestamp()}"
    thread_id = threading.get_ident()
    
    def check_connection():
        try:
            db.session.execute('SELECT 1')
            return True
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            return False
    
    try:
        if db.session.is_active:
            if not check_connection():
                logger.warning("Detected stale connection, cleaning up")
                db.session.remove()
                if hasattr(db.session, 'bind') and db.session.bind:
                    db.session.bind.dispose()
        
        yield db.session
        
        if db.session.is_active:
            try:
                db.session.commit()
                logger.debug(f"[SESSION COMMIT] ID: {session_id} Thread: {thread_id}")
            except:
                db.session.rollback()
                raise
            
    except Exception as e:
        logger.error(
            f"[SESSION ERROR] ID: {session_id} Thread: {thread_id}\n"
            f"Error: {str(e)}", exc_info=True
        )
        if db.session.is_active:
            db.session.rollback()
        raise
    finally:
        try:
            if db.session.is_active:
                db.session.remove()
                if hasattr(db.session, 'bind') and db.session.bind:
                    db.session.bind.dispose()
                logger.debug(f"[SESSION CLEANUP] ID: {session_id} Thread: {thread_id}")
        except Exception as e:
            logger.error(
                f"[SESSION CLEANUP ERROR] ID: {session_id} Thread: {thread_id}\n"
                f"Error: {str(e)}"
            )

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
    """Asynchronous session context manager for use in async functions."""
    session_id = f"session-{datetime.utcnow().timestamp()}"
    logger.debug(f"Starting new async session context: {session_id}")
    try:
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
    """Enhanced Celery task decorator that ensures proper app context and session management"""
    def decorator(f):
        # Generate the task name if not provided
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        
        # Create base task
        base_task = celery.task(
            name=task_name,
            **task_kwargs
        )(f)
        
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app import create_app
            app = create_app()
            
            logger.debug(f"[CELERY TASK START] {task_name}")
            
            try:
                with app.app_context():
                    # Ensure any lingering sessions are cleaned up
                    if db.session.is_active:
                        db.session.remove()
                    if hasattr(db.session, 'bind') and db.session.bind:
                        db.session.bind.dispose()
                    
                    result = base_task(*args, **kwargs)
                    return result
                    
            except Exception as e:
                logger.error(f"Task {task_name} failed: {str(e)}", exc_info=True)
                try:
                    if db.session.is_active:
                        db.session.remove()
                    if hasattr(db.session, 'bind') and db.session.bind:
                        db.session.bind.dispose()
                except:
                    pass
                raise
            finally:
                logger.debug(f"[CELERY TASK END] {task_name}")
                try:
                    if db.session.is_active:
                        db.session.remove()
                    if hasattr(db.session, 'bind') and db.session.bind:
                        db.session.bind.dispose()
                except:
                    pass
                
        # Copy celery task attributes
        wrapped.delay = base_task.delay
        wrapped.apply_async = base_task.apply_async
        
        return wrapped
    return decorator

def async_task(**task_kwargs):
    """Decorator for async Celery tasks"""
    def decorator(f):
        # Generate the task name if not provided
        task_name = task_kwargs.pop('name', None) or f'app.tasks.{f.__module__}.{f.__name__}'
        
        # Create base task
        base_task = celery.task(
            name=task_name,
            **task_kwargs
        )(f)
        
        @wraps(f)
        async def wrapped(*args, **kwargs):
            try:
                return await base_task(*args, **kwargs)
            except Exception as e:
                logger.error(f"Async task {task_name} failed: {str(e)}", exc_info=True)
                raise
                
        # Copy celery task attributes
        wrapped.delay = base_task.delay
        wrapped.apply_async = base_task.apply_async
        
        return wrapped
    return decorator