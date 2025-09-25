# app/routes/mobile_substitute_api.py

"""
Mobile Substitute Management API Routes

This module provides comprehensive mobile API endpoints for substitute management
including pool management, request handling, responses, and assignments.

Architecture:
- Modular design with dedicated helper functions
- Role-based access control with custom decorators
- Comprehensive error handling and validation
- Support for both ECS FC and Pub League systems
- Scalable pagination and filtering
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_, func, desc

from app.core import db
from app.decorators import jwt_role_required
from app.models import User, Player, Role, Team, League, Season, Match
from app.models.matches import TemporarySubAssignment
from app.models.substitutes import (
    SubstitutePool, SubstitutePoolHistory, SubstituteRequest,
    SubstituteResponse, SubstituteAssignment, EcsFcSubRequest,
    EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool,
    get_eligible_players, get_active_substitutes, log_pool_action
)
from app.models_ecs import EcsFcMatch
from app.models.league_features import SubRequest
from app.utils.mobile_auth import api_key_required
from app.utils.substitute_helpers import (
    validate_league_type, get_user_substitute_permissions,
    format_substitute_pool_response, format_substitute_request_response,
    format_substitute_assignment_response, can_user_respond_to_request,
    can_user_manage_team_subs
)
from app.utils.api_validators import (
    validate_substitute_request_data, validate_substitute_response_data,
    validate_substitute_assignment_data, validate_pool_join_data,
    validate_pagination_params, sanitize_input_data, format_validation_error
)
from app.utils.substitute_decorators import (
    substitute_pool_access_required, substitute_request_access_required,
    substitute_assignment_access_required
)

logger = logging.getLogger(__name__)

# Create the blueprint
mobile_substitute_api = Blueprint('mobile_substitute_api', __name__)

# League type configuration
LEAGUE_TYPES = ['ECS FC', 'Classic', 'Premier']
LEAGUE_ROLE_MAPPING = {
    'ECS FC': 'ECS FC Sub',
    'Classic': 'Classic Sub',
    'Premier': 'Premier Sub'
}

# Status constants
REQUEST_STATUSES = ['OPEN', 'FILLED', 'CANCELLED', 'EXPIRED']
ASSIGNMENT_STATUSES = ['ACTIVE', 'COMPLETED', 'CANCELLED']


# =============================================================================
# SUBSTITUTE POOL ENDPOINTS
# =============================================================================

@mobile_substitute_api.route('/substitute-pools', methods=['GET'])
@jwt_required()
@api_key_required
def get_substitute_pools():
    """
    Get substitute pools for all league types or specific league.

    Query Parameters:
        league_type (str): Filter by league type (ECS FC, Classic, Premier)
        include_stats (bool): Include pool statistics (default: false)

    Returns:
        200: List of substitute pools with player information
        400: Invalid league type
        401: Authentication required
    """
    try:
        current_user_id = int(get_jwt_identity())
        league_type = request.args.get('league_type')
        include_stats = request.args.get('include_stats', 'false').lower() == 'true'

        # Validate league type if provided
        if league_type and not validate_league_type(league_type):
            return jsonify({
                'error': 'Invalid league type',
                'valid_types': LEAGUE_TYPES
            }), 400

        with db.session() as session:
            # Get user permissions
            permissions = get_user_substitute_permissions(current_user_id, session)

            # Build query
            query = session.query(SubstitutePool).options(
                joinedload(SubstitutePool.player).joinedload(Player.user),
                joinedload(SubstitutePool.league)
            ).filter(SubstitutePool.is_active == True)

            # Filter by league type if specified
            if league_type:
                query = query.filter(SubstitutePool.league_type == league_type)

            pools = query.all()

            # Format response
            response_data = []
            for pool in pools:
                pool_data = format_substitute_pool_response(
                    pool, include_stats=include_stats, permissions=permissions
                )
                response_data.append(pool_data)

            return jsonify({
                'success': True,
                'pools': response_data,
                'total': len(response_data),
                'user_permissions': permissions
            }), 200

    except Exception as e:
        logger.exception(f"Error fetching substitute pools: {e}")
        return jsonify({
            'error': 'Failed to fetch substitute pools',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-pools/<league_type>', methods=['GET'])
@jwt_required()
@api_key_required
@substitute_pool_access_required
def get_substitute_pool_details(league_type):
    """
    Get detailed information about a specific league's substitute pool.

    Path Parameters:
        league_type (str): League type (ECS FC, Classic, Premier)

    Query Parameters:
        include_history (bool): Include pool history (default: false)
        include_available (bool): Include available players not in pool (default: false)

    Returns:
        200: Detailed pool information
        400: Invalid league type
        403: Access denied
        404: Pool not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        include_history = request.args.get('include_history', 'false').lower() == 'true'
        include_available = request.args.get('include_available', 'false').lower() == 'true'

        with db.session() as session:
            permissions = get_user_substitute_permissions(current_user_id, session)

            # Get active pools for this league type
            pools = session.query(SubstitutePool).options(
                joinedload(SubstitutePool.player).joinedload(Player.user),
                joinedload(SubstitutePool.league)
            ).filter(
                SubstitutePool.league_type == league_type,
                SubstitutePool.is_active == True
            ).all()

            response_data = {
                'league_type': league_type,
                'active_pools': [
                    format_substitute_pool_response(pool, include_stats=True, permissions=permissions)
                    for pool in pools
                ],
                'total_active': len(pools)
            }

            # Include available players if requested and user has permission
            if include_available and permissions.get('can_manage_pools', False):
                eligible_players = get_eligible_players(league_type, session=session)
                active_player_ids = {pool.player_id for pool in pools}
                available_players = [
                    {
                        'id': p.id,
                        'name': p.name,
                        'user_id': p.user_id,
                        'email': p.user.email if p.user else None,
                        'pronouns': p.pronouns,
                        'positions': p.positions
                    }
                    for p in eligible_players
                    if p.id not in active_player_ids
                ]
                response_data['available_players'] = available_players
                response_data['total_available'] = len(available_players)

            # Include history if requested and user has permission
            if include_history and permissions.get('can_view_history', False):
                history = session.query(SubstitutePoolHistory).options(
                    joinedload(SubstitutePoolHistory.player),
                    joinedload(SubstitutePoolHistory.performer)
                ).filter(
                    SubstitutePoolHistory.league_id.in_([
                        pool.league_id for pool in pools if pool.league_id
                    ])
                ).order_by(desc(SubstitutePoolHistory.performed_at)).limit(50).all()

                response_data['recent_history'] = [
                    entry.to_dict() for entry in history
                ]

            return jsonify({
                'success': True,
                'data': response_data
            }), 200

    except Exception as e:
        logger.exception(f"Error fetching pool details for {league_type}: {e}")
        return jsonify({
            'error': 'Failed to fetch pool details',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-pools/<league_type>/join', methods=['POST'])
@jwt_required()
@api_key_required
def join_substitute_pool(league_type):
    """
    Request to join a substitute pool.

    Path Parameters:
        league_type (str): League type to join

    Request Body:
        preferred_positions (list): Preferred playing positions
        max_matches_per_week (int): Maximum matches per week
        notes (str): Additional notes
        notification_preferences (dict): SMS, email, discord preferences

    Returns:
        201: Successfully requested to join pool
        400: Invalid data or already in pool
        403: Access denied (user doesn't have required role)
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}

        # Sanitize input data
        data = sanitize_input_data(data)

        if not validate_league_type(league_type):
            return jsonify({
                'error': 'Invalid league type',
                'valid_types': LEAGUE_TYPES
            }), 400

        # Validate pool join data
        validation_error = validate_pool_join_data(data)
        if validation_error:
            return jsonify(format_validation_error(validation_error)), 400

        with db.session() as session:
            # Get user and player
            user = session.query(User).options(
                joinedload(User.roles),
                joinedload(User.player)
            ).get(current_user_id)

            if not user or not user.player:
                return jsonify({
                    'error': 'Player profile required to join substitute pool'
                }), 400

            # Check if user has required role
            required_role = LEAGUE_ROLE_MAPPING.get(league_type)
            if not any(role.name == required_role for role in user.roles):
                return jsonify({
                    'error': f'Required role missing: {required_role}',
                    'contact_admin': 'Please contact an administrator to get substitute access'
                }), 403

            # Check if already in pool
            existing_pool = session.query(SubstitutePool).filter_by(
                player_id=user.player.id,
                league_type=league_type,
                is_active=True
            ).first()

            if existing_pool:
                return jsonify({
                    'error': 'Already in substitute pool for this league',
                    'pool_id': existing_pool.id
                }), 400

            # Get league for this type
            league = session.query(League).filter_by(name=league_type).first()

            # Create pool entry
            pool_entry = SubstitutePool(
                player_id=user.player.id,
                league_type=league_type,
                league_id=league.id if league else None,
                preferred_positions=','.join(data.get('preferred_positions', [])),
                max_matches_per_week=data.get('max_matches_per_week', 3),
                notes=data.get('notes', ''),
                sms_for_sub_requests=data.get('notification_preferences', {}).get('sms', True),
                email_for_sub_requests=data.get('notification_preferences', {}).get('email', True),
                discord_for_sub_requests=data.get('notification_preferences', {}).get('discord', True),
                is_active=True,  # Auto-approve for now, can be changed to require admin approval
                approved_by=current_user_id,
                approved_at=datetime.utcnow()
            )

            session.add(pool_entry)

            # Log the action
            log_pool_action(
                player_id=user.player.id,
                league_id=league.id if league else None,
                action='JOINED_POOL',
                notes=f'Player joined {league_type} substitute pool',
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session
            )

            session.commit()

            return jsonify({
                'success': True,
                'message': f'Successfully joined {league_type} substitute pool',
                'pool_id': pool_entry.id,
                'status': 'active'
            }), 201

    except Exception as e:
        logger.exception(f"Error joining substitute pool {league_type}: {e}")
        return jsonify({
            'error': 'Failed to join substitute pool',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-pools/<league_type>/leave', methods=['POST'])
@jwt_required()
@api_key_required
def leave_substitute_pool(league_type):
    """
    Leave a substitute pool.

    Path Parameters:
        league_type (str): League type to leave

    Request Body:
        reason (str): Optional reason for leaving

    Returns:
        200: Successfully left pool
        400: Not in pool
        404: Pool not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}
        reason = data.get('reason', 'Player requested to leave pool')

        with db.session() as session:
            user = session.query(User).options(joinedload(User.player)).get(current_user_id)

            if not user or not user.player:
                return jsonify({'error': 'Player profile required'}), 400

            # Find active pool entry
            pool_entry = session.query(SubstitutePool).filter_by(
                player_id=user.player.id,
                league_type=league_type,
                is_active=True
            ).first()

            if not pool_entry:
                return jsonify({
                    'error': f'Not currently in {league_type} substitute pool'
                }), 400

            # Deactivate pool entry
            pool_entry.is_active = False
            pool_entry.last_active_at = datetime.utcnow()

            # Log the action
            log_pool_action(
                player_id=user.player.id,
                league_id=pool_entry.league_id,
                action='LEFT_POOL',
                notes=reason,
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session
            )

            session.commit()

            return jsonify({
                'success': True,
                'message': f'Successfully left {league_type} substitute pool'
            }), 200

    except Exception as e:
        logger.exception(f"Error leaving substitute pool {league_type}: {e}")
        return jsonify({
            'error': 'Failed to leave substitute pool',
            'message': str(e)
        }), 500


# =============================================================================
# SUBSTITUTE REQUEST ENDPOINTS
# =============================================================================

@mobile_substitute_api.route('/substitute-requests', methods=['GET'])
@jwt_required()
@api_key_required
def get_substitute_requests():
    """
    Get substitute requests based on user permissions.

    Query Parameters:
        status (str): Filter by status (OPEN, FILLED, CANCELLED, EXPIRED)
        league_type (str): Filter by league type
        team_id (int): Filter by team (coaches see their teams, admins see all)
        include_responses (bool): Include player responses (default: false)
        limit (int): Number of results (default: 50, max: 100)
        offset (int): Pagination offset (default: 0)

    Returns:
        200: List of substitute requests
        400: Invalid parameters
    """
    try:
        current_user_id = int(get_jwt_identity())

        # Parse query parameters
        status = request.args.get('status')
        league_type = request.args.get('league_type')
        team_id = request.args.get('team_id', type=int)
        include_responses = request.args.get('include_responses', 'false').lower() == 'true'
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = int(request.args.get('offset', 0))

        # Validate pagination parameters
        pagination_error = validate_pagination_params(limit, offset)
        if pagination_error:
            return jsonify(format_validation_error(pagination_error)), 400

        # Validate parameters
        if status and status not in REQUEST_STATUSES:
            return jsonify({
                'error': 'Invalid status',
                'valid_statuses': REQUEST_STATUSES
            }), 400

        if league_type and not validate_league_type(league_type):
            return jsonify({
                'error': 'Invalid league type',
                'valid_types': LEAGUE_TYPES
            }), 400

        with db.session() as session:
            permissions = get_user_substitute_permissions(current_user_id, session)

            # Use legacy SubRequest table (what the web admin uses)
            legacy_query = session.query(SubRequest).options(
                joinedload(SubRequest.match),
                joinedload(SubRequest.team).joinedload(Team.league)
            )

            # Apply filters based on permissions
            if not permissions.get('can_manage_all_requests', False):
                # Limit to user's teams if they're a coach
                user_team_ids = permissions.get('coach_team_ids', [])
                if user_team_ids:
                    legacy_query = legacy_query.filter(SubRequest.team_id.in_(user_team_ids))
                else:
                    # Regular users see open requests they can respond to
                    legacy_query = legacy_query.filter(SubRequest.status.in_(['PENDING', 'OPEN']))

            # Apply status filter - map status values
            if status:
                # Map mobile API status to legacy status
                status_mapping = {
                    'OPEN': ['PENDING', 'OPEN'],
                    'FILLED': ['FULFILLED', 'FILLED'],
                    'CANCELLED': ['CANCELLED'],
                    'EXPIRED': ['EXPIRED']
                }
                legacy_statuses = status_mapping.get(status, [status])
                legacy_query = legacy_query.filter(SubRequest.status.in_(legacy_statuses))

            if team_id:
                legacy_query = legacy_query.filter(SubRequest.team_id == team_id)

            # Apply league type filter if specified
            if league_type:
                legacy_query = legacy_query.join(Match).join(Team).join(League).filter(
                    League.name == league_type
                )

            legacy_requests = legacy_query.order_by(
                desc(SubRequest.created_at)
            ).limit(limit).offset(offset).all()

            # Format response data
            response_data = []

            # Add legacy requests and format them for mobile API
            for req in legacy_requests:
                # Determine league type from team
                league_name = req.team.league.name if req.team and req.team.league else 'Unknown'

                # Format the legacy request to match mobile API structure
                req_data = {
                    'id': req.id,
                    'match_id': req.match_id,
                    'team_id': req.team_id,
                    'league_type': league_name,
                    'status': req.status,
                    'substitutes_needed': req.substitutes_needed or 1,
                    'positions_needed': 'Any',  # SubRequest doesn't track position, default to Any
                    'gender_preference': None,
                    'notes': req.notes,
                    'created_at': req.created_at.isoformat() if req.created_at else None,
                    'updated_at': req.updated_at.isoformat() if req.updated_at else None,
                    'expires_at': None,  # Legacy doesn't have expiration

                    # Team information
                    'team': {
                        'id': req.team.id,
                        'name': req.team.name,
                        'league_id': req.team.league_id,
                        'league_name': league_name
                    } if req.team else None,

                    # Match information
                    'match': {
                        'id': req.match.id,
                        'date': req.match.date.isoformat() if req.match and req.match.date else None,
                        'time': str(req.match.time) if req.match and req.match.time else None,
                        'home_team_id': req.match.home_team_id if req.match else None,
                        'away_team_id': req.match.away_team_id if req.match else None
                    } if req.match else None,

                    # Requester information (if available)
                    'requester': None,  # Legacy doesn't track requester

                    # Responses (if requested)
                    'responses': [] if include_responses else None
                }

                response_data.append(req_data)

            # Sort by creation date (most recent first)
            response_data.sort(key=lambda x: x.get('created_at', ''), reverse=True)

            return jsonify({
                'success': True,
                'requests': response_data,
                'total': len(response_data),
                'pagination': {
                    'limit': limit,
                    'offset': offset,
                    'has_more': len(response_data) == limit
                },
                'user_permissions': permissions
            }), 200

    except Exception as e:
        logger.exception(f"Error fetching substitute requests: {e}")
        return jsonify({
            'error': 'Failed to fetch substitute requests',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-requests', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach', 'ECS FC Coach'])
def create_substitute_request():
    """
    Create a new substitute request.

    Request Body:
        match_id (int): Match ID
        team_id (int): Team ID
        league_type (str): League type (ECS FC, Classic, Premier)
        positions_needed (str): Positions needed (optional)
        gender_preference (str): Gender preference (optional)
        substitutes_needed (int): Number of substitutes needed (default: 1)
        notes (str): Additional notes (optional)

    Returns:
        201: Request created successfully
        400: Invalid data
        403: Access denied
        409: Request already exists
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body required'}), 400

        # Validate required fields
        validation_error = validate_substitute_request_data(data)
        if validation_error:
            return jsonify({'error': validation_error}), 400

        match_id = data['match_id']
        team_id = data['team_id']
        league_type = data['league_type']

        with db.session() as session:
            permissions = get_user_substitute_permissions(current_user_id, session)

            # Check if user can create requests for this team
            if not can_user_manage_team_subs(current_user_id, team_id, permissions, session):
                return jsonify({
                    'error': 'Access denied',
                    'message': 'You can only create substitute requests for teams you coach'
                }), 403

            # Handle ECS FC requests
            if league_type == 'ECS FC':
                # Check if match exists
                match = session.query(EcsFcMatch).get(match_id)
                if not match:
                    return jsonify({'error': 'ECS FC match not found'}), 404

                # Check for existing request
                existing = session.query(EcsFcSubRequest).filter_by(
                    match_id=match_id,
                    team_id=team_id,
                    status='OPEN'
                ).first()

                if existing:
                    return jsonify({
                        'error': 'Open substitute request already exists for this match and team'
                    }), 409

                # Create ECS FC request
                sub_request = EcsFcSubRequest(
                    match_id=match_id,
                    team_id=team_id,
                    requested_by=current_user_id,
                    positions_needed=data.get('positions_needed'),
                    notes=data.get('notes'),
                    substitutes_needed=data.get('substitutes_needed', 1),
                    status='OPEN'
                )

            else:
                # Handle Pub League requests
                # Check if match exists
                match = session.query(Match).get(match_id)
                if not match:
                    return jsonify({'error': 'Match not found'}), 404

                # Check for existing request
                existing = session.query(SubstituteRequest).filter_by(
                    match_id=match_id,
                    team_id=team_id,
                    status='OPEN'
                ).first()

                if existing:
                    return jsonify({
                        'error': 'Open substitute request already exists for this match and team'
                    }), 409

                # Create Pub League request
                sub_request = SubstituteRequest(
                    match_id=match_id,
                    team_id=team_id,
                    requested_by=current_user_id,
                    positions_needed=data.get('positions_needed'),
                    gender_preference=data.get('gender_preference'),
                    notes=data.get('notes'),
                    substitutes_needed=data.get('substitutes_needed', 1),
                    status='OPEN'
                )

            session.add(sub_request)
            session.commit()

            # TODO: Send notifications to substitute pool
            # This would be handled by a background task

            response_data = format_substitute_request_response(
                sub_request, league_type, include_responses=False,
                permissions=permissions, session=session
            )

            return jsonify({
                'success': True,
                'message': 'Substitute request created successfully',
                'request': response_data
            }), 201

    except Exception as e:
        logger.exception(f"Error creating substitute request: {e}")
        return jsonify({
            'error': 'Failed to create substitute request',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-requests/<int:request_id>/respond', methods=['POST'])
@jwt_required()
@api_key_required
def respond_to_substitute_request(request_id):
    """
    Respond to a substitute request with availability.

    Path Parameters:
        request_id (int): Request ID

    Request Body:
        is_available (bool): Whether player is available
        response_text (str): Optional response message
        league_type (str): League type (ECS FC, Classic, Premier)

    Returns:
        201: Response recorded successfully
        400: Invalid data
        403: Access denied
        404: Request not found
        409: Already responded
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json()

        if not data or 'is_available' not in data or 'league_type' not in data:
            return jsonify({
                'error': 'Required fields: is_available, league_type'
            }), 400

        is_available = data['is_available']
        response_text = data.get('response_text', '')
        league_type = data['league_type']

        with db.session() as session:
            user = session.query(User).options(joinedload(User.player)).get(current_user_id)

            if not user or not user.player:
                return jsonify({'error': 'Player profile required'}), 400

            # Check if user can respond to this type of request
            if not can_user_respond_to_request(current_user_id, league_type, session):
                return jsonify({
                    'error': f'Access denied',
                    'message': f'You need the {LEAGUE_ROLE_MAPPING.get(league_type)} role to respond to {league_type} substitute requests'
                }), 403

            # Find the request
            if league_type == 'ECS FC':
                sub_request = session.query(EcsFcSubRequest).get(request_id)
                if not sub_request:
                    return jsonify({'error': 'ECS FC substitute request not found'}), 404

                # Check for existing response
                existing_response = session.query(EcsFcSubResponse).filter_by(
                    request_id=request_id,
                    player_id=user.player.id
                ).first()

                if existing_response:
                    return jsonify({
                        'error': 'You have already responded to this request'
                    }), 409

                # Create response
                response = EcsFcSubResponse(
                    request_id=request_id,
                    player_id=user.player.id,
                    is_available=is_available,
                    response_method='mobile_app',
                    response_text=response_text
                )

            else:
                sub_request = session.query(SubstituteRequest).get(request_id)
                if not sub_request:
                    return jsonify({'error': 'Substitute request not found'}), 404

                # Check for existing response
                existing_response = session.query(SubstituteResponse).filter_by(
                    request_id=request_id,
                    player_id=user.player.id
                ).first()

                if existing_response:
                    return jsonify({
                        'error': 'You have already responded to this request'
                    }), 409

                # Create response
                response = SubstituteResponse(
                    request_id=request_id,
                    player_id=user.player.id,
                    is_available=is_available,
                    response_method='mobile_app',
                    response_text=response_text
                )

            session.add(response)
            session.commit()

            return jsonify({
                'success': True,
                'message': 'Response recorded successfully',
                'response': {
                    'id': response.id,
                    'is_available': response.is_available,
                    'response_text': response.response_text,
                    'responded_at': response.responded_at.isoformat()
                }
            }), 201

    except Exception as e:
        logger.exception(f"Error responding to substitute request {request_id}: {e}")
        return jsonify({
            'error': 'Failed to record response',
            'message': str(e)
        }), 500


# =============================================================================
# SUBSTITUTE ASSIGNMENT ENDPOINTS (Admin Only)
# =============================================================================

@mobile_substitute_api.route('/substitute-assignments', methods=['GET'])
@jwt_required()
@api_key_required
def get_substitute_assignments():
    """
    Get substitute assignments based on user permissions.

    Query Parameters:
        status (str): Filter by status (ACTIVE, COMPLETED, CANCELLED)
        league_type (str): Filter by league type
        team_id (int): Filter by team
        player_id (int): Filter by player (users can see their own)
        limit (int): Number of results (default: 50)
        offset (int): Pagination offset (default: 0)

    Returns:
        200: List of substitute assignments
        400: Invalid parameters
    """
    try:
        current_user_id = int(get_jwt_identity())

        # Parse query parameters
        status = request.args.get('status')
        league_type = request.args.get('league_type')
        team_id = request.args.get('team_id', type=int)
        player_id = request.args.get('player_id', type=int)
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = int(request.args.get('offset', 0))

        with db.session() as session:
            permissions = get_user_substitute_permissions(current_user_id, session)
            user = session.query(User).options(joinedload(User.player)).get(current_user_id)

            # Get ECS FC assignments
            ecs_assignments = []
            if not league_type or league_type == 'ECS FC':
                ecs_query = session.query(EcsFcSubAssignment).options(
                    joinedload(EcsFcSubAssignment.request).joinedload(EcsFcSubRequest.match),
                    joinedload(EcsFcSubAssignment.player),
                    joinedload(EcsFcSubAssignment.assigner)
                )

                # Apply filters based on permissions
                if not permissions.get('can_manage_assignments', False):
                    # Regular users can only see their own assignments
                    if user and user.player:
                        ecs_query = ecs_query.filter(EcsFcSubAssignment.player_id == user.player.id)
                    else:
                        ecs_assignments = []  # No assignments if no player profile

                if player_id:
                    ecs_query = ecs_query.filter(EcsFcSubAssignment.player_id == player_id)

                if team_id:
                    ecs_query = ecs_query.join(EcsFcSubRequest).filter(
                        EcsFcSubRequest.team_id == team_id
                    )

                if ecs_query:
                    ecs_assignments = ecs_query.order_by(
                        desc(EcsFcSubAssignment.assigned_at)
                    ).limit(limit).offset(offset).all()

            # Get Pub League assignments
            pub_assignments = []
            if not league_type or league_type in ['Classic', 'Premier']:
                pub_query = session.query(SubstituteAssignment).options(
                    joinedload(SubstituteAssignment.request).joinedload(SubstituteRequest.match),
                    joinedload(SubstituteAssignment.player),
                    joinedload(SubstituteAssignment.assigner)
                )

                # Apply filters based on permissions
                if not permissions.get('can_manage_assignments', False):
                    if user and user.player:
                        pub_query = pub_query.filter(SubstituteAssignment.player_id == user.player.id)
                    else:
                        pub_assignments = []

                if player_id:
                    pub_query = pub_query.filter(SubstituteAssignment.player_id == player_id)

                if team_id:
                    pub_query = pub_query.join(SubstituteRequest).filter(
                        SubstituteRequest.team_id == team_id
                    )

                if league_type and league_type != 'ECS FC':
                    # Filter by league type through match
                    pub_query = pub_query.join(SubstituteRequest).join(Match).join(Team).join(League).filter(
                        League.name == league_type
                    )

                if pub_query:
                    pub_assignments = pub_query.order_by(
                        desc(SubstituteAssignment.assigned_at)
                    ).limit(limit).offset(offset).all()

            # Format responses
            response_data = []

            # Add ECS FC assignments
            for assignment in ecs_assignments:
                assignment_data = format_substitute_assignment_response(
                    assignment, 'ECS FC', permissions=permissions
                )
                response_data.append(assignment_data)

            # Add Pub League assignments
            for assignment in pub_assignments:
                # Determine league type
                league_name = 'Unknown'
                if assignment.request and assignment.request.match and assignment.request.match.home_team:
                    league_name = assignment.request.match.home_team.league.name

                assignment_data = format_substitute_assignment_response(
                    assignment, league_name, permissions=permissions
                )
                response_data.append(assignment_data)

            # Sort by assignment date (most recent first)
            response_data.sort(key=lambda x: x.get('assigned_at', ''), reverse=True)

            return jsonify({
                'success': True,
                'assignments': response_data,
                'total': len(response_data),
                'pagination': {
                    'limit': limit,
                    'offset': offset,
                    'has_more': len(response_data) == limit
                },
                'user_permissions': permissions
            }), 200

    except Exception as e:
        logger.exception(f"Error fetching substitute assignments: {e}")
        return jsonify({
            'error': 'Failed to fetch substitute assignments',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-requests/<int:request_id>/assign', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def assign_substitute(request_id):
    """
    Assign a substitute to fulfill a request (Admin only).

    Path Parameters:
        request_id (int): Request ID

    Request Body:
        player_id (int): Player to assign
        league_type (str): League type (ECS FC, Classic, Premier)
        position_assigned (str): Position assigned (optional)
        notes (str): Assignment notes (optional)

    Returns:
        201: Assignment created successfully
        400: Invalid data
        403: Access denied
        404: Request or player not found
        409: Assignment already exists
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json()

        if not data or 'player_id' not in data or 'league_type' not in data:
            return jsonify({
                'error': 'Required fields: player_id, league_type'
            }), 400

        player_id = data['player_id']
        league_type = data['league_type']
        position_assigned = data.get('position_assigned')
        notes = data.get('notes', '')

        with db.session() as session:
            # Verify player exists
            player = session.query(Player).get(player_id)
            if not player:
                return jsonify({'error': 'Player not found'}), 404

            # Find the request and create assignment
            if league_type == 'ECS FC':
                sub_request = session.query(EcsFcSubRequest).get(request_id)
                if not sub_request:
                    return jsonify({'error': 'ECS FC substitute request not found'}), 404

                # Check for existing assignment
                existing = session.query(EcsFcSubAssignment).filter_by(
                    request_id=request_id,
                    player_id=player_id
                ).first()

                if existing:
                    return jsonify({'error': 'Assignment already exists'}), 409

                # Create assignment
                assignment = EcsFcSubAssignment(
                    request_id=request_id,
                    player_id=player_id,
                    assigned_by=current_user_id,
                    position_assigned=position_assigned,
                    notes=notes
                )

            else:
                # First try the new SubstituteRequest table
                sub_request = session.query(SubstituteRequest).get(request_id)

                if not sub_request:
                    # If not found, check the legacy SubRequest table
                    legacy_request = session.query(SubRequest).get(request_id)
                    if not legacy_request:
                        return jsonify({'error': 'Substitute request not found'}), 404

                    # For legacy requests, we'll create a TemporarySubAssignment instead
                    # since the legacy system uses a different assignment model

                    # Check for existing legacy assignment
                    existing_temp = session.query(TemporarySubAssignment).filter_by(
                        match_id=legacy_request.match_id,
                        player_id=player_id,
                        team_id=legacy_request.team_id
                    ).first()

                    if existing_temp:
                        return jsonify({'error': 'Assignment already exists'}), 409

                    # Create temporary assignment for legacy request
                    assignment = TemporarySubAssignment(
                        match_id=legacy_request.match_id,
                        player_id=player_id,
                        team_id=legacy_request.team_id,
                        assigned_by=current_user_id
                    )

                    session.add(assignment)

                    # Update legacy request status
                    legacy_request.status = 'FULFILLED'

                    session.commit()

                    return jsonify({
                        'success': True,
                        'message': 'Substitute assigned successfully (legacy)',
                        'assignment': {
                            'id': assignment.id,
                            'match_id': assignment.match_id,
                            'player_id': assignment.player_id,
                            'team_id': assignment.team_id,
                            'position_assigned': position_assigned,  # Include requested position even if not stored
                            'notes': notes or f'Assigned via mobile app to substitute request {request_id}',
                            'assigned_at': assignment.created_at.isoformat()
                        }
                    }), 201

                else:
                    # Handle new SubstituteRequest normally
                    # Check for existing assignment
                    existing = session.query(SubstituteAssignment).filter_by(
                        request_id=request_id,
                        player_id=player_id
                    ).first()

                    if existing:
                        return jsonify({'error': 'Assignment already exists'}), 409

                    # Create assignment
                    assignment = SubstituteAssignment(
                        request_id=request_id,
                        player_id=player_id,
                        assigned_by=current_user_id,
                        position_assigned=position_assigned,
                        notes=notes
                    )

                    session.add(assignment)

                    # Update request status if all positions filled
                    current_assignments = session.query(
                        type(assignment)
                    ).filter_by(request_id=request_id).count() + 1  # +1 for the new assignment

                    if current_assignments >= sub_request.substitutes_needed:
                        sub_request.status = 'FILLED'
                        sub_request.filled_at = datetime.utcnow()

                    session.commit()

                    # TODO: Send notification to assigned player

                    permissions = get_user_substitute_permissions(current_user_id, session)
                    assignment_data = format_substitute_assignment_response(
                        assignment, league_type, permissions=permissions
                    )

                    return jsonify({
                        'success': True,
                        'message': 'Substitute assigned successfully',
                        'assignment': assignment_data
                    }), 201

    except Exception as e:
        logger.exception(f"Error assigning substitute to request {request_id}: {e}")
        return jsonify({
            'error': 'Failed to assign substitute',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-assignments/<int:assignment_id>', methods=['DELETE'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def remove_substitute_assignment(assignment_id):
    """
    Remove a substitute assignment (Admin only).

    Path Parameters:
        assignment_id (int): Assignment ID

    Request Body:
        league_type (str): League type (ECS FC, Classic, Premier)
        reason (str): Reason for removal (optional)

    Returns:
        200: Assignment removed successfully
        400: Invalid data
        403: Access denied
        404: Assignment not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}

        league_type = data.get('league_type')
        reason = data.get('reason', 'Assignment removed by admin')

        if not league_type:
            return jsonify({'error': 'league_type required'}), 400

        with db.session() as session:
            # Find and remove assignment
            if league_type == 'ECS FC':
                assignment = session.query(EcsFcSubAssignment).options(
                    joinedload(EcsFcSubAssignment.request)
                ).get(assignment_id)
            else:
                assignment = session.query(SubstituteAssignment).options(
                    joinedload(SubstituteAssignment.request)
                ).get(assignment_id)

            if not assignment:
                return jsonify({'error': 'Assignment not found'}), 404

            # Update request status back to OPEN if it was FILLED
            if assignment.request and assignment.request.status == 'FILLED':
                remaining_assignments = session.query(
                    type(assignment)
                ).filter_by(request_id=assignment.request_id).count() - 1  # -1 for the one being removed

                if remaining_assignments < assignment.request.substitutes_needed:
                    assignment.request.status = 'OPEN'
                    assignment.request.filled_at = None

            session.delete(assignment)
            session.commit()

            return jsonify({
                'success': True,
                'message': 'Assignment removed successfully'
            }), 200

    except Exception as e:
        logger.exception(f"Error removing substitute assignment {assignment_id}: {e}")
        return jsonify({
            'error': 'Failed to remove assignment',
            'message': str(e)
        }), 500


# =============================================================================
# POOL MANAGEMENT ENDPOINTS (Admin Only)
# =============================================================================

@mobile_substitute_api.route('/substitute-pools/<league_type>/approve/<int:player_id>', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def approve_pool_member(league_type, player_id):
    """
    Approve a player for the substitute pool (Admin only).

    Path Parameters:
        league_type (str): League type
        player_id (int): Player ID

    Request Body:
        notes (str): Approval notes (optional)

    Returns:
        200: Player approved successfully
        400: Invalid data
        404: Player or pool entry not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}
        notes = data.get('notes', f'Approved for {league_type} substitute pool')

        with db.session() as session:
            # Find pending pool entry
            pool_entry = session.query(SubstitutePool).filter_by(
                player_id=player_id,
                league_type=league_type,
                approved_at=None
            ).first()

            if not pool_entry:
                return jsonify({
                    'error': 'Pending pool entry not found for this player'
                }), 404

            # Approve the entry
            pool_entry.approved_by = current_user_id
            pool_entry.approved_at = datetime.utcnow()
            pool_entry.is_active = True

            # Log the action
            log_pool_action(
                player_id=player_id,
                league_id=pool_entry.league_id,
                action='APPROVED',
                notes=notes,
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session
            )

            session.commit()

            return jsonify({
                'success': True,
                'message': f'Player approved for {league_type} substitute pool'
            }), 200

    except Exception as e:
        logger.exception(f"Error approving pool member {player_id} for {league_type}: {e}")
        return jsonify({
            'error': 'Failed to approve pool member',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitute-pools/<league_type>/remove/<int:player_id>', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def remove_pool_member(league_type, player_id):
    """
    Remove a player from the substitute pool (Admin only).

    Path Parameters:
        league_type (str): League type
        player_id (int): Player ID

    Request Body:
        reason (str): Reason for removal

    Returns:
        200: Player removed successfully
        400: Invalid data
        404: Pool entry not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}
        reason = data.get('reason', 'Removed by admin')

        with db.session() as session:
            # Find active pool entry
            pool_entry = session.query(SubstitutePool).filter_by(
                player_id=player_id,
                league_type=league_type,
                is_active=True
            ).first()

            if not pool_entry:
                return jsonify({
                    'error': 'Active pool entry not found for this player'
                }), 404

            # Deactivate the entry
            pool_entry.is_active = False
            pool_entry.last_active_at = datetime.utcnow()

            # Log the action
            log_pool_action(
                player_id=player_id,
                league_id=pool_entry.league_id,
                action='REMOVED_BY_ADMIN',
                notes=reason,
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session
            )

            session.commit()

            return jsonify({
                'success': True,
                'message': f'Player removed from {league_type} substitute pool'
            }), 200

    except Exception as e:
        logger.exception(f"Error removing pool member {player_id} from {league_type}: {e}")
        return jsonify({
            'error': 'Failed to remove pool member',
            'message': str(e)
        }), 500