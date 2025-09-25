# app/utils/substitute_helpers.py

"""
Substitute Management Helper Functions

This module provides utility functions for substitute management including
permission checking, data validation, response formatting, and business logic.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_

from app.models import User, Player, Role, Team, League
from app.models.substitutes import (
    SubstitutePool, SubstituteRequest, SubstituteResponse, SubstituteAssignment,
    EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
)

logger = logging.getLogger(__name__)

# Constants
LEAGUE_TYPES = ['ECS FC', 'Classic', 'Premier']
LEAGUE_ROLE_MAPPING = {
    'ECS FC': 'ECS FC Sub',
    'Classic': 'Classic Sub',
    'Premier': 'Premier Sub'
}

ADMIN_ROLES = ['Global Admin', 'Pub League Admin']
COACH_ROLES = ['Pub League Coach', 'ECS FC Coach']


def validate_league_type(league_type: str) -> bool:
    """
    Validate if the provided league type is valid.

    Args:
        league_type (str): League type to validate

    Returns:
        bool: True if valid, False otherwise
    """
    return league_type in LEAGUE_TYPES


def get_user_substitute_permissions(user_id: int, session) -> Dict[str, Any]:
    """
    Get substitute-related permissions for a user.

    Args:
        user_id (int): User ID
        session: Database session

    Returns:
        dict: Dictionary containing permission flags and related data
    """
    try:
        user = session.query(User).options(
            joinedload(User.roles),
            joinedload(User.player)
        ).get(user_id)

        if not user:
            return {'error': 'User not found'}

        permissions = {
            'user_id': user_id,
            'has_player_profile': user.player is not None,
            'player_id': user.player.id if user.player else None,

            # Role-based permissions
            'is_admin': any(role.name in ADMIN_ROLES for role in user.roles),
            'is_coach': any(role.name in COACH_ROLES for role in user.roles),

            # Specific admin permissions
            'can_manage_pools': any(role.name in ADMIN_ROLES for role in user.roles),
            'can_manage_all_requests': any(role.name in ADMIN_ROLES for role in user.roles),
            'can_manage_assignments': any(role.name in ADMIN_ROLES for role in user.roles),
            'can_view_history': any(role.name in ADMIN_ROLES for role in user.roles),

            # Substitute permissions by league
            'substitute_roles': {},
            'can_respond_to_requests': {},

            # Coach permissions
            'coach_team_ids': [],
            'can_create_requests': False
        }

        # Check substitute roles for each league type
        for league_type, required_role in LEAGUE_ROLE_MAPPING.items():
            has_role = any(role.name == required_role for role in user.roles)
            permissions['substitute_roles'][league_type] = has_role
            permissions['can_respond_to_requests'][league_type] = has_role

        # Get coach team IDs if user is a coach
        if permissions['is_coach'] and user.player:
            # Get teams where user is a coach
            coach_teams = session.query(Team).join(
                'player_teams'
            ).filter(
                and_(
                    Team.player_teams.any(player_id=user.player.id),
                    Team.player_teams.any(is_coach=True)
                )
            ).all()

            permissions['coach_team_ids'] = [team.id for team in coach_teams]
            permissions['can_create_requests'] = len(coach_teams) > 0

        # Admin can create requests for any team
        if permissions['is_admin']:
            permissions['can_create_requests'] = True

        return permissions

    except Exception as e:
        logger.exception(f"Error getting user permissions for user {user_id}: {e}")
        return {'error': str(e)}


def can_user_respond_to_request(user_id: int, league_type: str, session) -> bool:
    """
    Check if a user can respond to substitute requests for a specific league type.

    Args:
        user_id (int): User ID
        league_type (str): League type
        session: Database session

    Returns:
        bool: True if user can respond, False otherwise
    """
    try:
        required_role = LEAGUE_ROLE_MAPPING.get(league_type)
        if not required_role:
            return False

        user = session.query(User).options(joinedload(User.roles)).get(user_id)
        if not user:
            return False

        return any(role.name == required_role for role in user.roles)

    except Exception as e:
        logger.exception(f"Error checking response permission for user {user_id}, league {league_type}: {e}")
        return False


def can_user_manage_team_subs(user_id: int, team_id: int, permissions: Dict[str, Any], session) -> bool:
    """
    Check if a user can manage substitute requests for a specific team.

    Args:
        user_id (int): User ID
        team_id (int): Team ID
        permissions (dict): User permissions from get_user_substitute_permissions
        session: Database session

    Returns:
        bool: True if user can manage, False otherwise
    """
    try:
        # Admins can manage any team
        if permissions.get('is_admin', False):
            return True

        # Coaches can only manage their own teams
        if permissions.get('is_coach', False):
            return team_id in permissions.get('coach_team_ids', [])

        return False

    except Exception as e:
        logger.exception(f"Error checking team management permission for user {user_id}, team {team_id}: {e}")
        return False


def validate_substitute_request_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Validate substitute request data.

    Args:
        data (dict): Request data to validate

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    required_fields = ['match_id', 'team_id', 'league_type']

    for field in required_fields:
        if field not in data:
            return f"Missing required field: {field}"

    if not validate_league_type(data['league_type']):
        return f"Invalid league type: {data['league_type']}"

    # Validate substitutes_needed
    substitutes_needed = data.get('substitutes_needed', 1)
    if not isinstance(substitutes_needed, int) or substitutes_needed < 1 or substitutes_needed > 10:
        return "substitutes_needed must be an integer between 1 and 10"

    return None


def format_substitute_pool_response(pool, include_stats: bool = False, permissions: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Format a substitute pool entry for API response.

    Args:
        pool: SubstitutePool instance
        include_stats (bool): Whether to include detailed statistics
        permissions (dict): User permissions

    Returns:
        dict: Formatted pool data
    """
    try:
        base_data = {
            'id': pool.id,
            'player_id': pool.player_id,
            'league_type': pool.league_type,
            'is_active': pool.is_active,
            'joined_pool_at': pool.joined_pool_at.isoformat() if pool.joined_pool_at else None,
            'last_active_at': pool.last_active_at.isoformat() if pool.last_active_at else None,

            # Player information
            'player': {
                'id': pool.player.id,
                'name': pool.player.name,
                'pronouns': pool.player.pronouns,
                'favorite_position': pool.player.favorite_position,
                'other_positions': pool.player.other_positions
            } if pool.player else None
        }

        # Add detailed stats if requested and user has permission
        if include_stats and permissions and permissions.get('can_view_history', False):
            base_data.update({
                'preferred_positions': pool.preferred_positions,
                'max_matches_per_week': pool.max_matches_per_week,
                'notes': pool.notes,
                'requests_received': pool.requests_received,
                'requests_accepted': pool.requests_accepted,
                'matches_played': pool.matches_played,
                'acceptance_rate': pool.acceptance_rate,
                'notification_preferences': {
                    'sms': pool.sms_for_sub_requests,
                    'email': pool.email_for_sub_requests,
                    'discord': pool.discord_for_sub_requests
                }
            })

            if pool.approved_by and pool.approved_at:
                base_data.update({
                    'approved_by': pool.approved_by,
                    'approved_at': pool.approved_at.isoformat()
                })

        return base_data

    except Exception as e:
        logger.exception(f"Error formatting pool response: {e}")
        return {'error': 'Failed to format pool data'}


def format_substitute_request_response(request, league_type: str, include_responses: bool = False,
                                     permissions: Dict[str, Any] = None, session=None) -> Dict[str, Any]:
    """
    Format a substitute request for API response.

    Args:
        request: SubstituteRequest or EcsFcSubRequest instance
        league_type (str): League type
        include_responses (bool): Whether to include player responses
        permissions (dict): User permissions
        session: Database session

    Returns:
        dict: Formatted request data
    """
    try:
        base_data = {
            'id': request.id,
            'league_type': league_type,
            'match_id': request.match_id,
            'team_id': request.team_id,
            'requested_by': request.requested_by,
            'status': request.status,
            'substitutes_needed': request.substitutes_needed,
            'notes': request.notes,
            'created_at': request.created_at.isoformat(),
            'updated_at': request.updated_at.isoformat(),
            'filled_at': request.filled_at.isoformat() if request.filled_at else None,

            # Match information
            'match': {
                'id': request.match.id,
                'date': request.match.date.isoformat() if hasattr(request.match, 'date') else None,
                'time': request.match.time.strftime('%H:%M') if hasattr(request.match, 'time') and request.match.time else None,
            } if hasattr(request, 'match') and request.match else None,

            # Team information
            'team': {
                'id': request.team.id,
                'name': request.team.name
            } if hasattr(request, 'team') and request.team else None,

            # Requester information
            'requester': {
                'id': request.requester.id,
                'username': request.requester.username,
                'display_name': request.requester.display_name
            } if hasattr(request, 'requester') and request.requester else None
        }

        # Add league-specific fields
        if league_type != 'ECS FC' and hasattr(request, 'gender_preference'):
            base_data['gender_preference'] = request.gender_preference

        if league_type == 'ECS FC' and hasattr(request, 'positions_needed'):
            base_data['positions_needed'] = request.positions_needed

        # Include responses if requested and user has permission
        if include_responses and session and permissions:
            can_view_responses = (
                permissions.get('can_manage_all_requests', False) or
                (request.team_id in permissions.get('coach_team_ids', [])) or
                (request.requested_by == permissions.get('user_id'))
            )

            if can_view_responses:
                if league_type == 'ECS FC':
                    responses = session.query(EcsFcSubResponse).options(
                        joinedload(EcsFcSubResponse.player)
                    ).filter_by(request_id=request.id).all()
                else:
                    responses = session.query(SubstituteResponse).options(
                        joinedload(SubstituteResponse.player)
                    ).filter_by(request_id=request.id).all()

                base_data['responses'] = []
                for response in responses:
                    response_data = {
                        'id': response.id,
                        'player_id': response.player_id,
                        'is_available': response.is_available,
                        'response_method': response.response_method,
                        'response_text': response.response_text,
                        'responded_at': response.responded_at.isoformat(),
                        'player': {
                            'id': response.player.id,
                            'name': response.player.name,
                            'pronouns': response.player.pronouns
                        } if response.player else None
                    }
                    base_data['responses'].append(response_data)

                # Count available responses
                available_count = sum(1 for r in responses if r.is_available)
                base_data['response_summary'] = {
                    'total_responses': len(responses),
                    'available_count': available_count,
                    'unavailable_count': len(responses) - available_count
                }

        return base_data

    except Exception as e:
        logger.exception(f"Error formatting request response: {e}")
        return {'error': 'Failed to format request data'}


def format_substitute_assignment_response(assignment, league_type: str, permissions: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Format a substitute assignment for API response.

    Args:
        assignment: SubstituteAssignment or EcsFcSubAssignment instance
        league_type (str): League type
        permissions (dict): User permissions

    Returns:
        dict: Formatted assignment data
    """
    try:
        base_data = {
            'id': assignment.id,
            'league_type': league_type,
            'request_id': assignment.request_id,
            'player_id': assignment.player_id,
            'assigned_by': assignment.assigned_by,
            'position_assigned': assignment.position_assigned,
            'notes': assignment.notes,
            'assigned_at': assignment.assigned_at.isoformat(),
            'notification_sent': assignment.notification_sent,
            'notification_sent_at': assignment.notification_sent_at.isoformat() if assignment.notification_sent_at else None,

            # Player information
            'player': {
                'id': assignment.player.id,
                'name': assignment.player.name,
                'pronouns': assignment.player.pronouns,
                'positions': assignment.player.positions
            } if hasattr(assignment, 'player') and assignment.player else None,

            # Assigner information
            'assigner': {
                'id': assignment.assigner.id,
                'username': assignment.assigner.username,
                'display_name': assignment.assigner.display_name
            } if hasattr(assignment, 'assigner') and assignment.assigner else None
        }

        # Add request information if available
        if hasattr(assignment, 'request') and assignment.request:
            base_data['request'] = {
                'id': assignment.request.id,
                'match_id': assignment.request.match_id,
                'team_id': assignment.request.team_id,
                'status': assignment.request.status,
                'substitutes_needed': assignment.request.substitutes_needed
            }

            # Add match information if available
            if hasattr(assignment.request, 'match') and assignment.request.match:
                base_data['match'] = {
                    'id': assignment.request.match.id,
                    'date': assignment.request.match.date.isoformat() if hasattr(assignment.request.match, 'date') else None,
                    'time': assignment.request.match.time.strftime('%H:%M') if hasattr(assignment.request.match, 'time') and assignment.request.match.time else None
                }

        return base_data

    except Exception as e:
        logger.exception(f"Error formatting assignment response: {e}")
        return {'error': 'Failed to format assignment data'}


def get_upcoming_matches_needing_subs(league_type: str = None, days_ahead: int = 30, session=None) -> List[Dict[str, Any]]:
    """
    Get upcoming matches that have open substitute requests.

    Args:
        league_type (str): Filter by league type (optional)
        days_ahead (int): Number of days to look ahead
        session: Database session

    Returns:
        list: List of matches with substitute requests
    """
    try:
        from app.models import Match
        from app.models_ecs import EcsFcMatch

        if not session:
            from app.core import db
            session = db.session

        end_date = datetime.now().date() + timedelta(days=days_ahead)
        matches_with_requests = []

        # Get ECS FC matches with open requests
        if not league_type or league_type == 'ECS FC':
            ecs_matches = session.query(EcsFcMatch).join(
                EcsFcSubRequest, EcsFcMatch.id == EcsFcSubRequest.match_id
            ).filter(
                EcsFcMatch.date >= datetime.now().date(),
                EcsFcMatch.date <= end_date,
                EcsFcSubRequest.status == 'OPEN'
            ).options(
                joinedload(EcsFcMatch.team),
                joinedload(EcsFcMatch.sub_requests)
            ).all()

            for match in ecs_matches:
                match_data = {
                    'id': match.id,
                    'league_type': 'ECS FC',
                    'date': match.date.isoformat(),
                    'time': match.time.strftime('%H:%M') if match.time else None,
                    'team': {
                        'id': match.team.id,
                        'name': match.team.name
                    } if match.team else None,
                    'open_requests': [
                        {
                            'id': req.id,
                            'substitutes_needed': req.substitutes_needed,
                            'positions_needed': req.positions_needed,
                            'created_at': req.created_at.isoformat()
                        }
                        for req in match.sub_requests if req.status == 'OPEN'
                    ]
                }
                matches_with_requests.append(match_data)

        # Get Pub League matches with open requests
        if not league_type or league_type in ['Classic', 'Premier']:
            pub_query = session.query(Match).join(
                SubstituteRequest, Match.id == SubstituteRequest.match_id
            ).filter(
                Match.date >= datetime.now().date(),
                Match.date <= end_date,
                SubstituteRequest.status == 'OPEN'
            ).options(
                joinedload(Match.home_team).joinedload(Team.league),
                joinedload(Match.away_team).joinedload(Team.league),
                joinedload(Match.substitute_requests)
            )

            if league_type and league_type != 'ECS FC':
                pub_query = pub_query.join(Team).join(League).filter(League.name == league_type)

            pub_matches = pub_query.all()

            for match in pub_matches:
                # Determine league type from teams
                match_league_type = 'Unknown'
                if match.home_team and match.home_team.league:
                    match_league_type = match.home_team.league.name

                match_data = {
                    'id': match.id,
                    'league_type': match_league_type,
                    'date': match.date.isoformat(),
                    'time': match.time.strftime('%H:%M') if match.time else None,
                    'home_team': {
                        'id': match.home_team.id,
                        'name': match.home_team.name
                    } if match.home_team else None,
                    'away_team': {
                        'id': match.away_team.id,
                        'name': match.away_team.name
                    } if match.away_team else None,
                    'open_requests': [
                        {
                            'id': req.id,
                            'team_id': req.team_id,
                            'substitutes_needed': req.substitutes_needed,
                            'positions_needed': req.positions_needed,
                            'gender_preference': req.gender_preference,
                            'created_at': req.created_at.isoformat()
                        }
                        for req in match.substitute_requests if req.status == 'OPEN'
                    ]
                }
                matches_with_requests.append(match_data)

        # Sort by date and time
        matches_with_requests.sort(key=lambda x: (x['date'], x.get('time', '')))

        return matches_with_requests

    except Exception as e:
        logger.exception(f"Error getting upcoming matches needing subs: {e}")
        return []


def get_player_substitute_stats(player_id: int, league_type: str = None, session=None) -> Dict[str, Any]:
    """
    Get substitute statistics for a player.

    Args:
        player_id (int): Player ID
        league_type (str): Filter by league type (optional)
        session: Database session

    Returns:
        dict: Player substitute statistics
    """
    try:
        if not session:
            from app.core import db
            session = db.session

        stats = {
            'player_id': player_id,
            'pool_memberships': [],
            'requests_received': 0,
            'requests_accepted': 0,
            'assignments_completed': 0,
            'acceptance_rate': 0.0,
            'recent_activity': []
        }

        # Get pool memberships
        pool_query = session.query(SubstitutePool).filter_by(player_id=player_id)
        if league_type:
            pool_query = pool_query.filter_by(league_type=league_type)

        pools = pool_query.all()
        stats['pool_memberships'] = [
            {
                'league_type': pool.league_type,
                'is_active': pool.is_active,
                'joined_at': pool.joined_pool_at.isoformat() if pool.joined_pool_at else None,
                'requests_received': pool.requests_received,
                'requests_accepted': pool.requests_accepted,
                'matches_played': pool.matches_played,
                'acceptance_rate': pool.acceptance_rate
            }
            for pool in pools
        ]

        # Calculate totals
        stats['requests_received'] = sum(pool.requests_received for pool in pools)
        stats['requests_accepted'] = sum(pool.requests_accepted for pool in pools)

        if stats['requests_received'] > 0:
            stats['acceptance_rate'] = (stats['requests_accepted'] / stats['requests_received']) * 100

        # Get recent assignments
        recent_assignments = session.query(SubstituteAssignment).options(
            joinedload(SubstituteAssignment.request).joinedload(SubstituteRequest.match)
        ).filter_by(player_id=player_id).order_by(
            SubstituteAssignment.assigned_at.desc()
        ).limit(10).all()

        for assignment in recent_assignments:
            activity = {
                'type': 'assignment',
                'date': assignment.assigned_at.isoformat(),
                'match_date': assignment.request.match.date.isoformat() if assignment.request and assignment.request.match else None,
                'position': assignment.position_assigned,
                'team_id': assignment.request.team_id if assignment.request else None
            }
            stats['recent_activity'].append(activity)

        stats['assignments_completed'] = len(recent_assignments)

        return stats

    except Exception as e:
        logger.exception(f"Error getting player substitute stats for player {player_id}: {e}")
        return {'error': str(e)}


def cleanup_expired_requests(days_old: int = 7, session=None) -> Dict[str, int]:
    """
    Mark old open substitute requests as expired.

    Args:
        days_old (int): Number of days after which to mark requests as expired
        session: Database session

    Returns:
        dict: Cleanup statistics
    """
    try:
        if not session:
            from app.core import db
            session = db.session

        cutoff_date = datetime.now() - timedelta(days=days_old)
        stats = {'ecs_fc_expired': 0, 'pub_league_expired': 0}

        # Expire ECS FC requests
        ecs_fc_expired = session.query(EcsFcSubRequest).filter(
            EcsFcSubRequest.status == 'OPEN',
            EcsFcSubRequest.created_at < cutoff_date
        ).update({'status': 'EXPIRED'})

        # Expire Pub League requests
        pub_league_expired = session.query(SubstituteRequest).filter(
            SubstituteRequest.status == 'OPEN',
            SubstituteRequest.created_at < cutoff_date
        ).update({'status': 'EXPIRED'})

        stats['ecs_fc_expired'] = ecs_fc_expired
        stats['pub_league_expired'] = pub_league_expired
        stats['total_expired'] = ecs_fc_expired + pub_league_expired

        session.commit()

        logger.info(f"Cleanup completed: {stats['total_expired']} requests marked as expired")
        return stats

    except Exception as e:
        logger.exception(f"Error during cleanup of expired requests: {e}")
        session.rollback()
        return {'error': str(e)}