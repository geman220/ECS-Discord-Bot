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
from app.core.session_manager import managed_session
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
    logger.info(f"🔵 [USER_API] player_lookup called with name: '{name_query}'")
    
    if not name_query:
        logger.warning(f"🔴 [USER_API] player_lookup missing name parameter")
        return jsonify({"error": "Missing name parameter"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [USER_API] Searching for player with name containing: '{name_query}'")
        # Perform a case-insensitive search using a partial match.
        player = session_db.query(Player).filter(Player.name.ilike(f"%{name_query}%")).first()
        if not player:
            logger.info(f"🟡 [USER_API] No player found for name query: '{name_query}'")
            return jsonify({"error": "Player not found"}), 404

        logger.info(f"🟢 [USER_API] Found player: {player.name} (ID: {player.id}, Discord: {player.discord_id})")
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
    logger.info(f"🔵 [USER_API] get_notifications called for discord_id: {discord_id}")
    
    if not discord_id:
        logger.warning(f"🔴 [USER_API] get_notifications missing discord_id parameter")
        return jsonify({"error": "Missing discord_id parameter"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [USER_API] Looking up player with discord_id: {discord_id}")
        player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
        if not player:
            logger.warning(f"🔴 [USER_API] Player not found for discord_id: {discord_id}")
            return jsonify({"error": "Player not found"}), 404

        logger.debug(f"🔵 [USER_API] Found player {player.name}, looking up user {player.user_id}")
        user = session_db.query(User).filter_by(id=player.user_id).first()
        if not user:
            logger.error(f"🔴 [USER_API] Associated user not found for player {player.name} (user_id: {player.user_id})")
            return jsonify({"error": "Associated user not found"}), 404

        notifications = {
            "discord": user.discord_notifications,
            "email": user.email_notifications,
            "sms": user.sms_notifications
        }
        sms_enrolled = bool(player.phone and user.sms_confirmation_code is None)
        phone_verified = bool(player.phone and player.is_phone_verified)
        
        logger.info(f"🟢 [USER_API] Retrieved notifications for {player.name}: discord={notifications['discord']}, email={notifications['email']}, sms={notifications['sms']}, enrolled={sms_enrolled}, verified={phone_verified}")
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
    data = request.json
    discord_id = data.get("discord_id") if data else None
    notifications = data.get("notifications") if data else None
    
    logger.info(f"🔵 [USER_API] update_notifications called for discord_id: {discord_id} with settings: {notifications}")

    if not discord_id or notifications is None:
        logger.warning(f"🔴 [USER_API] update_notifications missing required fields - discord_id: {discord_id}, notifications: {notifications}")
        return jsonify({"error": "Missing required fields"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [USER_API] Looking up player for notification update: {discord_id}")
        player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
        if not player:
            logger.warning(f"🔴 [USER_API] Player not found for notification update: {discord_id}")
            return jsonify({"error": "Player not found"}), 404

        user = session_db.query(User).filter_by(id=player.user_id).first()
        if not user:
            logger.error(f"🔴 [USER_API] Associated user not found for notification update - player: {player.name}")
            return jsonify({"error": "Associated user not found"}), 404

        # Save previous SMS state to detect changes.
        previous_sms = user.sms_notifications
        logger.debug(f"🔵 [USER_API] Previous notification state for {player.name}: discord={user.discord_notifications}, email={user.email_notifications}, sms={previous_sms}")

        user.discord_notifications = notifications.get("discord", False)
        user.email_notifications = notifications.get("email", False)
        user.sms_notifications = notifications.get("sms", False)

        if not notifications.get("sms", False) and previous_sms:
            # User has disabled SMS notifications.
            logger.info(f"🟡 [USER_API] Disabling SMS for {player.name} - marking phone as unverified")
            player.is_phone_verified = False
            player.sms_opt_out_timestamp = datetime.utcnow()
        
        session_db.commit()
        logger.info(f"🟢 [USER_API] Notification preferences updated for {player.name}: discord={user.discord_notifications}, email={user.email_notifications}, sms={user.sms_notifications}")

        # Notify the user via SMS about changes in SMS notification status.
        if notifications.get("sms", False) and not previous_sms:
            logger.debug(f"🔵 [USER_API] Sending SMS enable confirmation to {player.phone}")
            success, sid = send_sms(player.phone, "SMS notifications enabled for ECS FC. Reply END to unsubscribe.")
            if not success:
                logger.error(f"🔴 [USER_API] Failed to send SMS confirmation for user {user.id}: {sid}")
        elif not notifications.get("sms", False) and previous_sms:
            logger.debug(f"🔵 [USER_API] Sending SMS disable confirmation to {player.phone}")
            success, sid = send_sms(player.phone, "SMS notifications disabled for ECS FC. Reply START to re-subscribe.")
            if not success:
                logger.error(f"🔴 [USER_API] Failed to send SMS disable confirmation for user {user.id}: {sid}")

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
    data = request.json
    discord_id = data.get("discord_id") if data else None
    phone = data.get("phone") if data else None
    
    logger.info(f"🔵 [USER_API] sms_enroll called for discord_id: {discord_id} with phone: {phone}")
    
    if not discord_id or not phone:
        logger.warning(f"🔴 [USER_API] sms_enroll missing required fields - discord_id: {discord_id}, phone: {phone}")
        return jsonify({"error": "Missing required fields"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [USER_API] Looking up player for SMS enrollment: {discord_id}")
        player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
        if not player:
            logger.warning(f"🔴 [USER_API] Player not found for SMS enrollment: {discord_id}")
            return jsonify({"error": "Player not found"}), 404

        user = session_db.query(User).filter_by(id=player.user_id).first()
        if not user:
            logger.error(f"🔴 [USER_API] Associated user not found for SMS enrollment - player: {player.name}")
            return jsonify({"error": "Associated user not found"}), 404

        logger.debug(f"🔵 [USER_API] Updating phone number for {player.name}: {phone}")
        player.phone = phone
        
        logger.debug(f"🔵 [USER_API] Sending confirmation SMS to {phone}")
        success, msg_info = send_confirmation_sms(user)
        if success:
            session_db.commit()
            logger.info(f"🟢 [USER_API] SMS enrollment initiated successfully for {player.name} at {phone}")
            return jsonify({"message": "SMS enrollment initiated. Please check your phone for a confirmation code."}), 200
        else:
            logger.error(f"🔴 [USER_API] Failed to send confirmation SMS for {player.name}: {msg_info}")
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
    data = request.json
    discord_id = data.get("discord_id") if data else None
    code = data.get("code") if data else None
    
    logger.info(f"🔵 [USER_API] sms_confirm called for discord_id: {discord_id} with code: {'***' if code else 'None'}")
    
    if not discord_id or not code:
        logger.warning(f"🔴 [USER_API] sms_confirm missing required fields - discord_id: {discord_id}, code: {'provided' if code else 'missing'}")
        return jsonify({"error": "Missing required fields"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [USER_API] Looking up player for SMS confirmation: {discord_id}")
        player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
        if not player:
            logger.warning(f"🔴 [USER_API] Player not found for SMS confirmation: {discord_id}")
            return jsonify({"error": "Player not found"}), 404

        user = session_db.query(User).filter_by(id=player.user_id).first()
        if not user:
            logger.error(f"🔴 [USER_API] Associated user not found for SMS confirmation - player: {player.name}")
            return jsonify({"error": "Associated user not found"}), 404

        logger.debug(f"🔵 [USER_API] Verifying SMS confirmation code for {player.name}")
        if verify_sms_confirmation(user, code):
            player.is_phone_verified = True
            session_db.commit()
            logger.info(f"🟢 [USER_API] SMS confirmation successful for {player.name} - phone verified and notifications enabled")
            return jsonify({"message": "SMS enrollment confirmed and notifications enabled."}), 200
        else:
            logger.warning(f"🟡 [USER_API] Invalid SMS confirmation code for {player.name}")
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
    logger.info(f"🔵 [USER_API] team_lookup called with name: '{team_name_query}'")
    
    if not team_name_query:
        logger.warning(f"🔴 [USER_API] team_lookup missing name parameter")
        return jsonify({"error": "Missing name parameter"}), 400

    with managed_session() as session_db:
        logger.debug(f"🔵 [USER_API] Searching for team with name containing: '{team_name_query}'")
        # Find the team using a case-insensitive partial match.
        team = session_db.query(Team).filter(Team.name.ilike(f"%{team_name_query}%")).first()
        if not team:
            logger.info(f"🟡 [USER_API] No team found for name query: '{team_name_query}'")
            return jsonify({"error": "Team not found"}), 404

        logger.debug(f"🔵 [USER_API] Found team {team.name} (ID: {team.id}), retrieving current players")
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

        logger.info(f"🟢 [USER_API] Team lookup successful for '{team.name}' - returning {len(players_list)} current players")
        return jsonify({
            "team": {
                "id": team.id,
                "name": team.name
            },
            "players": players_list
        }), 200

@user_bp.route('/player/by_discord/<discord_id>', methods=['GET'])
def get_player_by_discord(discord_id: str):
    logger.info(f"🔵 [USER_API] get_player_by_discord called for discord_id: {discord_id}")
    
    try:
        with managed_session() as session_db:
            logger.debug(f"🔵 [USER_API] Looking up player with discord_id: {discord_id}")
            player = session_db.query(Player).filter_by(discord_id=discord_id).first()
            if not player:
                logger.info(f"🟡 [USER_API] No player found for discord_id: {discord_id}")
                return jsonify({"exists": False}), 404

            logger.debug(f"🔵 [USER_API] Found player: {player.name} (ID: {player.id}). Calculating expected roles...")
            import asyncio
            expected_roles = asyncio.run(get_expected_roles(session_db, player))
            logger.info(f"🟢 [USER_API] Player lookup successful for {player.name} - expected roles: {expected_roles}")
            return jsonify({
                "exists": True,
                "player_name": player.name,
                "expected_roles": expected_roles
            }), 200

    except Exception as e:
        logger.exception(f"🔴 [USER_API] Error in get_player_by_discord for discord_id: {discord_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


# I-Spy API endpoints for Discord bot
@user_bp.route('/ispy/categories', methods=['GET'])
def ispy_categories():
    """Get all available I-Spy venue categories for Discord bot."""
    try:
        from app.ispy_helpers import get_all_categories
        categories = get_all_categories()
        return jsonify({'categories': categories}), 200
        
    except Exception as e:
        logger.error(f"Error getting I-Spy categories: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/submit', methods=['POST'])
def ispy_submit_shot():
    """Submit a new I-Spy shot from Discord bot."""
    try:
        from app.ispy_helpers import (
            validate_shot_submission, create_shot_with_targets
        )
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        required_fields = ['targets', 'category', 'location', 'image_url']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Get Discord user ID from request headers
        author_discord_id = request.headers.get('X-Discord-User')
        if not author_discord_id:
            return jsonify({'error': 'Missing X-Discord-User header'}), 400
        
        # For Discord images, use URL as hash (simplified approach)
        image_data = data['image_url'].encode('utf-8')
        
        # Validate submission
        validation = validate_shot_submission(
            author_discord_id=author_discord_id,
            target_discord_ids=data['targets'],
            category_key=data['category'],
            location=data['location'],
            image_data=image_data
        )
        
        if not validation['valid']:
            return jsonify({'errors': validation['errors']}), 400
        
        # Get active season
        from app.ispy_helpers import get_active_season
        season = get_active_season()
        if not season:
            return jsonify({'error': 'No active I-Spy season'}), 404
        
        # Create the shot
        shot = create_shot_with_targets(
            author_discord_id=author_discord_id,
            target_discord_ids=data['targets'],
            category_id=validation['category_id'],
            location=data['location'],
            image_url=data['image_url'],
            image_hash=validation.get('image_hash'),
            season_id=season.id
        )
        
        return jsonify({
            'success': True,
            'shot_id': shot.id,
            'points_awarded': shot.total_points,
            'breakdown': {
                'base_points': shot.base_points,
                'bonus_points': shot.bonus_points,
                'streak_bonus': shot.streak_bonus
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error submitting I-Spy shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/leaderboard', methods=['GET'])
def ispy_leaderboard():
    """Get current season I-Spy leaderboard for Discord bot."""
    try:
        from app.ispy_helpers import get_active_season, get_leaderboard
        
        limit = int(request.args.get('limit', 10))
        limit = min(limit, 25)  # Cap at 25
        
        season = get_active_season()
        if not season:
            return jsonify({'error': 'No active I-Spy season'}), 404
        
        leaderboard = get_leaderboard(season.id, limit=limit)
        
        return jsonify({
            'season': {
                'id': season.id,
                'name': season.name
            },
            'leaderboard': leaderboard
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting I-Spy leaderboard: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/me', methods=['GET'])
def ispy_personal_stats():
    """Get personal I-Spy statistics for Discord bot user."""
    try:
        from app.ispy_helpers import get_active_season, get_user_personal_stats
        
        # Get Discord user ID from request headers
        discord_user_id = request.headers.get('X-Discord-User')
        if not discord_user_id:
            return jsonify({'error': 'Missing X-Discord-User header'}), 400
        
        season = get_active_season()
        if not season:
            return jsonify({'error': 'No active I-Spy season'}), 404
        
        stats = get_user_personal_stats(discord_user_id, season.id)
        
        return jsonify({
            'season': {
                'id': season.id,
                'name': season.name
            },
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting personal I-Spy stats: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/stats/category/<category_key>', methods=['GET'])
def ispy_category_stats(category_key):
    """Get leaderboard for a specific I-Spy category for Discord bot."""
    try:
        from app.ispy_helpers import get_active_season, get_category_leaderboard
        
        season = get_active_season()
        if not season:
            return jsonify({'error': 'No active I-Spy season'}), 404
        
        leaderboard = get_category_leaderboard(season.id, category_key, limit=10)
        
        if not leaderboard:
            return jsonify({'error': f'Category {category_key} not found or no data'}), 404
        
        return jsonify({
            'season': {
                'id': season.id,
                'name': season.name
            },
            'leaderboard': leaderboard
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting category stats: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# Admin I-Spy endpoints for Discord bot
@user_bp.route('/ispy/admin/disallow/<int:shot_id>', methods=['POST'])
def ispy_admin_disallow(shot_id):
    """Disallow an I-Spy shot (admin only) for Discord bot."""
    try:
        from app.ispy_helpers import disallow_shot
        
        # Get Discord user ID from request headers
        moderator_discord_id = request.headers.get('X-Discord-User')
        if not moderator_discord_id:
            return jsonify({'error': 'Missing X-Discord-User header'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        reason = data.get('reason', 'No reason provided')
        extra_penalty = data.get('extra_penalty', 0)
        
        result = disallow_shot(
            shot_id=shot_id,
            moderator_discord_id=moderator_discord_id,
            reason=reason,
            extra_penalty=extra_penalty
        )
        
        if result:
            return jsonify({
                'success': True,
                'shot_points': result['shot_points'],
                'extra_penalty': result['extra_penalty'],
                'total_penalty': result['total_penalty']
            }), 200
        else:
            return jsonify({'error': 'Shot not found or already disallowed'}), 404
        
    except Exception as e:
        logger.error(f"Error disallowing shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/admin/recategorize/<int:shot_id>', methods=['POST'])
def ispy_admin_recategorize(shot_id):
    """Recategorize an I-Spy shot (admin only) for Discord bot."""
    try:
        from app.ispy_helpers import recategorize_shot
        
        # Get Discord user ID from request headers
        moderator_discord_id = request.headers.get('X-Discord-User')
        if not moderator_discord_id:
            return jsonify({'error': 'Missing X-Discord-User header'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        new_category = data.get('new_category')
        if not new_category:
            return jsonify({'error': 'Missing new_category field'}), 400
        
        success = recategorize_shot(
            shot_id=shot_id,
            new_category_key=new_category,
            moderator_discord_id=moderator_discord_id
        )
        
        if success:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Shot not found or invalid category'}), 400
        
    except Exception as e:
        logger.error(f"Error recategorizing shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/admin/jail', methods=['POST'])
def ispy_admin_jail():
    """Jail an I-Spy user (admin only) for Discord bot."""
    try:
        from app.ispy_helpers import jail_user
        
        # Get Discord user ID from request headers
        moderator_discord_id = request.headers.get('X-Discord-User')
        if not moderator_discord_id:
            return jsonify({'error': 'Missing X-Discord-User header'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        required_fields = ['discord_id', 'hours']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        success = jail_user(
            discord_id=data['discord_id'],
            hours=data['hours'],
            moderator_discord_id=moderator_discord_id,
            reason=data.get('reason', 'No reason provided')
        )
        
        if success:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Failed to jail user'}), 500
        
    except Exception as e:
        logger.error(f"Error jailing user: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/cooldowns/<discord_id>', methods=['GET'])
def ispy_get_cooldowns(discord_id):
    """Get active cooldowns for a Discord user."""
    try:
        from app.ispy_helpers import get_user_cooldowns
        
        cooldowns = get_user_cooldowns(discord_id)
        
        return jsonify({
            'discord_id': discord_id,
            'cooldowns': cooldowns
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting user cooldowns: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@user_bp.route('/ispy/admin/reset-cooldowns', methods=['POST'])
def ispy_admin_reset_cooldowns():
    """Reset all cooldowns for a user (admin only)."""
    try:
        from app.ispy_helpers import reset_user_cooldowns
        
        # Get Discord user ID from request headers
        moderator_discord_id = request.headers.get('X-Discord-User')
        if not moderator_discord_id:
            return jsonify({'error': 'Missing X-Discord-User header'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        target_discord_id = data.get('target_discord_id')
        reason = data.get('reason', 'No reason provided')
        
        if not target_discord_id:
            return jsonify({'error': 'Missing target_discord_id field'}), 400
        
        success = reset_user_cooldowns(
            target_discord_id=target_discord_id,
            moderator_discord_id=moderator_discord_id,
            reason=reason
        )
        
        if success:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Failed to reset cooldowns'}), 500
        
    except Exception as e:
        logger.error(f"Error resetting cooldowns: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500