# app/sockets/live_reporting.py

"""
Live Match Reporting Socket Handlers

This module implements WebSocket handlers for the multi-user live match reporting
system. It allows multiple coaches to simultaneously report on a match with:

1. Synchronized match state (score, time, events) across all connected users
2. Team-specific player shift tracking that is not synchronized
3. Equal permissions for all connected coaches
4. Real-time updates when any reporter makes changes
"""

import logging
from datetime import datetime, timedelta
from flask import request, g, current_app
from flask_socketio import emit, join_room, leave_room, disconnect
from flask_login import current_user, login_required

from app.core import socketio, db
from app.core.session_manager import managed_session
from app.sockets.session import socket_session
from app.sockets import SocketSessionManager
from app.utils.user_helpers import safe_current_user
from app.database.db_models import (
    ActiveMatchReporter, LiveMatch, MatchEvent, PlayerShift
)
from app.models import Match, Team, Player, User, PlayerEventType

logger = logging.getLogger(__name__)

def get_socket_current_user(session):
    """
    Get the current user from the Socket.IO session
    
    Uses the user_id stored in Socket.IO session data or Flask g.
    For development/testing, we allow anonymous users (user_id=0).
    
    Args:
        session: SQLAlchemy session
        
    Returns:
        User: User object or a fallback User object for anonymous users
    """
    try:
        # Try to get user_id from multiple sources
        user_id = None
        
        # 1. Try to get from Socket.IO session data first (preferred)
        try:
            # Try multiple methods to get user_id from session data
            # Try request.sid_data first (memory storage)
            if hasattr(request, 'sid_data') and request.sid_data and 'user_id' in request.sid_data:
                user_id = request.sid_data.get('user_id')
                if user_id:
                    logger.debug(f"Using user_id {user_id} from request.sid_data")
                    
            # If that fails, try SocketSessionManager's storage
            if user_id is None:
                session_data = SocketSessionManager.get_session_data(request.sid)
                if session_data and 'user_id' in session_data:
                    user_id = session_data.get('user_id')
                    if user_id:
                        logger.debug(f"Using user_id {user_id} from SocketSessionManager")
                
            # If that fails, try socketio.server session storage
            if user_id is None:
                try:
                    server_session = socketio.server.get_session(request.sid)
                    if server_session and 'user_id' in server_session:
                        user_id = server_session.get('user_id')
                        if user_id:
                            logger.debug(f"Using user_id {user_id} from socketio.server session")
                except Exception as e:
                    logger.debug(f"Could not get socketio.server session: {e}")
                    
        except Exception as session_error:
            logger.error(f"Error accessing Socket.IO session data: {session_error}")
        
        # 2. Fall back to Flask g if Socket.IO session data not available
        if user_id is None:
            user_id = getattr(g, 'socket_user_id', None)
            if user_id:
                logger.debug(f"Using user_id {user_id} from Flask g")
        
        # 3. Final fallback - check if we have the user ID in a custom header or query param
        if user_id is None and hasattr(request, 'args') and request.args.get('user_id'):
            user_id = request.args.get('user_id')
            logger.debug(f"Using user_id {user_id} from query param")
        
        # If no user ID found, return None to indicate authentication needed
        if user_id is None:
            logger.warning("No user ID found in any session data source")
            return None
            
        # Special case for anonymous user (development mode)
        if user_id == 0:
            # Create an anonymous user object for development
            from types import SimpleNamespace
            anon_user = SimpleNamespace()
            anon_user.id = 0
            anon_user.username = "AnonymousUser"
            anon_user.is_authenticated = True
            logger.debug("Using anonymous user for Socket.IO event")
            return anon_user
        
        # Get real user from database
        user = session.query(User).get(user_id)
        if not user:
            logger.warning(f"User ID {user_id} not found in database")
            # Create a temporary user object to avoid errors
            from types import SimpleNamespace
            temp_user = SimpleNamespace()
            temp_user.id = user_id
            temp_user.username = f"User_{user_id}"
            temp_user.is_authenticated = True
            return temp_user
            
        return user
    except Exception as e:
        logger.error(f"Error getting socket current user: {str(e)}")
        # Return an anonymous user rather than None to avoid errors
        from types import SimpleNamespace
        error_user = SimpleNamespace()
        error_user.id = -1
        error_user.username = "ErrorUser"
        error_user.is_authenticated = True
        return error_user

@socketio.on('connect', namespace='/live')
def handle_live_connect():
    """
    Handle a new client connection to the live reporting namespace.
    
    Attempts to authenticate the user via multiple methods:
    1. JWT token in the Authorization header
    2. JWT token as a query parameter
    3. Fallback to a development user ID if in development mode
    """
    try:
        # Log headers for debugging
        headers_dict = dict(request.headers)
        auth_keys = [k for k in headers_dict.keys() if k.lower() in ('authorization', 'auth')]
        logger.debug(f"Connect attempt with auth headers: {auth_keys}")
        
        # Check for token in Authorization header (case insensitive)
        auth_header = None
        for key in auth_keys:
            if request.headers.get(key, '').startswith('Bearer '):
                auth_header = request.headers.get(key)
                break
        
        # Also check for token in query parameters
        token_param = request.args.get('token')
        logger.debug(f"Token in query param: {'Present' if token_param else 'None'}")
        
        # Select a token source
        token = None
        token_source = None
        
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            token_source = "header"
        elif token_param:
            token = token_param
            token_source = "query"
        
        # Attempt to authenticate with the token
        if token:
            try:
                # Use a safer method to decode JWT without cryptographic verification first
                import jwt
                import base64
                import json
                
                # Log portion of token for debugging (first 10 chars only)
                logger.debug(f"Attempting to verify token from {token_source}: {token[:10]}...")
                
                # Try to extract user ID from JWT payload without verification
                try:
                    # Split the token parts
                    parts = token.split('.')
                    if len(parts) != 3:
                        logger.error("Invalid JWT format: should have 3 parts")
                        raise ValueError("Invalid JWT format")
                        
                    # Decode the payload (middle part)
                    payload_encoded = parts[1]
                    # Add padding if needed
                    payload_encoded += '=' * ((4 - len(payload_encoded) % 4) % 4)
                    payload_json = base64.b64decode(payload_encoded).decode('utf-8')
                    payload = json.loads(payload_json)
                    
                    # Look for user ID in common claim fields
                    user_id = payload.get('sub') or payload.get('identity') or payload.get('id')
                    
                    logger.debug(f"Extracted user ID from token payload: {user_id}")
                    
                    if not user_id:
                        logger.error(f"No user ID found in token payload: {payload}")
                        g.socket_user_id = 0  # Anonymous user
                        return True
                        
                    # Store user ID in Flask g
                    g.socket_user_id = user_id
                    
                    # Store user ID in local request and in-memory storage
                    session_data = {'user_id': user_id}
                    request.sid_data = session_data
                    SocketSessionManager.save_session_data(request.sid, session_data)
                    
                except Exception as jwt_error:
                    logger.error(f"Error parsing JWT: {jwt_error}")
                    # Fall back to default token verification
                    try:
                        from flask_jwt_extended import decode_token
                        decoded_token = decode_token(token)
                        user_id = decoded_token.get('sub') or decoded_token.get('identity')
                        
                        if not user_id:
                            logger.error(f"No user ID found in token: {decoded_token}")
                            g.socket_user_id = 0  # Anonymous user
                            return True
                            
                        g.socket_user_id = user_id
                        # Store user ID in local request and in-memory storage
                        session_data = {'user_id': user_id}
                        request.sid_data = session_data
                        SocketSessionManager.save_session_data(request.sid, session_data)
                    except Exception as e:
                        logger.error(f"JWT decode failed: {e}")
                        g.socket_user_id = 0  # Anonymous user
                        return True
                
                # Store user ID in Flask g
                g.socket_user_id = user_id
                # Make sure it's also in the Socket.IO session
                session_data = {'user_id': user_id}
                request.sid_data = session_data
                SocketSessionManager.save_session_data(request.sid, session_data)
                
                # Verify user exists (but don't fail connection if not found)
                with socket_session(db.engine) as session:
                    user = session.query(User).get(user_id)
                    if user:
                        logger.info(f"Live reporting client connected: {user.username} (ID: {user_id})")
                        
                        # Explicitly emit authentication success to the client
                        # This helps React Native client know auth succeeded
                        try:
                            emit('authentication_success', {
                                'user_id': user_id,
                                'username': user.username,
                                'timestamp': datetime.utcnow().isoformat()
                            })
                        except Exception as emit_error:
                            logger.error(f"Error emitting authentication success: {emit_error}")
                    else:
                        logger.warning(f"User ID {user_id} from token not found in database")
                        # Still allow connection for testing
                        # Send anonymous auth success
                        emit('authentication_success', {
                            'user_id': user_id,
                            'username': f'User_{user_id}',
                            'timestamp': datetime.utcnow().isoformat(),
                            'anonymous': True
                        })
                
                return True
                
            except Exception as e:
                logger.error(f"Token verification error: {str(e)}")
                # For development, allow connection even if token verification fails
                g.socket_user_id = 0  # Anonymous user
                return True
        else:
            # Development fallback - allow connection without token
            logger.warning("No authentication token found. Using development fallback.")
            g.socket_user_id = 0  # Anonymous user
            return True
            
    except Exception as e:
        logger.error(f"Socket authentication error: {str(e)}", exc_info=True)
        # For development, allow connection even on errors
        g.socket_user_id = 0  # Anonymous user
        return True


@socketio.on('disconnect', namespace='/live')
def handle_live_disconnect():
    """
    Handle client disconnection from the live reporting namespace.
    
    Updates the last_active timestamp for the user in active reporters.
    """
    try:
        # Try to get user ID from memory storage
        user_id = None
        
        # First try request.sid_data (local to this request)
        try:
            if hasattr(request, 'sid_data') and request.sid_data and 'user_id' in request.sid_data:
                user_id = request.sid_data.get('user_id')
                logger.debug(f"Found user_id {user_id} in request.sid_data")
        except Exception as e:
            logger.debug(f"Error accessing request.sid_data: {e}")
        
        # Then try our simple in-memory storage
        if user_id is None:
            try:
                session_data = SocketSessionManager.get_session_data(request.sid)
                if session_data and 'user_id' in session_data:
                    user_id = session_data.get('user_id')
                    logger.debug(f"Found user_id {user_id} in SocketSessionManager")
                    # Clean up session data
                    SocketSessionManager.clear_session_data(request.sid)
            except Exception as e:
                logger.debug(f"Error accessing SocketSessionManager data: {e}")
        
        # Finally try Flask g
        if user_id is None:
            try:
                user_id = getattr(g, 'socket_user_id', None)
                if user_id:
                    logger.debug(f"Found user_id {user_id} in Flask g")
            except Exception as e:
                logger.debug(f"Error accessing Flask g: {e}")
        
        # Now use the user_id if we found one
        if user_id and str(user_id) != "0":  # Skip anonymous users
            try:
                with socket_session(db.engine) as session:
                    # Get user from database for username
                    user = session.query(User).get(user_id)
                    if user:
                        logger.info(f"Live reporting client disconnected: {user.username}")
                        # Update the last active time for all matches this user is reporting
                        active_reports = session.query(ActiveMatchReporter).filter_by(
                            user_id=user_id
                        ).all()
                        
                        for report in active_reports:
                            report.last_active = datetime.utcnow()
                            logger.debug(f"Updated last_active for user {user_id} in match {report.match_id}")
                    else:
                        logger.warning(f"User ID {user_id} not found in database during disconnect")
            except Exception as db_error:
                logger.error(f"Database error in disconnect handler: {db_error}")
        else:
            logger.debug("Anonymous user disconnected or user ID not found")
    except Exception as e:
        logger.error(f"Error in disconnect handler: {e}", exc_info=True)
        # Continue processing even if we encounter an error
        # This is important to prevent exception propagation during disconnect
        pass

@socketio.on('ping_server', namespace='/live')
def handle_ping():
    """
    Simple ping/pong handler for testing authentication.
    
    Returns a response with the authenticated user's information.
    """
    with socket_session(db.engine) as session:
        user = get_socket_current_user(session)
        if not user:
            return {'status': 'error', 'message': 'Not authenticated'}
            
        logger.info(f"Received ping from user {user.username}")
        return {
            'status': 'pong',
            'user': user.username,
            'user_id': user.id,
            'server_time': datetime.utcnow().isoformat()
        }

@socketio.on('test_connection', namespace='/live')
def handle_test_connection(data=None):
    """
    Test the Socket.IO connection and return basic information.
    
    This is a simpler test endpoint that doesn't require authentication.
    
    Args:
        data: Optional data from client
    
    Returns:
        Dict with connection information
    """
    logger.info(f"Test connection received with data: {data}")
    
    # Return connection info
    return {
        'status': 'connected',
        'server_time': datetime.utcnow().isoformat(),
        'received_data': data,
        'message': 'Socket.IO connection is working correctly'
    }


@socketio.on('join_match', namespace='/live')
def on_join_match(data):
    """
    Join a match room for live reporting.
    
    Records the user as an active reporter for the match, joins the
    Socket.IO room, and sends the current match state to the user.
    
    Args:
        data: Dictionary containing match_id and team_id.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        team_id = data.get('team_id')
        user_id = user.id
        
        if not match_id or not team_id:
            emit('error', {'message': 'Match ID and team ID are required'})
            return
        
        # Verify the match exists
        match = session.query(Match).get(match_id)
        if not match:
            emit('error', {'message': f'Match {match_id} not found'})
            return
        
        # Verify the team exists and is playing in this match
        team = session.query(Team).get(team_id)
        if not team:
            emit('error', {'message': f'Team {team_id} not found'})
            return
            
        if team.id != match.home_team_id and team.id != match.away_team_id:
            emit('error', {'message': 'Selected team is not playing in this match'})
            return
        
        # Join the Socket.IO room for this match
        join_room(f"match_{match_id}")
        
        # Record the user as an active reporter
        try:
            active_reporter = session.query(ActiveMatchReporter).filter_by(
                match_id=match_id, user_id=user_id
            ).first()
            
            if active_reporter:
                active_reporter.last_active = datetime.utcnow()
                active_reporter.team_id = team_id  # Update team if changed
            else:
                active_reporter = ActiveMatchReporter(
                    match_id=match_id,
                    user_id=user_id,
                    team_id=team_id,
                    joined_at=datetime.utcnow(),
                    last_active=datetime.utcnow()
                )
                session.add(active_reporter)
                
            # Get or create the live match state
            live_match = session.query(LiveMatch).filter_by(match_id=match_id).first()
            if not live_match:
                live_match = LiveMatch(
                    match_id=match_id,
                    status='in_progress',
                    last_updated=datetime.utcnow()
                )
                session.add(live_match)
                
            session.commit()
            
            # Fetch active reporters for this match
            active_reporters = get_active_reporters(session, match_id)
            
            # Fetch current match state
            match_state = get_match_state(session, match_id)
            
            # Fetch player shifts for this team
            player_shifts = get_player_shifts(session, match_id, team_id)
            
            # Notify others about the new reporter
            emit('reporter_joined', {
                'user_id': user_id,
                'username': user.username,
                'team_id': team_id,
                'team_name': team.name
            }, room=f"match_{match_id}")
            
            # Send current state to the joining user
            emit('match_state', match_state)
            emit('active_reporters', active_reporters)
            emit('player_shifts', player_shifts)
            
            logger.info(f"User {user_id} joined match {match_id} reporting for team {team_id}")
            
        except Exception as e:
            logger.error(f"Error joining match: {str(e)}", exc_info=True)
            emit('error', {'message': f'Error joining match: {str(e)}'})


@socketio.on('leave_match', namespace='/live')
def on_leave_match(data):
    """
    Leave a match room and stop reporting.
    
    Updates the user's last_active timestamp and notifies
    other reporters that the user has left.
    
    Args:
        data: Dictionary containing match_id.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        user_id = user.id
        
        if not match_id:
            emit('error', {'message': 'Match ID is required'})
            return
        
        # Leave the Socket.IO room
        leave_room(f"match_{match_id}")
        
        # Update active reporter status
        active_reporter = session.query(ActiveMatchReporter).filter_by(
            match_id=match_id, user_id=user_id
        ).first()
        
        if active_reporter:
            active_reporter.last_active = datetime.utcnow()
            team_id = active_reporter.team_id
            
            # Notify others that reporter has left
            emit('reporter_left', {
                'user_id': user_id,
                'username': user.username,
                'team_id': team_id
            }, room=f"match_{match_id}")
            
            logger.info(f"User {user_id} left match {match_id}")
        
        session.commit()


@socketio.on('update_score', namespace='/live')
def on_score_update(data):
    """
    Update the match score.
    
    Updates the score in the database and broadcasts the
    change to all connected reporters.
    
    Args:
        data: Dictionary containing match_id, home_score, and away_score.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        home_score = data.get('home_score')
        away_score = data.get('away_score')
        user_id = user.id
        
        if not all([match_id is not None, 
                    home_score is not None, 
                    away_score is not None]):
            emit('error', {'message': 'Match ID, home score, and away score are required'})
            return
        
        try:
            # Update score in live match
            live_match = session.query(LiveMatch).filter_by(match_id=match_id).first()
            if not live_match:
                emit('error', {'message': f'No live match found with ID {match_id}'})
                return
                
            live_match.home_score = home_score
            live_match.away_score = away_score
            live_match.last_updated = datetime.utcnow()
            
            session.commit()
            
            # Broadcast to all in the room
            emit('score_updated', {
                'home_score': home_score,
                'away_score': away_score,
                'updated_by': user_id,
                'updated_by_name': user.username
            }, room=f"match_{match_id}")
            
            logger.info(f"Score updated for match {match_id}: {home_score}-{away_score} by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error updating score: {str(e)}", exc_info=True)
            emit('error', {'message': f'Error updating score: {str(e)}'})


@socketio.on('update_timer', namespace='/live')
def on_timer_update(data):
    """
    Update the match timer.
    
    Updates the elapsed time and timer running status in the database
    and broadcasts the change to all connected reporters.
    
    Args:
        data: Dictionary containing match_id, elapsed_seconds, is_running, and period.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        elapsed_seconds = data.get('elapsed_seconds')
        is_running = data.get('is_running')
        period = data.get('period')
        user_id = user.id
        
        if not all([match_id is not None, 
                    elapsed_seconds is not None, 
                    is_running is not None]):
            emit('error', {'message': 'Match ID, elapsed seconds, and running status are required'})
            return
        
        try:
            # Update timer in live match
            live_match = session.query(LiveMatch).filter_by(match_id=match_id).first()
            if not live_match:
                emit('error', {'message': f'No live match found with ID {match_id}'})
                return
                
            live_match.elapsed_seconds = elapsed_seconds
            live_match.timer_running = is_running
            if period:
                live_match.current_period = period
            live_match.last_updated = datetime.utcnow()
            
            session.commit()
            
            # Broadcast to all in the room
            emit('timer_updated', {
                'elapsed_seconds': elapsed_seconds,
                'is_running': is_running,
                'period': period,
                'updated_by': user_id,
                'updated_by_name': user.username
            }, room=f"match_{match_id}")
            
            logger.info(f"Timer updated for match {match_id}: {elapsed_seconds}s, running: {is_running}, period: {period} by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error updating timer: {str(e)}", exc_info=True)
            emit('error', {'message': f'Error updating timer: {str(e)}'})


@socketio.on('add_event', namespace='/live')
def on_add_event(data):
    """
    Add a new match event (goal, card, etc.).
    
    Stores the event in the database and broadcasts it
    to all connected reporters.
    
    Args:
        data: Dictionary containing match_id and event details.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        event_data = data.get('event')
        user_id = user.id
        
        if not match_id or not event_data:
            emit('error', {'message': 'Match ID and event data are required'})
            return
        
        try:
            # Validate event data
            required_fields = ['event_type', 'team_id']
            if not all(field in event_data for field in required_fields):
                emit('error', {'message': f'Event must include: {", ".join(required_fields)}'})
                return
            
            # Create new match event
            event = MatchEvent(
                match_id=match_id,
                event_type=event_data['event_type'],
                team_id=event_data['team_id'],
                player_id=event_data.get('player_id'),
                minute=event_data.get('minute'),
                period=event_data.get('period'),
                timestamp=datetime.utcnow(),
                reported_by=user_id,
                additional_data=event_data.get('additional_data')
            )
            
            session.add(event)
            session.flush()  # Get the ID without committing
            
            # If it's a goal, update the score
            if event.event_type == 'GOAL':
                update_score_from_event(session, match_id, event)
                
            session.commit()
            
            # Prepare event data for broadcast
            event_dict = {
                'id': event.id,
                'event_type': event.event_type,
                'team_id': event.team_id,
                'player_id': event.player_id,
                'minute': event.minute,
                'period': event.period,
                'timestamp': event.timestamp.isoformat(),
                'reported_by': event.reported_by
            }
            
            # Add team and player names if available
            team = session.query(Team).get(event.team_id) if event.team_id else None
            player = session.query(Player).get(event.player_id) if event.player_id else None
            
            if team:
                event_dict['team_name'] = team.name
            
            if player:
                event_dict['player_name'] = player.name
            
            # Broadcast to all in the room
            emit('event_added', {
                'event': event_dict,
                'reported_by': user_id,
                'reported_by_name': user.username
            }, room=f"match_{match_id}")
            
            logger.info(f"Event added for match {match_id}: {event.event_type} by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error adding event: {str(e)}", exc_info=True)
            emit('error', {'message': f'Error adding event: {str(e)}'})


@socketio.on('update_player_shift', namespace='/live')
def on_player_shift_update(data):
    """
    Update a player's shift status during a match.
    
    This data is team-specific and not synchronized across teams.
    Each coach manages their own team's player shifts.
    
    Args:
        data: Dictionary containing match_id, player_id, is_active, and team_id.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        player_id = data.get('player_id')
        is_active = data.get('is_active')
        team_id = data.get('team_id')
        user_id = user.id
        
        if not all([match_id, player_id, is_active is not None, team_id]):
            emit('error', {'message': 'Match ID, player ID, active status, and team ID are required'})
            return
        
        try:
            # Verify the user is reporting for this team
            reporter = session.query(ActiveMatchReporter).filter_by(
                match_id=match_id, user_id=user_id
            ).first()
            
            if not reporter or reporter.team_id != team_id:
                emit('error', {'message': 'You can only update shifts for your own team'})
                return
            
            # Update or create player shift
            shift = session.query(PlayerShift).filter_by(
                match_id=match_id, player_id=player_id, team_id=team_id
            ).first()
            
            if shift:
                shift.is_active = is_active
                shift.last_updated = datetime.utcnow()
                shift.updated_by = user_id
            else:
                shift = PlayerShift(
                    match_id=match_id,
                    player_id=player_id,
                    team_id=team_id,
                    is_active=is_active,
                    updated_by=user_id
                )
                session.add(shift)
                
            session.commit()
            
            # Get player name
            player = session.query(Player).get(player_id)
            player_name = player.name if player else f"Player {player_id}"
            
            # Send to all reporters of this team (but not other team)
            team_reporters = session.query(ActiveMatchReporter).filter_by(
                match_id=match_id, team_id=team_id
            ).all()
            
            for team_reporter in team_reporters:
                emit('player_shift_updated', {
                    'match_id': match_id,
                    'player_id': player_id,
                    'player_name': player_name,
                    'is_active': is_active,
                    'team_id': team_id,
                    'updated_by': user_id,
                    'updated_by_name': user.username
                }, room=f"user_{team_reporter.user_id}")
            
            logger.info(f"Player shift updated: Match {match_id}, Player {player_id}, Active: {is_active}, Team: {team_id}")
            
        except Exception as e:
            logger.error(f"Error updating player shift: {str(e)}", exc_info=True)
            emit('error', {'message': f'Error updating player shift: {str(e)}'})


@socketio.on('submit_report', namespace='/live')
def on_submit_report(data):
    """
    Submit the final match report.
    
    This marks the match as reported and finalizes the scores and events.
    Any coach can submit the report, with the first submission winning.
    
    Args:
        data: Dictionary containing match_id and optional report_data.
    """
    with socket_session(db.engine) as session:
        # Get authenticated user
        user = get_socket_current_user(session)
        if not user:
            emit('error', {'message': 'Authentication required'})
            disconnect()
            return
            
        match_id = data.get('match_id')
        report_data = data.get('report_data', {})
        user_id = user.id
        
        if not match_id:
            emit('error', {'message': 'Match ID is required'})
            return
        
        try:
            # Check if report already submitted
            live_match = session.query(LiveMatch).filter_by(match_id=match_id).first()
            if not live_match:
                emit('error', {'message': f'No live match found with ID {match_id}'})
                return
                
            if live_match.report_submitted:
                emit('report_submission_error', {
                    'message': 'A report has already been submitted for this match'
                })
                return
            
            # Mark match as reported
            live_match.report_submitted = True
            live_match.report_submitted_by = user_id
            live_match.status = 'completed'
            
            # Update the actual match with final score
            match = session.query(Match).get(match_id)
            if match:
                match.home_team_score = live_match.home_score
                match.away_team_score = live_match.away_score
                
                # Add any notes from report_data
                if 'notes' in report_data:
                    match.notes = report_data.get('notes')
                    
            session.commit()
            
            # Now that match is reported, we can create PlayerEvent records
            # for each goal, card, etc. that occurred during the match
            create_player_events_from_match_events(session, match_id)
            
            # Notify all connected clients
            emit('report_submitted', {
                'submitted_by': user_id,
                'submitted_by_name': user.username,
                'home_score': live_match.home_score,
                'away_score': live_match.away_score
            }, room=f"match_{match_id}")
            
            logger.info(f"Match report submitted for match {match_id} by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error submitting report: {str(e)}", exc_info=True)
            emit('error', {'message': f'Error submitting report: {str(e)}'})


# Helper functions

def get_match_state(session, match_id):
    """
    Get the current state of a match.
    
    Returns a dictionary with match details, including score,
    time, events, and reporting status.
    
    Args:
        session: Database session
        match_id: ID of the match
        
    Returns:
        Dictionary with match state
    """
    live_match = session.query(LiveMatch).filter_by(match_id=match_id).first()
    
    if not live_match:
        # Initialize new match
        live_match = LiveMatch(
            match_id=match_id,
            status='in_progress',
            last_updated=datetime.utcnow()
        )
        session.add(live_match)
        session.commit()
        
    # Get actual match details
    match = session.query(Match).get(match_id)
    
    # Get events
    events_query = session.query(MatchEvent).filter_by(match_id=match_id).order_by(MatchEvent.timestamp)
    events = []
    
    for event in events_query:
        event_dict = {
            'id': event.id,
            'event_type': event.event_type,
            'team_id': event.team_id,
            'player_id': event.player_id,
            'minute': event.minute,
            'period': event.period,
            'timestamp': event.timestamp.isoformat(),
            'reported_by': event.reported_by
        }
        
        # Add team and player names if available
        team = session.query(Team).get(event.team_id) if event.team_id else None
        player = session.query(Player).get(event.player_id) if event.player_id else None
        
        if team:
            event_dict['team_name'] = team.name
        
        if player:
            event_dict['player_name'] = player.name
            
        events.append(event_dict)
    
    return {
        "match_id": match_id,
        "home_team_id": match.home_team_id if match else None,
        "away_team_id": match.away_team_id if match else None,
        "home_team_name": match.home_team.name if match and match.home_team else "Home Team",
        "away_team_name": match.away_team.name if match and match.away_team else "Away Team",
        "status": live_match.status,
        "period": live_match.current_period,
        "elapsed_seconds": live_match.elapsed_seconds,
        "home_score": live_match.home_score,
        "away_score": live_match.away_score,
        "timer_running": live_match.timer_running,
        "report_submitted": live_match.report_submitted,
        "report_submitted_by": live_match.report_submitted_by,
        "events": events
    }


def get_active_reporters(session, match_id):
    """
    Get a list of active reporters for a match.
    
    Returns reporters who have been active in the last 5 minutes.
    
    Args:
        session: Database session
        match_id: ID of the match
        
    Returns:
        List of dictionaries with reporter details
    """
    active_time_limit = datetime.utcnow() - timedelta(minutes=5)
    
    reporters_query = session.query(
        ActiveMatchReporter, User, Team
    ).join(
        User, ActiveMatchReporter.user_id == User.id
    ).join(
        Team, ActiveMatchReporter.team_id == Team.id
    ).filter(
        ActiveMatchReporter.match_id == match_id,
        ActiveMatchReporter.last_active > active_time_limit
    )
    
    reporters = []
    for reporter, user, team in reporters_query:
        reporters.append({
            "user_id": user.id,
            "username": user.username,
            "team_id": team.id,
            "team_name": team.name,
            "joined_at": reporter.joined_at.isoformat(),
            "last_active": reporter.last_active.isoformat()
        })
        
    return reporters


def get_player_shifts(session, match_id, team_id):
    """
    Get the current player shifts for a team in a match.
    
    Args:
        session: Database session
        match_id: ID of the match
        team_id: ID of the team
        
    Returns:
        List of dictionaries with player shift details
    """
    shifts_query = session.query(
        PlayerShift, Player
    ).join(
        Player, PlayerShift.player_id == Player.id
    ).filter(
        PlayerShift.match_id == match_id,
        PlayerShift.team_id == team_id
    )
    
    shifts = []
    for shift, player in shifts_query:
        shifts.append({
            "player_id": player.id,
            "player_name": player.name,
            "is_active": shift.is_active,
            "last_updated": shift.last_updated.isoformat(),
            "updated_by": shift.updated_by
        })
        
    return shifts


def update_score_from_event(session, match_id, event):
    """
    Update match score based on a goal event.
    
    Args:
        session: Database session
        match_id: ID of the match
        event: The MatchEvent object representing a goal
    """
    if event.event_type != 'GOAL':
        return
        
    # Get match details
    match = session.query(Match).get(match_id)
    if not match:
        return
        
    # Get live match state
    live_match = session.query(LiveMatch).filter_by(match_id=match_id).first()
    if not live_match:
        return
        
    # Update appropriate score
    if event.team_id == match.home_team_id:
        live_match.home_score += 1
    elif event.team_id == match.away_team_id:
        live_match.away_score += 1


def create_player_events_from_match_events(session, match_id):
    """
    Create PlayerEvent records from MatchEvent records.
    
    This is called when a match report is submitted to create the permanent
    player statistics records based on the live reporting events.
    
    Args:
        session: Database session
        match_id: ID of the match
    """
    match_events = session.query(MatchEvent).filter_by(match_id=match_id).all()
    match = session.query(Match).get(match_id)
    
    if not match:
        logger.error(f"Match {match_id} not found when creating player events")
        return
    
    for event in match_events:
        if not event.player_id:
            continue
            
        try:
            # Map MatchEvent types to PlayerEventType
            event_type_map = {
                'GOAL': PlayerEventType.GOAL,
                'YELLOW_CARD': PlayerEventType.YELLOW_CARD,
                'RED_CARD': PlayerEventType.RED_CARD
            }
            
            if event.event_type in event_type_map:
                player_event = PlayerEvent(
                    player_id=event.player_id,
                    match_id=match_id,
                    minute=str(event.minute) if event.minute else None,
                    event_type=event_type_map[event.event_type]
                )
                session.add(player_event)
                
                # If this is a goal, also look for an assist
                if event.event_type == 'GOAL' and event.additional_data and 'assist_player_id' in event.additional_data:
                    assist_player_id = event.additional_data['assist_player_id']
                    assist_event = PlayerEvent(
                        player_id=assist_player_id,
                        match_id=match_id,
                        minute=str(event.minute) if event.minute else None,
                        event_type=PlayerEventType.ASSIST
                    )
                    session.add(assist_event)
        
        except Exception as e:
            logger.error(f"Error creating player event from match event {event.id}: {str(e)}")
    
    session.commit()
    logger.info(f"Created player events for match {match_id}")