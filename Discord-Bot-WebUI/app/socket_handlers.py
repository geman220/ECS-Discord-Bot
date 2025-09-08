# app/socket_handlers.py

"""
Socket.IO Event Handlers

This is the SINGLE source of truth for all Socket.IO event handlers.
No other files should register Socket.IO handlers.
"""

import logging
from datetime import datetime
from flask import g, request, session
from flask_socketio import emit, join_room
from flask_login import login_required
from sqlalchemy import and_
import jwt
import threading
import time

from app.core import socketio, db
from app.core.session_manager import managed_session
from app.sockets.session import socket_session
from app.tasks.tasks_discord import fetch_role_status, update_player_discord_roles
from app.utils.user_helpers import safe_current_user
from app.models import Player, Team, Match
from app.models.players import player_teams

logger = logging.getLogger(__name__)

print("🎯 SINGLE SOCKET HANDLERS MODULE LOADED")
logger.info("🎯 SINGLE SOCKET HANDLERS MODULE LOADED")

# Import RSVP socket handlers to register them
from app.sockets import rsvp

# Global locks for preventing race conditions in draft operations
_draft_locks = {}  # Dictionary of player_id -> lock
_draft_lock_mutex = threading.Lock()  # Protects _draft_locks dictionary

def get_draft_lock(player_id: int) -> threading.Lock:
    """Get or create a lock for a specific player draft operation."""
    with _draft_lock_mutex:
        if player_id not in _draft_locks:
            _draft_locks[player_id] = threading.Lock()
        return _draft_locks[player_id]

def cleanup_draft_lock(player_id: int):
    """Clean up the lock for a player after operation completes."""
    with _draft_lock_mutex:
        _draft_locks.pop(player_id, None)


# =============================================================================
# CONNECTION HANDLERS
# =============================================================================

# Enhanced JWT Authentication Middleware for Socket.IO
def authenticate_socket_connection(auth=None):
    """
    Comprehensive JWT authentication middleware for Socket.IO connections.
    
    Extracts JWT tokens from:
    1. Auth object (auth.token)
    2. Authorization header (Bearer token)
    3. Query parameters (?token=...)
    4. Custom auth header variations
    
    Args:
        auth: Authentication object from Socket.IO client
        
    Returns:
        dict: Authentication result with user_id and status
    """
    token = None
    token_source = None
    
    try:
        # 1. Check auth object first (Socket.IO client auth parameter)
        if auth and isinstance(auth, dict):
            # Special handling for Discord bot connections
            if auth.get('type') == 'discord-bot' and auth.get('api_key'):
                logger.info(f"🔌 [AUTH] Discord bot authentication detected")
                # For Discord bot, we can skip JWT validation
                # Return authenticated with a special system user ID
                return {
                    'authenticated': True,
                    'user_id': -1,  # Special system user ID for Discord bot
                    'username': 'Discord Bot',
                    'auth_type': 'discord-bot'
                }
            
            token = auth.get('token')
            if token:
                token_source = "auth_object"
                logger.info(f"🔌 [AUTH] Token found in auth object")
        
        # 2. Check Authorization header
        if not token:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header[7:]  # Remove 'Bearer ' prefix
                token_source = "authorization_header"
                logger.info(f"🔌 [AUTH] Token found in Authorization header")
        
        # 3. Check query parameters
        if not token:
            token = request.args.get('token')
            if token:
                token_source = "query_parameter"
                logger.info(f"🔌 [AUTH] Token found in query parameter")
        
        # 4. Check alternative auth headers (for mobile compatibility)
        if not token:
            for header_name in ['X-Auth-Token', 'Auth-Token', 'JWT-Token']:
                token = request.headers.get(header_name)
                if token:
                    token_source = f"header_{header_name.lower()}"
                    logger.info(f"🔌 [AUTH] Token found in {header_name} header")
                    break
        
        if not token:
            logger.warning("🔌 [AUTH] No JWT token found in any source")
            return {
                'authenticated': False,
                'user_id': None,
                'error': 'No authentication token provided'
            }
        
        # Validate JWT token using existing API validation logic
        logger.info(f"🔌 [AUTH] Attempting JWT validation from {token_source}")
        logger.info(f"🔌 [AUTH] Token length: {len(token)}")
        
        # Use Flask-JWT-Extended for validation (same as API endpoints)
        from flask_jwt_extended import decode_token
        from flask import current_app
        
        try:
            # Try Flask-JWT-Extended first (matches API authentication)
            decoded_token = decode_token(token)
            user_id = decoded_token.get('sub') or decoded_token.get('identity')
            
        except Exception as jwt_ext_error:
            logger.warning(f"🔌 [AUTH] Flask-JWT-Extended failed: {jwt_ext_error}")
            
            # Fallback to manual JWT decode
            import jwt as pyjwt
            try:
                decoded_token = pyjwt.decode(
                    token,
                    current_app.config.get('JWT_SECRET_KEY'),
                    algorithms=['HS256']
                )
                user_id = decoded_token.get('sub') or decoded_token.get('identity') or decoded_token.get('id')
                
            except Exception as manual_error:
                logger.error(f"🔌 [AUTH] Manual JWT decode failed: {manual_error}")
                return {
                    'authenticated': False,
                    'user_id': None,
                    'error': f'Invalid JWT token: {str(manual_error)}'
                }
        
        if not user_id:
            logger.error("🔌 [AUTH] No user ID found in JWT token")
            return {
                'authenticated': False,
                'user_id': None,
                'error': 'JWT token missing user identifier'
            }
        
        # Verify user exists in database (optional but recommended)
        try:
            with managed_session() as session_db:
                user = session_db.query(User).get(user_id)
                if user:
                    logger.info(f"🔌 [AUTH] Authentication successful for user {user.username} (ID: {user_id})")
                    return {
                        'authenticated': True,
                        'user_id': user_id,
                        'username': user.username,
                        'token_source': token_source
                    }
                else:
                    logger.warning(f"🔌 [AUTH] User ID {user_id} not found in database")
                    # Still allow connection for testing, but mark as unverified
                    return {
                        'authenticated': True,
                        'user_id': user_id,
                        'username': f'User_{user_id}',
                        'token_source': token_source,
                        'unverified': True
                    }
        except Exception as db_error:
            logger.error(f"🔌 [AUTH] Database verification failed: {db_error}")
            # Still allow connection if DB check fails
            return {
                'authenticated': True,
                'user_id': user_id,
                'username': f'User_{user_id}',
                'token_source': token_source,
                'db_error': True
            }
            
    except Exception as e:
        logger.error(f"🔌 [AUTH] Authentication middleware error: {str(e)}", exc_info=True)
        return {
            'authenticated': False,
            'user_id': None,
            'error': f'Authentication system error: {str(e)}'
        }


@socketio.on('connect', namespace='/')
def handle_connect(auth):
    """Handle client connection to the default namespace with enhanced authentication."""
    logger.info("🔌 [CONNECT] Client connecting to Socket.IO default namespace")
    
    try:
        # Use enhanced authentication middleware
        auth_result = authenticate_socket_connection(auth)
        
        if auth_result['authenticated']:
            user_id = auth_result['user_id']
            username = auth_result.get('username', f'User_{user_id}')
            
            # Store user info in session for this connection
            session['user_id'] = user_id
            session['authenticated'] = True
            session['username'] = username
            
            # Store in Flask g for request context
            g.socket_user_id = user_id
            
            # Emit authentication success event
            emit('authentication_success', {
                'user_id': user_id,
                'username': username,
                'message': 'Authentication successful',
                'token_source': auth_result.get('token_source'),
                'timestamp': datetime.utcnow().isoformat(),
                'namespace': '/'
            })
            
            logger.info(f"🔌 [CONNECT] Successfully authenticated {username} (ID: {user_id})")
            
        else:
            # Authentication failed - still allow connection but inform client
            logger.warning(f"🔌 [CONNECT] Authentication failed: {auth_result.get('error')}")
            
            emit('authentication_failed', {
                'error': auth_result.get('error'),
                'message': 'Connection established without authentication',
                'timestamp': datetime.utcnow().isoformat(),
                'namespace': '/'
            })
        
        # Always emit connected event for backward compatibility
        emit('connected', {
            'message': 'Connected to Socket.IO',
            'authenticated': auth_result['authenticated'],
            'timestamp': datetime.utcnow().isoformat(),
            'namespace': '/'
        })
        
        return True  # Allow connection regardless of auth status
        
    except Exception as e:
        logger.error(f"🔌 [CONNECT] Connection handler error: {str(e)}", exc_info=True)
        
        # Emit error but still allow connection
        emit('connection_error', {
            'error': str(e),
            'message': 'Connection established with errors',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        return True


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
    """Handle player drafting with comprehensive error handling and race condition protection."""
    # Data validation first (before acquiring locks)
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
    
    # Acquire player-specific lock to prevent race conditions
    draft_lock = get_draft_lock(player_id)
    
    # Use a timeout to prevent indefinite blocking
    if not draft_lock.acquire(timeout=5.0):
        print(f"🚫 Draft operation timeout for player {player_id} - possibly concurrent request")
        emit('draft_error', {'message': 'Draft operation in progress for this player, please wait'})
        return
    
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
                
                # Get player and team (with players relationship eagerly loaded)
                from sqlalchemy.orm import joinedload
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).options(
                    joinedload(Team.players)
                ).filter(
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
                
                # Comprehensive check for existing assignment
                # Check both player_teams table and PlayerTeamSeason table
                existing_player_team = session.query(player_teams).filter(
                    player_teams.c.player_id == player_id,
                    player_teams.c.team_id.in_(
                        session.query(Team.id).filter(Team.league_id == league.id)
                    )
                ).first()
                
                if existing_player_team:
                    existing_team = session.query(Team).filter(Team.id == existing_player_team.team_id).first()
                    team_name = existing_team.name if existing_team else "unknown team"
                    print(f"🚫 Player {player.name} already assigned to {team_name} in {league.name}")
                    emit('draft_error', {'message': f'Player "{player.name}" is already assigned to {team_name} in {league.name}'})
                    return
                
                # Also check PlayerTeamSeason for current season
                from app.models import PlayerTeamSeason
                existing_pts = session.query(PlayerTeamSeason).filter(
                    PlayerTeamSeason.player_id == player_id,
                    PlayerTeamSeason.season_id == league.season_id,
                    PlayerTeamSeason.team_id.in_(
                        session.query(Team.id).filter(Team.league_id == league.id)
                    )
                ).first()
                
                if existing_pts:
                    existing_team = session.query(Team).filter(Team.id == existing_pts.team_id).first()
                    team_name = existing_team.name if existing_team else "unknown team"
                    print(f"🚫 Player {player.name} already has PlayerTeamSeason record with {team_name} in season {league.season_id}")
                    emit('draft_error', {'message': f'Player "{player.name}" is already assigned to {team_name} for this season'})
                    return
                
                # Execute the draft (check if already exists to avoid duplicates)
                # Check both directions: player.teams and team.players for safety
                if player not in team.players:
                    team.players.append(player)
                    player.primary_team_id = team_id
                    print(f"🎯 Added {player.name} to {team.name} and set as primary team (ID: {team_id})")
                else:
                    # Still set primary team even if relationship exists
                    player.primary_team_id = team_id
                    print(f"🎯 {player.name} already on {team.name} - updated primary team ID to {team_id}")
                
                # Create PlayerTeamSeason record for current season
                # We already checked above that no PTS record exists, so create it
                player_team_season = PlayerTeamSeason(
                    player_id=player_id,
                    team_id=team_id,
                    season_id=league.season_id
                )
                session.add(player_team_season)
                print(f"📝 Created new PlayerTeamSeason record for {player.name} to {team.name}")
                
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
                
                # Mark for Discord update (but we'll handle role assignment below)
                mark_player_for_discord_update(session, player_id)
                
                # Commit the transaction with proper error handling
                try:
                    session.commit()
                except Exception as commit_error:
                    session.rollback()
                    logger.error(f"💥 Draft commit failed: {str(commit_error)}")
                    emit('draft_error', {'message': f'Failed to save draft: {str(commit_error)}'})
                    return
                
                # Queue Discord role assignment task AFTER commit to add new team role (keep existing roles)
                from app.tasks.tasks_discord import assign_roles_to_player_task
                assign_roles_to_player_task.delay(player_id=player_id, only_add=True)
                print(f"🎭 Queued Discord role update for {player.name} (only_add = True to keep existing roles)")
                logger.info(f"🎭 Queued Discord role update for {player.name} (only_add = True to keep existing roles)")
                
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
                # Add timeout and expiration to prevent task buildup
                task = update_player_discord_roles.apply_async(
                    args=[player_id],
                    expires=300,  # Task expires after 5 minutes
                    priority=3    # Medium priority
                )
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
    finally:
        # Always release the lock
        draft_lock.release()
        cleanup_draft_lock(player_id)


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
# MATCH ROOM HANDLERS
# =============================================================================

@socketio.on('join_match', namespace='/')
def handle_join_match(data):
    """Handle client joining a match room - supports both web (Flask-Login) and mobile (JWT) authentication."""
    try:
        # Try JWT authentication first (for mobile apps)
        auth_result = authenticate_socket_connection(data.get('auth'))
        
        if not auth_result['authenticated']:
            # Fall back to Flask-Login (for web users)
            from flask_login import current_user
            if not current_user.is_authenticated:
                emit('error', {'message': 'Authentication required'})
                return
            user_id = current_user.id
            username = current_user.username
        else:
            user_id = auth_result['user_id']
            username = auth_result.get('username', f'User_{user_id}')
        
        match_id = data.get('match_id')
        team_id = data.get('team_id')
        
        if not match_id:
            emit('error', {'message': 'Match ID required'})
            return
            
        try:
            match_id = int(match_id)
        except ValueError:
            emit('error', {'message': 'Invalid match ID format'})
            return
        
        with managed_session() as session:
            # Verify match exists
            match = session.query(Match).get(match_id)
            if not match:
                emit('error', {'message': 'Match not found'})
                return
            
            # Get player info
            player = session.query(Player).filter(Player.user_id == user_id).first()
            player_name = player.name if player else username
            player_id = player.id if player else None
            
            # Join both room formats for compatibility  
            room_with_underscore = f'match_{match_id}'
            room_without_underscore = f'match{match_id}'
            join_room(room_with_underscore)
            join_room(room_without_underscore)
            
            # Send success response (compatible with RSVP expectations)
            emit('joined_match_rsvp', {
                'match_id': match_id,
                'room': room_without_underscore,  # Flutter expects this format
                'team_id': team_id,
                'match_info': {
                    'home_team_id': match.home_team_id,
                    'home_team_name': match.home_team.name,
                    'away_team_id': match.away_team_id,
                    'away_team_name': match.away_team.name,
                    'date': match.date.isoformat(),
                    'time': match.time.isoformat() if match.time else None
                },
                'message': 'Successfully joined match room for RSVP updates'
            })
            
            logger.info(f"👥 User {username} (player: {player_name}) joined match {match_id} room via join_match")
            
    except Exception as e:
        logger.error(f"Error joining match: {str(e)}", exc_info=True)
        emit('error', {'message': 'Failed to join match'})


@socketio.on('join_match_room', namespace='/')
@login_required
def handle_join_match_room(data):
    """Handle coach joining a match room for real-time match event reporting."""
    try:
        from flask_login import current_user
        from app.models import Player, Team, Match, player_teams
        
        match_id = data.get('match_id')
        if not match_id:
            emit('match_room_error', {'message': 'Match ID is required'})
            return
        
        try:
            match_id = int(match_id)
        except ValueError:
            emit('match_room_error', {'message': 'Invalid match ID format'})
            return
        
        with managed_session() as session:
            # Get the match
            match = session.query(Match).filter(Match.id == match_id).first()
            if not match:
                emit('match_room_error', {'message': 'Match not found'})
                return
            
            # Get user's player record
            player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not player:
                emit('match_room_error', {'message': 'Player profile not found'})
                return
            
            # Check if user is a coach for either team in this match
            user_teams = session.query(player_teams).filter(
                and_(
                    player_teams.c.player_id == player.id,
                    player_teams.c.is_coach == True,
                    player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
                )
            ).all()
            
            if not user_teams:
                emit('match_room_error', {'message': 'You are not authorized to report for this match'})
                return
            
            # Join the match room
            room = f'match_{match_id}'
            join_room(room)
            
            # Get current connected coaches in room
            connected_coaches = get_match_room_coaches(match_id, session)
            
            # Add current user to the list
            if current_user.id not in [coach['user_id'] for coach in connected_coaches]:
                connected_coaches.append({
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': player.name,
                    'team_name': user_teams[0].team_id == match.home_team_id and match.home_team.name or match.away_team.name
                })
            
            # Store coach in match room (you may want to implement Redis storage for this)
            # For now, we'll broadcast the join event
            
            emit('joined_match_room', {
                'match_id': match_id,
                'room': room,
                'match': match.to_dict(include_teams=True, include_events=True),
                'connected_coaches': connected_coaches,
                'your_team_id': user_teams[0].team_id
            })
            
            # Broadcast to room that a new coach joined
            emit('coach_joined', {
                'coach': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': player.name,
                    'team_name': user_teams[0].team_id == match.home_team_id and match.home_team.name or match.away_team.name
                }
            }, room=room)
            
            logger.info(f"Coach {current_user.username} joined match room {room}")
            
    except Exception as e:
        logger.error(f"Error joining match room: {str(e)}", exc_info=True)
        emit('match_room_error', {'message': 'Failed to join match room'})


@socketio.on('leave_match_room', namespace='/')
@login_required
def handle_leave_match_room(data):
    """Handle coach leaving a match room."""
    try:
        from flask_login import current_user
        
        match_id = data.get('match_id')
        if not match_id:
            emit('match_room_error', {'message': 'Match ID is required'})
            return
        
        room = f'match_{match_id}'
        
        # Broadcast to room that coach left
        emit('coach_left', {
            'user_id': current_user.id,
            'username': current_user.username
        }, room=room)
        
        emit('left_match_room', {'match_id': match_id})
        logger.info(f"Coach {current_user.username} left match room {room}")
        
    except Exception as e:
        logger.error(f"Error leaving match room: {str(e)}", exc_info=True)
        emit('match_room_error', {'message': 'Failed to leave match room'})


@socketio.on('report_match_event', namespace='/')
@login_required
def handle_report_match_event(data):
    """Handle reporting a match event (goal, assist, card, etc.)."""
    try:
        from flask_login import current_user
        from app.models import Player, Team, Match, player_teams
        from app.models.stats import PlayerEvent, PlayerEventType
        
        match_id = data.get('match_id')
        event_type = data.get('event_type')
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        minute = data.get('minute')
        
        if not all([match_id, event_type]):
            emit('match_event_error', {'message': 'Match ID and event type are required'})
            return
        
        # Validate event type
        if event_type not in [e.value for e in PlayerEventType]:
            emit('match_event_error', {'message': 'Invalid event type'})
            return
        
        # For own goals, team_id is required instead of player_id
        if event_type == 'own_goal' and not team_id:
            emit('match_event_error', {'message': 'Team ID is required for own goals'})
            return
        elif event_type != 'own_goal' and not player_id:
            emit('match_event_error', {'message': 'Player ID is required for this event type'})
            return
        
        with managed_session() as session:
            # Get the match
            match = session.query(Match).filter(Match.id == match_id).first()
            if not match:
                emit('match_event_error', {'message': 'Match not found'})
                return
            
            # Verify user is authorized to report for this match
            reporting_player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not reporting_player:
                emit('match_event_error', {'message': 'Player profile not found'})
                return
            
            user_teams = session.query(player_teams).filter(
                and_(
                    player_teams.c.player_id == reporting_player.id,
                    player_teams.c.is_coach == True,
                    player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
                )
            ).all()
            
            if not user_teams:
                emit('match_event_error', {'message': 'You are not authorized to report for this match'})
                return
            
            # Create the event
            event = PlayerEvent(
                match_id=match_id,
                event_type=PlayerEventType(event_type),
                minute=str(minute) if minute else None
            )
            
            if event_type == 'own_goal':
                event.team_id = team_id
            else:
                event.player_id = player_id
            
            session.add(event)
            session.commit()
            
            # Broadcast event to all coaches in the room
            room = f'match_{match_id}'
            event_data = {
                'event': event.to_dict(include_player=True),
                'reported_by': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': reporting_player.name
                },
                'match_id': match_id
            }
            
            emit('match_event_reported', event_data, room=room)
            emit('event_reported_success', event_data)
            
            logger.info(f"Match event reported: {event_type} by {current_user.username} for match {match_id}")
            
    except Exception as e:
        logger.error(f"Error reporting match event: {str(e)}", exc_info=True)
        emit('match_event_error', {'message': 'Failed to report match event'})


@socketio.on('delete_match_event', namespace='/')
@login_required 
def handle_delete_match_event(data):
    """Handle deleting a match event."""
    try:
        from flask_login import current_user
        from app.models import Player, player_teams
        from app.models.stats import PlayerEvent
        
        event_id = data.get('event_id')
        match_id = data.get('match_id')
        
        if not all([event_id, match_id]):
            emit('match_event_error', {'message': 'Event ID and Match ID are required'})
            return
        
        with managed_session() as session:
            # Get the event
            event = session.query(PlayerEvent).filter(PlayerEvent.id == event_id).first()
            if not event:
                emit('match_event_error', {'message': 'Event not found'})
                return
            
            # Verify user is authorized
            reporting_player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not reporting_player:
                emit('match_event_error', {'message': 'Player profile not found'})
                return
            
            user_teams = session.query(player_teams).filter(
                and_(
                    player_teams.c.player_id == reporting_player.id,
                    player_teams.c.is_coach == True,
                    player_teams.c.team_id.in_([event.match.home_team_id, event.match.away_team_id])
                )
            ).all()
            
            if not user_teams:
                emit('match_event_error', {'message': 'You are not authorized to delete this event'})
                return
            
            # Delete the event
            session.delete(event)
            session.commit()
            
            # Broadcast deletion to all coaches in the room
            room = f'match_{match_id}'
            deletion_data = {
                'event_id': event_id,
                'deleted_by': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': reporting_player.name
                },
                'match_id': match_id
            }
            
            emit('match_event_deleted', deletion_data, room=room)
            emit('event_deleted_success', deletion_data)
            
            logger.info(f"Match event {event_id} deleted by {current_user.username}")
            
    except Exception as e:
        logger.error(f"Error deleting match event: {str(e)}", exc_info=True)
        emit('match_event_error', {'message': 'Failed to delete match event'})


@socketio.on('start_match_timer', namespace='/')
@login_required
def handle_start_match_timer(data):
    """Handle starting the match timer."""
    try:
        from flask_login import current_user
        from app.models import Player, player_teams
        
        match_id = data.get('match_id')
        if not match_id:
            emit('match_timer_error', {'message': 'Match ID is required'})
            return
        
        with managed_session() as session:
            # Verify authorization
            reporting_player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not reporting_player:
                emit('match_timer_error', {'message': 'Player profile not found'})
                return
            
            # Store timer state (you may want to implement Redis storage)
            # For now, just broadcast the timer start
            room = f'match_{match_id}'
            timer_data = {
                'action': 'start',
                'match_id': match_id,
                'started_by': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': reporting_player.name
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
            emit('match_timer_updated', timer_data, room=room)
            emit('timer_action_success', timer_data)
            
            logger.info(f"Match timer started by {current_user.username} for match {match_id}")
            
    except Exception as e:
        logger.error(f"Error starting match timer: {str(e)}", exc_info=True)
        emit('match_timer_error', {'message': 'Failed to start match timer'})


@socketio.on('pause_match_timer', namespace='/')
@login_required
def handle_pause_match_timer(data):
    """Handle pausing the match timer."""
    try:
        from flask_login import current_user
        from app.models import Player
        
        match_id = data.get('match_id')
        current_time = data.get('current_time', 0)
        
        if not match_id:
            emit('match_timer_error', {'message': 'Match ID is required'})
            return
        
        with managed_session() as session:
            reporting_player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not reporting_player:
                emit('match_timer_error', {'message': 'Player profile not found'})
                return
            
            room = f'match_{match_id}'
            timer_data = {
                'action': 'pause',
                'match_id': match_id,
                'current_time': current_time,
                'paused_by': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': reporting_player.name
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
            emit('match_timer_updated', timer_data, room=room)
            emit('timer_action_success', timer_data)
            
            logger.info(f"Match timer paused by {current_user.username} for match {match_id}")
            
    except Exception as e:
        logger.error(f"Error pausing match timer: {str(e)}", exc_info=True)
        emit('match_timer_error', {'message': 'Failed to pause match timer'})


@socketio.on('resume_match_timer', namespace='/')
@login_required
def handle_resume_match_timer(data):
    """Handle resuming the match timer."""
    try:
        from flask_login import current_user
        from app.models import Player
        
        match_id = data.get('match_id')
        current_time = data.get('current_time', 0)
        
        if not match_id:
            emit('match_timer_error', {'message': 'Match ID is required'})
            return
        
        with managed_session() as session:
            reporting_player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not reporting_player:
                emit('match_timer_error', {'message': 'Player profile not found'})
                return
            
            room = f'match_{match_id}'
            timer_data = {
                'action': 'resume',
                'match_id': match_id,
                'current_time': current_time,
                'resumed_by': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': reporting_player.name
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
            emit('match_timer_updated', timer_data, room=room)
            emit('timer_action_success', timer_data)
            
            logger.info(f"Match timer resumed by {current_user.username} for match {match_id}")
            
    except Exception as e:
        logger.error(f"Error resuming match timer: {str(e)}", exc_info=True)
        emit('match_timer_error', {'message': 'Failed to resume match timer'})


@socketio.on('end_match', namespace='/')
@login_required
def handle_end_match(data):
    """Handle ending the match."""
    try:
        from flask_login import current_user
        from app.models import Player, Match, player_teams
        
        match_id = data.get('match_id')
        home_score = data.get('home_score')
        away_score = data.get('away_score')
        
        if not all([match_id, home_score is not None, away_score is not None]):
            emit('match_end_error', {'message': 'Match ID and both scores are required'})
            return
        
        with managed_session() as session:
            # Get the match
            match = session.query(Match).filter(Match.id == match_id).first()
            if not match:
                emit('match_end_error', {'message': 'Match not found'})
                return
            
            # Verify authorization
            reporting_player = session.query(Player).filter(Player.user_id == current_user.id).first()
            if not reporting_player:
                emit('match_end_error', {'message': 'Player profile not found'})
                return
            
            user_teams = session.query(player_teams).filter(
                and_(
                    player_teams.c.player_id == reporting_player.id,
                    player_teams.c.is_coach == True,
                    player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
                )
            ).all()
            
            if not user_teams:
                emit('match_end_error', {'message': 'You are not authorized to end this match'})
                return
            
            # Update match scores
            match.home_team_score = int(home_score)
            match.away_team_score = int(away_score)
            session.commit()
            
            room = f'match_{match_id}'
            end_data = {
                'action': 'end',
                'match_id': match_id,
                'home_score': home_score,
                'away_score': away_score,
                'ended_by': {
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'player_name': reporting_player.name
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
            emit('match_ended', end_data, room=room)
            emit('match_end_success', end_data)
            
            logger.info(f"Match {match_id} ended by {current_user.username} with score {home_score}-{away_score}")
            
    except Exception as e:
        logger.error(f"Error ending match: {str(e)}", exc_info=True)
        emit('match_end_error', {'message': 'Failed to end match'})


@socketio.on('get_connected_coaches', namespace='/')
@login_required
def handle_get_connected_coaches(data):
    """Get list of currently connected coaches for a match."""
    try:
        match_id = data.get('match_id')
        if not match_id:
            emit('coaches_error', {'message': 'Match ID is required'})
            return
        
        with managed_session() as session:
            connected_coaches = get_match_room_coaches(match_id, session)
            emit('connected_coaches', {
                'match_id': match_id,
                'coaches': connected_coaches
            })
            
    except Exception as e:
        logger.error(f"Error getting connected coaches: {str(e)}", exc_info=True)
        emit('coaches_error', {'message': 'Failed to get connected coaches'})


def get_match_room_coaches(match_id, session):
    """Helper function to get connected coaches for a match room."""
    try:
        room_name = f'match_{match_id}'
        connected_coaches = []
        
        # Try to get participants from the socket server
        if hasattr(socketio, 'server') and hasattr(socketio.server, 'manager'):
            try:
                # Get all socket IDs currently in the room
                participants = socketio.server.manager.get_participants('/', room_name)
                
                for sid in participants:
                    try:
                        # Get session data for this socket
                        session_data = socketio.server.get_session(sid)
                        user_id = session_data.get('user_id')
                        
                        if user_id:
                            # Get user and player info from database
                            from app.models import Player, User
                            user = session.query(User).filter(User.id == user_id).first()
                            if user:
                                player = session.query(Player).filter(Player.user_id == user_id).first()
                                if player:
                                    connected_coaches.append({
                                        'user_id': user.id,
                                        'username': user.username,
                                        'player_name': player.name,
                                        'team_name': None  # Could be enhanced to include team info
                                    })
                    except Exception as e:
                        logger.warning(f"Error getting user info for socket {sid}: {str(e)}")
                        continue
                        
            except Exception as e:
                logger.warning(f"Error getting room participants: {str(e)}")
        
        return connected_coaches
        
    except Exception as e:
        logger.error(f"Error in get_match_room_coaches: {str(e)}", exc_info=True)
        return []


# =============================================================================
# TEST HANDLERS
# =============================================================================

@socketio.on('update_player_position', namespace='/')
def handle_update_player_position(data):
    """Handle updating a player's position on the pitch."""
    logger.info(f"Received position update request: {data}")
    
    try:
        # Validate required data
        required_fields = ['player_id', 'team_id', 'position', 'league_name']
        if not all(field in data for field in required_fields):
            emit('error', {'message': 'Missing required data'})
            return
        
        player_id = int(data['player_id'])
        team_id = int(data['team_id'])
        position = data['position']
        league_name = data['league_name']
        
        # Validate position
        valid_positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench']
        if position not in valid_positions:
            emit('error', {'message': f'Invalid position: {position}'})
            return
        
        with managed_session() as session:
            # Get player and team
            player = session.query(Player).filter(Player.id == player_id).first()
            team = session.query(Team).filter(Team.id == team_id).first()
            
            if not player:
                emit('error', {'message': 'Player not found'})
                return
            
            if not team:
                emit('error', {'message': 'Team not found'})
                return
            
            # Check if player is on this team
            if team not in player.teams:
                emit('error', {'message': 'Player is not on this team'})
                return
            
            # Update the position in player_teams table
            from sqlalchemy import text
            
            # Update the position field in the player_teams association table
            update_stmt = text("""
                UPDATE player_teams 
                SET position = :position 
                WHERE player_id = :player_id AND team_id = :team_id
            """)
            
            result = session.execute(update_stmt, {
                'position': position,
                'player_id': player_id,
                'team_id': team_id
            })
            
            if result.rowcount == 0:
                # Player might not be on the team yet - this shouldn't happen but let's handle it
                emit('error', {'message': 'Player-team relationship not found'})
                return
            
            session.commit()
            
            # Emit to all clients in the draft room
            room = f"draft_{league_name}"
            player_data = {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url,
                'favorite_position': player.favorite_position
            }
            
            emit('player_position_updated', {
                'player': player_data,
                'team_id': team_id,
                'team_name': team.name,
                'position': position,
                'league_name': league_name
            }, room=room)
            
            logger.info(f"Updated {player.name} position to {position} on team {team.name}")
        
    except Exception as e:
        logger.error(f"Error updating player position: {str(e)}", exc_info=True)
        emit('error', {'message': 'Failed to update player position'})


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
                
                # Get player and team (with players relationship eagerly loaded)
                from sqlalchemy.orm import joinedload
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).options(
                    joinedload(Team.players)
                ).filter(
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
                
                # Remove player from team using SQLAlchemy ORM
                team.players.remove(player)
                
                # Clear primary team if it matches the team being removed
                if player.primary_team_id == team_id:
                    player.primary_team_id = None
                    print(f"🗑️ Cleared primary team for {player.name}")
                
                # Remove PlayerTeamSeason records for current season
                from app.models import PlayerTeamSeason
                season_records = session.query(PlayerTeamSeason).filter(
                    PlayerTeamSeason.player_id == player_id,
                    PlayerTeamSeason.team_id == team_id,
                    PlayerTeamSeason.season_id == league.season_id
                ).all()
                
                for record in season_records:
                    session.delete(record)
                    print(f"🗑️ Removed PlayerTeamSeason record: {record.id}")
                    logger.info(f"🗑️ Removed PlayerTeamSeason record: {record.id}")
            
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
                
                # Queue Discord role update task AFTER commit to ensure team removal is reflected
                from app.tasks.tasks_discord import assign_roles_to_player_task
                assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
                
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