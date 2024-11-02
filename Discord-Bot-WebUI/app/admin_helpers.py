from app import db
from app.decorators import db_operation, query_operation
from app.models import (
    User, Role, Permission, MLSMatch, ScheduledMessage,
    Announcement, Team, Match, Availability, Player,
    League, PlayerSeasonStats, Season
)
from sqlalchemy.orm import joinedload
from sqlalchemy import or_
from twilio.rest import Client
from datetime import datetime
from typing import Optional
import docker
import logging
import requests

logger = logging.getLogger(__name__)

@query_operation
def get_filtered_users(filters):
    """Get filtered user query based on provided filters."""
    # Start with base query and joins
    query = User.query.options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.team),
        joinedload(User.player).joinedload(Player.league)
    )

    if filters.get('search'):
        search = f"%{filters['search']}%"
        query = query.filter(or_(
            User.username.ilike(search),
            User.email.ilike(search)
        ))
    
    query = query.outerjoin(Player).outerjoin(Team).outerjoin(League)

    # Role filter
    if filters.get('role'):
        query = query.join(User.roles).filter(Role.name == filters['role'])
        
    # League filter    
    if filters.get('league'):
        if filters['league'] == 'none':
            query = query.filter(Player.league_id.is_(None))
        else:
            try:
                league_id = int(filters['league'])
                query = query.filter(Player.league_id == league_id)
            except ValueError:
                logger.warning(f"Invalid league ID: {filters['league']}")
            
    # Active players filter - convert string to boolean properly
    if filters.get('active'):
        is_active = filters['active'].lower() == 'true' if isinstance(filters['active'], str) else bool(filters['active'])
        if isinstance(is_active, bool):  # Only apply filter if we have a valid boolean
            query = query.filter(Player.is_current_player == is_active)
            
    # Approval status filter
    if filters.get('approved'):
        is_approved = filters['approved'].lower() == 'true' if isinstance(filters['approved'], str) else bool(filters['approved'])
        if isinstance(is_approved, bool):  # Only apply filter if we have a valid boolean
            query = query.filter(User.is_approved == is_approved)

    return query.distinct()  # Use distinct to avoid duplicates from joins

@db_operation
def handle_user_action(action, user_id):
    """Handle user-related actions (approve, remove, reset_password)."""
    user = User.query.get_or_404(user_id)
    if action == 'approve':
        user.is_approved = True
    elif action == 'remove':
        db.session.delete(user)
    return True

# Docker Container Helpers
def get_docker_client():
    """Initialize and return Docker client."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Error initializing Docker client: {e}")
        return None

@query_operation
def get_container_data():
    """Fetch and format Docker container data."""
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

@db_operation
def manage_docker_container(container_id, action):
    """Manage Docker container actions (start, stop, restart)."""
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

# SMS Helpers
def send_sms_message(to_phone_number: str, message_body: str) -> bool:
    """
    Send SMS message using Twilio.
    
    Args:
        to_phone_number: Recipient phone number
        message_body: Message content
        
    Returns:
        bool: Success status
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

# Announcement Management Helpers
@db_operation
def handle_announcement_update(title: str = None, content: str = None, 
                            announcement_id: int = None) -> bool:
    """
    Create or update announcement.
    
    Args:
        title: Announcement title
        content: Announcement content
        announcement_id: ID of existing announcement to update
        
    Returns:
        bool: Success status
    """
    try:
        if announcement_id:
            announcement = Announcement.query.get_or_404(announcement_id)
            announcement.title = title or announcement.title
            announcement.content = content or announcement.content
        else:
            max_position = db.session.query(
                db.func.max(Announcement.position)
            ).scalar() or 0
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

@query_operation
def get_role_permissions_data(role_id: int) -> list:
    """
    Get permissions for a specific role.
    
    Args:
        role_id: Role ID
        
    Returns:
        list: Permission IDs for the role
    """
    role = Role.query.get(role_id)
    if not role:
        return None
    return [perm.id for perm in role.permissions]

@db_operation
def handle_permissions_update(role_id: int, permission_ids: list) -> bool:
    """
    Update role permissions.
    
    Args:
        role_id: Role ID
        permission_ids: List of permission IDs to assign
        
    Returns:
        bool: Success status
    """
    try:
        role = Role.query.get_or_404(role_id)
        role.permissions = Permission.query.filter(
            Permission.id.in_(permission_ids)
        ).all()
        return True
    except Exception as e:
        logger.error(f"Error updating permissions: {e}")
        return False

# RSVP Management Helpers
@query_operation
def get_rsvp_status_data(match: Match) -> list:
    """
    Get RSVP status data for a match.
    
    Args:
        match: Match object
        
    Returns:
        list: RSVP status data for all players
    """
    players_with_availability = db.session.query(Player, Availability).\
        outerjoin(
            Availability,
            (Player.id == Availability.player_id) & 
            (Availability.match_id == match.id)
        ).\
        filter(
            (Player.team_id == match.home_team_id) | 
            (Player.team_id == match.away_team_id)
        ).\
        options(joinedload(Player.team)).\
        all()

    rsvp_data = [{
        'player': player,
        'team': player.team,
        'response': availability.response if availability else 'No Response',
        'responded_at': availability.responded_at if availability else None
    } for player, availability in players_with_availability]

    return sorted(rsvp_data, key=lambda x: (x['team'].name, x['player'].name))

# Match Statistics Helpers
@query_operation
def get_match_stats() -> dict:
    """
    Get comprehensive match statistics.
    
    Returns:
        dict: Match statistics data
    """
    try:
        total_matches = Match.query.count()
        completed_matches = Match.query.filter(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).count()
        
        upcoming_matches = Match.query.filter(
            Match.date >= datetime.utcnow()
        ).count()
        
        return {
            'total_matches': total_matches,
            'completed_matches': completed_matches,
            'upcoming_matches': upcoming_matches,
            'completion_rate': (completed_matches / total_matches * 100) 
                if total_matches > 0 else 0
        }
    except Exception as e:
        logger.error(f"Error getting match stats: {e}")
        return {}

# System Health Check Helpers
def check_system_health() -> dict:
    """
    Check system health status.
    
    Returns:
        dict: Health check results
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
        from flask import current_app
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

def check_task_status() -> dict:
    """
    Get status of background tasks.
    
    Returns:
        dict: Task status information
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
            } for t in tasks[:10]]  # Return details for last 10 tasks
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

@query_operation
def get_container_logs(container_id: str) -> Optional[str]:
    """
    Retrieve logs from a specific Docker container.
    
    Args:
        container_id: ID of the Docker container
        
    Returns:
        Optional[str]: Container logs if successful, None if failed
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

def get_initial_expected_roles(player):
    """Helper function to get expected roles synchronously for initial page load."""
    if player.team:
        roles = []
        # Add team-specific role
        role_suffix = 'Coach' if player.is_coach else 'Player' 
        roles.append(f"ECS-FC-PL-{player.team.name}-{role_suffix}")
        
        # Add league role
        if player.team.league:
            league_map = {
                'Premier': 'ECS-FC-PL-PREMIER',
                'Classic': 'ECS-FC-PL-CLASSIC',
                'ECS FC': 'ECS-FC-LEAGUE'
            }
            league_role = league_map.get(player.team.league.name)
            if league_role:
                roles.append(league_role)
                
        # Add referee role if applicable
        if player.is_ref:
            roles.append('Referee')
            
        return roles
    return []

def get_stored_expected_roles(player):
    """Get expected roles based on stored data without making API calls"""
    expected_roles = []
    
    if player.team:
        # Add team role
        role_suffix = 'Coach' if player.is_coach else 'Player'
        expected_roles.append(f"ECS-FC-PL-{player.team.name}-{role_suffix}")
        
        # Add league role if exists
        if player.team.league:
            league_map = {
                'Premier': 'ECS-FC-PL-PREMIER',
                'Classic': 'ECS-FC-PL-CLASSIC',
                'ECS FC': 'ECS-FC-LEAGUE'
            }
            if player.team.league.name in league_map:
                expected_roles.append(league_map[player.team.league.name])
    
    # Add referee role if applicable
    if player.is_ref:
        expected_roles.append('Referee')
    
    return expected_roles