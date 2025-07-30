from flask import Blueprint, request, jsonify
from flask_login import login_required
from app.models import User, UserFCMToken, Team, Player
from app.models.players import player_teams
from app.services.notification_service import notification_service
from app.core import db
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

team_notifications_bp = Blueprint('team_notifications', __name__, url_prefix='/api/team-notifications')

def find_team_by_discord_role(team_name):
    """
    Find a team by Discord role name with normalization
    
    Examples:
    - "ECS-FC-PL-TEAM-H-PLAYER" -> "Team H"
    - "ECS-FC-PL-DRAGONS-PLAYER" -> "Dragons"  
    - "ECS-FC-PL-VAN-GOAL-PLAYER" -> "Van Goal"
    """
    # First try exact match on discord_player_role_id
    team = Team.query.filter_by(discord_player_role_id=team_name).first()
    
    if not team:
        # Extract and normalize team identifier from Discord role name
        team_parts = team_name.upper().split('-')
        if len(team_parts) >= 4 and team_parts[0:3] == ['ECS', 'FC', 'PL'] and team_parts[-1] == 'PLAYER':
            # Get the team identifier parts (everything between ECS-FC-PL and PLAYER)
            team_identifier_parts = team_parts[3:-1]  # Gets ["TEAM", "H"] or ["DRAGONS"] or ["VAN", "GOAL"]
            
            if team_identifier_parts:
                if len(team_identifier_parts) >= 2 and team_identifier_parts[0] == 'TEAM':
                    # Handle legacy format: "ECS-FC-PL-TEAM-H-PLAYER" -> "Team H"
                    team_letter = team_identifier_parts[1]
                    normalized_team_name = f"Team {team_letter}"
                else:
                    # Handle new format: join parts with spaces and title case
                    # "ECS-FC-PL-DRAGONS-PLAYER" -> "Dragons"
                    # "ECS-FC-PL-VAN-GOAL-PLAYER" -> "Van Goal"
                    normalized_team_name = ' '.join(word.capitalize() for word in team_identifier_parts)
                
                # Try to find team by normalized name
                team = Team.query.filter(Team.name.ilike(normalized_team_name)).first()
                
                if team:
                    logger.info(f"Normalized Discord role '{team_name}' to team name '{normalized_team_name}'")
    
    return team

@team_notifications_bp.route('/send', methods=['POST'])
def send_team_notification():
    """
    API endpoint for Discord bot to trigger team push notifications
    Expected payload:
    {
        "team_name": "ECS-FC-PL-TEAM1-PLAYER",
        "message": "Team message from coach",
        "coach_discord_id": "123456789012345678",
        "title": "Team Message"
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        team_name = data.get('team_name')
        message = data.get('message')
        coach_discord_id = data.get('coach_discord_id')
        title = data.get('title', '⚽ Team Message')
        
        if not all([team_name, message, coach_discord_id]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: team_name, message, coach_discord_id'
            }), 400
        
        # Validate team name format (should match Discord role naming)
        if not team_name.lower().startswith('ecs-fc-pl-') or not team_name.lower().endswith('-player'):
            return jsonify({
                'success': False,
                'error': 'Invalid team name format'
            }), 400
        
        # Find the team using helper function with normalization
        team = find_team_by_discord_role(team_name)
        
        if not team:
            return jsonify({
                'success': False,
                'error': f'Team not found for Discord role: {team_name}'
            }), 404
        
        # Get all players on this team who have Discord IDs and are linked to users
        team_players = db.session.query(Player, User).join(
            player_teams, Player.id == player_teams.c.player_id
        ).join(
            User, Player.user_id == User.id
        ).filter(
            player_teams.c.team_id == team.id,
            Player.discord_id.isnot(None)
        ).all()
        
        # Collect all active FCM tokens for team members (avoiding duplicates)
        team_tokens = []
        for player, user in team_players:
            user_tokens = UserFCMToken.query.filter_by(
                user_id=user.id,
                is_active=True
            ).all()
            
            # Add all active tokens for this user
            for token in user_tokens:
                team_tokens.append(token.fcm_token)
        
        logger.info(f"Found {len(team_tokens)} FCM tokens for team {team.name} (Discord role: {team_name})")
        
        if not team_tokens:
            return jsonify({
                'success': True,
                'message': 'No team members found with push notification tokens',
                'tokens_sent': 0
            })
        
        # Send the push notification
        result = notification_service.send_general_notification(
            team_tokens, 
            title, 
            message,
            extra_data={
                'type': 'team_message',
                'team_name': team_name,
                'coach_discord_id': coach_discord_id,
                'source': 'discord_bot'
            }
        )
        
        logger.info(f"Team notification sent: {result}")
        
        return jsonify({
            'success': True,
            'message': f'Team notification sent to {len(team_tokens)} devices',
            'team_name': team.name,
            'team_discord_role': team_name,
            'tokens_sent_to': len(team_tokens),
            'result': result
        })
        
    except Exception as e:
        logger.error(f"Error sending team notification: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@team_notifications_bp.route('/teams/<team_name>/members', methods=['GET'])
def get_team_members(team_name):
    """
    Get team members with push notification tokens for a specific team
    Used for verification and testing
    """
    try:
        # Find the team using helper function with normalization
        team = find_team_by_discord_role(team_name)
        
        if not team:
            return jsonify({
                'success': False,
                'error': f'Team not found for Discord role: {team_name}'
            }), 404
        
        # Get all team members first (without tokens to avoid duplicates)
        team_players = db.session.query(Player, User).join(
            player_teams, Player.id == player_teams.c.player_id
        ).join(
            User, Player.user_id == User.id
        ).filter(
            player_teams.c.team_id == team.id,
            Player.discord_id.isnot(None)
        ).all()
        
        team_members = []
        for player, user in team_players:
            # Get active FCM tokens for this user
            active_tokens = UserFCMToken.query.filter_by(
                user_id=user.id, 
                is_active=True
            ).all()
            
            # Determine if user has active tokens and what platforms
            has_active_token = len(active_tokens) > 0
            platforms = [token.platform for token in active_tokens] if active_tokens else []
            primary_platform = platforms[0] if platforms else None
            
            team_members.append({
                'player_id': player.id,
                'player_name': player.name,
                'user_id': user.id,
                'username': user.username,
                'discord_id': player.discord_id,
                'platform': primary_platform,
                'platforms': platforms,  # Show all platforms they have tokens for
                'active_token_count': len(active_tokens),
                'has_active_token': has_active_token
            })
        
        # Count members with active tokens
        members_with_active_tokens = sum(1 for member in team_members if member['has_active_token'])
        
        return jsonify({
            'success': True,
            'team_name': team_name,
            'team_id': team.id,
            'team_db_name': team.name,
            'members': team_members,
            'total_members': len(team_members),
            'total_with_tokens': members_with_active_tokens
        })
        
    except Exception as e:
        logger.error(f"Error getting team members: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500