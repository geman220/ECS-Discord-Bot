# app/sockets/rsvp.py

"""
RSVP Socket.IO Event Handlers

This module handles all WebSocket events for the RSVP system, providing real-time
synchronization between Discord bot, mobile apps, and web interface.

All RSVP updates still go through the database first, but WebSocket events
provide instant notification to all connected clients.
"""

import logging
from datetime import datetime
from flask import g, request, session
from flask_socketio import emit, join_room, leave_room, rooms
from sqlalchemy import and_

from app.core import socketio, db
from app.core.session_manager import managed_session
from app.models import Match, Player, Team, Availability, User
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Track which users are in which match rooms for efficient broadcasting
match_room_users = {}  # {match_id: {user_id: {username, player_name, team_id}}}


def emit_rsvp_update(match_id, player_id, availability, source='system', player_name=None, team_id=None):
    """
    Emit an RSVP update to all clients in a match room.
    
    This is the central function for broadcasting RSVP changes to all connected clients.
    Called after database updates from any source (web, mobile app, Discord).
    
    Args:
        match_id: ID of the match
        player_id: ID of the player who RSVP'd
        availability: 'yes', 'no', 'maybe', or 'no_response'
        source: Origin of the update ('web', 'mobile', 'discord', 'system')
        player_name: Optional player name to avoid DB lookup
        team_id: Optional team ID for the player
    """
    try:
        # Get player name if not provided
        if not player_name and player_id:
            with managed_session() as session:
                player = session.query(Player).get(player_id)
                if player:
                    player_name = player.name
                    # Get team_id if not provided
                    if not team_id:
                        match = session.query(Match).get(match_id)
                        if match:
                            # Check if player is on home or away team
                            if player in match.home_team.players:
                                team_id = match.home_team_id
                            elif player in match.away_team.players:
                                team_id = match.away_team_id
        
        # Support both room formats for compatibility
        room_with_underscore = f'match_{match_id}'  # Current Flask format
        room_without_underscore = f'match{match_id}'  # Flutter expected format
        
        event_data = {
            'match_id': match_id,
            'player_id': player_id,
            'availability': availability,
            'timestamp': datetime.utcnow().isoformat(),
            'player_name': player_name,
            'team_id': team_id,
            'source': source
        }
        
        # PERFORMANCE OPTIMIZATION: Emit to both rooms in parallel and skip summary for speed
        # Summary updates are expensive and not critical for real-time RSVP changes
        # Clients can update their local state based on the individual rsvp_update event
        socketio.emit('rsvp_update', event_data, room=room_with_underscore, namespace='/')
        socketio.emit('rsvp_update', event_data, room=room_without_underscore, namespace='/')
        
        logger.debug(f"📤 Emitted RSVP update to rooms {room_with_underscore} & {room_without_underscore}: {player_name} -> {availability} (source: {source})")
        
        # Skip summary emission for real-time performance - clients can calculate locally
        # emit_rsvp_summary(match_id)  # Commented out for speed
        
    except Exception as e:
        logger.error(f"Error emitting RSVP update: {str(e)}", exc_info=True)


def emit_rsvp_summary(match_id):
    """
    Emit a summary of current RSVPs for a match.
    
    Useful for updating UI counters without fetching full RSVP lists.
    """
    try:
        with managed_session() as session:
            # Get RSVP counts by response type
            availability_counts = session.query(
                Availability.response,
                db.func.count(Availability.id)
            ).filter(
                Availability.match_id == match_id
            ).group_by(Availability.response).all()
            
            counts = {'yes': 0, 'no': 0, 'maybe': 0}
            for response, count in availability_counts:
                if response in counts:
                    counts[response] = count
            
            # Get match details
            match = session.query(Match).get(match_id)
            if match:
                summary_data = {
                    'match_id': match_id,
                    'home_team_id': match.home_team_id,
                    'away_team_id': match.away_team_id,
                    'rsvp_counts': counts,
                    'total_responses': sum(counts.values()),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                # Emit to both room formats for compatibility
                room_with_underscore = f'match_{match_id}'
                room_without_underscore = f'match{match_id}'
                socketio.emit('rsvp_summary', summary_data, room=room_with_underscore, namespace='/')
                socketio.emit('rsvp_summary', summary_data, room=room_without_underscore, namespace='/')
                
                logger.debug(f"📊 Emitted RSVP summary for match {match_id}: {counts}")
                
    except Exception as e:
        logger.error(f"Error emitting RSVP summary: {str(e)}", exc_info=True)


@socketio.on('join_match_rsvp', namespace='/')
def handle_join_match_rsvp(data):
    """
    Handle client joining a match room for RSVP updates.
    
    Mobile apps and web clients call this to receive real-time RSVP updates
    for a specific match.
    
    Expected data:
    {
        'match_id': 123,
        'team_id': 45 (optional - for coaches/admins),
        'auth': {'token': 'jwt_token'} (for mobile apps)
    }
    """
    try:
        # Authenticate the user (lazy import to avoid circular dependency)
        from app.socket_handlers import authenticate_socket_connection
        # Lazy import to avoid circular dependency
        from app.socket_handlers import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        
        if not auth_result['authenticated']:
            # For web users, check Flask-Login
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
        
        # Join the match room
        room = f'match_{match_id}'
        join_room(room)
        
        # Get player info and current RSVPs
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
            
            # Track user in room
            if match_id not in match_room_users:
                match_room_users[match_id] = {}
            
            match_room_users[match_id][user_id] = {
                'username': username,
                'player_name': player_name,
                'player_id': player_id,
                'team_id': team_id,
                'joined_at': datetime.utcnow().isoformat()
            }
            
            # Get current RSVPs for initial state
            current_rsvps = get_match_rsvps_data(match_id, team_id, session)
            
            # Send success response with initial data
            emit('joined_match_rsvp', {
                'match_id': match_id,
                'room': room,
                'team_id': team_id,
                'current_rsvps': current_rsvps,
                'match_info': {
                    'home_team_id': match.home_team_id,
                    'home_team_name': match.home_team.name,
                    'away_team_id': match.away_team_id,
                    'away_team_name': match.away_team.name,
                    'date': match.date.isoformat(),
                    'time': match.time.isoformat() if match.time else None
                },
                'message': 'Successfully joined match RSVP updates'
            })
            
            # Notify others in room (optional, for presence awareness)
            emit('user_joined_rsvp', {
                'user_id': user_id,
                'player_name': player_name,
                'timestamp': datetime.utcnow().isoformat()
            }, room=room, include_self=False)
            
            logger.info(f"👥 User {username} (player: {player_name}) joined match {match_id} RSVP room")
            
    except Exception as e:
        logger.error(f"Error joining match RSVP room: {str(e)}", exc_info=True)
        emit('error', {'message': 'Failed to join match room'})


@socketio.on('leave_match_rsvp', namespace='/')
def handle_leave_match_rsvp(data):
    """Handle client leaving a match RSVP room."""
    try:
        match_id = data.get('match_id')
        if not match_id:
            return
            
        room = f'match_{match_id}'
        leave_room(room)
        
        # Get user info for tracking
        from flask_login import current_user
        # Lazy import to avoid circular dependency
        from app.socket_handlers import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        
        if auth_result['authenticated']:
            user_id = auth_result['user_id']
        elif current_user.is_authenticated:
            user_id = current_user.id
        else:
            user_id = None
        
        # Remove from tracking
        if user_id and match_id in match_room_users and user_id in match_room_users[match_id]:
            player_name = match_room_users[match_id][user_id].get('player_name', 'Unknown')
            del match_room_users[match_id][user_id]
            
            # Clean up empty match entries
            if not match_room_users[match_id]:
                del match_room_users[match_id]
            
            # Notify others in room
            emit('user_left_rsvp', {
                'user_id': user_id,
                'player_name': player_name,
                'timestamp': datetime.utcnow().isoformat()
            }, room=room)
        
        emit('left_match_rsvp', {'match_id': match_id})
        logger.info(f"👋 User left match {match_id} RSVP room")
        
    except Exception as e:
        logger.error(f"Error leaving match RSVP room: {str(e)}", exc_info=True)


@socketio.on('get_match_rsvps_live', namespace='/')
def handle_get_match_rsvps_live(data):
    """
    Get current RSVPs for a match via WebSocket.
    
    This provides the same data as the REST endpoint but via WebSocket,
    useful for mobile apps that want to use pure WebSocket communication.
    """
    try:
        # Authenticate
        # Lazy import to avoid circular dependency
        from app.socket_handlers import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        from flask_login import current_user
        
        if not auth_result['authenticated'] and not current_user.is_authenticated:
            emit('rsvps_error', {'message': 'Authentication required'})
            return
        
        match_id = data.get('match_id')
        team_id = data.get('team_id')  # Optional filter
        include_details = data.get('include_details', True)
        
        if not match_id:
            emit('rsvps_error', {'message': 'Match ID required'})
            return
        
        with managed_session() as session:
            rsvps_data = get_match_rsvps_data(match_id, team_id, session, include_details)
            
            emit('match_rsvps_data', {
                'match_id': match_id,
                'team_id': team_id,
                'rsvps': rsvps_data,
                'timestamp': datetime.utcnow().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error getting match RSVPs: {str(e)}", exc_info=True)
        emit('rsvps_error', {'message': 'Failed to get match RSVPs'})


@socketio.on('update_rsvp_live', namespace='/')
def handle_update_rsvp_live(data):
    """
    Update RSVP via WebSocket (alternative to REST API).
    
    This still updates the database first, then broadcasts to all clients.
    Mobile apps can use this instead of the REST endpoint for a pure WebSocket flow.
    
    Expected data:
    {
        'match_id': 123,
        'response': 'yes' | 'no' | 'maybe' | 'no_response',
        'auth': {'token': 'jwt_token'}
    }
    """
    try:
        # Authenticate
        # Lazy import to avoid circular dependency
        from app.socket_handlers import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        from flask_login import current_user
        
        if auth_result['authenticated']:
            user_id = auth_result['user_id']
        elif current_user.is_authenticated:
            user_id = current_user.id
        else:
            emit('rsvp_error', {'message': 'Authentication required'})
            return
        
        match_id = data.get('match_id')
        response = data.get('response')
        
        if not match_id or not response:
            emit('rsvp_error', {'message': 'Match ID and response required'})
            return
        
        if response not in ['yes', 'no', 'maybe', 'no_response']:
            emit('rsvp_error', {'message': 'Invalid response value'})
            return
        
        with managed_session() as session:
            # Get player
            player = session.query(Player).filter(Player.user_id == user_id).first()
            if not player:
                emit('rsvp_error', {'message': 'Player profile not found'})
                return
            
            # Verify match exists
            match = session.query(Match).get(match_id)
            if not match:
                emit('rsvp_error', {'message': 'Match not found'})
                return
            
            # Update availability in database
            availability = session.query(Availability).filter_by(
                match_id=match_id,
                player_id=player.id
            ).first()
            
            old_response = availability.response if availability else 'no_response'
            
            if response == 'no_response':
                if availability:
                    session.delete(availability)
            else:
                if availability:
                    availability.response = response
                    availability.responded_at = datetime.utcnow()
                else:
                    availability = Availability(
                        match_id=match_id,
                        player_id=player.id,
                        response=response,
                        discord_id=player.discord_id,
                        responded_at=datetime.utcnow()
                    )
                    session.add(availability)
            
            session.commit()
            
            # Determine team_id
            team_id = None
            if player in match.home_team.players:
                team_id = match.home_team_id
            elif player in match.away_team.players:
                team_id = match.away_team_id
            
            # Send success response to requester
            emit('rsvp_updated', {
                'success': True,
                'match_id': match_id,
                'player_id': player.id,
                'old_response': old_response,
                'new_response': response,
                'message': f'RSVP updated to {response}'
            })
            
            # Broadcast to all clients in match room
            emit_rsvp_update(
                match_id=match_id,
                player_id=player.id,
                availability=response,
                source='mobile',
                player_name=player.name,
                team_id=team_id
            )
            
            # Trigger Discord notification if player has Discord ID
            if player.discord_id:
                from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task
                notify_discord_of_rsvp_change_task.delay(match_id)
            
            logger.info(f"✅ RSVP updated via WebSocket: {player.name} -> {response} for match {match_id}")
            
    except Exception as e:
        logger.error(f"Error updating RSVP via WebSocket: {str(e)}", exc_info=True)
        emit('rsvp_error', {'message': 'Failed to update RSVP'})


def get_match_rsvps_data(match_id, team_id=None, session=None, include_details=True):
    """
    Helper function to get RSVP data for a match.
    
    Args:
        match_id: ID of the match
        team_id: Optional team ID to filter by
        session: Database session
        include_details: Include player details (names, IDs)
    
    Returns:
        Dictionary with RSVP data organized by response type
    """
    try:
        if not session:
            session = db.session
        
        # Build query
        query = session.query(Availability, Player).join(Player).filter(
            Availability.match_id == match_id
        )
        
        # Filter by team if specified
        if team_id:
            from app.models import player_teams
            query = query.join(player_teams, Player.id == player_teams.c.player_id).filter(
                player_teams.c.team_id == team_id
            )
        
        availabilities = query.all()
        
        # Organize by response type
        rsvp_data = {
            'yes': [],
            'no': [],
            'maybe': [],
            'no_response': []
        }
        
        for availability, player in availabilities:
            player_info = {
                'player_id': player.id,
                'player_name': player.name
            }
            
            if include_details:
                player_info.update({
                    'discord_id': player.discord_id,
                    'profile_picture_url': player.profile_picture_url,
                    'responded_at': availability.responded_at.isoformat() if availability.responded_at else None
                })
            
            if availability.response in rsvp_data:
                rsvp_data[availability.response].append(player_info)
        
        # Add summary counts
        rsvp_data['summary'] = {
            'yes_count': len(rsvp_data['yes']),
            'no_count': len(rsvp_data['no']),
            'maybe_count': len(rsvp_data['maybe']),
            'total_responses': len(rsvp_data['yes']) + len(rsvp_data['no']) + len(rsvp_data['maybe'])
        }
        
        return rsvp_data
        
    except Exception as e:
        logger.error(f"Error getting match RSVP data: {str(e)}", exc_info=True)
        return {'yes': [], 'no': [], 'maybe': [], 'no_response': [], 'error': str(e)}


# Register this module's handlers with the main socketio instance
logger.info("🎯 RSVP Socket handlers registered")