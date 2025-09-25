# app/utils/substitute_decorators.py

"""
Substitute Management Permission Decorators

This module provides specialized decorators for substitute management endpoints
to handle role-based access control and permission validation.
"""

import logging
from functools import wraps
from typing import List, Optional

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.utils.substitute_helpers import (
    validate_league_type, get_user_substitute_permissions,
    can_user_respond_to_request, can_user_manage_team_subs
)

logger = logging.getLogger(__name__)


def substitute_pool_access_required(f):
    """
    Decorator to ensure user has access to substitute pool information.

    For most pool endpoints, this is just basic authentication.
    Admin-only operations are handled by separate role decorators.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Extract league_type from URL parameters
            league_type = kwargs.get('league_type')

            if not league_type or not validate_league_type(league_type):
                return jsonify({
                    'error': 'Invalid league type',
                    'valid_types': ['ECS FC', 'Classic', 'Premier']
                }), 400

            # Basic authentication is handled by @jwt_required()
            # This decorator just validates the league type
            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in substitute_pool_access_required: {e}")
            return jsonify({
                'error': 'Access validation failed',
                'message': str(e)
            }), 500

    return decorated_function


def substitute_request_access_required(f):
    """
    Decorator to ensure user has access to view substitute requests.

    Users can view:
    - Requests they created
    - Requests for teams they coach
    - Open requests for leagues they can substitute in
    - All requests if they're an admin
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())

            # Get user permissions - this will be used by the endpoint
            # to filter which requests the user can see
            from app.core import db
            with db.session() as session:
                permissions = get_user_substitute_permissions(current_user_id, session)

                if 'error' in permissions:
                    return jsonify({
                        'error': 'Permission check failed',
                        'message': permissions['error']
                    }), 500

            # Add permissions to request context for use in endpoint
            request.user_permissions = permissions

            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in substitute_request_access_required: {e}")
            return jsonify({
                'error': 'Access validation failed',
                'message': str(e)
            }), 500

    return decorated_function


def substitute_assignment_access_required(f):
    """
    Decorator to ensure user has access to view substitute assignments.

    Users can view:
    - Their own assignments
    - Assignments for teams they coach
    - All assignments if they're an admin
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())

            from app.core import db
            with db.session() as session:
                permissions = get_user_substitute_permissions(current_user_id, session)

                if 'error' in permissions:
                    return jsonify({
                        'error': 'Permission check failed',
                        'message': permissions['error']
                    }), 500

            # Add permissions to request context
            request.user_permissions = permissions

            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in substitute_assignment_access_required: {e}")
            return jsonify({
                'error': 'Access validation failed',
                'message': str(e)
            }), 500

    return decorated_function


def substitute_role_required(league_types: List[str]):
    """
    Decorator to require specific substitute roles for league types.

    Args:
        league_types (list): List of league types user must have substitute roles for

    Example:
        @substitute_role_required(['ECS FC', 'Classic'])
        def some_endpoint():
            # User must have both 'ECS FC Sub' and 'Classic Sub' roles
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                current_user_id = int(get_jwt_identity())

                from app.core import db
                with db.session() as session:
                    permissions = get_user_substitute_permissions(current_user_id, session)

                    if 'error' in permissions:
                        return jsonify({
                            'error': 'Permission check failed',
                            'message': permissions['error']
                        }), 500

                    # Check if user has required substitute roles
                    missing_roles = []
                    for league_type in league_types:
                        if not permissions.get('substitute_roles', {}).get(league_type, False):
                            missing_roles.append(f"{league_type} Sub")

                    if missing_roles:
                        return jsonify({
                            'error': 'Insufficient substitute permissions',
                            'missing_roles': missing_roles,
                            'message': 'Contact an administrator to get substitute access'
                        }), 403

                return f(*args, **kwargs)

            except Exception as e:
                logger.exception(f"Error in substitute_role_required: {e}")
                return jsonify({
                    'error': 'Permission validation failed',
                    'message': str(e)
                }), 500

        return decorated_function
    return decorator


def team_management_required(f):
    """
    Decorator to ensure user can manage substitute requests for a team.

    Expects 'team_id' in request data or URL parameters.

    Users can manage teams if they are:
    - Coaches of the specific team
    - Admins (can manage any team)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())

            # Try to get team_id from URL kwargs or request data
            team_id = kwargs.get('team_id')
            if not team_id:
                data = request.get_json() or {}
                team_id = data.get('team_id')

            if not team_id:
                return jsonify({
                    'error': 'team_id required'
                }), 400

            from app.core import db
            with db.session() as session:
                permissions = get_user_substitute_permissions(current_user_id, session)

                if 'error' in permissions:
                    return jsonify({
                        'error': 'Permission check failed',
                        'message': permissions['error']
                    }), 500

                if not can_user_manage_team_subs(current_user_id, team_id, permissions, session):
                    return jsonify({
                        'error': 'Access denied',
                        'message': 'You can only manage substitute requests for teams you coach'
                    }), 403

            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in team_management_required: {e}")
            return jsonify({
                'error': 'Permission validation failed',
                'message': str(e)
            }), 500

    return decorated_function


def substitute_response_permission_required(f):
    """
    Decorator to ensure user can respond to substitute requests.

    Expects 'league_type' in request data.

    Users can respond if they have the appropriate substitute role for the league.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())

            # Get league_type from request data
            data = request.get_json() or {}
            league_type = data.get('league_type')

            if not league_type:
                return jsonify({
                    'error': 'league_type required in request body'
                }), 400

            from app.core import db
            with db.session() as session:
                if not can_user_respond_to_request(current_user_id, league_type, session):
                    required_role = {
                        'ECS FC': 'ECS FC Sub',
                        'Classic': 'Classic Sub',
                        'Premier': 'Premier Sub'
                    }.get(league_type, 'Unknown')

                    return jsonify({
                        'error': 'Access denied',
                        'message': f'You need the {required_role} role to respond to {league_type} substitute requests',
                        'required_role': required_role
                    }), 403

            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in substitute_response_permission_required: {e}")
            return jsonify({
                'error': 'Permission validation failed',
                'message': str(e)
            }), 500

    return decorated_function


def pool_management_required(f):
    """
    Decorator to ensure user can manage substitute pools (admin only).

    Only users with Global Admin or Pub League Admin roles can manage pools.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())

            from app.core import db
            with db.session() as session:
                permissions = get_user_substitute_permissions(current_user_id, session)

                if 'error' in permissions:
                    return jsonify({
                        'error': 'Permission check failed',
                        'message': permissions['error']
                    }), 500

                if not permissions.get('can_manage_pools', False):
                    return jsonify({
                        'error': 'Admin access required',
                        'message': 'Only administrators can manage substitute pools',
                        'required_roles': ['Global Admin', 'Pub League Admin']
                    }), 403

            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in pool_management_required: {e}")
            return jsonify({
                'error': 'Permission validation failed',
                'message': str(e)
            }), 500

    return decorated_function


def assignment_management_required(f):
    """
    Decorator to ensure user can manage substitute assignments (admin only).

    Only users with Global Admin or Pub League Admin roles can assign/remove substitutes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())

            from app.core import db
            with db.session() as session:
                permissions = get_user_substitute_permissions(current_user_id, session)

                if 'error' in permissions:
                    return jsonify({
                        'error': 'Permission check failed',
                        'message': permissions['error']
                    }), 500

                if not permissions.get('can_manage_assignments', False):
                    return jsonify({
                        'error': 'Admin access required',
                        'message': 'Only administrators can manage substitute assignments',
                        'required_roles': ['Global Admin', 'Pub League Admin']
                    }), 403

            return f(*args, **kwargs)

        except Exception as e:
            logger.exception(f"Error in assignment_management_required: {e}")
            return jsonify({
                'error': 'Permission validation failed',
                'message': str(e)
            }), 500

    return decorated_function