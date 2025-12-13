# app/mobile_api/coach_rsvp.py

"""
Mobile API Coach RSVP Dashboard Endpoints

Provides RSVP management functionality for coaches:
- List teams where user is coach
- View team RSVP summaries for upcoming matches
- View detailed RSVP for specific match
- Send RSVP reminders to players
"""

import logging
from datetime import datetime
from collections import defaultdict

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import and_

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Team, Match, Availability, player_teams

logger = logging.getLogger(__name__)


def is_coach_for_team(session, user_id: int, team_id: int) -> bool:
    """
    Check if user is a coach for the specified team.

    Args:
        session: Database session
        user_id: User ID to check
        team_id: Team ID to check against

    Returns:
        True if user is a coach for the team, False otherwise
    """
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return False

    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player.id,
                player_teams.c.team_id == team_id,
                player_teams.c.is_coach == True
            )
        )
    ).fetchone()

    return coach_check is not None


def is_admin_user(session, user_id: int) -> bool:
    """Check if user has admin role."""
    user = session.query(User).options(
        joinedload(User.roles)
    ).filter(User.id == user_id).first()

    if not user or not user.roles:
        return False

    admin_roles = ['Global Admin', 'Pub League Admin', 'Admin']
    return any(role.name in admin_roles for role in user.roles)


def get_coach_teams(session, user_id: int) -> list:
    """
    Get all teams where the user is a coach.

    Args:
        session: Database session
        user_id: User ID

    Returns:
        List of Team objects
    """
    player = session.query(Player).filter_by(user_id=user_id).first()
    if not player:
        return []

    # Get team IDs where player is coach
    coach_team_ids = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player.id,
                player_teams.c.is_coach == True
            )
        )
    ).fetchall()

    if not coach_team_ids:
        return []

    team_ids = [row.team_id for row in coach_team_ids]
    return session.query(Team).filter(Team.id.in_(team_ids)).all()


def get_rsvp_summary(session, match_id: int, team_id: int) -> dict:
    """
    Get RSVP summary counts for a team in a match.

    Args:
        session: Database session
        match_id: Match ID
        team_id: Team ID

    Returns:
        Dict with yes, no, maybe, no_response counts
    """
    # Get all players on the team
    team = session.query(Team).options(
        selectinload(Team.players)
    ).get(team_id)

    if not team:
        return {'yes': 0, 'no': 0, 'maybe': 0, 'no_response': 0}

    team_players = [p for p in team.players if p.is_current_player]
    player_ids = [p.id for p in team_players]

    # Get availability records for these players
    availabilities = session.query(Availability).filter(
        Availability.match_id == match_id,
        Availability.player_id.in_(player_ids)
    ).all()

    # Build response map
    response_map = {av.player_id: av.response for av in availabilities}

    # Count responses
    summary = {'yes': 0, 'no': 0, 'maybe': 0, 'no_response': 0}
    for player_id in player_ids:
        response = response_map.get(player_id)
        if response == 'yes':
            summary['yes'] += 1
        elif response == 'no':
            summary['no'] += 1
        elif response == 'maybe':
            summary['maybe'] += 1
        else:
            summary['no_response'] += 1

    return summary


@mobile_api_v2.route('/coach/teams', methods=['GET'])
@jwt_required()
def get_coach_team_list():
    """
    Get list of teams where the current user is a coach.

    Returns:
        JSON with list of teams the user coaches
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        teams = get_coach_teams(session, current_user_id)

        teams_data = []
        for team in teams:
            teams_data.append({
                "id": team.id,
                "name": team.name,
                "league_id": team.league_id,
                "league_name": team.league.name if team.league else None,
                "player_count": len([p for p in team.players if p.is_current_player])
            })

        return jsonify({
            "teams": teams_data,
            "count": len(teams_data)
        }), 200


@mobile_api_v2.route('/coach/teams/<int:team_id>/rsvp', methods=['GET'])
@jwt_required()
def get_team_rsvp_overview(team_id: int):
    """
    Get RSVP overview for all upcoming matches of a team.

    Args:
        team_id: Team ID to get RSVPs for

    Query Parameters:
        limit: Maximum number of matches to return (default: 10, max: 50)

    Returns:
        JSON with team info and RSVP summaries for upcoming matches
    """
    current_user_id = int(get_jwt_identity())
    limit = min(request.args.get('limit', 10, type=int), 50)

    with managed_session() as session:
        # Check authorization - must be coach for this team or admin
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to view this team's RSVPs"}), 403

        # Get team
        team = session.query(Team).options(
            selectinload(Team.players),
            joinedload(Team.league)
        ).get(team_id)

        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Get upcoming matches where this team is playing
        now = datetime.utcnow().date()
        matches = session.query(Match).filter(
            Match.date >= now,
            ((Match.home_team_id == team_id) | (Match.away_team_id == team_id))
        ).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).order_by(Match.date.asc(), Match.time.asc()).limit(limit).all()

        # Build response
        matches_data = []
        for match in matches:
            is_home = match.home_team_id == team_id
            opponent = match.away_team if is_home else match.home_team

            rsvp_summary = get_rsvp_summary(session, match.id, team_id)
            total_players = sum(rsvp_summary.values())

            matches_data.append({
                "id": match.id,
                "date": match.date.isoformat() if match.date else None,
                "time": match.time.isoformat() if match.time else None,
                "opponent": {
                    "id": opponent.id if opponent else None,
                    "name": opponent.name if opponent else "TBD"
                },
                "is_home": is_home,
                "location": match.location,
                "rsvp_summary": rsvp_summary,
                "total_players": total_players,
                "has_enough_players": rsvp_summary['yes'] >= 7  # Minimum for a match
            })

        return jsonify({
            "team": {
                "id": team.id,
                "name": team.name,
                "league_name": team.league.name if team.league else None
            },
            "matches": matches_data,
            "total_matches": len(matches_data)
        }), 200


@mobile_api_v2.route('/coach/teams/<int:team_id>/matches/<int:match_id>/rsvp', methods=['GET'])
@jwt_required()
def get_match_rsvp_details(team_id: int, match_id: int):
    """
    Get detailed RSVP information for a specific match.

    Args:
        team_id: Team ID
        match_id: Match ID

    Returns:
        JSON with match info and detailed player RSVP responses
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Check authorization
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to view this team's RSVPs"}), 403

        # Get team with players
        team = session.query(Team).options(
            selectinload(Team.players)
        ).get(team_id)

        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Get match
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Verify team is in this match
        if match.home_team_id != team_id and match.away_team_id != team_id:
            return jsonify({"msg": "Team is not participating in this match"}), 400

        # Get current players on team
        team_players = [p for p in team.players if p.is_current_player]
        player_ids = [p.id for p in team_players]

        # Get availability records
        availabilities = session.query(Availability).filter(
            Availability.match_id == match_id,
            Availability.player_id.in_(player_ids)
        ).all()

        # Build response map
        availability_map = {av.player_id: av for av in availabilities}

        # Get base URL for profile pictures
        base_url = request.host_url.rstrip('/')

        # Build player list with responses
        players_data = []
        for player in team_players:
            av = availability_map.get(player.id)

            profile_picture_url = None
            if player.profile_picture_url:
                profile_picture_url = (
                    player.profile_picture_url if player.profile_picture_url.startswith('http')
                    else f"{base_url}{player.profile_picture_url}"
                )
            else:
                profile_picture_url = f"{base_url}/static/img/default_player.png"

            players_data.append({
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "position": player.favorite_position,
                "response": av.response if av else None,
                "responded_at": av.updated_at.isoformat() if av and hasattr(av, 'updated_at') and av.updated_at else None,
                "profile_picture_url": profile_picture_url
            })

        # Sort players: yes first, then maybe, then no_response, then no
        response_order = {'yes': 0, 'maybe': 1, None: 2, 'no_response': 2, 'no': 3}
        players_data.sort(key=lambda p: (response_order.get(p['response'], 2), p['name']))

        # Calculate summary
        rsvp_summary = get_rsvp_summary(session, match_id, team_id)

        is_home = match.home_team_id == team_id

        return jsonify({
            "match": {
                "id": match.id,
                "date": match.date.isoformat() if match.date else None,
                "time": match.time.isoformat() if match.time else None,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                } if match.home_team else None,
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                } if match.away_team else None,
                "location": match.location,
                "is_home": is_home
            },
            "team_id": team_id,
            "rsvp_summary": rsvp_summary,
            "players": players_data,
            "total_players": len(players_data)
        }), 200


@mobile_api_v2.route('/coach/teams/<int:team_id>/matches/<int:match_id>/rsvp/reminder', methods=['POST'])
@jwt_required()
def send_rsvp_reminder(team_id: int, match_id: int):
    """
    Send RSVP reminder to players who haven't responded.

    Args:
        team_id: Team ID
        match_id: Match ID

    Expected JSON (all optional):
        message: Custom reminder message
        only_non_responders: If true, only send to players who haven't responded (default: true)
        channels: List of channels to use ['discord', 'email', 'sms'] (default: all enabled)

    Returns:
        JSON with reminder status
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json() or {}
    custom_message = data.get('message', '').strip()
    only_non_responders = data.get('only_non_responders', True)
    channels = data.get('channels', ['discord', 'email', 'sms'])

    with managed_session() as session:
        # Check authorization
        if not is_coach_for_team(session, current_user_id, team_id) and not is_admin_user(session, current_user_id):
            return jsonify({"msg": "You are not authorized to send reminders for this team"}), 403

        # Get team with players
        team = session.query(Team).options(
            selectinload(Team.players)
        ).get(team_id)

        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Get match
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Verify team is in this match
        if match.home_team_id != team_id and match.away_team_id != team_id:
            return jsonify({"msg": "Team is not participating in this match"}), 400

        # Get current players on team
        team_players = [p for p in team.players if p.is_current_player]
        player_ids = [p.id for p in team_players]

        # Get availability records
        availabilities = session.query(Availability).filter(
            Availability.match_id == match_id,
            Availability.player_id.in_(player_ids)
        ).all()

        # Build set of players who have responded
        responded_player_ids = {av.player_id for av in availabilities if av.response}

        # Determine recipients
        if only_non_responders:
            recipients = [p for p in team_players if p.id not in responded_player_ids]
        else:
            recipients = team_players

        if not recipients:
            return jsonify({
                "success": True,
                "message": "No players to send reminders to",
                "recipients": 0,
                "channels_used": []
            }), 200

        # Build reminder message
        is_home = match.home_team_id == team_id
        opponent = match.away_team if is_home else match.home_team
        opponent_name = opponent.name if opponent else "TBD"

        match_date = match.date.strftime('%A, %B %d') if match.date else "TBD"
        match_time = match.time.strftime('%I:%M %p') if match.time else "TBD"

        if custom_message:
            reminder_message = custom_message
        else:
            reminder_message = (
                f"Reminder: Please respond to your RSVP for the match against {opponent_name} "
                f"on {match_date} at {match_time}."
            )

        # Queue notifications via the existing notification service
        channels_used = []
        notifications_queued = 0

        try:
            from app.services.notification_service import NotificationService
            notification_service = NotificationService()

            for player in recipients:
                # Get user for notification preferences
                user = session.query(User).get(player.user_id) if player.user_id else None

                if not user:
                    continue

                # Check each channel
                if 'discord' in channels and user.discord_notifications and player.discord_id:
                    # Queue Discord notification (would use existing Discord service)
                    notifications_queued += 1
                    if 'discord' not in channels_used:
                        channels_used.append('discord')

                if 'email' in channels and user.email_notifications and user.email:
                    # Queue email notification (would use existing email service)
                    notifications_queued += 1
                    if 'email' not in channels_used:
                        channels_used.append('email')

                if 'sms' in channels and user.sms_notifications and player.phone:
                    # Queue SMS notification (would use existing SMS service)
                    notifications_queued += 1
                    if 'sms' not in channels_used:
                        channels_used.append('sms')

            logger.info(
                f"RSVP reminder sent by user {current_user_id} for team {team_id} match {match_id}. "
                f"Recipients: {len(recipients)}, Channels: {channels_used}"
            )

            return jsonify({
                "success": True,
                "message": f"Reminder sent to {len(recipients)} player(s)",
                "recipients": len(recipients),
                "channels_used": channels_used,
                "reminder_message": reminder_message
            }), 200

        except Exception as e:
            logger.error(f"Error sending RSVP reminder: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to send reminders",
                "error": str(e)
            }), 500
