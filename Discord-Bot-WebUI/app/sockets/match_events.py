# app/sockets/match_events.py

"""
Socket.IO Match Event Handlers

Handlers for match room management, event reporting, and live match coordination.
"""

import logging
from datetime import datetime

from flask_login import login_required
from flask_socketio import emit, join_room
from sqlalchemy import and_

from app.core import socketio
from app.core.session_manager import managed_session
from app.sockets.auth import authenticate_socket_connection

logger = logging.getLogger(__name__)


@socketio.on('join_match', namespace='/')
def handle_join_match(data):
    """Handle client joining a match room - supports both web (Flask-Login) and mobile (JWT) authentication."""
    from app.models import Player, Match

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
        from app.models import Player, Match, player_teams
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
        from app.models import Player

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
    from app.core import socketio

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
