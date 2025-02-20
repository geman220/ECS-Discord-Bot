# app/admin_helpers.py

"""
Miscellaneous Helpers Module

This module provides various helper functions for:
  - Retrieving initial role status for a player without making Discord API calls.
  - Filtering and retrieving users based on dynamic criteria.
  - Handling user actions (approve, remove, reset password).
  - Interacting with Docker containers (e.g., retrieving container data and managing containers).
  - Sending SMS messages using Twilio.
  - Managing announcements (create/update).
  - Retrieving role permissions and updating role permissions.
  - Managing RSVP data for matches.
  - Gathering match statistics.
  - Performing system health checks (database, Redis, Celery, Docker, and task status).
  - Determining initial expected roles for a player.
"""

import logging
import docker
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from twilio.rest import Client
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from flask import current_app

from app.models import User, Role, Player, Team, League, Match, Availability, Announcement, Permission
from app.discord_utils import get_expected_roles
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
        db.session.delete(user)
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
        client = Client(
            current_app.config.get('TWILIO_ACCOUNT_SID'),
            current_app.config.get('TWILIO_AUTH_TOKEN')
        )
        message = client.messages.create(
            body=message_body,
            from_=current_app.config.get('TWILIO_PHONE_NUMBER'),
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
            max_position = db.session.query(db.func.max(Announcement.position)).scalar() or 0
            announcement = Announcement(
                title=title,
                content=content,
                position=max_position + 1
            )
            db.session.add(announcement)
        return True
    except Exception as e:
        logger.error(f"Error handling announcement: {e}")
        return False


def get_role_permissions_data(role_id: int, session=None) -> Optional[List[int]]:
    """
    Retrieve permission IDs for a specific role.

    Args:
        role_id: The ID of the role.
        session: (Optional) A SQLAlchemy session to use for the query.
        
    Returns:
        A list of permission IDs for the role, or None if the role is not found.
    """
    if session is None:
        session = db.session
    role = session.query(Role).get(role_id)
    if not role:
        return None
    return [perm.id for perm in role.permissions]


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
            session = db.session
        role = session.query(Role).get_or_404(role_id)
        role.permissions = session.query(Permission).filter(Permission.id.in_(permission_ids)).all()
        session.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating permissions: {e}")
        return False


# --------------------
# RSVP Management Helpers
# --------------------

def get_rsvp_status_data(match: Match) -> List[Dict[str, Any]]:
    """
    Retrieve RSVP status data for a match.

    Joins the Player and Availability tables to collect each player's RSVP response,
    their team, and the response timestamp, and returns the results sorted by team and player name.

    Args:
        match: The Match object.

    Returns:
        A sorted list of dictionaries containing RSVP status data.
    """
    players_with_availability = db.session.query(Player, Availability).\
        outerjoin(
            Availability,
            (Player.id == Availability.player_id) & (Availability.match_id == match.id)
        ).\
        filter(
            (Player.primary_team_id == match.home_team_id) | (Player.primary_team_id == match.away_team_id)
        ).\
        options(joinedload(Player.primary_team)).\
        all()

    rsvp_data = [{
        'player': player,
        'team': player.primary_team,
        'response': availability.response if availability else 'No Response',
        'responded_at': availability.responded_at if availability else None
    } for player, availability in players_with_availability]

    return sorted(rsvp_data, key=lambda x: (x['team'].name, x['player'].name))


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
        db.session.execute('SELECT 1')
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

    Based on the player's team and league information, as well as their role (coach or referee),
    constructs a list of expected role strings.

    Args:
        player: The Player object.

    Returns:
        A list of expected role strings.
    """
    if player.primary_team:
        roles = []
        role_suffix = 'Coach' if player.is_coach else 'Player'
        roles.append(f"ECS-FC-PL-{player.primary_team.name}-{role_suffix}")
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
            
        return roles
    return []