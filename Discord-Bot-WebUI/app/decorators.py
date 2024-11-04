from functools import wraps
from celery import shared_task
from datetime import datetime
from flask import flash, redirect, url_for, abort, jsonify
from flask_login import current_user
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app import db
from contextlib import contextmanager
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)

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
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        try:
            result = f(*args, **kwargs)
            db.session.commit()
            return result
        except Exception as e:
            db.session.rollback()
            raise
        finally:
            db.session.remove()
    return decorated

def query_operation(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        try:
            return f(*args, **kwargs)
        finally:
            db.session.remove()
    return decorated

@contextmanager
def session_context():
    try:
        yield db.session
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    finally:
        db.session.remove()

def celery_task(bind_self=True, **celery_kwargs):
    def decorator(f: Callable) -> Callable:
        task_name = celery_kwargs.get('name') or f'app.tasks.{f.__module__}.{f.__name__}'
        default_kwargs = {
            'bind': bind_self,
            'max_retries': 3,
            'default_retry_delay': 60,
            'autoretry_for': (Exception,),
            'retry_backoff': True,
            'name': task_name
        }
        task_kwargs = {**default_kwargs, **celery_kwargs}
        
        @shared_task(**task_kwargs)
        @wraps(f)
        def wrapped_task(*args: Any, **kwargs: Any) -> Any:
            from app import create_app, db
            session_id = f"{task_name}-{datetime.utcnow().timestamp()}"
            
            app = create_app()
            with app.app_context():
                try:
                    logger.info(f"Starting task {task_name} (session: {session_id})")
                    result = f(*args, **kwargs) if not bind_self else f(args[0], *args[1:], **kwargs)
                    try:
                        db.session.commit()
                        logger.debug(f"Committed database changes for {task_name} (session: {session_id})")
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Database error in {task_name} (session: {session_id}): {str(e)}")
                        raise
                    return result
                except Exception as e:
                    logger.error(f"Error in {task_name} (session: {session_id}): {str(e)}", exc_info=True)
                    if bind_self:
                        raise args[0].retry(exc=e)
                    else:
                        raise e
                finally:
                    db.session.remove()
                    logger.debug(f"Cleaned up database session for {task_name} (session: {session_id})")
        return wrapped_task
    return decorator

def async_task(**celery_kwargs):
    def decorator(f: Callable) -> Callable:
        task_name = celery_kwargs.get('name') or f'app.tasks.{f.__module__}.{f.__name__}'
        
        @celery_task(**celery_kwargs)
        @wraps(f)
        def wrapped_task(self, *args: Any, **kwargs: Any) -> Any:
            import asyncio
            session_id = f"{task_name}-{datetime.utcnow().timestamp()}"
            
            try:
                logger.debug(f"Creating event loop for {task_name} (session: {session_id})")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                result = loop.run_until_complete(f(self, *args, **kwargs))
                return result
            except Exception as e:
                logger.error(f"Error in async task {task_name} (session: {session_id}): {str(e)}", 
                           exc_info=True)
                raise
            finally:
                loop.close()
                logger.debug(f"Closed event loop for {task_name} (session: {session_id})")
        return wrapped_task
    return decorator