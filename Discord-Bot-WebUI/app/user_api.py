# app/user_api.py

"""
User API Module

This module defines a set of API endpoints for user-related operations,
including player lookup, notification preferences retrieval and updates,
SMS enrollment and confirmation, and team lookup via case-insensitive queries.
"""

import logging
from datetime import datetime
import ipaddress

from flask import Blueprint, request, jsonify, g, url_for, current_app
from app import csrf
from app.models import User, Player, Team, player_teams
from app.discord_utils import get_expected_roles
from app.sms_helpers import (
    send_sms,
    verify_sms_confirmation,
    send_confirmation_sms
)

logger = logging.getLogger(__name__)
user_bp = Blueprint('user_api', __name__)
csrf.exempt(user_bp)


@user_bp.before_request
def limit_remote_addr():
    """
    Restrict API access to allowed hosts and mobile devices.
    
    This function allows access from:
    1. Specific hosts in the allowed_hosts list
    2. IP ranges using CIDR notation (e.g., local network)
    3. Mobile devices with valid API key
    """
    allowed_hosts = [
        # Server and development hosts
        '127.0.0.1:5000', 
        'localhost:5000', 
        'webui:5000',
        '192.168.1.112:5000',
        
        # Mobile development
        '10.0.2.2:5000',      # Android emulator default
        '192.168.1.0/24',     # Local network (allows any IP in this range)
        '192.168.0.0/24',     # Alternative local network
    ]
    
    # Check if host is in the allowed hosts list (direct match)
    if request.host in allowed_hosts:
        return
    
    # Check IP ranges (CIDR notation)
    client_ip = request.host.split(':')[0]  # Remove port if present
    for allowed in allowed_hosts:
        if '/' in allowed:  # This is a CIDR notation
            try:
                network = ipaddress.ip_network(allowed)
                if ipaddress.ip_address(client_ip) in network:
                    return
            except (ValueError, ipaddress.AddressValueError):
                # Skip invalid IP addresses or networks
                continue
    
    # Check for API key in headers (for mobile app)
    api_key = request.headers.get('X-API-Key')
    if api_key and api_key == current_app.config.get('MOBILE_API_KEY', 'ecs-soccer-mobile-key'):
        return
    
    # If we get here, access is denied
    logger.warning(f"API access denied for host: {request.host}")
    return "Access Denied", 403


@user_bp.route('/player_lookup', methods=['GET'])
def player_lookup():
    """
    Lookup a player using a case-insensitive partial match on the player's name.

    Query Parameters:
        name (str): The partial name to search for.

    Returns:
        JSON response with the player's id, name, and discord_id if found,
        or an error message if not found or if the parameter is missing.
    """
    name_query = request.args.get("name")
    if not name_query:
        return jsonify({"error": "Missing name parameter"}), 400

    session_db = g.db_session
    # Perform a case-insensitive search using a partial match.
    player = session_db.query(Player).filter(Player.name.ilike(f"%{name_query}%")).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    return jsonify({
        "id": player.id,
        "name": player.name,
        "discord_id": player.discord_id
    }), 200


@user_bp.route('/get_notifications', methods=['GET'])
def get_notifications():
    """
    Retrieve notification preferences for a player based on their discord_id.

    Query Parameters:
        discord_id (str): The discord ID of the player.

    Returns:
        JSON response containing the user's notification preferences,
        SMS enrollment status, and phone verification status.
    """
    discord_id = request.args.get("discord_id")
    if not discord_id:
        return jsonify({"error": "Missing discord_id parameter"}), 400

    session_db = g.db_session
    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    notifications = {
        "discord": user.discord_notifications,
        "email": user.email_notifications,
        "sms": user.sms_notifications
    }
    sms_enrolled = bool(player.phone and user.sms_confirmation_code is None)
    phone_verified = bool(player.phone and player.is_phone_verified)
    return jsonify({
        "notifications": notifications,
        "sms_enrolled": sms_enrolled,
        "phone_verified": phone_verified
    }), 200


@user_bp.route('/update_notifications', methods=['POST'])
def update_notifications():
    """
    Update a user's notification preferences.

    Expects a JSON payload containing:
        - discord_id: The user's discord ID.
        - notifications: A dictionary with keys 'discord', 'email', and 'sms'.

    Returns:
        JSON response confirming successful update or describing errors.
    """
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    notifications = data.get("notifications")

    if not discord_id or notifications is None:
        return jsonify({"error": "Missing required fields"}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    # Save previous SMS state to detect changes.
    previous_sms = user.sms_notifications

    user.discord_notifications = notifications.get("discord", False)
    user.email_notifications = notifications.get("email", False)
    user.sms_notifications = notifications.get("sms", False)

    if not notifications.get("sms", False) and previous_sms:
        # User has disabled SMS notifications.
        player.is_phone_verified = False
        player.sms_opt_out_timestamp = datetime.utcnow()
    session_db.commit()

    # Notify the user via SMS about changes in SMS notification status.
    if notifications.get("sms", False) and not previous_sms:
        success, sid = send_sms(player.phone, "SMS notifications enabled for ECS FC. Reply END to unsubscribe.")
        if not success:
            logger.error(f"Failed to send SMS confirmation for user {user.id}: {sid}")
    elif not notifications.get("sms", False) and previous_sms:
        success, sid = send_sms(player.phone, "SMS notifications disabled for ECS FC. Reply START to re-subscribe.")
        if not success:
            logger.error(f"Failed to send SMS disable confirmation for user {user.id}: {sid}")

    return jsonify({"message": "Notification preferences updated successfully"}), 200


@user_bp.route('/sms_enroll', methods=['POST'])
def sms_enroll():
    """
    Initiate SMS enrollment for a user.

    Expects a JSON payload containing:
        - discord_id: The user's discord ID.
        - phone: The user's phone number.

    The function updates the player's phone number and triggers the sending
    of a confirmation SMS containing a verification code.

    Returns:
        JSON response indicating success or error.
    """
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    phone = data.get("phone")
    if not discord_id or not phone:
        return jsonify({"error": "Missing required fields"}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    player.phone = phone
    success, msg_info = send_confirmation_sms(user)
    if success:
        session_db.commit()
        return jsonify({"message": "SMS enrollment initiated. Please check your phone for a confirmation code."}), 200
    else:
        return jsonify({"error": msg_info}), 400


@user_bp.route('/sms_confirm', methods=['POST'])
def sms_confirm():
    """
    Confirm SMS enrollment using a verification code.

    Expects a JSON payload containing:
        - discord_id: The user's discord ID.
        - code: The confirmation code received via SMS.

    If the code is verified, marks the player's phone as verified and enables SMS notifications.

    Returns:
        JSON response confirming the SMS enrollment or an error message.
    """
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    code = data.get("code")
    if not discord_id or not code:
        return jsonify({"error": "Missing required fields"}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    if verify_sms_confirmation(user, code):
        player.is_phone_verified = True
        session_db.commit()
        return jsonify({"message": "SMS enrollment confirmed and notifications enabled."}), 200
    else:
        return jsonify({"error": "Invalid confirmation code."}), 400


@user_bp.route('/team_lookup', methods=['GET'])
def team_lookup():
    """
    Lookup a team using a case-insensitive partial match on the team's name.

    Query Parameters:
        name (str): The partial team name to search for.

    Returns:
        JSON response containing the team's id, name, and a list of current players
        (each with their id, name, and discord_id), or an error message.
    """
    team_name_query = request.args.get("name")
    if not team_name_query:
        return jsonify({"error": "Missing name parameter"}), 400

    session_db = g.db_session
    # Find the team using a case-insensitive partial match.
    team = session_db.query(Team).filter(Team.name.ilike(f"%{team_name_query}%")).first()
    if not team:
        return jsonify({"error": "Team not found"}), 404

    # Retrieve players associated with the team who are marked as current.
    # NOTE: Uses a join on the association table since Player no longer has a direct "team_id" column.
    players = (
        session_db.query(Player)
        .join(player_teams)
        .filter(
            player_teams.c.team_id == team.id,
            Player.is_current_player == True
        )
        .all()
    )

    players_list = [{
        "id": player.id,
        "name": player.name,
        "discord_id": player.discord_id,
        "is_current_player": player.is_current_player
    } for player in players]

    return jsonify({
        "team": {
            "id": team.id,
            "name": team.name
        },
        "players": players_list
    }), 200

@user_bp.route('/player/by_discord/<discord_id>', methods=['GET'])
def get_player_by_discord(discord_id: str):
    try:
        logger.info(f"Looking up player with discord_id: {discord_id}")
        player = g.db_session.query(Player).filter_by(discord_id=discord_id).first()
        if not player:
            logger.info(f"No player found for discord_id: {discord_id}")
            return jsonify({"exists": False}), 404

        logger.info(f"Found player: {player.name} (ID: {player.id}). Calculating expected roles...")
        import asyncio
        expected_roles = asyncio.run(get_expected_roles(g.db_session, player))
        logger.info(f"Expected roles for player {player.name}: {expected_roles}")
        return jsonify({
            "exists": True,
            "player_name": player.name,
            "expected_roles": expected_roles
        }), 200

    except Exception as e:
        logger.exception(f"Error in get_player_by_discord for discord_id: {discord_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500