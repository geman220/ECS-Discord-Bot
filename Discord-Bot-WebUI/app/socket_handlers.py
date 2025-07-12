# app/socket_handlers.py

"""
Socket.IO Event Handlers

This is the SINGLE source of truth for all Socket.IO event handlers.
No other files should register Socket.IO handlers.
"""

import logging
from flask import g
from flask_socketio import emit, join_room
from flask_login import login_required
from sqlalchemy import and_

from app.core import socketio, db
from app.core.session_manager import managed_session
from app.sockets.session import socket_session
from app.tasks.tasks_discord import fetch_role_status, update_player_discord_roles
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

print("🎯 SINGLE SOCKET HANDLERS MODULE LOADED")
logger.info("🎯 SINGLE SOCKET HANDLERS MODULE LOADED")


# =============================================================================
# CONNECTION HANDLERS
# =============================================================================

@socketio.on('connect', namespace='/')
def handle_connect():
    """Handle client connection to the default namespace."""
    print("🔌 HANDLER EXECUTING: Client connected to Socket.IO")
    logger.info("🔌 HANDLER EXECUTING: Client connected to Socket.IO")
    emit('connected', {'message': 'Connected successfully', 'status': 'success'})


@socketio.on('disconnect', namespace='/')
def handle_disconnect():
    """Handle client disconnection."""
    print("🔌 Client disconnected from Socket.IO")
    logger.info("🔌 Client disconnected from Socket.IO")


# =============================================================================
# DRAFT SYSTEM HANDLERS
# =============================================================================

@socketio.on('join_draft_room', namespace='/')
def handle_join_draft_room(data):
    """Handle joining a draft room for a specific league."""
    print(f"🏠 Join draft room request: {data}")
    logger.info(f"🏠 Join draft room request: {data}")
    
    # Check authentication using Flask-Login's current_user
    from flask_login import current_user
    
    print(f"🔍 Authentication check: current_user.is_authenticated = {current_user.is_authenticated}")
    logger.info(f"🔍 Authentication check: current_user.is_authenticated = {current_user.is_authenticated}")
    
    if not current_user.is_authenticated:
        print("🚫 Unauthenticated user tried to join draft room")
        emit('error', {'message': 'Authentication required'})
        return
    
    league_name = data.get('league_name')
    if league_name:
        room = f'draft_{league_name}'
        join_room(room)
        emit('joined_room', {'room': room, 'league': league_name})
        print(f"🏠 User {current_user.username} joined room: {room}")
        logger.info(f"🏠 User {current_user.username} joined room: {room}")


@socketio.on('draft_player_enhanced', namespace='/')
def handle_draft_player_enhanced(data):
    """Handle player drafting with comprehensive error handling."""
    try:
        print(f"🎯 Draft player request: {data}")
        logger.info(f"🎯 Draft player request: {data}")
        
        # Authentication check using Flask-Login's current_user
        from flask_login import current_user
        
        print(f"🔍 Draft auth check: current_user.is_authenticated = {current_user.is_authenticated}")
        logger.info(f"🔍 Draft auth check: current_user.is_authenticated = {current_user.is_authenticated}")
        
        if not current_user.is_authenticated:
            print("🚫 Unauthenticated draft attempt")
            emit('draft_error', {'message': 'Authentication required'})
            return
        
        # Data validation
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        league_name = data.get('league_name')
        
        if not all([player_id, team_id, league_name]):
            print(f"🚫 Missing data: {data}")
            emit('draft_error', {'message': 'Missing required data: player_id, team_id, or league_name'})
            return
        
        # Convert to integers
        try:
            player_id = int(player_id)
            team_id = int(team_id)
        except ValueError:
            print(f"🚫 Invalid ID format")
            emit('draft_error', {'message': 'Invalid player or team ID format'})
            return
        
        # Database operations
        from app.models import Player, Team, League, player_teams, Season
        from app.db_utils import mark_player_for_discord_update
        
        try:
            with managed_session() as session:
                # Normalize league name
                db_league_name = {
                    'classic': 'Classic',
                    'premier': 'Premier',
                    'ecs_fc': 'ECS FC'
                }.get(league_name.lower(), league_name)
                
                # Get league (check if its season is current)
                league = session.query(League).join(Season).filter(
                    League.name == db_league_name,
                    Season.is_current == True
                ).first()
                
                if not league:
                    print(f"🚫 League not found: {db_league_name}")
                    emit('draft_error', {'message': f'League "{db_league_name}" not found'})
                    return
                
                # Get player and team
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).filter(
                    Team.id == team_id,
                    Team.league_id == league.id
                ).first()
                
                if not player:
                    print(f"🚫 Player not found: {player_id}")
                    emit('draft_error', {'message': f'Player with ID {player_id} not found'})
                    return
                
                if not team:
                    print(f"🚫 Team not found: {team_id}")
                    emit('draft_error', {'message': f'Team with ID {team_id} not found'})
                    return
                
                # Check for existing assignment
                existing_assignment = session.query(player_teams).filter(
                    player_teams.c.player_id == player_id,
                    player_teams.c.team_id.in_(
                        session.query(Team.id).filter(Team.league_id == league.id)
                    )
                ).first()
                
                if existing_assignment:
                    print(f"🚫 Player already assigned")
                    emit('draft_error', {'message': f'Player "{player.name}" is already assigned to a team'})
                    return
                
                # Execute the draft
                team.players.append(player)
                
                # Record the draft pick in history
                try:
                    from app.draft_enhanced import DraftService
                    draft_position = DraftService.record_draft_pick(
                        session=session,
                        player_id=player_id,
                        team_id=team_id,
                        league_id=league.id,
                        season_id=league.season_id,
                        drafted_by_user_id=current_user.id,
                        notes=f"Drafted via Socket by {current_user.username}"
                    )
                    print(f"📊 Draft pick #{draft_position} recorded for {player.name} to {team.name}")
                    logger.info(f"📊 Draft pick #{draft_position} recorded for {player.name} to {team.name}")
                except Exception as e:
                    print(f"⚠️ Failed to record draft pick: {str(e)}")
                    logger.error(f"Failed to record draft pick: {str(e)}")
                    # Don't fail the entire operation if draft history fails
                
                # Mark for Discord update
                mark_player_for_discord_update(session, player_id)
                
                # Commit the transaction
                session.commit()
                
                # Success response with full player data for creating the team player card
                response_data = {
                    'success': True,
                    'player': {
                        'id': player.id,
                        'name': player.name,
                        'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_medium': getattr(player, 'profile_picture_medium', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_webp': getattr(player, 'profile_picture_webp', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'favorite_position': player.favorite_position or 'Any',
                        'is_ref': player.is_ref,
                        'career_goals': player.career_stats[0].goals if player.career_stats else 0,
                        'career_assists': player.career_stats[0].assists if player.career_stats else 0,
                        'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
                        'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
                        # Calculate average stats per season
                        'avg_goals_per_season': (
                            round(player.career_stats[0].goals / max(len(player.teams) or 1, 1), 1) 
                            if player.career_stats else 0
                        ),
                        'avg_assists_per_season': (
                            round(player.career_stats[0].assists / max(len(player.teams) or 1, 1), 1) 
                            if player.career_stats else 0
                        ),
                        'league_experience_seasons': 0,  # Could be calculated if needed
                        'attendance_estimate': 75,  # Default value
                        'experience_level': 'New Player'  # Default value
                    },
                    'team_id': team.id,
                    'team_name': team.name,
                    'league_name': league_name
                }
                
                emit('player_drafted_enhanced', response_data)
                print(f"✅ Successfully drafted {player.name} to {team.name}")
                logger.info(f"✅ Successfully drafted {player.name} to {team.name}")
            
            # Trigger Discord role update task (outside the database session)
            from app.tasks.tasks_discord import update_player_discord_roles
            try:
                task = update_player_discord_roles.delay(player_id)
                print(f"🤖 Discord role update task queued: {task.id}")
                logger.info(f"🤖 Discord role update task queued for player {player_id}: {task.id}")
            except Exception as e:
                print(f"⚠️ Failed to queue Discord role update: {str(e)}")
                logger.warning(f"Failed to queue Discord role update: {str(e)}")
                
        except Exception as e:
            print(f"💥 Draft error: {str(e)}")
            logger.error(f"💥 Draft error: {str(e)}", exc_info=True)
            emit('draft_error', {'message': 'Internal server error occurred during draft'})
            
    except Exception as e:
        print(f"🚫 Authentication or validation error: {str(e)}")
        logger.error(f"Authentication or validation error: {str(e)}", exc_info=True)
        emit('draft_error', {'message': 'Authentication or validation failed'})


# =============================================================================
# DISCORD ROLE MANAGEMENT HANDLERS
# =============================================================================

@socketio.on('update_single_player')
@login_required
def handle_single_player_update(data):
    """Queue an update for a single player's Discord roles."""
    with socket_session(db.engine) as session:
        player_id = data.get('player_id')
        if player_id:
            task = update_player_discord_roles.delay(player_id)
            logger.info(f"Queued update for player {player_id}, task ID: {task.id}")
            emit('role_update', {
                'id': player_id,
                'status_class': 'info',
                'status_text': 'Update Queued', 
                'task_id': task.id
            })


@socketio.on('mass_update_roles')
@login_required
def handle_mass_update():
    """Queue a mass update of Discord roles for all players."""
    with socket_session(db.engine) as session:
        task = fetch_role_status.delay()
        logger.info(f"Queued mass update, task ID: {task.id}")
        emit('mass_update_started', {'task_id': task.id})


@socketio.on('check_task_status')
@login_required
def handle_task_status(data):
    """Check the status of an asynchronous task."""
    with socket_session(db.engine) as session:
        task_id = data.get('task_id')
        if task_id:
            task = fetch_role_status.AsyncResult(task_id)
            if task.ready():
                emit('task_complete', {
                    'task_id': task_id,
                    'status': 'complete' if task.successful() else 'failed',
                    'result': task.get() if task.successful() else None,
                    'error': str(task.result) if not task.successful() else None
                })
            else:
                emit('task_status', {'task_id': task_id, 'status': task.status})


# =============================================================================
# TEST HANDLERS
# =============================================================================

@socketio.on('remove_player_enhanced', namespace='/')
def handle_remove_player_enhanced(data):
    """Handle removing a player from a team (return to draft pool)."""
    try:
        print(f"🗑️ Remove player request: {data}")
        logger.info(f"🗑️ Remove player request: {data}")
        
        # Authentication check using Flask-Login's current_user
        from flask_login import current_user
        
        print(f"🔍 Remove auth check: current_user.is_authenticated = {current_user.is_authenticated}")
        logger.info(f"🔍 Remove auth check: current_user.is_authenticated = {current_user.is_authenticated}")
        
        if not current_user.is_authenticated:
            print("🚫 Unauthenticated remove attempt")
            emit('remove_error', {'message': 'Authentication required'})
            return
        
        # Data validation
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        league_name = data.get('league_name')
        
        if not all([player_id, team_id, league_name]):
            print(f"🚫 Missing data for remove: {data}")
            emit('remove_error', {'message': 'Missing required data: player_id, team_id, or league_name'})
            return
        
        # Convert to integers
        try:
            player_id = int(player_id)
            team_id = int(team_id)
        except ValueError:
            print(f"🚫 Invalid ID format for remove")
            emit('remove_error', {'message': 'Invalid player or team ID format'})
            return
        
        # Database operations
        from app.models import Player, Team, League, player_teams, Season
        from app.db_utils import mark_player_for_discord_update
        
        try:
            with managed_session() as session:
                # Normalize league name
                db_league_name = {
                    'classic': 'Classic',
                    'premier': 'Premier',
                    'ecs_fc': 'ECS FC'
                }.get(league_name.lower(), league_name)
                
                # Get league (check if its season is current)
                league = session.query(League).join(Season).filter(
                    League.name == db_league_name,
                    Season.is_current == True
                ).first()
                
                if not league:
                    print(f"🚫 League not found for remove: {db_league_name}")
                    emit('remove_error', {'message': f'League "{db_league_name}" not found'})
                    return
                
                # Get player and team
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).filter(
                    Team.id == team_id,
                    Team.league_id == league.id
                ).first()
                
                if not player:
                    print(f"🚫 Player not found for remove: {player_id}")
                    emit('remove_error', {'message': f'Player with ID {player_id} not found'})
                    return
                
                if not team:
                    print(f"🚫 Team not found for remove: {team_id}")
                    emit('remove_error', {'message': f'Team with ID {team_id} not found'})
                    return
                
                # Check if player is actually on this team
                if player not in team.players:
                    print(f"🚫 Player not on team for remove")
                    emit('remove_error', {'message': f'Player "{player.name}" is not on team "{team.name}"'})
                    return
                
                # Remove player from team
                team.players.remove(player)
            
                # Remove from draft history and adjust subsequent picks
                try:
                    from app.draft_enhanced import DraftService
                    DraftService.remove_draft_pick(
                        session=session,
                        player_id=player_id,
                        season_id=league.season_id,
                        league_id=league.id
                    )
                    print(f"📊 Removed draft history for {player.name} and adjusted subsequent picks")
                    logger.info(f"📊 Removed draft history for {player.name} and adjusted subsequent picks")
                except Exception as e:
                    print(f"⚠️ Failed to remove draft history: {str(e)}")
                    logger.error(f"Failed to remove draft history: {str(e)}")
                    # Don't fail the entire operation if draft history removal fails
                
                # Mark for Discord update
                mark_player_for_discord_update(session, player_id)
                
                # Get the exact same enhanced player data that's used during initial page load
                from app.draft_enhanced import DraftService
                try:
                    print(f"🔍 Getting enhanced player data for {player.name} (ID: {player.id}) using same method as page load...")
                    
                    # Set up the Flask application context to match the route context
                    # The enhanced data method expects g.db_session to be available
                    g.db_session = session
                    
                    # Use the exact same method that generates initial player data
                    # Use league.season_id to match exactly what the route does
                    enhanced_players = DraftService.get_enhanced_player_data([player], league.season_id)
                    
                    if enhanced_players and len(enhanced_players) > 0:
                        # Use the first (and only) enhanced player data
                        enhanced_player = enhanced_players[0]
                        print(f"✅ Successfully got enhanced data for {player.name}")
                        print(f"   - League experience seasons: {enhanced_player.get('league_experience_seasons', 'N/A')}")
                        print(f"   - Experience level: {enhanced_player.get('experience_level', 'N/A')}")
                        print(f"   - Attendance estimate: {enhanced_player.get('attendance_estimate', 'N/A')}")
                        
                        # Create response using the enhanced data (this ensures 100% consistency with page load)
                        player_data = {
                            'id': enhanced_player['id'],
                            'name': enhanced_player['name'],
                            'profile_picture_url': enhanced_player['profile_picture_url'],
                            'profile_picture_medium': enhanced_player.get('profile_picture_medium', enhanced_player['profile_picture_url']),
                            'profile_picture_webp': enhanced_player.get('profile_picture_webp', enhanced_player['profile_picture_url']),
                            'favorite_position': enhanced_player['favorite_position'],
                            'career_goals': enhanced_player['career_goals'],
                            'career_assists': enhanced_player['career_assists'],
                            'career_yellow_cards': enhanced_player['career_yellow_cards'],
                            'career_red_cards': enhanced_player['career_red_cards'],
                            'league_experience_seasons': enhanced_player['league_experience_seasons'],
                            'attendance_estimate': enhanced_player['attendance_estimate'],
                            'experience_level': enhanced_player['experience_level'],
                            'expected_weeks_available': enhanced_player['expected_weeks_available']
                        }
                    else:
                        print(f"❌ No enhanced data returned for {player.name}, using fallback")
                        raise Exception("No enhanced player data returned")
                        
                except Exception as e:
                    print(f"⚠️ Error getting enhanced player data for {player.id}: {e}")
                    logger.warning(f"Error getting enhanced player data for player {player.id}: {e}")
                    
                    # Fallback to basic player data (should rarely be needed)
                    player_data = {
                        'id': player.id,
                        'name': player.name,
                        'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_medium': getattr(player, 'profile_picture_medium', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_webp': getattr(player, 'profile_picture_webp', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'favorite_position': player.favorite_position or 'Any',
                        'career_goals': player.career_stats[0].goals if player.career_stats else 0,
                        'career_assists': player.career_stats[0].assists if player.career_stats else 0,
                        'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
                        'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
                        'league_experience_seasons': 0,
                        'attendance_estimate': None,  # No historical data for fallback case
                        'experience_level': 'New Player',
                        'expected_weeks_available': player.expected_weeks_available or 'All weeks'
                    }
                
                # Commit the transaction
                session.commit()
                
                # Success response with full enhanced player data
                response_data = {
                    'success': True,
                    'player': player_data,
                    'team_id': team.id,
                    'team_name': team.name,
                    'league_name': league_name
                }
                
                emit('player_removed_enhanced', response_data)
                print(f"✅ Successfully removed {player.name} from {team.name}")
                logger.info(f"✅ Successfully removed {player.name} from {team.name}")
                
                # Clean up Flask context
                if hasattr(g, 'db_session'):
                    delattr(g, 'db_session')
            
            # Trigger Discord role update task (will remove roles since player is no longer on team)
            from app.tasks.tasks_discord import update_player_discord_roles
            try:
                task = update_player_discord_roles.delay(player_id)
                print(f"🤖 Discord role update task queued: {task.id}")
                logger.info(f"🤖 Discord role update task queued for player {player_id}: {task.id}")
            except Exception as e:
                print(f"⚠️ Failed to queue Discord role update: {str(e)}")
                logger.warning(f"Failed to queue Discord role update: {str(e)}")
                
        except Exception as e:
            print(f"💥 Database error during player removal: {str(e)}")
            logger.error(f"💥 Database error during player removal: {str(e)}", exc_info=True)
            emit('remove_error', {'message': 'Database error occurred during player removal'})
            return
            
    except Exception as e:
        print(f"💥 Remove error: {str(e)}")
        logger.error(f"💥 Remove error: {str(e)}", exc_info=True)
        emit('remove_error', {'message': 'Internal server error occurred during player removal'})


@socketio.on('simple_test', namespace='/')
def handle_simple_test(data):
    """Simple test handler for debugging."""
    print(f"🔧 Simple test: {data}")
    logger.info(f"🔧 Simple test: {data}")
    emit('simple_response', {'message': 'Test successful!', 'data': data})


print("🎯 ALL SOCKET HANDLERS REGISTERED")
logger.info("🎯 ALL SOCKET HANDLERS REGISTERED")

# Debug: Check if handlers are actually registered
print(f"🔍 SocketIO instance: {id(socketio)}")
logger.info(f"🔍 SocketIO instance: {id(socketio)}")

# Debug: Try to check registered handlers
try:
    if hasattr(socketio.server, 'handlers'):
        default_handlers = socketio.server.handlers.get('/', {})
        print(f"🔍 Handlers in default namespace: {list(default_handlers.keys())}")
        logger.info(f"🔍 Handlers in default namespace: {list(default_handlers.keys())}")
    else:
        print("🚫 No server.handlers attribute found")
except Exception as e:
    print(f"🚫 Error checking handlers: {e}")
    logger.error(f"🚫 Error checking handlers: {e}")