# app/mobile_api/match_reporting.py

"""
Mobile API Match Reporting Endpoints

Provides match event reporting functionality for mobile clients:
- Get match info for reporting
- Add/update/delete match events (goals, cards, etc.)
- Update match scores
"""

import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from sqlalchemy import and_

from datetime import datetime
from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Team, Match, player_teams
from app.models.stats import PlayerEvent, PlayerEventType
from app.teams_helpers import update_player_stats, update_standings
from app.services.event_deduplication import (
    check_duplicate_player_event,
    find_near_duplicate_player_events,
    create_player_event_idempotent,
    parse_client_timestamp,
    get_reporter_name
)

logger = logging.getLogger(__name__)

# Valid event types
VALID_EVENT_TYPES = ['goal', 'assist', 'yellow_card', 'red_card', 'own_goal']


def is_coach_for_match(session, player_id: int, match: Match) -> bool:
    """Check if a player is a coach for either team in a match."""
    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player_id,
                player_teams.c.is_coach == True,
                player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
            )
        )
    ).fetchall()
    return len(coach_check) > 0


def can_report_match(session, user: User, player: Player, match: Match) -> bool:
    """
    Check if a user has permission to report/edit a match.

    Allowed roles:
    - Global Admin, Pub League Admin, admin role - can edit any match
    - Pub League Ref - can edit any match
    - Assigned referee for the match - can edit
    - Coach for either team - can edit

    Regular players on the roster are NOT allowed to report matches.

    Args:
        session: Database session
        user: User object
        player: Player object (may be None if user has no player profile)
        match: Match object

    Returns:
        bool: True if user can report/edit the match
    """
    # Check admin roles
    is_global_admin = user.has_role('Global Admin')
    is_pub_league_admin = user.has_role('Pub League Admin')
    is_admin = is_global_admin or is_pub_league_admin
    is_pub_league_ref = user.has_role('Pub League Ref')

    # Admins and refs can edit any match
    if is_admin or is_global_admin or is_pub_league_admin or is_pub_league_ref:
        return True

    # If no player profile, can't check team membership
    if not player:
        return False

    # Check if user is the assigned referee for this match
    if player.is_ref and match.ref_id == player.id:
        return True

    # Check if user is a coach for either team
    if is_coach_for_match(session, player.id, match):
        return True

    return False


def get_coach_team_id(session, player_id: int, match: Match) -> int:
    """Get the team ID for which the player is a coach in this match."""
    coach_check = session.execute(
        player_teams.select().where(
            and_(
                player_teams.c.player_id == player_id,
                player_teams.c.is_coach == True,
                player_teams.c.team_id.in_([match.home_team_id, match.away_team_id])
            )
        )
    ).fetchone()
    return coach_check.team_id if coach_check else None


def _notify_opposing_coaches_to_verify(session, match: Match, just_verified: str) -> None:
    """
    Push-notify the OTHER team's coaches that they should verify the match.

    Called from the verify endpoint after one team verifies. No-op if the match
    is already fully verified.

    Args:
        session: SQLAlchemy session
        match: Match instance with home_team and away_team eager-loaded
        just_verified: 'home' or 'away' - which side was just verified
    """
    if match.fully_verified:
        return

    if just_verified == 'home':
        target_team_id = match.away_team_id
        target_team_name = match.away_team.name
        verified_team_name = match.home_team.name
    else:
        target_team_id = match.home_team_id
        target_team_name = match.home_team.name
        verified_team_name = match.away_team.name

    coach_user_ids = [
        row[0] for row in (
            session.query(Player.user_id)
            .join(player_teams, player_teams.c.player_id == Player.id)
            .filter(
                player_teams.c.team_id == target_team_id,
                player_teams.c.is_coach.is_(True),
                Player.user_id.isnot(None),
            )
            .distinct()
            .all()
        )
    ]
    if not coach_user_ids:
        return

    try:
        from app.services.notification_orchestrator import (
            orchestrator,
            NotificationPayload,
            NotificationType,
        )
        date_str = match.date.strftime('%b %-d') if match.date else 'recent'
        score_str = f"{match.home_team_score}-{match.away_team_score}"
        orchestrator.send(NotificationPayload(
            notification_type=NotificationType.MATCH_VERIFICATION_NEEDED,
            title="Match needs your verification",
            message=(
                f"{verified_team_name} confirmed the {date_str} result "
                f"({score_str}) against {target_team_name}. "
                f"Take a look and confirm if it matches your records."
            ),
            user_ids=coach_user_ids,
            data={
                'type': 'verify_match',
                'match_id': str(match.id),
            },
            priority='high',
            # Push-only delivery: in-app bell entry still fires (default), but
            # email/SMS/Discord are suppressed so coaches aren't multi-channel spammed.
            force_push=True,
            force_email=False,
            force_sms=False,
            force_discord=False,
        ))
    except Exception as exc:
        # Notification failures should never break the verify request itself.
        logger.exception(f"Failed to push verification notification for match {match.id}: {exc}")


@mobile_api_v2.route('/matches/<int:match_id>/reporting', methods=['GET'])
@jwt_required()
def get_match_reporting_info(match_id: int):
    """
    Get match information for reporting.
    Returns match details, team rosters, and whether user can edit.

    Args:
        match_id: Match ID

    Returns:
        JSON with match info, rosters, and permissions
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get user and player
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Player profile is optional - admins/refs may not have one
        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get match with teams
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.events),
            joinedload(Match.availability)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check if user can report for this match (admins, refs, coaches)
        can_report = can_report_match(session, user, player, match)
        coach_team_id = get_coach_team_id(session, player.id, match) if player and is_coach_for_match(session, player.id, match) else None

        # Determine verification permissions.
        # Once a team is verified, no one (coach or admin) needs to verify it again
        # via the mobile flow — admins can always undo via the web "reject" path.
        is_admin = user.has_role('Global Admin') or user.has_role('Pub League Admin')
        is_ref = user.has_role('Pub League Ref') or (player and player.is_ref and match.ref_id == player.id)
        admin_or_ref = is_admin or is_ref
        user_team_ids = [t.id for t in player.teams] if player else []
        can_verify_home = (admin_or_ref or (match.home_team_id in user_team_ids)) and not match.home_team_verified
        can_verify_away = (admin_or_ref or (match.away_team_id in user_team_ids)) and not match.away_team_verified

        # Build availability lookup by player_id
        availability_by_player = {}
        for a in match.availability:
            availability_by_player[a.player_id] = a.response or 'no_response'

        # RSVP sort priority: yes=0, maybe=1, no_response=2, no=3
        rsvp_sort_order = {'yes': 0, 'maybe': 1, 'no_response': 2, 'no': 3}

        # Get home team roster with availability
        home_players = []
        home_seen_ids = set()
        for p in match.home_team.players:
            if p.is_current_player:
                home_players.append({
                    "id": p.id,
                    "name": p.name,
                    "jersey_number": p.jersey_number,
                    "position": p.favorite_position,
                    "availability": availability_by_player.get(p.id, 'no_response'),
                    "is_sub": False
                })
                home_seen_ids.add(p.id)
        home_players.sort(key=lambda x: rsvp_sort_order.get(x['availability'], 2))

        # Get away team roster with availability
        away_players = []
        away_seen_ids = set()
        for p in match.away_team.players:
            if p.is_current_player:
                away_players.append({
                    "id": p.id,
                    "name": p.name,
                    "jersey_number": p.jersey_number,
                    "position": p.favorite_position,
                    "availability": availability_by_player.get(p.id, 'no_response'),
                    "is_sub": False
                })
                away_seen_ids.add(p.id)
        away_players.sort(key=lambda x: rsvp_sort_order.get(x['availability'], 2))

        # Add assigned temp subs to each team's roster
        from app.models.matches import TemporarySubAssignment
        temp_subs = session.query(TemporarySubAssignment).options(
            joinedload(TemporarySubAssignment.player)
        ).filter_by(
            match_id=match_id,
            is_active=True
        ).all()

        for ts in temp_subs:
            if ts.team_id == match.home_team_id and ts.player_id not in home_seen_ids:
                home_players.append({
                    "id": ts.player.id,
                    "name": ts.player.name,
                    "jersey_number": ts.player.jersey_number,
                    "position": ts.player.favorite_position,
                    "availability": "yes",
                    "is_sub": True
                })
            elif ts.team_id == match.away_team_id and ts.player_id not in away_seen_ids:
                away_players.append({
                    "id": ts.player.id,
                    "name": ts.player.name,
                    "jersey_number": ts.player.jersey_number,
                    "position": ts.player.favorite_position,
                    "availability": "yes",
                    "is_sub": True
                })

        # Get existing events
        events = []
        for event in match.events:
            events.append({
                "id": event.id,
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event.player.name if event.player else None,
                "team_id": event.team_id,
                "minute": event.minute,
                "client_timestamp": event.client_timestamp.isoformat() if event.client_timestamp else None
            })

        return jsonify({
            "match": {
                "id": match.id,
                "date": match.date.isoformat() if match.date else None,
                "time": match.time.isoformat() if match.time else None,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score,
                "home_team_verified": match.home_team_verified,
                "away_team_verified": match.away_team_verified,
                "fully_verified": match.fully_verified,
                "home_verifier": (match.home_verifier.player.name if match.home_verifier and hasattr(match.home_verifier, 'player') and match.home_verifier.player
                                  else match.home_verifier.username if match.home_verifier else None),
                "away_verifier": (match.away_verifier.player.name if match.away_verifier and hasattr(match.away_verifier, 'player') and match.away_verifier.player
                                  else match.away_verifier.username if match.away_verifier else None),
                "home_team_verified_at": match.home_team_verified_at.isoformat() if match.home_team_verified_at else None,
                "away_team_verified_at": match.away_team_verified_at.isoformat() if match.away_team_verified_at else None
            },
            "home_roster": home_players,
            "away_roster": away_players,
            "events": events,
            "can_report": can_report,
            "can_verify_home": can_verify_home,
            "can_verify_away": can_verify_away,
            "coach_team_id": coach_team_id
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events', methods=['GET'])
@jwt_required()
def get_match_events(match_id: int):
    """
    Get all events for a match.

    Args:
        match_id: Match ID

    Returns:
        JSON with list of match events
    """
    with managed_session() as session:
        match = session.query(Match).options(
            joinedload(Match.events).joinedload(PlayerEvent.player)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        events = []
        for event in match.events:
            events.append({
                "id": event.id,
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event.player.name if event.player else None,
                "team_id": event.team_id,
                "minute": event.minute,
                "client_timestamp": event.client_timestamp.isoformat() if event.client_timestamp else None
            })

        return jsonify({
            "match_id": match_id,
            "events": events,
            "home_team_score": match.home_team_score,
            "away_team_score": match.away_team_score
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events', methods=['POST'])
@jwt_required()
def add_match_event(match_id: int):
    """
    Add a match event (goal, card, etc.) with offline resilience support.

    Args:
        match_id: Match ID

    Expected JSON:
        event_type: Type of event (goal, assist, yellow_card, red_card, own_goal)
        player_id: ID of player (required except for own_goal)
        team_id: ID of team (required for own_goal)
        minute: Match minute when event occurred (optional)
        idempotency_key: Client-generated unique key for deduplication (optional)
        client_timestamp: ISO timestamp from client device (optional)
        force: Set to true to bypass near-duplicate detection (optional)

    Returns:
        JSON with created event and status (created, duplicate, or near_duplicate)
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    event_type = data.get('event_type')
    player_id = data.get('player_id')
    team_id = data.get('team_id')
    minute = data.get('minute')
    idempotency_key = data.get('idempotency_key')
    client_timestamp_str = data.get('client_timestamp')
    force = data.get('force', False)

    # Validate event type
    if not event_type or event_type not in VALID_EVENT_TYPES:
        return jsonify({"msg": f"Invalid event type. Must be one of: {', '.join(VALID_EVENT_TYPES)}"}), 400

    # Validate required fields
    if event_type == 'own_goal':
        if not team_id:
            return jsonify({"msg": "team_id is required for own_goal events"}), 400
    else:
        if not player_id:
            return jsonify({"msg": "player_id is required for this event type"}), 400

    with managed_session() as session:
        # Get user and optional player profile
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization (admins, refs, coaches)
        if not can_report_match(session, user, player, match):
            return jsonify({"msg": "You are not authorized to report events for this match"}), 403

        # Validate player/team belongs to match
        if player_id:
            event_player = session.query(Player).get(player_id)
            if not event_player:
                return jsonify({"msg": "Player not found"}), 404

            # Check player is on one of the match teams
            player_team_ids = {t.id for t in event_player.teams}
            if match.home_team_id not in player_team_ids and match.away_team_id not in player_team_ids:
                return jsonify({"msg": "Player is not on either team in this match"}), 400

        if team_id:
            if team_id not in [match.home_team_id, match.away_team_id]:
                return jsonify({"msg": "Team is not in this match"}), 400

        # Parse client timestamp
        client_timestamp = parse_client_timestamp(client_timestamp_str)

        # Check for exact duplicate by idempotency_key
        if idempotency_key:
            existing = check_duplicate_player_event(session, match_id, idempotency_key)
            if existing:
                logger.info(f"Duplicate event detected via REST: idempotency_key={idempotency_key}")
                # Get reporter name for iOS compatibility
                original_reporter = get_reporter_name(session, existing.reported_by) if existing.reported_by else None
                # Return 200 for idempotent success (not an error)
                return jsonify({
                    "status": "duplicate",
                    "is_duplicate": True,  # iOS compatibility
                    "success": True,
                    "event": existing.to_dict(include_player=True) if existing.player else existing.to_dict(),
                    "original_event_id": existing.id,  # iOS compatibility alias
                    "original_reporter": original_reporter,  # iOS compatibility
                    "message": "Event already exists with this idempotency key"
                }), 200

        # Check for near-duplicates unless force=True
        if not force:
            near_dupes = find_near_duplicate_player_events(
                session=session,
                match_id=match_id,
                player_id=player_id,
                event_type=event_type,
                minute=str(minute) if minute else None,
                exclude_idempotency_key=idempotency_key
            )

            if near_dupes:
                logger.info(f"Near-duplicate events found via REST: {len(near_dupes)} matches")
                return jsonify({
                    "status": "near_duplicate",
                    "is_duplicate": False,  # iOS compatibility - not an exact duplicate
                    "success": False,
                    "near_duplicates": [e.to_dict() for e in near_dupes],
                    "message": "Similar events found - set force=true to confirm creation",
                    "idempotency_key": idempotency_key
                }), 409  # Conflict status

        # Create the event
        event = PlayerEvent(
            match_id=match_id,
            event_type=PlayerEventType(event_type),
            minute=str(minute) if minute else None,
            idempotency_key=idempotency_key,
            client_timestamp=client_timestamp,
            reported_by=current_user_id  # Track who reported this event
        )

        if event_type == 'own_goal':
            event.team_id = team_id
        else:
            event.player_id = player_id

        session.add(event)

        # Update player season/career stats (except for own goals which have no player)
        if event_type != 'own_goal' and player_id:
            try:
                update_player_stats(session, player_id, event_type, match, increment=True)
                logger.info(f"Updated stats for player {player_id}: +1 {event_type}")
            except Exception as e:
                logger.error(f"Failed to update player stats: {e}")
                # Continue - event is still valid even if stats update fails

        # Adding an event mutates the match — restart the two-coach handshake.
        if match.reset_verification():
            logger.info(f"Match {match_id} verification reset due to new event")

        session.commit()

        # Get player name for response
        event_player_name = None
        if event.player_id:
            event_player = session.query(Player).get(event.player_id)
            event_player_name = event_player.name if event_player else None

        return jsonify({
            "status": "created",
            "success": True,
            "event": {
                "id": event.id,
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type.value,
                "player_id": event.player_id,
                "player_name": event_player_name,
                "team_id": event.team_id,
                "minute": event.minute,
                "client_timestamp": event.client_timestamp.isoformat() if event.client_timestamp else None
            }
        }), 201


@mobile_api_v2.route('/matches/<int:match_id>/events/<int:event_id>', methods=['PUT'])
@jwt_required()
def update_match_event(match_id: int, event_id: int):
    """
    Update a match event.

    Args:
        match_id: Match ID
        event_id: Event ID

    Expected JSON:
        player_id: New player ID (optional)
        team_id: New team ID (optional, for own_goal)
        minute: New minute (optional)

    Returns:
        JSON with updated event
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    with managed_session() as session:
        # Get user and optional player profile
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get event
        event = session.query(PlayerEvent).filter_by(
            id=event_id,
            match_id=match_id
        ).first()

        if not event:
            return jsonify({"msg": "Event not found"}), 404

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization (admins, refs, coaches)
        if not can_report_match(session, user, player, match):
            return jsonify({"msg": "You are not authorized to update events for this match"}), 403

        # Track old player for stats update
        old_player_id = event.player_id
        event_type = event.event_type.value

        # Update fields
        if 'player_id' in data:
            new_player_id = data['player_id']
            if new_player_id:
                event_player = session.query(Player).get(new_player_id)
                if not event_player:
                    return jsonify({"msg": "Player not found"}), 404
                event.player_id = new_player_id
            else:
                event.player_id = None

        if 'team_id' in data:
            event.team_id = data['team_id']

        if 'minute' in data:
            event.minute = str(data['minute']) if data['minute'] else None

        # Update player stats if player changed (except for own goals)
        if event_type != 'own_goal' and 'player_id' in data:
            new_player_id = data.get('player_id')
            if old_player_id != new_player_id:
                try:
                    # Decrement old player's stats
                    if old_player_id:
                        update_player_stats(session, old_player_id, event_type, match, increment=False)
                        logger.info(f"Updated stats for player {old_player_id}: -1 {event_type}")
                    # Increment new player's stats
                    if new_player_id:
                        update_player_stats(session, new_player_id, event_type, match, increment=True)
                        logger.info(f"Updated stats for player {new_player_id}: +1 {event_type}")
                except Exception as e:
                    logger.error(f"Failed to update player stats on event update: {e}")

        # Mirror the edit onto the paired MatchEvent row so the /live feed
        # stays consistent with PlayerEvent. Finds by derived idempotency_key.
        try:
            if event.idempotency_key and event.idempotency_key.startswith('pe_'):
                from app.database.db_models import MatchEvent as _LiveMatchEvent
                me_key = event.idempotency_key[len('pe_'):]
                live_event = session.query(_LiveMatchEvent).filter_by(
                    match_id=match_id, idempotency_key=me_key
                ).first()
                if live_event is not None:
                    if 'player_id' in data:
                        live_event.player_id = event.player_id
                    if 'team_id' in data:
                        live_event.team_id = event.team_id
                    if 'minute' in data:
                        # Both tables are VARCHAR(10) post-widening migration; string passthrough.
                        m = data.get('minute')
                        live_event.minute = str(m) if m is not None else None
        except Exception:
            logger.exception(f"Failed to mirror PlayerEvent edit onto MatchEvent for match {match_id}")

        # Editing an event mutates the match — restart the two-coach handshake.
        if match.reset_verification():
            logger.info(f"Match {match_id} verification reset due to event update")

        session.commit()

        # Get player name for response
        event_player_name = None
        if event.player_id:
            event_player = session.query(Player).get(event.player_id)
            event_player_name = event_player.name if event_player else None

        event_payload = {
            "id": event.id,
            "event_type": event.event_type.value,
            "player_id": event.player_id,
            "player_name": event_player_name,
            "team_id": event.team_id,
            "minute": event.minute,
        }

        # V2: broadcast event_updated to the /live room so in-room coaches
        # refresh when an admin edits via REST mid-match. Safe no-op if no
        # LiveMatchState exists for this match.
        try:
            from app.services.live_reporting import redis_state
            if redis_state.load_state('pub', match_id) is not None:
                from app.core import socketio as _socketio
                _socketio.emit(
                    'event_updated',
                    {
                        'match_id': match_id,
                        'league_type': 'pub',
                        'event': event_payload,
                        'updated_by': current_user_id,
                    },
                    room=f"match_{match_id}",
                    namespace='/live',
                )
        except Exception:
            logger.exception(f"Failed to broadcast event_updated for match {match_id}")

        return jsonify({
            "success": True,
            "event": event_payload,
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events/<int:event_id>', methods=['DELETE'])
@jwt_required()
def delete_match_event(match_id: int, event_id: int):
    """
    Delete a match event.

    Args:
        match_id: Match ID
        event_id: Event ID

    Returns:
        JSON with success message
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get user and optional player profile
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get event
        event = session.query(PlayerEvent).filter_by(
            id=event_id,
            match_id=match_id
        ).first()

        if not event:
            return jsonify({"msg": "Event not found"}), 404

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization (admins, refs, coaches)
        if not can_report_match(session, user, player, match):
            return jsonify({"msg": "You are not authorized to delete events for this match"}), 403

        event_type = event.event_type.value
        event_player_id = event.player_id

        # Decrement player stats before deleting (except for own goals)
        if event_type != 'own_goal' and event_player_id:
            try:
                update_player_stats(session, event_player_id, event_type, match, increment=False)
                logger.info(f"Updated stats for player {event_player_id}: -1 {event_type}")
            except Exception as e:
                logger.error(f"Failed to update player stats on event delete: {e}")

        # Assist-cascade: when deleting a GOAL that has a paired ASSIST PlayerEvent
        # (created server-side via additional_data.assist_player_id), delete the
        # ASSIST too and reverse its stats. Key pattern: '{match_event_key}::assist'.
        paired_assist = None
        if event_type == 'goal' and event.idempotency_key and event.idempotency_key.startswith('pe_'):
            match_event_key = event.idempotency_key[len('pe_'):]
            paired_assist = session.query(PlayerEvent).filter_by(
                match_id=match_id,
                idempotency_key=f"{match_event_key}::assist",
            ).first()
            if paired_assist is not None:
                try:
                    if paired_assist.player_id:
                        update_player_stats(
                            session, paired_assist.player_id, 'assist', match, increment=False
                        )
                        logger.info(
                            f"Updated stats for paired assist player {paired_assist.player_id}: -1 assist"
                        )
                    session.delete(paired_assist)
                except Exception:
                    logger.exception(f"Failed to cascade-delete paired assist for match {match_id}")

        deleted_event_id = event.id
        # Mirror the delete onto the paired MatchEvent row so the /live feed
        # doesn't show a ghost event after admin edits via REST.
        try:
            from app.database.db_models import MatchEvent as _LiveMatchEvent
            live_event = None
            if event.idempotency_key and event.idempotency_key.startswith('pe_'):
                me_key = event.idempotency_key[len('pe_'):]
                live_event = session.query(_LiveMatchEvent).filter_by(
                    match_id=match_id, idempotency_key=me_key
                ).first()
            if live_event is None:
                # Fallback for pre-V2 PlayerEvents that lack an idempotency_key:
                # heuristic match on (match_id, player_id, event_type, minute).
                live_event = session.query(_LiveMatchEvent).filter_by(
                    match_id=match_id,
                    player_id=event.player_id,
                    event_type=event.event_type.name,  # enum → UPPERCASE string
                    minute=event.minute,
                ).first()
            if live_event is not None:
                session.delete(live_event)
        except Exception:
            logger.exception(f"Failed to mirror PlayerEvent delete onto MatchEvent for match {match_id}")

        session.delete(event)

        # Deleting an event mutates the match — restart the two-coach handshake.
        if match.reset_verification():
            logger.info(f"Match {match_id} verification reset due to event deletion")

        session.commit()

        # V2: notify /live room so in-room coaches drop this event from their UI.
        try:
            from app.services.live_reporting import redis_state
            if redis_state.load_state('pub', match_id) is not None:
                from app.core import socketio as _socketio
                _socketio.emit(
                    'event_deleted',
                    {
                        'match_id': match_id,
                        'league_type': 'pub',
                        'event_id': deleted_event_id,
                        'deleted_by': current_user_id,
                    },
                    room=f"match_{match_id}",
                    namespace='/live',
                )
        except Exception:
            logger.exception(f"Failed to broadcast event_deleted for match {match_id}")

        return jsonify({
            "success": True,
            "message": f"Event ({event_type}) deleted successfully"
        }), 200


@mobile_api_v2.route('/report_match/<int:match_id>', methods=['POST'])
@jwt_required()
def report_match(match_id: int):
    """
    Submit a complete match report with score and events.

    This is the final submission endpoint that marks the match as reported.

    Args:
        match_id: Match ID

    Expected JSON:
        home_team_score: Final home team score (required)
        away_team_score: Final away team score (required)
        notes: Optional match notes
        events: Optional list of events to add
            Each event: { player_id, event_type, minute, team_id (for own_goal) }

    Returns:
        JSON with reported match details
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    home_score = data.get('home_team_score')
    away_score = data.get('away_team_score')

    if home_score is None or away_score is None:
        return jsonify({"msg": "Both home_team_score and away_team_score are required"}), 400

    try:
        home_score = int(home_score)
        away_score = int(away_score)
    except (ValueError, TypeError):
        return jsonify({"msg": "Scores must be integers"}), 400

    if home_score < 0 or away_score < 0:
        return jsonify({"msg": "Scores cannot be negative"}), 400

    with managed_session() as session:
        # Get user and optional player profile
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get match with teams
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization (admins, refs, coaches)
        if not can_report_match(session, user, player, match):
            return jsonify({"msg": "You are not authorized to report this match"}), 403

        # Capture pre-mutation state so we can detect actual data changes below.
        old_home_score = match.home_team_score
        old_away_score = match.away_team_score
        old_notes = match.notes

        # Update scores
        match.home_team_score = home_score
        match.away_team_score = away_score

        # Add notes if provided
        notes = data.get('notes')
        if notes:
            match.notes = notes

        # If the report resubmission actually changes the data (scores, notes, or
        # any incoming events), restart the two-coach handshake. We do this BEFORE
        # re-applying any verify_* flags below, so a submitter who verifies in the
        # same request still ends up verified.
        events_data = data.get('events', [])
        score_changed = (old_home_score != home_score) or (old_away_score != away_score)
        notes_changed = bool(notes) and notes != old_notes
        if score_changed or notes_changed or events_data:
            if match.reset_verification():
                logger.info(f"Match {match_id} verification reset due to report resubmission")

        # Handle verification if requested
        verify_home = data.get('verify_home_team', False)
        verify_away = data.get('verify_away_team', False)

        if verify_home or verify_away:
            is_admin = user.has_role('Global Admin') or user.has_role('Pub League Admin')
            is_ref = user.has_role('Pub League Ref') or (player and player.is_ref and match.ref_id == player.id)
            admin_or_ref = is_admin or is_ref
            user_team_ids = [t.id for t in player.teams] if player else []
            now = datetime.utcnow()

            if verify_home and (admin_or_ref or match.home_team_id in user_team_ids):
                match.home_team_verified = True
                match.home_team_verified_by = current_user_id
                match.home_team_verified_at = now
                logger.info(f"Home team verified for match {match_id} by user {current_user_id}")

            if verify_away and (admin_or_ref or match.away_team_id in user_team_ids):
                match.away_team_verified = True
                match.away_team_verified_by = current_user_id
                match.away_team_verified_at = now
                logger.info(f"Away team verified for match {match_id} by user {current_user_id}")

        # Add events if provided (with idempotency support)
        events_result = []

        for event_data in events_data:
            event_type = event_data.get('event_type')
            if not event_type or event_type not in VALID_EVENT_TYPES:
                continue  # Skip invalid events

            idempotency_key = event_data.get('idempotency_key')
            client_timestamp_str = event_data.get('client_timestamp')
            client_timestamp = parse_client_timestamp(client_timestamp_str)

            # Check for exact duplicate by idempotency_key
            if idempotency_key:
                existing = check_duplicate_player_event(session, match_id, idempotency_key)
                if existing:
                    logger.info(f"Duplicate event in report_match: idempotency_key={idempotency_key}")
                    events_result.append({
                        "idempotency_key": idempotency_key,
                        "id": existing.id,
                        "status": "duplicate"
                    })
                    continue

            event = PlayerEvent(
                match_id=match_id,
                event_type=PlayerEventType(event_type),
                minute=str(event_data.get('minute')) if event_data.get('minute') else None,
                idempotency_key=idempotency_key,
                client_timestamp=client_timestamp,
                reported_by=current_user_id  # Track who reported this event
            )

            if event_type == 'own_goal':
                event.team_id = event_data.get('team_id')
            else:
                event.player_id = event_data.get('player_id')

            session.add(event)
            session.flush()  # Get the ID

            # Update player season/career stats (except for own goals)
            if event_type != 'own_goal' and event.player_id:
                try:
                    update_player_stats(session, event.player_id, event_type, match, increment=True)
                    logger.info(f"Updated stats for player {event.player_id}: +1 {event_type}")
                except Exception as e:
                    logger.error(f"Failed to update player stats in report_match: {e}")

            events_result.append({
                "idempotency_key": idempotency_key,
                "id": event.id,
                "event_type": event_type,
                "player_id": event.player_id,
                "team_id": event.team_id,
                "minute": event.minute,
                "status": "created"
            })

        session.commit()

        # Update standings after match is reported
        try:
            update_standings(session, match)
        except Exception as standings_error:
            logger.error(f"Failed to update standings for match {match_id}: {standings_error}")

        logger.info(f"Match {match_id} reported by user {current_user_id}: {home_score}-{away_score}")

        # Count created vs duplicate events
        created_count = sum(1 for e in events_result if e.get('status') == 'created')
        duplicate_count = sum(1 for e in events_result if e.get('status') == 'duplicate')

        # V2 status flip: update Redis LiveMatchState + matches.report_submitted_at
        # + cancel any in-flight timer Celery jobs + broadcast report_submitted to
        # the /live room. Safe no-op if Redis is unavailable.
        try:
            from app.core import socketio as _socketio
            from app.services.live_reporting.submit_helper import submit_match_report
            submit_match_report(
                session=session,
                match_id=match_id,
                league_type='pub',
                submitted_by_user_id=current_user_id,
                socketio=_socketio,
            )
        except Exception:
            logger.exception(f"V2 submit_match_report failed for match {match_id}; REST write already succeeded")

        return jsonify({
            "success": True,
            "msg": "Match reported successfully",
            "match": {
                "id": match.id,
                "date": match.date.isoformat() if match.date else None,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score,
                "reported": match.reported,
                "notes": match.notes,
                "home_team_verified": match.home_team_verified,
                "away_team_verified": match.away_team_verified,
                "fully_verified": match.fully_verified
            },
            "events_created": created_count,
            "events_duplicate": duplicate_count,
            "events": events_result
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/score', methods=['PUT'])
@jwt_required()
def update_match_score(match_id: int):
    """
    Update the final score for a match.

    Args:
        match_id: Match ID

    Expected JSON:
        home_team_score: Home team score
        away_team_score: Away team score

    Returns:
        JSON with updated match
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    home_score = data.get('home_team_score')
    away_score = data.get('away_team_score')

    if home_score is None or away_score is None:
        return jsonify({"msg": "Both home_team_score and away_team_score are required"}), 400

    try:
        home_score = int(home_score)
        away_score = int(away_score)
    except (ValueError, TypeError):
        return jsonify({"msg": "Scores must be integers"}), 400

    if home_score < 0 or away_score < 0:
        return jsonify({"msg": "Scores cannot be negative"}), 400

    with managed_session() as session:
        # Get user and optional player profile
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get match
        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization (admins, refs, coaches)
        if not can_report_match(session, user, player, match):
            return jsonify({"msg": "You are not authorized to update scores for this match"}), 403

        # Detect actual score change before mutating
        score_changed = (match.home_team_score != home_score) or (match.away_team_score != away_score)

        # Update scores
        match.home_team_score = home_score
        match.away_team_score = away_score

        # Only restart the two-coach handshake if scores actually moved.
        # A no-op resubmission shouldn't punish coaches who already verified.
        if score_changed:
            if match.reset_verification():
                logger.info(f"Match {match_id} verification reset due to score change")

        session.commit()

        # Update standings after score change
        try:
            update_standings(session, match)
        except Exception as standings_error:
            logger.error(f"Failed to update standings for match {match_id}: {standings_error}")

        # V2: if a live match is in progress in Redis, sync the new score into
        # the state blob + broadcast score_updated so in-room coaches see the
        # admin-driven correction immediately. Safe no-op when there's no state.
        if score_changed:
            try:
                from app.services.live_reporting import redis_state
                live_state = redis_state.load_state('pub', match_id)
                if live_state is not None and live_state.get('report_status') != redis_state.REPORT_SUBMITTED:
                    redis_state.set_scores(live_state, home_score, away_score, current_user_id)
                    redis_state.save_state('pub', match_id, live_state)
                    from app.core import socketio as _socketio
                    _socketio.emit(
                        'score_updated',
                        {
                            'match_id': match_id,
                            'league_type': 'pub',
                            'home_score': home_score,
                            'away_score': away_score,
                            'last_score_sequence': live_state['last_score_sequence'],
                            'server_epoch_ms': redis_state.now_ms(),
                            'updated_by': current_user_id,
                            'source': 'rest_score_put',
                        },
                        room=f"match_{match_id}",
                        namespace='/live',
                    )
            except Exception:
                logger.exception(f"Failed to sync REST score PUT into Redis for match {match_id}")

        return jsonify({
            "success": True,
            "match": {
                "id": match.id,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score
            }
        }), 200


@mobile_api_v2.route('/matches/<int:match_id>/events/resolve', methods=['POST'])
@jwt_required()
def resolve_event_conflict(match_id: int):
    """
    Resolve near-duplicate event conflicts.

    This endpoint is used when the client receives a near_duplicate response
    and wants to either:
    1. Force create the new event (confirming it's not a duplicate)
    2. Accept an existing event as the correct one

    Args:
        match_id: Match ID

    Expected JSON:
        action: 'create' to force create, 'accept' to accept existing
        event_data: Event data for 'create' action
        idempotency_key: Client-generated unique key
        client_timestamp: ISO timestamp from client device
        accepted_event_id: ID of existing event to accept (for 'accept' action)

    Returns:
        JSON with resolved event
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    action = data.get('action')
    if action not in ['create', 'accept']:
        return jsonify({"msg": "action must be 'create' or 'accept'"}), 400

    with managed_session() as session:
        # Get user and optional player profile
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        # Get match
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Check authorization
        if not can_report_match(session, user, player, match):
            return jsonify({"msg": "You are not authorized to resolve conflicts for this match"}), 403

        if action == 'accept':
            # Accept an existing event as the correct one
            accepted_event_id = data.get('accepted_event_id')
            if not accepted_event_id:
                return jsonify({"msg": "accepted_event_id is required for 'accept' action"}), 400

            existing = session.query(PlayerEvent).filter_by(
                id=accepted_event_id,
                match_id=match_id
            ).first()

            if not existing:
                return jsonify({"msg": "Event not found"}), 404

            return jsonify({
                "status": "accepted",
                "success": True,
                "event": existing.to_dict(),
                "message": "Existing event accepted"
            }), 200

        elif action == 'create':
            # Force create a new event
            event_data = data.get('event_data') or data.get('event')
            if not event_data:
                return jsonify({"msg": "event_data is required for 'create' action"}), 400

            event_type = event_data.get('event_type')
            if not event_type or event_type not in VALID_EVENT_TYPES:
                return jsonify({"msg": f"Invalid event type. Must be one of: {', '.join(VALID_EVENT_TYPES)}"}), 400

            player_id = event_data.get('player_id')
            team_id = event_data.get('team_id')
            minute = event_data.get('minute')
            idempotency_key = data.get('idempotency_key')
            client_timestamp_str = data.get('client_timestamp')
            client_timestamp = parse_client_timestamp(client_timestamp_str)

            # Validate required fields
            if event_type == 'own_goal':
                if not team_id:
                    return jsonify({"msg": "team_id is required for own_goal events"}), 400
            else:
                if not player_id:
                    return jsonify({"msg": "player_id is required for this event type"}), 400

            # Check for exact duplicate (still maintain idempotency)
            if idempotency_key:
                existing = check_duplicate_player_event(session, match_id, idempotency_key)
                if existing:
                    original_reporter = get_reporter_name(session, existing.reported_by) if existing.reported_by else None
                    return jsonify({
                        "status": "duplicate",
                        "is_duplicate": True,  # iOS compatibility
                        "success": True,
                        "event": existing.to_dict(),
                        "original_event_id": existing.id,  # iOS compatibility alias
                        "original_reporter": original_reporter,  # iOS compatibility
                        "message": "Event already exists with this idempotency key"
                    }), 200

            # Create the event (skip near-duplicate check)
            event = PlayerEvent(
                match_id=match_id,
                event_type=PlayerEventType(event_type),
                minute=str(minute) if minute else None,
                idempotency_key=idempotency_key,
                client_timestamp=client_timestamp,
                reported_by=current_user_id  # Track who reported this event
            )

            if event_type == 'own_goal':
                event.team_id = team_id
            else:
                event.player_id = player_id

            session.add(event)

            # Update player stats
            if event_type != 'own_goal' and player_id:
                try:
                    update_player_stats(session, player_id, event_type, match, increment=True)
                    logger.info(f"Updated stats for player {player_id}: +1 {event_type} (conflict resolved)")
                except Exception as e:
                    logger.error(f"Failed to update player stats in resolve_conflict: {e}")

            # Force-creating an event mutates the match — restart the two-coach handshake.
            if match.reset_verification():
                logger.info(f"Match {match_id} verification reset due to force-created event")

            session.commit()

            # Get player name for response
            event_player_name = None
            if event.player_id:
                event_player = session.query(Player).get(event.player_id)
                event_player_name = event_player.name if event_player else None

            return jsonify({
                "status": "created",
                "success": True,
                "event": {
                    "id": event.id,
                    "idempotency_key": event.idempotency_key,
                    "event_type": event.event_type.value,
                    "player_id": event.player_id,
                    "player_name": event_player_name,
                    "team_id": event.team_id,
                    "minute": event.minute,
                    "client_timestamp": event.client_timestamp.isoformat() if event.client_timestamp else None
                },
                "message": "Event created (conflict resolved)"
            }), 201


@mobile_api_v2.route('/matches/<int:match_id>/verify', methods=['POST'])
@jwt_required()
def verify_match(match_id: int):
    """
    Verify match results for a team.

    Each team's coach must verify separately. Admins and refs can verify any team.

    Args:
        match_id: Match ID

    Expected JSON:
        team: 'home', 'away', or 'both' (which team to verify for)

    Returns:
        JSON with updated verification status
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    team = data.get('team')
    if team not in ('home', 'away', 'both'):
        return jsonify({"msg": "team must be 'home', 'away', or 'both'"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        player = session.query(Player).filter_by(user_id=current_user_id).first()

        match = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.home_verifier),
            joinedload(Match.away_verifier)
        ).get(match_id)

        if not match:
            return jsonify({"msg": "Match not found"}), 404

        # Match must be reported before it can be verified
        if not match.reported:
            return jsonify({"msg": "Match must be reported before it can be verified"}), 400

        # Determine permissions
        is_admin = user.has_role('Global Admin') or user.has_role('Pub League Admin')
        is_ref = user.has_role('Pub League Ref') or (player and player.is_ref and match.ref_id == player.id)
        admin_or_ref = is_admin or is_ref
        user_team_ids = [t.id for t in player.teams] if player else []

        now = datetime.utcnow()
        verified_teams = []
        newly_verified = set()  # Tracks fresh verifications for post-commit notifications

        # Verify home team
        if team in ('home', 'both'):
            can_verify_home = admin_or_ref or (match.home_team_id in user_team_ids)
            if not can_verify_home:
                return jsonify({"msg": "You are not authorized to verify for the home team"}), 403
            if match.home_team_verified:
                verified_teams.append('home (already verified)')
            else:
                match.home_team_verified = True
                match.home_team_verified_by = current_user_id
                match.home_team_verified_at = now
                verified_teams.append('home')
                newly_verified.add('home')
                logger.info(f"Home team verified for match {match_id} by user {current_user_id}")

        # Verify away team
        if team in ('away', 'both'):
            can_verify_away = admin_or_ref or (match.away_team_id in user_team_ids)
            if not can_verify_away:
                return jsonify({"msg": "You are not authorized to verify for the away team"}), 403
            if match.away_team_verified:
                verified_teams.append('away (already verified)')
            else:
                match.away_team_verified = True
                match.away_team_verified_by = current_user_id
                match.away_team_verified_at = now
                verified_teams.append('away')
                newly_verified.add('away')
                logger.info(f"Away team verified for match {match_id} by user {current_user_id}")

        session.commit()

        # Push the OTHER team's coaches if exactly one side was just verified.
        # If both were verified in this call (e.g. team='both' from an admin), the
        # match is now fully verified and there's no one left to notify.
        if not match.fully_verified:
            if 'home' in newly_verified and 'away' not in newly_verified:
                _notify_opposing_coaches_to_verify(session, match, 'home')
            elif 'away' in newly_verified and 'home' not in newly_verified:
                _notify_opposing_coaches_to_verify(session, match, 'away')

        return jsonify({
            "success": True,
            "verified_teams": verified_teams,
            "match": {
                "id": match.id,
                "home_team": {
                    "id": match.home_team.id,
                    "name": match.home_team.name
                },
                "away_team": {
                    "id": match.away_team.id,
                    "name": match.away_team.name
                },
                "home_team_score": match.home_team_score,
                "away_team_score": match.away_team_score,
                "home_team_verified": match.home_team_verified,
                "away_team_verified": match.away_team_verified,
                "fully_verified": match.fully_verified,
                "home_verifier": (match.home_verifier.player.name if match.home_verifier and hasattr(match.home_verifier, 'player') and match.home_verifier.player
                                  else match.home_verifier.username if match.home_verifier else None),
                "away_verifier": (match.away_verifier.player.name if match.away_verifier and hasattr(match.away_verifier, 'player') and match.away_verifier.player
                                  else match.away_verifier.username if match.away_verifier else None),
                "home_team_verified_at": match.home_team_verified_at.isoformat() if match.home_team_verified_at else None,
                "away_team_verified_at": match.away_team_verified_at.isoformat() if match.away_team_verified_at else None
            }
        }), 200
