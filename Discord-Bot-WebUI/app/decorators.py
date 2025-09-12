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

from sqlalchemy.exc import SQLAlchemyError

from flask import (
    redirect, url_for, abort, jsonify,
    current_app, has_app_context, g
)
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from app.core import celery
from app.core.session_manager import managed_session

# ROOT CAUSE FIX: Global registry for two-phase task metadata
_two_phase_task_registry = {}

# Special mapping for tasks where the task name doesn't match the function name
_task_name_to_function_mapping = {
    'cleanup_pub_league_discord_resources': 'cleanup_pub_league_discord_resources_celery_task',
    'cleanup_league_discord_resources': 'cleanup_league_discord_resources_task'
}

def register_two_phase_task(task_name, extract_data=None, execute_async=None, final_db_update=None, requires_final_db_update=False):
    """
    Register a two-phase task in the global registry.
    
    This is the ROOT CAUSE FIX for the attribute attachment issue.
    Instead of relying on function attributes that may not transfer properly through decorators,
    we use a global registry that persists regardless of function wrapping.
    """
    _two_phase_task_registry[task_name] = {
        'is_two_phase': True,
        'extract_data': extract_data,
        'execute_async': execute_async,
        'final_db_update': final_db_update,
        'requires_final_db_update': requires_final_db_update
    }
from app.utils.user_helpers import safe_current_user
from app.alert_helpers import show_success, show_error, show_warning, show_info

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
            from flask_login import current_user
            
            if not current_user.is_authenticated:
                show_warning('Please log in to access this page.')
                return redirect(url_for('auth.login'))

            session = getattr(g, 'db_session', None)
            if session is None:
                show_error('Database session not available.')
                return redirect(url_for('auth.login'))

            logger.debug(f"Role decorator - Current user ID: {current_user.id}")
            logger.debug(f"Role decorator - Session: {session}")

            # Check for role impersonation first, then fall back to real roles
            from app.role_impersonation import is_impersonation_active, get_effective_roles
            
            if is_impersonation_active():
                user_roles = get_effective_roles()
                logger.debug(f"Role decorator - Using impersonation roles: {user_roles}")
            else:
                # Load user with roles from current session to avoid session binding issues
                from app.models import User
                from sqlalchemy.orm import selectinload
                
                db_user = session.query(User).options(
                    selectinload(User.roles)
                ).get(current_user.id)
                
                if not db_user:
                    show_error('User not found.')
                    return redirect(url_for('auth.login'))
                
                user_roles = [role.name for role in db_user.roles]
                logger.debug(f"Role decorator - User roles from fresh query: {user_roles}")
            
            if not any(role in user_roles for role in roles):
                show_error(f'Access denied: Required roles: {", ".join(roles)}')
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
                show_warning('Please log in to access this page.')
                return redirect(url_for('auth.login'))

            session = getattr(g, 'db_session', None)
            if session is None:
                show_error('Database session not available.')
                return redirect(url_for('auth.login'))

            # Check for role impersonation first, then fall back to real permissions
            from app.role_impersonation import is_impersonation_active, has_effective_permission
            
            if is_impersonation_active():
                has_perm = has_effective_permission(permission_name)
            else:
                user = session.merge(user)
                has_perm = user.has_permission(permission_name)
            
            if not has_perm:
                show_error(f'Access denied: {permission_name} permission required.')
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
            show_error('Invalid access: player_id missing.')
            return abort(400)

        session = getattr(g, 'db_session', None)
        if session is None:
            flash('Database session not available.', 'danger')
            return redirect(url_for('auth.login'))

        player = session.query(Player).get(player_id)
        if not player:
            show_error('Player not found.')
            return abort(404)

        admin_roles = ['Global Admin', 'Pub League Admin']
        
        # Check for role impersonation first, then fall back to real roles
        from app.role_impersonation import is_impersonation_active, get_effective_roles
        
        if is_impersonation_active():
            user_roles = get_effective_roles()
        else:
            user = session.merge(user)
            user_roles = [role.name for role in user.roles]

        is_admin = any(role in user_roles for role in admin_roles)
        is_owner = (user.id == player.user_id)

        if not (is_admin or is_owner):
            show_error('Access denied: You do not have permission to perform this action.')
            return abort(403)

        return func(*args, **kwargs)

    return decorated_function


# ------------------------------------------------------------------
# JWT-Based Decorators for API Endpoints
# ------------------------------------------------------------------

def jwt_role_required(roles):
    """
    Decorator to ensure that the current JWT-authenticated user has one of the required roles.
    Global Admin users are always allowed regardless of specified roles.
    
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
            
            # Global Admin always has access
            if 'Global Admin' in user_roles:
                return f(*args, **kwargs)
                
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
    Uses the standardized managed_session context manager for proper session handling.
    
    Yields:
        A database session.
    """
    # Use the established managed_session context manager
    with managed_session() as session:
        yield session


def celery_task(func=None, **task_kwargs):
    """
    Decorator for wrapping functions as Celery tasks with session management.

    Handles both synchronous and asynchronous functions by creating a new
    database session from the Flask app context.

    Args:
        func: The function to decorate (when used without parentheses)
        **task_kwargs: Keyword arguments for Celery task configuration.

    Returns:
        function: The decorated Celery task.
    """
    def celery_task_decorator(f):
        if 'name' in task_kwargs:
            task_name = task_kwargs.pop('name')
        else:
            # Fix task name generation - avoid duplicating 'app.tasks' prefix
            module_name = f.__module__
            if module_name.startswith('app.tasks.'):
                task_name = f'{module_name}.{f.__name__}'
            else:
                task_name = f'app.tasks.{module_name}.{f.__name__}'
        task_kwargs.pop('bind', None)  # Remove bind if present

        @celery.task(name=task_name, bind=True, **task_kwargs)
        @wraps(f)
        def wrapped(self, *args, **kwargs):
            app = celery.flask_app
            with app.app_context():
                # Import session tracking utilities
                from app.utils.task_monitor import register_session_start, register_session_end
                
                # Create a unique session ID for tracking
                import uuid
                session_id = str(uuid.uuid4())
                
                # Get stack trace for debugging orphaned sessions
                import traceback
                stack_trace = ''.join(traceback.format_stack())
                
                # Track session creation
                register_session_start(session_id, self.request.id, stack_trace)
                
                # Use managed_session for proper session handling
                session = None
                try:
                    # Check if this is a two-phase async task
                    # ROOT CAUSE FIX: Check function attributes, original function, AND global registry
                    task_metadata = _two_phase_task_registry.get(task_name, {})
                    original_func = getattr(f, '_original_func', None)
                    
                    # ENHANCED ROOT CAUSE FIX: Also check by task name in global scope
                    # This handles cases where attributes are attached after decoration
                    task_func_name = task_name.split('.')[-1]  # Get just the function name
                    global_task_func = None
                    
                    # Check if we have a special mapping for this task name
                    if task_name in _task_name_to_function_mapping:
                        task_func_name = _task_name_to_function_mapping[task_name]
                    
                    # Try to find the task function in the global namespace
                    try:
                        import importlib
                        module_path = '.'.join(task_name.split('.')[:-1])
                        if module_path:
                            module = importlib.import_module(module_path)
                            global_task_func = getattr(module, task_func_name, None)
                        else:
                            # If no module path, try to find in discord_cleanup module
                            if task_name in ['cleanup_pub_league_discord_resources', 'cleanup_league_discord_resources']:
                                from app.tasks import discord_cleanup
                                global_task_func = getattr(discord_cleanup, task_func_name, None)
                    except Exception:
                        pass
                    
                    has_extract_data = (hasattr(f, '_extract_data') or 
                                       (original_func and hasattr(original_func, '_extract_data')) or
                                       (global_task_func and hasattr(global_task_func, '_extract_data')))
                    has_two_phase = (hasattr(f, '_two_phase') or 
                                    (original_func and hasattr(original_func, '_two_phase')) or
                                    (global_task_func and hasattr(global_task_func, '_two_phase')))
                    
                    # DEBUG: Log what we're finding
                    logger.debug(f"DEBUG {task_name}: task_func_name={task_func_name}, f._extract_data={hasattr(f, '_extract_data')}, f._two_phase={hasattr(f, '_two_phase')}, original_func={original_func is not None}, global_task_func={global_task_func is not None}")
                    if original_func:
                        logger.debug(f"DEBUG {task_name}: original_func._extract_data={hasattr(original_func, '_extract_data')}, original_func._two_phase={hasattr(original_func, '_two_phase')}")
                    if global_task_func:
                        logger.debug(f"DEBUG {task_name}: global_task_func._extract_data={hasattr(global_task_func, '_extract_data')}, global_task_func._two_phase={hasattr(global_task_func, '_two_phase')}")
                    
                    is_two_phase_async = (asyncio.iscoroutinefunction(f) and 
                                         (has_extract_data or has_two_phase or 
                                          task_metadata.get('is_two_phase', False)))
                    
                    if is_two_phase_async:
                        # Two-phase async task: Extract data with session, then run async without session
                        with managed_session() as session:
                            # ROOT CAUSE FIX: Check function attributes, original function, global function, then registry
                            extract_func = None
                            if hasattr(f, '_extract_data'):
                                extract_func = f._extract_data
                            elif original_func and hasattr(original_func, '_extract_data'):
                                extract_func = original_func._extract_data
                            elif global_task_func and hasattr(global_task_func, '_extract_data'):
                                extract_func = global_task_func._extract_data
                            elif 'extract_data' in task_metadata:
                                extract_func = task_metadata['extract_data']
                            
                            if extract_func:
                                # New pattern: function has _extract_data method
                                try:
                                    data = extract_func(session, *args, **kwargs)
                                    # Handle case where extract function returns None (e.g., missing entity)
                                    if data is None:
                                        logger.warning(f"Extract function returned None for task {f.__name__} - skipping execution")
                                        register_session_end(session_id, 'committed')
                                        return {'success': False, 'message': 'Required entity not found'}
                                    
                                    # ROOT CAUSE FIX: Expunge all SQLAlchemy objects from session before data leaves scope
                                    # This prevents detached object references from holding onto session memory
                                    logger.info(f"Expunging all objects from session for task {task_name}")
                                    session.expunge_all()
                                    
                                except Exception as e:
                                    logger.error(f"Error in extract function for task {f.__name__}: {e}", exc_info=True)
                                    register_session_end(session_id, 'rollback')
                                    raise
                            else:
                                # Legacy pattern: function implements two-phase internally
                                result = f(self, session, *args, **kwargs)
                                register_session_end(session_id, 'committed')
                                return result
                        
                        # Session is now closed, run async execution
                        from app.api_utils import async_to_sync
                        execute_func = None
                        if hasattr(f, '_execute_async'):
                            execute_func = f._execute_async
                        elif original_func and hasattr(original_func, '_execute_async'):
                            execute_func = original_func._execute_async
                        elif global_task_func and hasattr(global_task_func, '_execute_async'):
                            execute_func = global_task_func._execute_async
                        elif 'execute_async' in task_metadata:
                            execute_func = task_metadata['execute_async']
                        
                        if execute_func:
                            try:
                                result = async_to_sync(execute_func(data))
                            except Exception as e:
                                logger.error(f"Error in async execute function for task {f.__name__}: {e}", exc_info=True)
                                return {'success': False, 'message': f'Async execution failed: {str(e)}', 'error': str(e)}
                        else:
                            # Fallback: call original function with data
                            try:
                                result = async_to_sync(f(data))
                            except Exception as e:
                                logger.error(f"Error in fallback async execution for task {f.__name__}: {e}", exc_info=True)
                                return {'success': False, 'message': f'Fallback execution failed: {str(e)}', 'error': str(e)}
                        
                        # Check if task requires a final database update
                        final_update_func = None
                        requires_final_update = (
                            (hasattr(f, '_requires_final_db_update') and f._requires_final_db_update) or
                            (original_func and hasattr(original_func, '_requires_final_db_update') and original_func._requires_final_db_update) or
                            (global_task_func and hasattr(global_task_func, '_requires_final_db_update') and global_task_func._requires_final_db_update) or
                            task_metadata.get('requires_final_db_update', False)
                        )
                        
                        if requires_final_update:
                            if hasattr(f, '_final_db_update'):
                                final_update_func = f._final_db_update
                            elif original_func and hasattr(original_func, '_final_db_update'):
                                final_update_func = original_func._final_db_update
                            elif global_task_func and hasattr(global_task_func, '_final_db_update'):
                                final_update_func = global_task_func._final_db_update
                            elif 'final_db_update' in task_metadata:
                                final_update_func = task_metadata['final_db_update']
                        
                        if final_update_func:
                            with managed_session() as final_session:
                                try:
                                    result = final_update_func(final_session, result)
                                    # Emit socket event if result has socket data
                                    if result.get('success'):
                                        try:
                                            from app import socketio
                                            socketio.emit('role_update', result)
                                        except Exception as e:
                                            logger.warning(f"Failed to emit socket event: {e}")
                                except Exception as e:
                                    logger.error(f"Error in final database update for {task_name}: {e}")
                                    # Don't fail the task if final update fails
                        
                        register_session_end(session_id, 'committed')
                        return result
                    
                    else:
                        # Standard sync task
                        with managed_session() as session:
                            if asyncio.iscoroutinefunction(f):
                                # Async function without two-phase pattern - this is now an error
                                logger.error(f"Async task {task_name} must implement two-phase pattern (_extract_data and _execute_async methods)")
                                raise RuntimeError(f"Async task {task_name} must use two-phase pattern. See ASYNC_TASK_MIGRATION.md for migration guide.")
                            else:
                                # Sync function - call normally with session
                                result = f(self, session, *args, **kwargs)
                            
                            register_session_end(session_id, 'committed')
                            return result
                except Exception as e:
                    # Record error in session tracking (rollback happens automatically in managed_session)
                    register_session_end(session_id, 'error-rollback')
                    
                    logger.error(f"Task {task_name} failed: {str(e)}", exc_info=True)
                    raise
                finally:
                    # Ensure session is marked as closed
                    try:
                        register_session_end(session_id, 'closed')
                        # Force cleanup any lingering connections
                        if session and hasattr(session, 'close'):
                            session.close()
                    except Exception as e:
                        logger.error(f"Failed to register session end: {str(e)}")
        
        # ROOT CAUSE FIX: Copy any existing attributes from original function to wrapped function  
        # This ensures attributes attached before OR after decoration are preserved
        for attr_name in ['_extract_data', '_execute_async', '_two_phase', '_requires_final_db_update', '_final_db_update']:
            if hasattr(f, attr_name):
                setattr(wrapped, attr_name, getattr(f, attr_name))
        
        # Store original function reference so we can check for attributes added later
        wrapped._original_func = f
        
        return wrapped
    
    # Handle both @celery_task and @celery_task() usage
    if func is None:
        # Called with parentheses: @celery_task()
        return celery_task_decorator
    else:
        # Called without parentheses: @celery_task
        return celery_task_decorator(func)


def async_task(**task_kwargs):
    """
    Decorator for asynchronous Celery tasks with improved session handling.

    Ensures that sessions are properly committed or rolled back in all execution
    paths, including error paths. Also provides better error reporting and task
    retry capability.

    Args:
        **task_kwargs: Keyword arguments for Celery task configuration.

    Returns:
        function: The decorated async Celery task.
    """
    def async_task_decorator(f):
        if 'name' in task_kwargs:
            task_name = task_kwargs.pop('name')
        else:
            # Fix task name generation - avoid duplicating 'app.tasks' prefix
            module_name = f.__module__
            if module_name.startswith('app.tasks.'):
                task_name = f'{module_name}.{f.__name__}'
            else:
                task_name = f'app.tasks.{module_name}.{f.__name__}'
        # Add bind=True for better task control
        task_kwargs['bind'] = True
        max_retries = task_kwargs.pop('max_retries', 3)
        
        # Create the base Celery task
        @celery.task(name=task_name, max_retries=max_retries, **task_kwargs)
        @wraps(f)
        def task_wrapper(self, *args, **kwargs):
            """Wrapper function that runs the async task in a new event loop"""
            app = celery.flask_app
            
            with app.app_context():
                # Use the new async_to_sync utility for safe async execution
                from app.api_utils import async_to_sync
                
                # Define the actual async execution function using managed_session
                async def execute_async():
                    # Use managed_session in an async context
                    from app.utils.task_session_manager import async_task_session
                    try:
                        async with async_task_session() as session:
                            # Execute the task with session and args
                            result = await f(session, *args, **kwargs)
                            # Commit happens automatically in async_task_session
                            return result
                    except SQLAlchemyError as e:
                        # Rollback happens automatically, just handle retry
                        logger.error(f"Database error in {task_name}: {e}", exc_info=True)
                        raise self.retry(exc=e, countdown=60, max_retries=max_retries)
                    except Exception as e:
                        # Rollback happens automatically, just log and re-raise
                        logger.error(f"Error in {task_name}: {e}", exc_info=True)
                        raise
                
                # Use the safe async execution utility
                return async_to_sync(execute_async())
        
        # Create an async wrapper that has the same interface for local calls
        @wraps(f)
        async def wrapped(*args, **kwargs):
            async with async_session_context() as session:
                return await f(session, *args, **kwargs)
        
        # Expose Celery task methods on our wrapper
        wrapped.delay = task_wrapper.delay
        wrapped.apply_async = task_wrapper.apply_async
        wrapped.name = task_name
        return wrapped
    
    return async_task_decorator