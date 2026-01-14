# app/sockets/match_lineup.py

"""
Match Lineup Socket.IO Event Handlers

This module handles real-time WebSocket events for match lineup collaboration,
allowing coaches to collaborate on per-match lineups in real-time.

Events:
- join_lineup_room: Join a lineup room for a specific match/team
- leave_lineup_room: Leave a lineup room
- update_lineup_position: Move a player to a position (broadcasts to room)
- remove_lineup_position: Remove a player from lineup (broadcasts to room)
- save_lineup_notes: Save notes for the lineup

All lineup updates go through the database first, then WebSocket events
provide instant notification to all connected clients (other coaches).
"""

import logging
import time
from datetime import datetime

from flask import request
from flask_socketio import emit, join_room, leave_room

from app.core import socketio
from app.core.session_manager import managed_session
from app.models import Match, Team, Player, User, MatchLineup, player_teams

logger = logging.getLogger(__name__)

# Track which coaches are in which lineup rooms for presence awareness
# Structure: {room_key: {user_id: {name, sid, joined_at, joined_at_timestamp}}}
lineup_room_coaches = {}

# Reverse mapping for efficient cleanup on disconnect: {sid: [(room_key, user_id), ...]}
_sid_to_lineup_rooms = {}

# TTL for room tracking entries (2 hours)
_ROOM_COACH_TTL = 7200
# Cleanup interval counter
_lineup_cleanup_counter = 0
_LINEUP_CLEANUP_INTERVAL = 100


def _get_room_key(match_id, team_id):
    """Generate consistent room key for lineup rooms."""
    return f"lineup_match_{match_id}_team_{team_id}"


def _cleanup_stale_coaches():
    """Remove room coach entries that are older than TTL."""
    current_time = time.time()
    stale_entries = []

    for room_key, coaches in list(lineup_room_coaches.items()):
        for user_id, coach_data in list(coaches.items()):
            joined_at = coach_data.get('joined_at_timestamp', 0)
            if current_time - joined_at > _ROOM_COACH_TTL:
                stale_entries.append((room_key, user_id, coach_data.get('sid')))

    for room_key, user_id, sid in stale_entries:
        _remove_coach_from_room(room_key, user_id, sid)

    if stale_entries:
        logger.info(f"Cleaned up {len(stale_entries)} stale lineup room coach entries")


def _remove_coach_from_room(room_key, user_id, sid=None):
    """Remove a coach from room tracking."""
    if room_key in lineup_room_coaches and user_id in lineup_room_coaches[room_key]:
        del lineup_room_coaches[room_key][user_id]
        if not lineup_room_coaches[room_key]:
            del lineup_room_coaches[room_key]

    # Clean up reverse mapping
    if sid and sid in _sid_to_lineup_rooms:
        _sid_to_lineup_rooms[sid] = [
            (r, u) for r, u in _sid_to_lineup_rooms[sid]
            if not (r == room_key and u == user_id)
        ]
        if not _sid_to_lineup_rooms[sid]:
            del _sid_to_lineup_rooms[sid]


def cleanup_lineup_rooms_for_sid(sid):
    """Clean up all lineup room entries for a disconnected socket."""
    if sid not in _sid_to_lineup_rooms:
        return []

    cleaned_entries = []
    for room_key, user_id in _sid_to_lineup_rooms[sid]:
        if room_key in lineup_room_coaches and user_id in lineup_room_coaches[room_key]:
            coach_name = lineup_room_coaches[room_key][user_id].get('name', 'Unknown')
            cleaned_entries.append((room_key, user_id, coach_name))
            del lineup_room_coaches[room_key][user_id]
            if not lineup_room_coaches[room_key]:
                del lineup_room_coaches[room_key]

    del _sid_to_lineup_rooms[sid]
    return cleaned_entries


def get_active_coaches_for_room(room_key):
    """Get list of active coaches in a lineup room."""
    if room_key not in lineup_room_coaches:
        return []

    coaches = []
    for user_id, data in lineup_room_coaches[room_key].items():
        coaches.append({
            'user_id': user_id,
            'name': data.get('name', 'Unknown'),
            'joined_at': data.get('joined_at')
        })
    return coaches


def _is_coach_for_team(user_id, team_id, session_db):
    """Check if user is a coach for the given team."""
    from sqlalchemy import and_

    player = session_db.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return False

    result = session_db.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player.id,
                player_teams.c.team_id == team_id,
                player_teams.c.is_coach == True
            )
        )
    ).first()

    return result is not None


def _is_admin(user_id, session_db):
    """Check if user has admin role."""
    user = session_db.query(User).filter_by(id=user_id).first()
    if not user:
        return False
    return any(role.name.lower() in ['admin', 'superadmin'] for role in user.roles)


def _check_lineup_permission(user_id, team_id, session_db):
    """Check if user has permission to edit team lineup."""
    if _is_admin(user_id, session_db):
        return True
    return _is_coach_for_team(user_id, team_id, session_db)


# ============================================================================
# Emit functions (called from API endpoints for cross-client sync)
# ============================================================================

def emit_lineup_updated(match_id, team_id, positions, updated_by_user_id):
    """Emit lineup update to all clients in the lineup room."""
    room_key = _get_room_key(match_id, team_id)

    try:
        with managed_session() as session:
            user = session.query(User).filter_by(id=updated_by_user_id).first()
            updated_by_name = user.username if user else 'Unknown'
    except Exception:
        updated_by_name = 'Unknown'

    event_data = {
        'match_id': match_id,
        'team_id': team_id,
        'positions': positions,
        'updated_by': updated_by_user_id,
        'updated_by_name': updated_by_name,
        'timestamp': datetime.utcnow().isoformat()
    }

    # Emit to default namespace (web browser clients)
    socketio.emit('lineup_updated', event_data, room=room_key, namespace='/')
    # Emit to /live namespace (Flutter mobile clients)
    socketio.emit('lineup_updated', event_data, room=room_key, namespace='/live')

    logger.debug(f"Emitted lineup_updated to room {room_key}")


def emit_position_updated(match_id, team_id, player_id, position, order, updated_by_user_id):
    """Emit single position update to all clients in the lineup room."""
    room_key = _get_room_key(match_id, team_id)

    try:
        with managed_session() as session:
            user = session.query(User).filter_by(id=updated_by_user_id).first()
            updated_by_name = user.username if user else 'Unknown'

            player = session.query(Player).filter_by(id=player_id).first()
            player_name = player.name if player else 'Unknown'
    except Exception:
        updated_by_name = 'Unknown'
        player_name = 'Unknown'

    event_data = {
        'match_id': match_id,
        'team_id': team_id,
        'player_id': player_id,
        'player_name': player_name,
        'position': position,
        'order': order,
        'updated_by': updated_by_user_id,
        'updated_by_name': updated_by_name,
        'timestamp': datetime.utcnow().isoformat()
    }

    socketio.emit('lineup_position_updated', event_data, room=room_key, namespace='/')
    socketio.emit('lineup_position_updated', event_data, room=room_key, namespace='/live')

    logger.debug(f"Emitted lineup_position_updated to room {room_key}: {player_name} -> {position}")


def emit_player_removed(match_id, team_id, player_id, updated_by_user_id):
    """Emit player removal to all clients in the lineup room."""
    room_key = _get_room_key(match_id, team_id)

    try:
        with managed_session() as session:
            user = session.query(User).filter_by(id=updated_by_user_id).first()
            updated_by_name = user.username if user else 'Unknown'

            player = session.query(Player).filter_by(id=player_id).first()
            player_name = player.name if player else 'Unknown'
    except Exception:
        updated_by_name = 'Unknown'
        player_name = 'Unknown'

    event_data = {
        'match_id': match_id,
        'team_id': team_id,
        'player_id': player_id,
        'player_name': player_name,
        'updated_by': updated_by_user_id,
        'updated_by_name': updated_by_name,
        'timestamp': datetime.utcnow().isoformat()
    }

    socketio.emit('lineup_player_removed', event_data, room=room_key, namespace='/')
    socketio.emit('lineup_player_removed', event_data, room=room_key, namespace='/live')

    logger.debug(f"Emitted lineup_player_removed to room {room_key}: {player_name}")


def emit_rsvp_to_lineup_room(match_id, team_id, player_id, new_status, color):
    """
    Emit RSVP change to lineup room (called from rsvp.py when RSVP changes).

    This allows lineup view to update RSVP indicators in real-time.
    """
    room_key = _get_room_key(match_id, team_id)

    try:
        with managed_session() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            player_name = player.name if player else 'Unknown'
    except Exception:
        player_name = 'Unknown'

    event_data = {
        'match_id': match_id,
        'team_id': team_id,
        'player_id': player_id,
        'player_name': player_name,
        'new_status': new_status,
        'color': color,
        'timestamp': datetime.utcnow().isoformat()
    }

    socketio.emit('rsvp_changed', event_data, room=room_key, namespace='/')
    socketio.emit('rsvp_changed', event_data, room=room_key, namespace='/live')

    logger.debug(f"Emitted rsvp_changed to lineup room {room_key}: {player_name} -> {new_status}")


# ============================================================================
# Socket.IO Event Handlers - Default Namespace (/)
# ============================================================================

@socketio.on('join_lineup_room', namespace='/')
def handle_join_lineup_room(data):
    """
    Handle client joining a lineup room for real-time updates.

    Expected data:
    {
        'match_id': 123,
        'team_id': 45,
        'auth': {'token': 'jwt_token'} (for mobile apps)
    }
    """
    try:
        # Authenticate the user
        from app.sockets.auth import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))

        if not auth_result['authenticated']:
            # For web users, check Flask-Login
            from flask_login import current_user
            if not current_user.is_authenticated:
                emit('lineup_error', {'message': 'Authentication required'})
                return
            user_id = current_user.id
            username = current_user.username
        else:
            user_id = auth_result['user_id']
            username = auth_result.get('username', f'User_{user_id}')

        match_id = data.get('match_id')
        team_id = data.get('team_id')

        if not match_id or not team_id:
            emit('lineup_error', {'message': 'Match ID and Team ID required'})
            return

        try:
            match_id = int(match_id)
            team_id = int(team_id)
        except ValueError:
            emit('lineup_error', {'message': 'Invalid match or team ID format'})
            return

        room_key = _get_room_key(match_id, team_id)
        join_room(room_key)

        with managed_session() as session:
            # Verify match and team exist
            match = session.query(Match).filter_by(id=match_id).first()
            if not match:
                emit('lineup_error', {'message': 'Match not found'})
                return

            team = session.query(Team).filter_by(id=team_id).first()
            if not team:
                emit('lineup_error', {'message': 'Team not found'})
                return

            # Verify team is in this match
            if team_id not in [match.home_team_id, match.away_team_id]:
                emit('lineup_error', {'message': 'Team is not part of this match'})
                return

            # Check if user is coach or admin
            is_coach = _check_lineup_permission(user_id, team_id, session)

            # Get user's display name
            user = session.query(User).filter_by(id=user_id).first()
            display_name = user.username if user else username

            # Track coach in room
            global _lineup_cleanup_counter
            sid = request.sid

            if room_key not in lineup_room_coaches:
                lineup_room_coaches[room_key] = {}

            lineup_room_coaches[room_key][user_id] = {
                'name': display_name,
                'sid': sid,
                'is_coach': is_coach,
                'joined_at': datetime.utcnow().isoformat(),
                'joined_at_timestamp': time.time()
            }

            # Track reverse mapping for disconnect cleanup
            if sid not in _sid_to_lineup_rooms:
                _sid_to_lineup_rooms[sid] = []
            _sid_to_lineup_rooms[sid].append((room_key, user_id))

            # Periodically cleanup stale entries
            _lineup_cleanup_counter += 1
            if _lineup_cleanup_counter >= _LINEUP_CLEANUP_INTERVAL:
                _lineup_cleanup_counter = 0
                _cleanup_stale_coaches()

            # Get current lineup data
            lineup = session.query(MatchLineup).filter_by(
                match_id=match_id,
                team_id=team_id
            ).first()

            lineup_data = {
                'id': lineup.id if lineup else None,
                'positions': lineup.positions if lineup else [],
                'notes': lineup.notes if lineup else None,
                'version': lineup.version if lineup else 1
            }

            # Get active coaches
            active_coaches = get_active_coaches_for_room(room_key)

            # Send success response with initial data
            emit('joined_lineup_room', {
                'match_id': match_id,
                'team_id': team_id,
                'room': room_key,
                'lineup': lineup_data,
                'active_coaches': active_coaches,
                'is_coach': is_coach,
                'message': 'Successfully joined lineup room'
            })

            # Notify others in room
            emit('coach_joined', {
                'user_id': user_id,
                'coach_name': display_name,
                'is_coach': is_coach,
                'timestamp': datetime.utcnow().isoformat()
            }, room=room_key, include_self=False)

            logger.info(f"User {display_name} joined lineup room {room_key}")

    except Exception as e:
        logger.error(f"Error joining lineup room: {str(e)}", exc_info=True)
        emit('lineup_error', {'message': 'Failed to join lineup room'})


@socketio.on('leave_lineup_room', namespace='/')
def handle_leave_lineup_room(data):
    """Handle client leaving a lineup room."""
    try:
        match_id = data.get('match_id')
        team_id = data.get('team_id')

        if not match_id or not team_id:
            return

        room_key = _get_room_key(match_id, team_id)
        leave_room(room_key)

        # Get user info
        from flask_login import current_user
        from app.sockets.auth import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))

        if auth_result['authenticated']:
            user_id = auth_result['user_id']
        elif current_user.is_authenticated:
            user_id = current_user.id
        else:
            user_id = None

        # Remove from tracking
        sid = request.sid
        if user_id and room_key in lineup_room_coaches and user_id in lineup_room_coaches[room_key]:
            coach_name = lineup_room_coaches[room_key][user_id].get('name', 'Unknown')
            _remove_coach_from_room(room_key, user_id, sid)

            # Notify others in room
            emit('coach_left', {
                'user_id': user_id,
                'coach_name': coach_name,
                'timestamp': datetime.utcnow().isoformat()
            }, room=room_key)

        emit('left_lineup_room', {'match_id': match_id, 'team_id': team_id})
        logger.info(f"User left lineup room {room_key}")

    except Exception as e:
        logger.error(f"Error leaving lineup room: {str(e)}", exc_info=True)


@socketio.on('update_lineup_position', namespace='/')
def handle_update_lineup_position(data):
    """
    Handle position update via WebSocket (alternative to REST API).

    Expected data:
    {
        'match_id': 123,
        'team_id': 45,
        'player_id': 10,
        'position': 'lw',
        'order': 0,
        'auth': {'token': 'jwt_token'} (for mobile apps)
    }
    """
    try:
        # Authenticate
        from app.sockets.auth import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        from flask_login import current_user

        if auth_result['authenticated']:
            user_id = auth_result['user_id']
        elif current_user.is_authenticated:
            user_id = current_user.id
        else:
            emit('lineup_error', {'message': 'Authentication required'})
            return

        match_id = data.get('match_id')
        team_id = data.get('team_id')
        player_id = data.get('player_id')
        position = data.get('position')
        order = data.get('order')

        if not all([match_id, team_id, player_id, position]):
            emit('lineup_error', {'message': 'Missing required fields'})
            return

        try:
            match_id = int(match_id)
            team_id = int(team_id)
            player_id = int(player_id)
            if order is not None:
                order = int(order)
        except ValueError:
            emit('lineup_error', {'message': 'Invalid ID format'})
            return

        with managed_session() as session:
            # Check permission
            if not _check_lineup_permission(user_id, team_id, session):
                emit('lineup_error', {'message': 'You are not authorized to edit this lineup'})
                return

            # Get or create lineup
            lineup = session.query(MatchLineup).filter_by(
                match_id=match_id,
                team_id=team_id
            ).first()

            if not lineup:
                lineup = MatchLineup(
                    match_id=match_id,
                    team_id=team_id,
                    positions=[],
                    created_by=user_id
                )
                session.add(lineup)
                session.flush()

            # Update position
            lineup.add_player(player_id, position, order)
            lineup.last_updated_by = user_id
            lineup.increment_version()

            session.commit()

            # Emit to requester
            emit('lineup_position_updated_ack', {
                'success': True,
                'player_id': player_id,
                'position': position,
                'order': order,
                'version': lineup.version
            })

            # Broadcast to room
            emit_position_updated(match_id, team_id, player_id, position, order, user_id)

            logger.info(f"Position updated via socket: player {player_id} -> {position}")

    except Exception as e:
        logger.error(f"Error updating lineup position via socket: {str(e)}", exc_info=True)
        emit('lineup_error', {'message': 'Failed to update position'})


@socketio.on('remove_lineup_position', namespace='/')
def handle_remove_lineup_position(data):
    """
    Handle player removal via WebSocket.

    Expected data:
    {
        'match_id': 123,
        'team_id': 45,
        'player_id': 10,
        'auth': {'token': 'jwt_token'} (for mobile apps)
    }
    """
    try:
        # Authenticate
        from app.sockets.auth import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        from flask_login import current_user

        if auth_result['authenticated']:
            user_id = auth_result['user_id']
        elif current_user.is_authenticated:
            user_id = current_user.id
        else:
            emit('lineup_error', {'message': 'Authentication required'})
            return

        match_id = data.get('match_id')
        team_id = data.get('team_id')
        player_id = data.get('player_id')

        if not all([match_id, team_id, player_id]):
            emit('lineup_error', {'message': 'Missing required fields'})
            return

        try:
            match_id = int(match_id)
            team_id = int(team_id)
            player_id = int(player_id)
        except ValueError:
            emit('lineup_error', {'message': 'Invalid ID format'})
            return

        with managed_session() as session:
            # Check permission
            if not _check_lineup_permission(user_id, team_id, session):
                emit('lineup_error', {'message': 'You are not authorized to edit this lineup'})
                return

            lineup = session.query(MatchLineup).filter_by(
                match_id=match_id,
                team_id=team_id
            ).first()

            if not lineup:
                emit('lineup_error', {'message': 'Lineup not found'})
                return

            removed = lineup.remove_player(player_id)
            if not removed:
                emit('lineup_error', {'message': 'Player not in lineup'})
                return

            lineup.last_updated_by = user_id
            lineup.increment_version()

            session.commit()

            # Emit to requester
            emit('lineup_player_removed_ack', {
                'success': True,
                'player_id': player_id,
                'version': lineup.version
            })

            # Broadcast to room
            emit_player_removed(match_id, team_id, player_id, user_id)

            logger.info(f"Player {player_id} removed from lineup via socket")

    except Exception as e:
        logger.error(f"Error removing player from lineup via socket: {str(e)}", exc_info=True)
        emit('lineup_error', {'message': 'Failed to remove player'})


@socketio.on('save_lineup_notes', namespace='/')
def handle_save_lineup_notes(data):
    """
    Save notes for a lineup.

    Expected data:
    {
        'match_id': 123,
        'team_id': 45,
        'notes': 'Rotation plan...',
        'auth': {'token': 'jwt_token'}
    }
    """
    try:
        # Authenticate
        from app.sockets.auth import authenticate_socket_connection
        auth_result = authenticate_socket_connection(data.get('auth'))
        from flask_login import current_user

        if auth_result['authenticated']:
            user_id = auth_result['user_id']
        elif current_user.is_authenticated:
            user_id = current_user.id
        else:
            emit('lineup_error', {'message': 'Authentication required'})
            return

        match_id = data.get('match_id')
        team_id = data.get('team_id')
        notes = data.get('notes', '')

        if not match_id or not team_id:
            emit('lineup_error', {'message': 'Missing match_id or team_id'})
            return

        try:
            match_id = int(match_id)
            team_id = int(team_id)
        except ValueError:
            emit('lineup_error', {'message': 'Invalid ID format'})
            return

        with managed_session() as session:
            if not _check_lineup_permission(user_id, team_id, session):
                emit('lineup_error', {'message': 'You are not authorized to edit this lineup'})
                return

            lineup = session.query(MatchLineup).filter_by(
                match_id=match_id,
                team_id=team_id
            ).first()

            if not lineup:
                lineup = MatchLineup(
                    match_id=match_id,
                    team_id=team_id,
                    positions=[],
                    notes=notes,
                    created_by=user_id
                )
                session.add(lineup)
            else:
                lineup.notes = notes
                lineup.last_updated_by = user_id

            session.commit()

            # Emit to requester
            emit('lineup_notes_saved', {
                'success': True,
                'notes': notes
            })

            # Broadcast notes update to room
            room_key = _get_room_key(match_id, team_id)
            socketio.emit('lineup_notes_updated', {
                'match_id': match_id,
                'team_id': team_id,
                'notes': notes,
                'updated_by': user_id,
                'timestamp': datetime.utcnow().isoformat()
            }, room=room_key, namespace='/')

            logger.info(f"Lineup notes saved for match {match_id} team {team_id}")

    except Exception as e:
        logger.error(f"Error saving lineup notes: {str(e)}", exc_info=True)
        emit('lineup_error', {'message': 'Failed to save notes'})


# ============================================================================
# /LIVE Namespace Handlers (for Flutter mobile clients)
# ============================================================================

@socketio.on('join_lineup_room', namespace='/live')
def handle_join_lineup_room_live(data):
    """Join lineup room (/live namespace for mobile clients)."""
    handle_join_lineup_room(data)


@socketio.on('leave_lineup_room', namespace='/live')
def handle_leave_lineup_room_live(data):
    """Leave lineup room (/live namespace for mobile clients)."""
    handle_leave_lineup_room(data)


@socketio.on('update_lineup_position', namespace='/live')
def handle_update_lineup_position_live(data):
    """Update lineup position (/live namespace for mobile clients)."""
    handle_update_lineup_position(data)


@socketio.on('remove_lineup_position', namespace='/live')
def handle_remove_lineup_position_live(data):
    """Remove lineup position (/live namespace for mobile clients)."""
    handle_remove_lineup_position(data)


@socketio.on('save_lineup_notes', namespace='/live')
def handle_save_lineup_notes_live(data):
    """Save lineup notes (/live namespace for mobile clients)."""
    handle_save_lineup_notes(data)


# Register this module's handlers
logger.info("Match Lineup Socket handlers registered for / and /live namespaces")
