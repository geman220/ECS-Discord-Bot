# app/admin_helpers.py

"""
Miscellaneous Helpers Module

This module provides various helper functions for:
  - Retrieving initial role status for a player without making Discord API calls.
  - Filtering and retrieving users based on dynamic criteria.
  - Handling user actions (approve, remove, reset password).
  - Interacting with Docker containers (e.g., retrieving container data and managing containers).
  - Managing substitute players and substitute requests.
  - Sending SMS messages using Twilio.
  - Managing announcements (create/update).
  - Retrieving role permissions and updating role permissions.
  - Managing RSVP data for matches.
  - Managing temporary substitute assignments.
  - Gathering match statistics.
  - Performing system health checks (database, Redis, Celery, Docker, and task status).
  - Determining initial expected roles for a player.
"""

import logging
import docker
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from twilio.rest import Client
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from flask import current_app, g

from app.models import User, Role, Player, Team, League, Match, Availability, Announcement, Permission, TemporarySubAssignment, SubRequest, Schedule
from app.discord_utils import get_expected_roles, normalize_name
from app.core import db

logger = logging.getLogger(__name__)


# --------------------
# User & Role Helpers
# --------------------

async def get_initial_role_status(player: Player) -> Dict[str, Any]:
    """
    Get initial role status for a player without making Discord API calls.

    Compares the player's current Discord roles with the expected roles and returns
    a dictionary indicating the sync status along with role details.

    Args:
        player: The Player object.

    Returns:
        A dictionary containing:
          - current_roles: The player's current Discord roles.
          - expected_roles: The expected roles from get_expected_roles.
          - last_verified: A formatted timestamp or 'Never' if not verified.
          - status_class, status_text, status_html: Visual indicators for the status.
    """
    try:
        current_roles = player.discord_roles or []
        # Await the async function to get expected roles.
        expected_roles = await get_expected_roles(player)
        
        if not player.discord_last_verified:
            status = {
                'status_class': 'info',
                'status_text': 'Never Verified',
                'status_html': '<span class="badge bg-info">Never Verified</span>'
            }
        elif sorted(current_roles) == sorted(expected_roles):
            status = {
                'status_class': 'success',
                'status_text': 'Synced',
                'status_html': '<span class="badge bg-success">Synced</span>'
            }
        else:
            status = {
                'status_class': 'warning',
                'status_text': 'Out of Sync',
                'status_html': '<span class="badge bg-warning">Out of Sync</span>'
            }
            
        return {
            'current_roles': current_roles,
            'expected_roles': expected_roles,
            'last_verified': player.discord_last_verified.strftime('%Y-%m-%d %H:%M:%S') if player.discord_last_verified else 'Never',
            **status
        }
        
    except Exception as e:
        logger.error(f"Error getting initial role status for player {player.id}: {str(e)}")
        return {
            'current_roles': [],
            'expected_roles': [],
            'status_class': 'danger',
            'status_text': 'Error',
            'status_html': '<span class="badge bg-danger">Error</span>',
            'last_verified': 'Never'
        }


def get_filtered_users(filters) -> List[User]:
    """
    Get filtered users based on provided filters.

    Builds a query for the User model, applying filters for search, role, league,
    active status, and approval status, and returns a distinct query result.

    Args:
        filters: A dictionary of filter criteria.

    Returns:
        A SQLAlchemy query object for User objects that match the filters.
        (Call .all() on the returned query when you need to iterate over the results.)
    """
    query = User.query.options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.primary_team),
        joinedload(User.player).joinedload(Player.league)
    )

    if filters.get('search'):
        search = f"%{filters['search']}%"
        query = query.filter(or_(
            User.username.ilike(search),
            User.email.ilike(search)
        ))
    
    query = query.outerjoin(Player).outerjoin(Team).outerjoin(League)

    if filters.get('role'):
        query = query.join(User.roles).filter(Role.name == filters['role'])
        
    if filters.get('league'):
        if filters['league'] == 'none':
            query = query.filter(Player.league_id.is_(None))
        else:
            try:
                league_id = int(filters['league'])
                query = query.filter(Player.league_id == league_id)
            except ValueError:
                logger.warning(f"Invalid league ID: {filters['league']}")
            
    if filters.get('active'):
        is_active = filters['active'].lower() == 'true' if isinstance(filters['active'], str) else bool(filters['active'])
        if isinstance(is_active, bool):
            query = query.filter(Player.is_current_player == is_active)
            
    if filters.get('approved'):
        is_approved = filters['approved'].lower() == 'true' if isinstance(filters['approved'], str) else bool(filters['approved'])
        if isinstance(is_approved, bool):
            query = query.filter(User.is_approved == is_approved)

    # Return the query object so that methods like .count() are available.
    return query.distinct()


def handle_user_action(action: str, user_id: int) -> bool:
    """
    Handle a user-related action, such as approving or removing a user.

    Args:
        action: The action to perform ('approve', 'remove', or 'reset_password').
        user_id: The ID of the user on which to perform the action.

    Returns:
        True if the action was handled successfully.
    """
    user = User.query.get_or_404(user_id)
    if action == 'approve':
        user.is_approved = True
    elif action == 'remove':
        g.db_session.delete(user)
    # Additional actions (e.g., password reset) can be implemented as needed.
    return True


# --------------------
# Docker Container Helpers
# --------------------

def get_docker_client() -> Optional[docker.DockerClient]:
    """
    Initialize and return a Docker client from the environment.

    Returns:
        A DockerClient instance if successful, or None if an error occurs.
    """
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Error initializing Docker client: {e}")
        return None


def get_container_data() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch and format data for all Docker containers.

    Returns:
        A list of dictionaries with container ID, name, status, and image, or None if fetching fails.
    """
    client = get_docker_client()
    if not client:
        return None
    try:
        containers = client.containers.list(all=True)
        return [{
            'id': container.id[:12],
            'name': container.name,
            'status': container.status,
            'image': container.image.tags[0] if container.image.tags else 'Unknown'
        } for container in containers]
    except Exception as e:
        logger.error(f"Error fetching container data: {e}")
        return None


def manage_docker_container(container_id: str, action: str) -> bool:
    """
    Manage a Docker container by performing the specified action.

    Supported actions are 'start', 'stop', and 'restart'.

    Args:
        container_id: The ID of the Docker container.
        action: The action to perform.

    Returns:
        True if the action was successful, False otherwise.
    """
    client = get_docker_client()
    if not client:
        return False
    try:
        container = client.containers.get(container_id)
        if action == 'start':
            container.start()
        elif action == 'stop':
            container.stop()
        elif action == 'restart':
            container.restart()
        return True
    except Exception as e:
        logger.error(f"Error managing container {container_id}: {e}")
        return False


# --------------------
# SMS Helpers
# --------------------

def send_sms_message(to_phone_number: str, message_body: str) -> bool:
    """
    Send an SMS message using Twilio.

    Args:
        to_phone_number: The recipient's phone number.
        message_body: The content of the SMS.

    Returns:
        True if the SMS was sent successfully, False otherwise.
    """
    try:
        import os
        
        # Get credentials directly from environment variables
        twilio_sid = os.environ.get('TWILIO_SID') or os.environ.get('TWILIO_ACCOUNT_SID')
        twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        twilio_phone_number = os.environ.get('TWILIO_PHONE_NUMBER')
        
        # Fall back to config if not in environment
        if not twilio_sid:
            twilio_sid = current_app.config.get('TWILIO_SID') or current_app.config.get('TWILIO_ACCOUNT_SID')
        if not twilio_auth_token:
            twilio_auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
        if not twilio_phone_number:
            twilio_phone_number = current_app.config.get('TWILIO_PHONE_NUMBER')
        
        # Clean auth token (remove any whitespace)
        if twilio_auth_token:
            twilio_auth_token = twilio_auth_token.strip()
        
        # Validate credentials exist
        if not all([twilio_sid, twilio_auth_token, twilio_phone_number]):
            logger.error("Missing Twilio credentials in configuration")
            return False
            
        # Normalize phone number for Twilio
        if to_phone_number and not to_phone_number.startswith('+'):
            if len(to_phone_number) == 10:
                to_phone_number = '+1' + to_phone_number
            else:
                to_phone_number = '+' + to_phone_number
                
        client = Client(twilio_sid, twilio_auth_token)
        message = client.messages.create(
            body=message_body,
            from_=twilio_phone_number,
            to=to_phone_number
        )
        logger.info(f"SMS sent successfully: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")
        return False


# --------------------
# Announcement Management Helpers
# --------------------

def handle_announcement_update(title: str = None, content: str = None, 
                               announcement_id: int = None) -> bool:
    """
    Create or update an announcement.

    Args:
        title: The title of the announcement.
        content: The content of the announcement.
        announcement_id: (Optional) If provided, updates the existing announcement.

    Returns:
        True if the announcement was created or updated successfully, False otherwise.
    """
    try:
        if announcement_id:
            announcement = Announcement.query.get_or_404(announcement_id)
            announcement.title = title or announcement.title
            announcement.content = content or announcement.content
        else:
            max_position = g.db_session.query(db.func.max(Announcement.position)).scalar() or 0
            announcement = Announcement(
                title=title,
                content=content,
                position=max_position + 1
            )
            g.db_session.add(announcement)
        return True
    except Exception as e:
        logger.error(f"Error handling announcement: {e}")
        return False


def get_role_permissions_data(role_id: int, session=None) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieve permission details for a specific role.

    Args:
        role_id: The ID of the role.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A list of permission objects with id and name for the role, or None if the role is not found.
    """
    if session is None:
        session = g.db_session
    role = session.query(Role).get(role_id)
    if not role:
        return None
    return [{'id': perm.id, 'name': perm.name} for perm in role.permissions]


def handle_permissions_update(role_id: int, permission_ids: List[int], session=None) -> bool:
    """
    Update a role's permissions.

    Args:
        role_id: The ID of the role.
        permission_ids: A list of permission IDs to assign to the role.
        session: (Optional) A SQLAlchemy session to use for the query.

    Returns:
        True if the permissions were updated successfully, False otherwise.
    """
    try:
        if session is None:
            session = g.db_session
        
        logger.info(f"Updating permissions for role_id: {role_id} with permission_ids: {permission_ids}")
        
        # First, close any existing transaction to ensure a clean state
        try:
            session.rollback()
        except:
            pass  # Ignore if there's no active transaction
        
        role = session.query(Role).get(role_id)
        if not role:
            logger.error(f"Role with ID {role_id} not found")
            return False
        
        logger.info(f"Found role: {role.name}")
        
        # Clear existing permissions first
        role.permissions.clear()
        
        # Add new permissions
        if permission_ids:
            new_permissions = session.query(Permission).filter(Permission.id.in_(permission_ids)).all()
            logger.info(f"Found {len(new_permissions)} permissions to add")
            for perm in new_permissions:
                logger.info(f"Adding permission: {perm.name}")
                role.permissions.append(perm)
        
        # Explicitly add the role back to the session
        session.add(role)
        
        # Flush and commit in separate steps for debugging
        session.flush()
        logger.info(f"After flush: Role {role.name} has {len(role.permissions)} permissions")
        
        session.commit()
        logger.info("Transaction committed successfully")
        
        # Verify with a new query using the same session
        session.expunge_all()  # Clear session cache
        role_check = session.query(Role).get(role_id)
        logger.info(f"Verification query: Role {role_check.name} has {len(role_check.permissions)} permissions")
        for perm in role_check.permissions:
            logger.info(f"  - {perm.name}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating permissions: {e}", exc_info=True)
        if session:
            try:
                session.rollback()
            except:
                pass
        return False


# --------------------
# RSVP Management Helpers
# --------------------

def get_rsvp_status_data(match: Match, session=None) -> List[Dict[str, Any]]:
    """
    Retrieve RSVP status data for a match.

    Joins the Player and Availability tables to collect each player's RSVP response,
    their team, and the response timestamp, and returns the results sorted by team and player name.
    Also includes temporary subs assigned to each team for this match.

    Args:
        match: The Match object.
        session: (Optional) A SQLAlchemy session to use for the query.

    Returns:
        A sorted list of dictionaries containing RSVP status data.
    """
    if session is None:
        session = g.db_session
        
    # Get regular team players with their availability
    players_with_availability = session.query(Player, Availability).\
        outerjoin(
            Availability,
            (Player.id == Availability.player_id) & (Availability.match_id == match.id)
        ).\
        filter(
            (Player.primary_team_id == match.home_team_id) | (Player.primary_team_id == match.away_team_id)
        ).\
        options(joinedload(Player.primary_team), joinedload(Player.user)).\
        all()

    rsvp_data = [{
        'player': player,
        'team': player.primary_team,
        'response': availability.response if availability else 'No Response',
        'responded_at': availability.responded_at if availability else None,
        'discord_synced': availability.discord_id is not None if availability else False,
        'is_temp_sub': False,
        'assignment_id': None  # Regular team players don't have assignment_id
    } for player, availability in players_with_availability]
    
    # Get temporary subs assigned to this match
    sub_assignments = session.query(TemporarySubAssignment).filter(
        TemporarySubAssignment.match_id == match.id
    ).options(
        joinedload(TemporarySubAssignment.player),
        joinedload(TemporarySubAssignment.team),
        joinedload(TemporarySubAssignment.player).joinedload(Player.user)
    ).all()
    
    # Add temporary subs to the result
    for assignment in sub_assignments:
        # Sub availability (if they explicitly RSVP'd to the match)
        sub_availability = session.query(Availability).filter(
            Availability.player_id == assignment.player_id,
            Availability.match_id == match.id
        ).first()
        
        rsvp_data.append({
            'player': assignment.player,
            'team': assignment.team,
            'response': sub_availability.response if sub_availability else 'Yes',  # Default subs to Yes
            'responded_at': sub_availability.responded_at if sub_availability else assignment.created_at,
            'discord_synced': sub_availability.discord_id is not None if sub_availability else False,
            'is_temp_sub': True,
            'assignment_id': assignment.id,
            'assigned_by': assignment.assigner.username if hasattr(assignment, 'assigner') else 'Unknown'
        })
    
    # Add substitute assignments from unified substitute system
    try:
        from app.models_substitute_pools import SubstituteAssignment, SubstituteRequest
        
        # Determine league type from the match teams
        home_team = match.home_team
        if home_team and home_team.league:
            league_name = home_team.league.name
            if 'Premier' in league_name:
                league_type = 'Premier'
            elif 'Classic' in league_name:
                league_type = 'Classic'
            else:
                league_type = 'Classic'  # Default
        else:
            league_type = 'Classic'  # Default
        
        # Get substitute assignments for this regular match
        substitute_assignments = session.query(SubstituteAssignment).join(
            SubstituteRequest
        ).options(
            joinedload(SubstituteAssignment.player).joinedload(Player.user),
            joinedload(SubstituteAssignment.assigned_by)
        ).filter(
            SubstituteRequest.match_id == match.id
        ).all()
        
        # Add substitute assignments to the data
        for assignment in substitute_assignments:
            player = assignment.player
            assigned_by_user = assignment.assigned_by
            
            if player:
                # Determine which team they're assigned to based on the request
                request = assignment.request
                assigned_team = session.query(Team).get(request.team_id) if request else match.home_team
                
                rsvp_data.append({
                    'player': player,
                    'team': assigned_team,
                    'response': 'Substitute',
                    'responded_at': assignment.created_at,
                    'discord_synced': False,
                    'is_temp_sub': True,
                    'assigned_by': assigned_by_user.username if assigned_by_user else 'Admin',
                    'assignment_notes': assignment.notes or '',
                    'position_assigned': assignment.position_assigned or '',
                    'assignment_id': assignment.id  # Add assignment_id for remove button
                })
    
    except ImportError:
        # Unified substitute system not available, skip
        pass
    except Exception as e:
        logger.warning(f"Could not load substitute assignments for match {match.id}: {e}")

    return sorted(rsvp_data, key=lambda x: (x['team'].name, x['is_temp_sub'], x['player'].name))


def get_ecs_fc_rsvp_status_data(ecs_match, session=None):
    """
    Retrieve RSVP status data for an ECS FC match.
    
    Similar to get_rsvp_status_data but for ECS FC matches, which only have one team
    (the ECS FC team) since opponents are external teams.

    Args:
        ecs_match: The EcsFcMatch object.
        session: (Optional) A SQLAlchemy session to use for the query.

    Returns:
        A sorted list of dictionaries containing RSVP status data.
    """
    if session is None:
        from app.core import db
        session = g.db_session
    
    from app.models import Player, Team, TemporarySubAssignment
    from app.models_ecs import EcsFcAvailability
    from sqlalchemy.orm import joinedload
    
    # Get the ECS FC team
    team = session.query(Team).get(ecs_match.team_id)
    if not team:
        return []
    
    # Get team players with their ECS FC availability
    # Use the many-to-many relationship to get all players on the team
    players_with_availability = session.query(Player, EcsFcAvailability).\
        outerjoin(
            EcsFcAvailability,
            (Player.id == EcsFcAvailability.player_id) & (EcsFcAvailability.ecs_fc_match_id == ecs_match.id)
        ).\
        join(Player.teams).\
        filter(Team.id == ecs_match.team_id).\
        options(joinedload(Player.primary_team), joinedload(Player.user)).\
        all()

    rsvp_data = [{
        'player': player,
        'team': team,
        'response': availability.response if availability else 'No Response',
        'responded_at': availability.response_time if availability else None,
        'discord_synced': availability.discord_id is not None if availability else False,
        'is_temp_sub': False,
        'assignment_id': None  # Regular team players don't have assignment_id
    } for player, availability in players_with_availability]
    
    # Add substitute assignments from unified substitute system
    try:
        from app.models_substitute_pools import SubstituteAssignment, SubstituteRequest
        
        # Get substitute assignments for this ECS FC match
        substitute_assignments = session.query(SubstituteAssignment).join(
            SubstituteRequest
        ).options(
            joinedload(SubstituteAssignment.player).joinedload(Player.user),
            joinedload(SubstituteAssignment.assigner)
        ).filter(
            SubstituteRequest.match_id == ecs_match.id
        ).all()
        
        # Add substitute assignments to the data
        for assignment in substitute_assignments:
            player = assignment.player
            assigned_by_user = assignment.assigner
            
            if player:
                rsvp_data.append({
                    'player': player,
                    'team': team,
                    'response': 'Substitute',
                    'responded_at': assignment.created_at,
                    'discord_synced': False,
                    'is_temp_sub': True,
                    'assigned_by': assigned_by_user.username if assigned_by_user else 'Admin',
                    'assignment_notes': assignment.notes or '',
                    'position_assigned': assignment.position_assigned or '',
                    'assignment_id': assignment.id  # Add assignment_id for remove button
                })
    
    except ImportError:
        # Unified substitute system not available, skip
        pass
    except Exception as e:
        logger.warning(f"Could not load unified substitute assignments for ECS FC match {ecs_match.id}: {e}")
    
    # Add ECS FC specific substitute assignments
    try:
        from app.models_ecs_subs import EcsFcSubAssignment
        
        # Get ECS FC substitute assignments for this match
        ecs_fc_assignments = session.query(EcsFcSubAssignment).join(
            EcsFcSubAssignment.request
        ).options(
            joinedload(EcsFcSubAssignment.player).joinedload(Player.user),
            joinedload(EcsFcSubAssignment.assigner)
        ).filter(
            EcsFcSubAssignment.request.has(match_id=ecs_match.id)
        ).all()
        
        # Add ECS FC substitute assignments to the data
        for assignment in ecs_fc_assignments:
            player = assignment.player
            assigned_by_user = assignment.assigner
            
            if player:
                rsvp_data.append({
                    'player': player,
                    'team': team,
                    'response': 'Substitute',
                    'responded_at': assignment.assigned_at,
                    'discord_synced': False,
                    'is_temp_sub': True,
                    'assigned_by': assigned_by_user.username if assigned_by_user else 'Admin',
                    'assignment_notes': assignment.notes or '',
                    'position_assigned': assignment.position_assigned or '',
                    'assignment_id': assignment.id  # Add assignment_id for remove button
                })
    
    except ImportError:
        # ECS FC substitute system not available, skip
        pass
    except Exception as e:
        logger.warning(f"Could not load ECS FC substitute assignments for ECS FC match {ecs_match.id}: {e}")
    
    return sorted(rsvp_data, key=lambda x: (x['player'].name))


# --------------------
# Match Statistics Helpers
# --------------------

def get_match_stats() -> Dict[str, Any]:
    """
    Retrieve comprehensive match statistics.

    Computes total matches, completed matches, upcoming matches, and the completion rate.

    Returns:
        A dictionary containing match statistics.
    """
    try:
        total_matches = Match.query.count()
        completed_matches = Match.query.filter(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).count()
        upcoming_matches = Match.query.filter(Match.date >= datetime.utcnow()).count()
        
        return {
            'total_matches': total_matches,
            'completed_matches': completed_matches,
            'upcoming_matches': upcoming_matches,
            'completion_rate': (completed_matches / total_matches * 100) if total_matches > 0 else 0
        }
    except Exception as e:
        logger.error(f"Error getting match stats: {e}")
        return {}


# --------------------
# System Health Check Helpers
# --------------------

def check_system_health() -> Dict[str, Any]:
    """
    Check the overall system health.

    Returns:
        A dictionary with health check results for the database, Redis, Celery, and Docker,
        as well as an overall health status.
    """
    health_status = {
        'database': check_database_health(),
        'redis': check_redis_health(),
        'celery': check_celery_health(),
        'docker': check_docker_health()
    }
    health_status['overall'] = all(health_status.values())
    return health_status


def check_database_health() -> bool:
    """Check database connection health."""
    try:
        from sqlalchemy import text
        g.db_session.execute(text('SELECT 1'))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def check_redis_health() -> bool:
    """Check Redis connection health."""
    try:
        redis_client = current_app.extensions['redis']
        redis_client.ping()
        return True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False


def check_celery_health() -> bool:
    """Check Celery worker health."""
    try:
        response = requests.get('http://flower:5555/api/workers')
        workers = response.json()
        return any(worker.get('status', False) for worker in workers.values())
    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        return False


def check_docker_health() -> bool:
    """Check Docker daemon health."""
    client = get_docker_client()
    return client is not None


def check_task_status() -> Dict[str, Any]:
    """
    Retrieve status of background tasks.

    Fetches tasks from the Flower API and returns summary counts along with details of up to 10 tasks.

    Returns:
        A dictionary containing task status metrics.
    """
    try:
        response = requests.get('http://flower:5555/api/tasks')
        tasks = response.json()
        return {
            'total': len(tasks),
            'succeeded': sum(1 for t in tasks if t.get('state') == 'SUCCESS'),
            'failed': sum(1 for t in tasks if t.get('state') == 'FAILURE'),
            'pending': sum(1 for t in tasks if t.get('state') == 'PENDING'),
            'tasks': [{
                'id': t.get('uuid', 'N/A'),
                'name': t.get('name', 'N/A'),
                'state': t.get('state', 'N/A'),
                'received': t.get('received', 'N/A'),
                'started': t.get('started', 'N/A'),
            } for t in tasks[:10]]
        }
    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        return {
            'error': str(e),
            'total': 0,
            'succeeded': 0,
            'failed': 0,
            'pending': 0,
            'tasks': []
        }


def get_container_logs(container_id: str) -> Optional[str]:
    """
    Retrieve logs from a specific Docker container.

    Args:
        container_id: The Docker container ID.

    Returns:
        The container logs as a string if successful, or None if an error occurs.
    """
    client = get_docker_client()
    if not client:
        logger.error("Docker client initialization failed")
        return None
    
    try:
        container = client.containers.get(container_id)
        logs = container.logs().decode('utf-8')
        logger.debug(f"Successfully retrieved logs for container {container_id}")
        return logs
    except docker.errors.NotFound:
        logger.error(f"Container {container_id} not found")
        return None
    except docker.errors.APIError as e:
        logger.error(f"Docker API error while retrieving logs for container {container_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error retrieving logs for container {container_id}: {e}")
        return None


def get_initial_expected_roles(player: Player) -> List[str]:
    """
    Determine the expected roles for a player for initial page load.

    Based on the player's team and league information, as well as their role (coach, referee, sub),
    constructs a list of expected role strings.

    Args:
        player: The Player object.

    Returns:
        A list of expected role strings.
    """
    roles = []
    
    if player.primary_team:
        role_suffix = 'Coach' if player.is_coach else 'Player'
        roles.append(f"ECS-FC-PL-{normalize_name(player.primary_team.name)}-{role_suffix}")
        if player.primary_team.league:
            league_map = {
                'Premier': 'ECS-FC-PL-PREMIER',
                'Classic': 'ECS-FC-PL-CLASSIC',
                'ECS FC': 'ECS-FC-LEAGUE'
            }
            # Updated to reference primary_team instead of non-existent team
            league_role = league_map.get(player.primary_team.league.name)
            if league_role:
                roles.append(league_role)
    
    if player.is_ref:
        roles.append('Referee')
    
    if player.is_sub:
        roles.append('Substitute')
            
    return roles


# --------------------
# Temporary Sub Management Helpers
# --------------------

def get_available_subs(session=None, league_type=None) -> List[Dict[str, Any]]:
    """
    Retrieve a list of players marked as substitutes, optionally filtered by league type.
    
    Args:
        session: (Optional) A SQLAlchemy session to use for the query.
        league_type: (Optional) Filter subs by league type ('Classic', 'Premier', 'ECS FC').
                    If None, returns all pub league subs (Classic + Premier).
        
    Returns:
        A list of dictionaries containing sub player information.
    """
    if session is None:
        session = g.db_session
    
    # First, get legacy subs (using is_sub flag) - these are general subs for all leagues
    legacy_subs = session.query(Player).filter(
        Player.is_sub == True,
        Player.is_current_player == True
    ).options(
        joinedload(Player.user),
        joinedload(Player.primary_team)
    ).all()
    
    # Then get subs from the new SubstitutePool system
    from app.models_substitute_pools import SubstitutePool
    pool_query = session.query(Player).join(
        SubstitutePool, Player.id == SubstitutePool.player_id
    ).filter(
        SubstitutePool.is_active == True
    )
    
    # Filter by league type if specified
    if league_type:
        pool_query = pool_query.filter(SubstitutePool.league_type == league_type)
    else:
        # Default to pub league subs only (Classic + Premier)
        pool_query = pool_query.filter(SubstitutePool.league_type.in_(['Classic', 'Premier']))
    
    pool_subs = pool_query.options(
        joinedload(Player.user),
        joinedload(Player.primary_team)
    ).all()
    
    # For league-specific requests, only include legacy subs if no league type specified
    # or if they're in a team that matches the league type
    filtered_legacy_subs = []
    if league_type:
        # If league type is specified, filter legacy subs by their team's league
        for sub in legacy_subs:
            if sub.primary_team and sub.primary_team.league:
                team_league_name = sub.primary_team.league.name.lower()
                if (league_type == 'Premier' and 'premier' in team_league_name) or \
                   (league_type == 'Classic' and 'classic' in team_league_name) or \
                   (league_type == 'ECS FC' and 'ecs' in team_league_name):
                    filtered_legacy_subs.append(sub)
            elif not league_type or league_type in ['Classic', 'Premier']:
                # If no team info, include for pub leagues as fallback
                filtered_legacy_subs.append(sub)
    else:
        # If no league type specified, include all legacy subs
        filtered_legacy_subs = legacy_subs
    
    # Combine both lists, removing duplicates
    all_subs = {}
    for sub in filtered_legacy_subs + pool_subs:
        if sub.id not in all_subs:
            all_subs[sub.id] = sub
    
    return [{
        'id': sub.id,
        'name': sub.name,
        'primary_team_id': sub.primary_team_id,
        'primary_team_name': sub.primary_team.name if sub.primary_team else None,
        'profile_picture_url': sub.profile_picture_url,
        'discord_id': sub.discord_id,
        'phone': sub.phone,
        'email': sub.user.email if sub.user else None
    } for sub in all_subs.values()]


def determine_match_league_type(match, session=None):
    """
    Determine the league type for a match based on the teams involved.
    
    Args:
        match: The Match object
        session: (Optional) A SQLAlchemy session
        
    Returns:
        String: 'Premier', 'Classic', or None if undetermined
    """
    if session is None:
        session = g.db_session
        
    # Check both home and away teams for league information
    teams_to_check = [match.home_team, match.away_team]
    
    for team in teams_to_check:
        if team and team.league:
            league_name = team.league.name.lower()
            if 'premier' in league_name:
                return 'Premier'
            elif 'classic' in league_name:
                return 'Classic'
            elif 'ecs' in league_name:
                return 'ECS FC'
    
    # Fallback: check season league_type if teams don't have clear league info
    for team in teams_to_check:
        if team and team.league and team.league.season:
            season_type = team.league.season.league_type
            if season_type == 'Pub League':
                # Default to Classic for pub league if we can't determine specifically
                return 'Classic'
    
    return None


def get_subs_by_match_league_type(matches, session=None):
    """
    Get available substitutes grouped by match, filtered by each match's league type.
    
    Args:
        matches: List of Match objects
        session: (Optional) A SQLAlchemy session
        
    Returns:
        Dict: {match_id: [list of available subs for that match's league]}
    """
    if session is None:
        session = g.db_session
        
    subs_by_match = {}
    
    for match in matches:
        league_type = determine_match_league_type(match, session)
        match_subs = get_available_subs(session=session, league_type=league_type)
        subs_by_match[match.id] = {
            'league_type': league_type,
            'subs': match_subs
        }
    
    return subs_by_match


def get_match_subs(match_id: int, session=None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Retrieve all temporary subs assigned to a specific match, organized by team.
    
    Args:
        match_id: The ID of the match.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A dictionary with team IDs as keys and lists of sub information as values.
    """
    if session is None:
        session = g.db_session
        
    sub_assignments = session.query(TemporarySubAssignment).filter(
        TemporarySubAssignment.match_id == match_id
    ).options(
        joinedload(TemporarySubAssignment.player),
        joinedload(TemporarySubAssignment.team),
        joinedload(TemporarySubAssignment.assigner)
    ).all()
    
    # Organize by team
    subs_by_team = {}
    for assignment in sub_assignments:
        team_id = assignment.team_id
        if team_id not in subs_by_team:
            subs_by_team[team_id] = []
            
        subs_by_team[team_id].append({
            'id': assignment.id,
            'player_id': assignment.player_id,
            'player_name': assignment.player.name,
            'team_id': assignment.team_id,
            'team_name': assignment.team.name,
            'assigned_by': assignment.assigner.username,
            'created_at': assignment.created_at,
            'profile_picture_url': assignment.player.profile_picture_url
        })
    
    return subs_by_team


def assign_sub_to_team(match_id: int, player_id: int, team_id: int, user_id: int, session=None) -> Tuple[bool, str]:
    """
    Assign a substitute player to a team for a specific match.
    
    Args:
        match_id: The ID of the match.
        player_id: The ID of the player to assign as a sub.
        team_id: The ID of the team to which the player will be assigned.
        user_id: The ID of the user making the assignment.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A tuple of (success: bool, message: str)
    """
    if session is None:
        session = g.db_session
        
    try:
        # Check if player exists
        player = session.query(Player).get(player_id)
        if not player:
            return False, "Player not found"
            
        # Check if player is in the substitute pool OR marked as a sub (for backward compatibility)
        from app.models_substitute_pools import SubstitutePool
        in_sub_pool = session.query(SubstitutePool).filter_by(
            player_id=player_id,
            is_active=True
        ).first()
        
        if not in_sub_pool and not player.is_sub:
            return False, "Player is not in the substitute pool or marked as a substitute"
            
        # Check if match exists and belongs to the team
        match = session.query(Match).get(match_id)
        if not match:
            return False, "Match not found"
            
        if match.home_team_id != team_id and match.away_team_id != team_id:
            return False, "Team is not part of this match"
            
        # Check if sub is already assigned to this match
        existing_assignment = session.query(TemporarySubAssignment).filter(
            TemporarySubAssignment.match_id == match_id,
            TemporarySubAssignment.player_id == player_id
        ).first()
        
        if existing_assignment:
            return False, "Player is already assigned as a sub for this match"
            
        # Check if team already has enough substitutes assigned
        sub_request = session.query(SubRequest).filter_by(
            match_id=match_id,
            team_id=team_id
        ).first()
        
        if sub_request:
            current_assignments = session.query(TemporarySubAssignment).filter_by(
                match_id=match_id,
                team_id=team_id
            ).count()
            
            if current_assignments >= sub_request.substitutes_needed:
                return False, f"Team already has {current_assignments} of {sub_request.substitutes_needed} substitutes assigned"
            
        # Create the assignment
        sub_assignment = TemporarySubAssignment(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            assigned_by=user_id,
            created_at=datetime.utcnow()
        )
        
        session.add(sub_assignment)
        session.commit()
        logger.info(f"Assigned player {player_id} as a sub for team {team_id} in match {match_id} by user {user_id}")
        
        return True, "Sub assigned successfully"
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error assigning sub: {str(e)}")
        return False, f"Error: {str(e)}"


def remove_sub_assignment(assignment_id: int, user_id: int, session=None) -> Tuple[bool, str]:
    """
    Remove a temporary sub assignment.
    
    Args:
        assignment_id: The ID of the assignment to remove.
        user_id: The ID of the user performing the removal.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A tuple of (success: bool, message: str)
    """
    if session is None:
        session = g.db_session
        
    try:
        assignment = session.query(TemporarySubAssignment).get(assignment_id)
        if not assignment:
            return False, "Assignment not found"
            
        # Keep track of info for logging
        match_id = assignment.match_id
        player_id = assignment.player_id
        team_id = assignment.team_id
        
        session.delete(assignment)
        session.commit()
        
        logger.info(f"Removed sub assignment of player {player_id} for team {team_id} in match {match_id} by user {user_id}")
        return True, "Sub assignment removed successfully"
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error removing sub assignment: {str(e)}")
        return False, f"Error: {str(e)}"


def get_player_active_sub_assignments(player_id: int, session=None) -> List[Dict[str, Any]]:
    """
    Get all active sub assignments for a player (matches that haven't occurred yet).
    
    Args:
        player_id: The ID of the player.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A list of dictionaries containing assignment information.
    """
    if session is None:
        session = g.db_session
        
    current_date = datetime.utcnow().date()
    
    assignments = session.query(TemporarySubAssignment).join(
        Match, TemporarySubAssignment.match_id == Match.id
    ).filter(
        TemporarySubAssignment.player_id == player_id,
        Match.date >= current_date
    ).options(
        joinedload(TemporarySubAssignment.match),
        joinedload(TemporarySubAssignment.team),
        joinedload(TemporarySubAssignment.assigner)
    ).all()
    
    return [{
        'id': assignment.id,
        'match_id': assignment.match_id,
        'match_date': assignment.match.date,
        'match_time': assignment.match.time,
        'match_location': assignment.match.location,
        'team_id': assignment.team_id,
        'team_name': assignment.team.name,
        'assigned_by': assignment.assigner.username,
        'created_at': assignment.created_at,
        'home_team_name': assignment.match.home_team.name,
        'away_team_name': assignment.match.away_team.name
    } for assignment in assignments]


def cleanup_old_sub_assignments(session=None) -> Tuple[int, str]:
    """
    Clean up sub assignments for matches that occurred in the past.
    This should be run automatically via a scheduled task every Monday.
    
    Args:
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A tuple of (count_deleted: int, message: str)
    """
    if session is None:
        session = g.db_session
        
    try:
        current_date = datetime.utcnow().date()
        
        # Find all assignments for matches that have already occurred
        old_assignments = session.query(TemporarySubAssignment).join(
            Match, TemporarySubAssignment.match_id == Match.id
        ).filter(
            Match.date < current_date
        ).all()
        
        if not old_assignments:
            return 0, "No old assignments found"
        
        # Delete the assignments
        count = len(old_assignments)
        for assignment in old_assignments:
            session.delete(assignment)
            
        session.commit()
        logger.info(f"Cleaned up {count} old sub assignments")
        
        return count, f"Successfully removed {count} old sub assignments"
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error cleaning up old sub assignments: {str(e)}")
        return 0, f"Error: {str(e)}"


def get_sub_requests(filters=None, session=None):
    """
    Retrieve sub requests based on provided filters.
    
    Args:
        filters: A dictionary of filter criteria (match_id, team_id, status, etc.).
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A SQLAlchemy query object for SubRequest objects that match the filters.
    """
    if session is None:
        session = g.db_session
        
    query = session.query(SubRequest).options(
        joinedload(SubRequest.match),
        joinedload(SubRequest.team),
        joinedload(SubRequest.requester),
        joinedload(SubRequest.fulfiller)
    )
    
    if filters:
        if filters.get('match_id'):
            query = query.filter(SubRequest.match_id == filters['match_id'])
        if filters.get('team_id'):
            query = query.filter(SubRequest.team_id == filters['team_id'])
        if filters.get('status'):
            if filters['status'] != 'ALL':
                query = query.filter(SubRequest.status == filters['status'])
        if filters.get('week'):
            query = query.join(Match, SubRequest.match_id == Match.id)\
                         .join(Schedule, Match.schedule_id == Schedule.id)\
                         .filter(Schedule.week == filters['week'])
    
    return query


def create_sub_request(match_id, team_id, requested_by, notes=None, substitutes_needed=1, session=None):
    """
    Create a new sub request.
    
    Args:
        match_id: The ID of the match.
        team_id: The ID of the team.
        requested_by: The ID of the user making the request.
        notes: (Optional) Additional notes for the request.
        substitutes_needed: (Optional) Number of substitutes needed (default 1).
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A tuple of (success: bool, message: str, request_id: int)
    """
    if session is None:
        session = g.db_session
        
    try:
        # Check if the match exists
        match = session.query(Match).get(match_id)
        if not match:
            return False, "Match not found", None
            
        # Check if the team is part of this match
        if match.home_team_id != team_id and match.away_team_id != team_id:
            return False, "Team is not part of this match", None
            
        # Check if there's already a request for this match and team
        existing_request = session.query(SubRequest).filter(
            SubRequest.match_id == match_id,
            SubRequest.team_id == team_id
        ).first()
        
        if existing_request:
            return False, "A sub request already exists for this team and match", None
            
        # Create the request
        sub_request = SubRequest(
            match_id=match_id,
            team_id=team_id,
            requested_by=requested_by,
            notes=notes,
            substitutes_needed=substitutes_needed,
            status='PENDING',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        session.add(sub_request)
        session.flush()  # Get the ID without committing
        
        request_id = sub_request.id
        session.commit()
        logger.info(f"Created sub request {request_id} for match {match_id}, team {team_id} by user {requested_by}")
        
        return True, "Sub request created successfully", request_id
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error creating sub request: {str(e)}")
        return False, f"Error: {str(e)}", None


def update_sub_request_status(request_id, status, fulfilled_by=None, session=None):
    """
    Update the status of a sub request.
    
    Args:
        request_id: The ID of the request.
        status: The new status (PENDING, APPROVED, DECLINED, FULFILLED).
        fulfilled_by: (Optional) The ID of the user who fulfilled the request.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A tuple of (success: bool, message: str)
    """
    if session is None:
        session = g.db_session
        
    try:
        sub_request = session.query(SubRequest).get(request_id)
        if not sub_request:
            return False, "Sub request not found"
            
        # Update the status
        sub_request.status = status
        sub_request.updated_at = datetime.utcnow()
        
        # If the request is being fulfilled, update the fulfiller
        if status == 'FULFILLED' and fulfilled_by:
            sub_request.fulfilled_by = fulfilled_by
        
        session.commit()
        logger.info(f"Updated sub request {request_id} status to {status}")
        
        return True, "Sub request updated successfully"
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating sub request: {str(e)}")
        return False, f"Error: {str(e)}"