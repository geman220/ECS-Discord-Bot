from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user

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
