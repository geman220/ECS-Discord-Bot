# app/mobile_api/pitch_view.py

"""
Pitch View API Endpoints

Unified API for pitch view functionality supporting both modes:
- Draft Mode: Season-long position planning during draft
- Match Mode: Per-match lineup assignments with RSVP integration

Supports:
- Real-time collaboration between coaches
- RSVP status integration (match mode)
- Optimistic locking for concurrent edits
- Mobile app integration
"""

import logging
from datetime import datetime

from flask import jsonify, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import (
    Player, Team, Match, Availability, User, MatchLineup,
    player_teams
)
from app.models_ecs import EcsFcMatch, EcsFcAvailability

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================

def get_rsvp_color(status):
    """Convert RSVP status to color code."""
    colors = {
        'yes': 'green',
        'maybe': 'yellow',
        'no': 'red'
    }
    return colors.get(status, 'gray')


def is_coach_for_team(user_id, team_id, session_db):
    """Check if user is a coach for the given team."""
    from sqlalchemy import and_

    player = session_db.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return False

    # Check if player is coach for this team
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


def is_admin(user_id, session_db):
    """Check if user has admin role."""
    user = session_db.query(User).filter_by(id=user_id).first()
    if not user:
        return False
    return any(role.name.lower() in ['admin', 'superadmin'] for role in user.roles)


def check_coach_permission(user_id, team_id, session_db):
    """Check if user has permission to edit team lineup (coach or admin)."""
    if is_admin(user_id, session_db):
        return True
    return is_coach_for_team(user_id, team_id, session_db)


def build_roster_response(players, match=None, session_db=None):
    """
    Build roster response with optional RSVP status.

    Args:
        players: List of Player objects
        match: Match object (if match mode, for RSVP data)
        session_db: Database session

    Returns:
        List of player dictionaries with stats and optional RSVP
    """
    roster = []

    # Get RSVP data for match mode
    rsvp_map = {}
    if match and session_db:
        availabilities = session_db.query(Availability).filter_by(match_id=match.id).all()
        for avail in availabilities:
            rsvp_map[avail.player_id] = avail.response

    for player in players:
        player_data = {
            'player_id': player.id,
            'name': player.name,
            'profile_picture_url': getattr(player, 'profile_picture_url', None) or '/static/img/default_player.png',
            'favorite_position': player.favorite_position,
            'other_positions': player.other_positions,
            'rsvp_status': None,
            'rsvp_color': None,
            'stats': {
                'goals': 0,
                'assists': 0,
                'attendance_rate': None
            }
        }

        # Add RSVP data for match mode
        if match:
            rsvp_status = rsvp_map.get(player.id, 'unavailable')
            player_data['rsvp_status'] = rsvp_status
            player_data['rsvp_color'] = get_rsvp_color(rsvp_status)

        # Add stats if available
        if hasattr(player, 'career_stats') and player.career_stats:
            for stat in player.career_stats:
                player_data['stats']['goals'] = stat.goals or 0
                player_data['stats']['assists'] = stat.assists or 0

        if hasattr(player, 'attendance_stats') and player.attendance_stats:
            player_data['stats']['attendance_rate'] = player.attendance_stats.attendance_rate

        roster.append(player_data)

    return roster


# ============================================================================
# Draft Mode Endpoints
# ============================================================================

@mobile_api_v2.route('/teams/<int:team_id>/draft/pitch', methods=['GET'])
@jwt_required()
def get_team_draft_pitch(team_id):
    """
    Get team's draft pitch positions.

    Returns roster with positions from player_teams table (position column).
    No RSVP data in draft mode.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        team = session_db.query(Team).filter_by(id=team_id).first()
        if not team:
            return jsonify({'msg': 'Team not found'}), 404

        # Get team players with their draft positions
        players = team.players

        # Build positions from player_teams position column
        positions = []
        for i, player in enumerate(players):
            # Get position from player_teams association
            result = session_db.execute(
                player_teams.select().where(
                    player_teams.c.player_id == player.id,
                    player_teams.c.team_id == team_id
                )
            ).first()

            if result:
                pos = result.position if result.position else 'bench'
                positions.append({
                    'player_id': player.id,
                    'position': pos,
                    'order': i
                })

        roster = build_roster_response(players, match=None, session_db=session_db)

        return jsonify({
            'mode': 'draft',
            'pitch': {
                'id': None,
                'positions': positions,
                'notes': None,
                'version': 1
            },
            'roster': roster,
            'team': {
                'id': team.id,
                'name': team.name
            },
            'match': None,
            'active_coaches': []
        }), 200


@mobile_api_v2.route('/teams/<int:team_id>/draft/pitch', methods=['PUT'])
@jwt_required()
def update_team_draft_pitch(team_id):
    """
    Update team's draft pitch positions.

    Expected JSON:
        positions: List of {player_id, position, order}
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        team = session_db.query(Team).filter_by(id=team_id).first()
        if not team:
            return jsonify({'msg': 'Team not found'}), 404

        data = request.json or {}
        positions = data.get('positions', [])

        # Update player_teams position column for each player
        for pos_entry in positions:
            player_id = pos_entry.get('player_id')
            position = pos_entry.get('position', 'bench')

            if player_id:
                session_db.execute(
                    player_teams.update().where(
                        player_teams.c.player_id == player_id,
                        player_teams.c.team_id == team_id
                    ).values(position=position)
                )

        session_db.commit()

        return jsonify({
            'msg': 'Draft positions updated',
            'version': 1,
            'positions': positions
        }), 200


@mobile_api_v2.route('/teams/<int:team_id>/draft/pitch/position', methods=['PATCH'])
@jwt_required()
def update_team_draft_position(team_id):
    """
    Update single player's draft position.

    Expected JSON:
        player_id: Player ID
        position: New position code
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        data = request.json or {}
        player_id = data.get('player_id')
        position = data.get('position', 'bench')

        if not player_id:
            return jsonify({'msg': 'Missing player_id'}), 400

        session_db.execute(
            player_teams.update().where(
                player_teams.c.player_id == player_id,
                player_teams.c.team_id == team_id
            ).values(position=position)
        )
        session_db.commit()

        return jsonify({
            'msg': 'Position updated',
            'player_id': player_id,
            'position': position,
            'version': 1
        }), 200


# ============================================================================
# Match Mode Endpoints
# ============================================================================

@mobile_api_v2.route('/matches/<int:match_id>/teams/<int:team_id>/lineup', methods=['GET'])
@jwt_required()
def get_match_lineup(match_id, team_id):
    """
    Get team's lineup for a specific match with RSVP status.

    Returns:
        - Lineup positions from match_lineups table
        - Roster with RSVP status (green/yellow/red/gray)
        - Match info
        - Active coaches currently editing
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        match = session_db.query(Match).filter_by(id=match_id).first()
        if not match:
            return jsonify({'msg': 'Match not found'}), 404

        team = session_db.query(Team).filter_by(id=team_id).first()
        if not team:
            return jsonify({'msg': 'Team not found'}), 404

        # Verify team is in this match
        if team_id not in [match.home_team_id, match.away_team_id]:
            return jsonify({'msg': 'Team is not part of this match'}), 400

        # Get or create lineup
        lineup = session_db.query(MatchLineup).filter_by(
            match_id=match_id,
            team_id=team_id
        ).first()

        # Get opponent team
        opponent_id = match.away_team_id if team_id == match.home_team_id else match.home_team_id
        opponent = session_db.query(Team).filter_by(id=opponent_id).first()

        # Build response
        pitch_data = {
            'id': lineup.id if lineup else None,
            'positions': lineup.positions if lineup else [],
            'notes': lineup.notes if lineup else None,
            'version': lineup.version if lineup else 1
        }

        roster = build_roster_response(team.players, match=match, session_db=session_db)

        return jsonify({
            'mode': 'match',
            'pitch': pitch_data,
            'roster': roster,
            'team': {
                'id': team.id,
                'name': team.name
            },
            'match': {
                'id': match.id,
                'date': match.date.isoformat() if match.date else None,
                'time': match.time.isoformat() if match.time else None,
                'opponent': opponent.name if opponent else 'Unknown',
                'location': match.location
            },
            'active_coaches': []  # Populated via Socket.IO
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/teams/<int:team_id>/lineup', methods=['PUT'])
@jwt_required()
def update_match_lineup(match_id, team_id):
    """
    Update entire lineup for a match (with optimistic locking).

    Expected JSON:
        positions: List of {player_id, position, order}
        notes: Optional notes
        version: Current version for optimistic locking
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        match = session_db.query(Match).filter_by(id=match_id).first()
        if not match:
            return jsonify({'msg': 'Match not found'}), 404

        if team_id not in [match.home_team_id, match.away_team_id]:
            return jsonify({'msg': 'Team is not part of this match'}), 400

        data = request.json or {}
        positions = data.get('positions', [])
        notes = data.get('notes')
        client_version = data.get('version', 0)

        # Get or create lineup
        lineup = session_db.query(MatchLineup).filter_by(
            match_id=match_id,
            team_id=team_id
        ).first()

        if lineup:
            # Check version for optimistic locking
            if client_version and lineup.version != client_version:
                return jsonify({
                    'msg': 'Lineup was modified by another coach. Please refresh and try again.',
                    'current_version': lineup.version,
                    'your_version': client_version
                }), 409

            lineup.positions = positions
            lineup.notes = notes
            lineup.last_updated_by = current_user_id
            lineup.increment_version()
        else:
            lineup = MatchLineup(
                match_id=match_id,
                team_id=team_id,
                positions=positions,
                notes=notes,
                created_by=current_user_id
            )
            session_db.add(lineup)

        session_db.commit()
        session_db.refresh(lineup)

        # Emit Socket.IO event for real-time sync
        try:
            from app.sockets.match_lineup import emit_lineup_updated
            emit_lineup_updated(match_id, team_id, positions, current_user_id)
        except ImportError:
            pass  # Socket handlers not yet implemented

        return jsonify({
            'msg': 'Lineup updated',
            'id': lineup.id,
            'version': lineup.version,
            'positions': lineup.positions,
            'updated_at': lineup.updated_at.isoformat() if lineup.updated_at else None
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/teams/<int:team_id>/lineup/position', methods=['PATCH'])
@jwt_required()
def update_match_lineup_position(match_id, team_id):
    """
    Update single player position in lineup (for drag-and-drop).

    Expected JSON:
        player_id: Player ID
        position: New position code
        order: Priority order within position (optional)
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        match = session_db.query(Match).filter_by(id=match_id).first()
        if not match:
            return jsonify({'msg': 'Match not found'}), 404

        if team_id not in [match.home_team_id, match.away_team_id]:
            return jsonify({'msg': 'Team is not part of this match'}), 400

        data = request.json or {}
        player_id = data.get('player_id')
        position = data.get('position')
        order = data.get('order')

        if not player_id or not position:
            return jsonify({'msg': 'Missing player_id or position'}), 400

        # Get or create lineup
        lineup = session_db.query(MatchLineup).filter_by(
            match_id=match_id,
            team_id=team_id
        ).first()

        if not lineup:
            lineup = MatchLineup(
                match_id=match_id,
                team_id=team_id,
                positions=[],
                created_by=current_user_id
            )
            session_db.add(lineup)
            session_db.flush()

        # Use model method to add/move player
        lineup.add_player(player_id, position, order)
        lineup.last_updated_by = current_user_id
        lineup.increment_version()

        session_db.commit()

        # Emit Socket.IO event
        try:
            from app.sockets.match_lineup import emit_position_updated
            emit_position_updated(match_id, team_id, player_id, position, order, current_user_id)
        except ImportError:
            pass

        return jsonify({
            'msg': 'Position updated',
            'player_id': player_id,
            'position': position,
            'order': order,
            'version': lineup.version
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/teams/<int:team_id>/lineup/position/<int:player_id>', methods=['DELETE'])
@jwt_required()
def remove_from_match_lineup(match_id, team_id, player_id):
    """
    Remove player from lineup (back to available pool).
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        lineup = session_db.query(MatchLineup).filter_by(
            match_id=match_id,
            team_id=team_id
        ).first()

        if not lineup:
            return jsonify({'msg': 'Lineup not found'}), 404

        removed = lineup.remove_player(player_id)
        if not removed:
            return jsonify({'msg': 'Player not in lineup'}), 404

        lineup.last_updated_by = current_user_id
        lineup.increment_version()

        session_db.commit()

        # Emit Socket.IO event
        try:
            from app.sockets.match_lineup import emit_player_removed
            emit_player_removed(match_id, team_id, player_id, current_user_id)
        except ImportError:
            pass

        return jsonify({
            'msg': 'Player removed from lineup',
            'player_id': player_id,
            'version': lineup.version
        }), 200


# ============================================================================
# Additional Utility Endpoints
# ============================================================================

@mobile_api_v2.route('/matches/<int:match_id>/teams/<int:team_id>/roster', methods=['GET'])
@jwt_required()
def get_team_roster_with_rsvp(match_id, team_id):
    """
    Get team roster with RSVP status for a specific match.

    Useful for populating the available players list.
    """
    with managed_session() as session_db:
        match = session_db.query(Match).filter_by(id=match_id).first()
        if not match:
            return jsonify({'msg': 'Match not found'}), 404

        team = session_db.query(Team).filter_by(id=team_id).first()
        if not team:
            return jsonify({'msg': 'Team not found'}), 404

        roster = build_roster_response(team.players, match=match, session_db=session_db)

        return jsonify({
            'roster': roster,
            'team_id': team_id,
            'match_id': match_id
        }), 200


# ============================================================================
# ECS FC Match Mode Endpoints
# ============================================================================

def build_ecs_fc_roster_response(players, ecs_match, session_db):
    """
    Build roster response with ECS FC RSVP status.

    Args:
        players: List of Player objects
        ecs_match: EcsFcMatch object
        session_db: Database session

    Returns:
        List of player dictionaries with stats and RSVP status
    """
    roster = []

    # Get RSVP data from EcsFcAvailability
    rsvp_map = {}
    if ecs_match:
        player_ids = [p.id for p in players]
        availabilities = session_db.query(EcsFcAvailability).filter(
            EcsFcAvailability.ecs_fc_match_id == ecs_match.id,
            EcsFcAvailability.player_id.in_(player_ids)
        ).all()
        rsvp_map = {a.player_id: a.response for a in availabilities}

    for player in players:
        rsvp_status = rsvp_map.get(player.id, 'unavailable')
        rsvp_color = get_rsvp_color(rsvp_status)

        # Get player stats
        from app.models import PlayerCareerStats, PlayerAttendanceStats

        career_stats = session_db.query(PlayerCareerStats).filter_by(player_id=player.id).first()
        attendance_stats = session_db.query(PlayerAttendanceStats).filter_by(player_id=player.id).first()

        roster.append({
            'player_id': player.id,
            'name': player.name,
            'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
            'favorite_position': player.favorite_position,
            'other_positions': player.other_positions,
            'rsvp_status': rsvp_status,
            'rsvp_color': rsvp_color,
            'stats': {
                'goals': career_stats.goals if career_stats else 0,
                'assists': career_stats.assists if career_stats else 0,
                'attendance_rate': attendance_stats.attendance_rate if attendance_stats else None
            }
        })

    return roster


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/lineup', methods=['GET'])
@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/teams/<int:team_id>/lineup', methods=['GET'])
@jwt_required()
def get_ecs_fc_match_lineup(match_id, team_id=None):
    """
    Get team's lineup for an ECS FC match with RSVP status.

    ECS FC matches have one team (the ECS FC team) vs an external opponent.
    The team_id parameter is optional - if not provided, uses the match's team.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        ecs_match = session_db.query(EcsFcMatch).filter_by(id=match_id).first()
        if not ecs_match:
            return jsonify({'msg': 'ECS FC match not found'}), 404

        # For ECS FC, always use the match's team_id (ignore any passed team_id)
        team_id = ecs_match.team_id

        team = session_db.query(Team).options(
            joinedload(Team.players)
        ).filter_by(id=team_id).first()
        if not team:
            return jsonify({'msg': 'Team not found'}), 404

        # Get or check existing lineup (using ecs_fc_match_id convention)
        # For ECS FC, we store match_id as negative to distinguish from regular matches
        # Or we can use a separate identifier
        lineup = session_db.query(MatchLineup).filter_by(
            match_id=-match_id,  # Negative ID convention for ECS FC
            team_id=team_id
        ).first()

        # Build response
        pitch_data = {
            'id': lineup.id if lineup else None,
            'positions': lineup.positions if lineup else [],
            'notes': lineup.notes if lineup else None,
            'version': lineup.version if lineup else 1
        }

        roster = build_ecs_fc_roster_response(team.players, ecs_match, session_db)

        # Get active coaches from socket tracking
        active_coaches = []
        try:
            from app.sockets.match_lineup import get_active_coaches_for_room, _get_room_key
            room_key = _get_room_key(-match_id, team_id)
            active_coaches = get_active_coaches_for_room(room_key)
        except ImportError:
            pass

        return jsonify({
            'mode': 'match',
            'match_type': 'ecs_fc',
            'pitch': pitch_data,
            'roster': roster,
            'team': {
                'id': team.id,
                'name': team.name
            },
            'match': {
                'id': match_id,
                'date': ecs_match.match_date.isoformat() if ecs_match.match_date else None,
                'time': ecs_match.match_time.strftime('%H:%M:%S') if ecs_match.match_time else None,
                'opponent': ecs_match.opponent_name,
                'location': ecs_match.location
            },
            'active_coaches': active_coaches
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/lineup', methods=['PUT'])
@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/teams/<int:team_id>/lineup', methods=['PUT'])
@jwt_required()
def update_ecs_fc_match_lineup(match_id, team_id=None):
    """
    Update team's lineup for an ECS FC match (full replacement).
    The team_id parameter is optional - if not provided, uses the match's team.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        ecs_match = session_db.query(EcsFcMatch).filter_by(id=match_id).first()
        if not ecs_match:
            return jsonify({'msg': 'ECS FC match not found'}), 404

        # For ECS FC, always use the match's team_id (ignore any passed team_id)
        team_id = ecs_match.team_id

        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        data = request.json or {}
        positions = data.get('positions', [])
        notes = data.get('notes')
        version = data.get('version')

        # Use negative match_id for ECS FC
        lineup = session_db.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=team_id
        ).first()

        # Optimistic locking check
        if lineup and version is not None and lineup.version != version:
            return jsonify({
                'msg': 'Lineup was modified by another coach. Please refresh and try again.',
                'current_version': lineup.version,
                'your_version': version
            }), 409

        if not lineup:
            lineup = MatchLineup(
                match_id=-match_id,  # Negative for ECS FC
                team_id=team_id,
                positions=positions,
                notes=notes,
                created_by=current_user_id
            )
            session_db.add(lineup)
        else:
            lineup.positions = positions
            if notes is not None:
                lineup.notes = notes
            lineup.last_updated_by = current_user_id
            lineup.increment_version()

        session_db.commit()

        # Emit Socket.IO event
        try:
            from app.sockets.match_lineup import emit_lineup_updated
            emit_lineup_updated(-match_id, team_id, positions, current_user_id)
        except ImportError:
            pass

        return jsonify({
            'msg': 'Lineup updated',
            'id': lineup.id,
            'version': lineup.version,
            'positions': lineup.positions,
            'updated_at': lineup.updated_at.isoformat() if lineup.updated_at else None
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/lineup/position', methods=['PATCH'])
@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/teams/<int:team_id>/lineup/position', methods=['PATCH'])
@jwt_required()
def update_ecs_fc_lineup_position(match_id, team_id=None):
    """
    Update single player position for ECS FC match lineup.
    The team_id parameter is optional - if not provided, uses the match's team.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        ecs_match = session_db.query(EcsFcMatch).filter_by(id=match_id).first()
        if not ecs_match:
            return jsonify({'msg': 'ECS FC match not found'}), 404

        # For ECS FC, always use the match's team_id (ignore any passed team_id)
        team_id = ecs_match.team_id

        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        data = request.json or {}
        player_id = data.get('player_id')
        position = data.get('position')
        order = data.get('order')

        if not player_id or not position:
            return jsonify({'msg': 'Missing player_id or position'}), 400

        # Get or create lineup (negative match_id for ECS FC)
        lineup = session_db.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=team_id
        ).first()

        if not lineup:
            lineup = MatchLineup(
                match_id=-match_id,
                team_id=team_id,
                positions=[],
                created_by=current_user_id
            )
            session_db.add(lineup)
            session_db.flush()

        lineup.add_player(player_id, position, order)
        lineup.last_updated_by = current_user_id
        lineup.increment_version()

        session_db.commit()

        # Emit Socket.IO event
        try:
            from app.sockets.match_lineup import emit_position_updated
            emit_position_updated(-match_id, team_id, player_id, position, order, current_user_id)
        except ImportError:
            pass

        return jsonify({
            'msg': 'Position updated',
            'player_id': player_id,
            'position': position,
            'order': order,
            'version': lineup.version
        }), 200


@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/lineup/position/<int:player_id>', methods=['DELETE'])
@mobile_api_v2.route('/ecs-fc-matches/<int:match_id>/teams/<int:team_id>/lineup/position/<int:player_id>', methods=['DELETE'])
@jwt_required()
def remove_from_ecs_fc_lineup(match_id, player_id, team_id=None):
    """
    Remove player from ECS FC match lineup.
    The team_id parameter is optional - if not provided, uses the match's team.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        ecs_match = session_db.query(EcsFcMatch).filter_by(id=match_id).first()
        if not ecs_match:
            return jsonify({'msg': 'ECS FC match not found'}), 404

        # For ECS FC, always use the match's team_id (ignore any passed team_id)
        team_id = ecs_match.team_id

        if not check_coach_permission(current_user_id, team_id, session_db):
            return jsonify({'msg': 'You are not authorized to edit this team\'s lineup'}), 403

        lineup = session_db.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=team_id
        ).first()

        if not lineup:
            return jsonify({'msg': 'Lineup not found'}), 404

        removed = lineup.remove_player(player_id)
        if not removed:
            return jsonify({'msg': 'Player not in lineup'}), 404

        lineup.last_updated_by = current_user_id
        lineup.increment_version()

        session_db.commit()

        # Emit Socket.IO event
        try:
            from app.sockets.match_lineup import emit_player_removed
            emit_player_removed(-match_id, team_id, player_id, current_user_id)
        except ImportError:
            pass

        return jsonify({
            'msg': 'Player removed from lineup',
            'player_id': player_id,
            'version': lineup.version
        }), 200
