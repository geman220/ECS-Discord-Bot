# app/role_impersonation.py

"""
Role Impersonation Module

This module provides functionality for administrators to temporarily view the application
as if they have different roles or permissions. This is useful for testing role-based
access control without having to create test accounts or switch between accounts.
"""

import logging
from flask import Blueprint, request, jsonify, session, redirect, url_for, g
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.models import Role, Permission
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user
from app.alert_helpers import show_error

logger = logging.getLogger(__name__)
role_impersonation_bp = Blueprint('role_impersonation', __name__)

# Session keys for impersonation
IMPERSONATION_ACTIVE_KEY = 'role_impersonation_active'
IMPERSONATED_ROLES_KEY = 'impersonated_roles' 
IMPERSONATED_PERMISSIONS_KEY = 'impersonated_permissions'
ORIGINAL_ROLES_KEY = 'original_roles'


def is_impersonation_active():
    """Check if role impersonation is currently active."""
    return session.get(IMPERSONATION_ACTIVE_KEY, False)


def get_impersonated_roles():
    """Get the currently impersonated roles."""
    if is_impersonation_active():
        return session.get(IMPERSONATED_ROLES_KEY, [])
    return None


def get_impersonated_permissions():
    """Get the currently impersonated permissions."""
    if is_impersonation_active():
        return session.get(IMPERSONATED_PERMISSIONS_KEY, [])
    return None


def get_effective_roles():
    """Get the effective roles (impersonated if active, otherwise real roles)."""
    if is_impersonation_active():
        return get_impersonated_roles()
    else:
        if safe_current_user.is_authenticated:
            return [role.name for role in safe_current_user.roles]
        return []


def get_effective_permissions():
    """Get the effective permissions (impersonated if active, otherwise real permissions)."""
    if is_impersonation_active():
        return get_impersonated_permissions()
    else:
        if safe_current_user.is_authenticated:
            return [
                permission.name
                for role in safe_current_user.roles
                for permission in role.permissions
            ]
        return []


def has_effective_permission(permission_name):
    """Check if user has a permission (considering impersonation)."""
    return permission_name in get_effective_permissions()


def has_effective_role(role_name):
    """Check if user has a role (considering impersonation)."""
    return role_name in get_effective_roles()


@role_impersonation_bp.route('/api/role-impersonation/available-roles', methods=['GET'])
@login_required
@role_required(['Global Admin'])
def get_available_roles():
    """Get all available roles that can be impersonated."""
    try:
        session_db = g.db_session
        roles = session_db.query(Role).options(
            joinedload(Role.permissions)
        ).all()
        
        role_list = []
        for role in roles:
            permissions = [perm.name for perm in role.permissions]
            role_list.append({
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'permissions': permissions
            })
        
        return jsonify({
            'roles': role_list,
            'current_impersonation': {
                'active': is_impersonation_active(),
                'roles': get_impersonated_roles() if is_impersonation_active() else [],
                'original_roles': session.get(ORIGINAL_ROLES_KEY, [])
            }
        })
        
    except Exception as e:
        logger.exception("Error fetching available roles for impersonation")
        return jsonify({'error': 'Failed to fetch available roles'}), 500


@role_impersonation_bp.route('/api/role-impersonation/start', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def start_impersonation():
    """Start role impersonation with specified roles."""
    try:
        data = request.get_json()
        role_names = data.get('roles', [])
        
        if not role_names:
            return jsonify({'error': 'No roles specified'}), 400
        
        session_db = g.db_session
        
        # Validate that all specified roles exist
        roles = session_db.query(Role).options(
            joinedload(Role.permissions)
        ).filter(Role.name.in_(role_names)).all()
        
        if len(roles) != len(role_names):
            found_roles = [role.name for role in roles]
            missing_roles = [name for name in role_names if name not in found_roles]
            return jsonify({'error': f'Roles not found: {missing_roles}'}), 400
        
        # Store original roles if not already impersonating
        if not is_impersonation_active():
            original_roles = [role.name for role in safe_current_user.roles]
            session[ORIGINAL_ROLES_KEY] = original_roles
        
        # Calculate permissions for the impersonated roles
        impersonated_permissions = []
        for role in roles:
            for permission in role.permissions:
                if permission.name not in impersonated_permissions:
                    impersonated_permissions.append(permission.name)
        
        # Set impersonation session data
        session[IMPERSONATION_ACTIVE_KEY] = True
        session[IMPERSONATED_ROLES_KEY] = role_names
        session[IMPERSONATED_PERMISSIONS_KEY] = impersonated_permissions
        
        logger.info(f"Admin {safe_current_user.username} started role impersonation: {role_names}")
        
        return jsonify({
            'message': 'Role impersonation started',
            'impersonated_roles': role_names,
            'impersonated_permissions': impersonated_permissions
        })
        
    except Exception as e:
        logger.exception("Error starting role impersonation")
        return jsonify({'error': 'Failed to start role impersonation'}), 500


@role_impersonation_bp.route('/api/role-impersonation/stop', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def stop_impersonation():
    """Stop role impersonation and return to original roles."""
    try:
        if not is_impersonation_active():
            return jsonify({'message': 'No active impersonation to stop'})
        
        original_roles = session.get(ORIGINAL_ROLES_KEY, [])
        
        # Clear impersonation session data
        session.pop(IMPERSONATION_ACTIVE_KEY, None)
        session.pop(IMPERSONATED_ROLES_KEY, None)
        session.pop(IMPERSONATED_PERMISSIONS_KEY, None)
        session.pop(ORIGINAL_ROLES_KEY, None)
        
        logger.info(f"Admin {safe_current_user.username} stopped role impersonation")
        
        return jsonify({
            'message': 'Role impersonation stopped',
            'restored_roles': original_roles
        })
        
    except Exception as e:
        logger.exception("Error stopping role impersonation")
        return jsonify({'error': 'Failed to stop role impersonation'}), 500


@role_impersonation_bp.route('/stop-impersonation', methods=['POST'])
@login_required
def stop_impersonation_form():
    """Stop role impersonation via form submission (for the banner button)."""
    try:
        # Check REAL user roles (not impersonated), since we need to stop impersonation
        real_user_roles = [role.name for role in safe_current_user.roles] if safe_current_user.is_authenticated else []
        if 'Global Admin' not in real_user_roles:
            show_error('Access denied: Only Global Admins can use role impersonation.')
            return redirect(request.referrer or '/')
        
        if not is_impersonation_active():
            return redirect(request.referrer or '/')
        
        # Clear impersonation session data
        session.pop(IMPERSONATION_ACTIVE_KEY, None)
        session.pop(IMPERSONATED_ROLES_KEY, None)
        session.pop(IMPERSONATED_PERMISSIONS_KEY, None)
        session.pop(ORIGINAL_ROLES_KEY, None)
        
        logger.info(f"Admin {safe_current_user.username} stopped role impersonation via form")
        
        # Redirect back to the same page
        return redirect(request.referrer or '/')
        
    except Exception as e:
        logger.exception("Error stopping role impersonation via form")
        return redirect(request.referrer or '/')


@role_impersonation_bp.route('/debug-roles', methods=['GET'])
@login_required
def debug_roles():
    """Debug endpoint to see current vs impersonated roles."""
    from app.role_impersonation import is_impersonation_active, get_effective_roles, get_effective_permissions
    
    try:
        real_roles = [role.name for role in safe_current_user.roles] if safe_current_user.is_authenticated else []
        effective_roles = get_effective_roles()
        effective_permissions = get_effective_permissions()
        
        return jsonify({
            'impersonation_active': is_impersonation_active(),
            'real_roles': real_roles,
            'effective_roles': effective_roles,
            'effective_permissions': effective_permissions,
            'session_data': {
                'impersonation_active': session.get(IMPERSONATION_ACTIVE_KEY, False),
                'impersonated_roles': session.get(IMPERSONATED_ROLES_KEY, []),
                'impersonated_permissions': session.get(IMPERSONATED_PERMISSIONS_KEY, []),
                'original_roles': session.get(ORIGINAL_ROLES_KEY, [])
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@role_impersonation_bp.route('/api/role-impersonation/status', methods=['GET'])
@login_required
@role_required(['Global Admin'])
def get_impersonation_status():
    """Get current impersonation status."""
    try:
        return jsonify({
            'active': is_impersonation_active(),
            'impersonated_roles': get_impersonated_roles() if is_impersonation_active() else [],
            'impersonated_permissions': get_impersonated_permissions() if is_impersonation_active() else [],
            'original_roles': session.get(ORIGINAL_ROLES_KEY, []),
            'effective_roles': get_effective_roles(),
            'effective_permissions': get_effective_permissions()
        })
        
    except Exception as e:
        logger.exception("Error getting impersonation status")
        return jsonify({'error': 'Failed to get impersonation status'}), 500