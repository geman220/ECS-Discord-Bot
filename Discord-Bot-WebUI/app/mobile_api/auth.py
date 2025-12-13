# app/api/auth.py

"""
Authentication API Endpoints

Handles user authentication including:
- Email/password login
- Discord OAuth flow
- 2FA verification
- User profile retrieval
"""

import logging
from urllib.parse import quote

from flask import jsonify, request, session, current_app
from flask_jwt_extended import jwt_required, create_access_token, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Season, player_teams
from app.app_api_helpers import (
    generate_pkce_codes,
    exchange_discord_code,
    get_discord_user_data,
    process_discord_user,
    build_player_response,
    get_player_response_data,
    get_player_stats,
)
from app.etag_utils import make_etag_response, CACHE_DURATIONS

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/get_discord_auth_url', methods=['GET'])
def get_discord_auth_url():
    """
    Generate and return a Discord OAuth2 authorization URL for mobile app.
    Uses the combined login+authorize URL pattern that works reliably.

    Optional query parameters:
        redirect_uri: The URI to redirect to after authorization
        force_consent: If true, will add force_verify=true to ensure Discord shows auth page

    Returns:
        JSON with Discord authorization URL, PKCE code verifier, and state parameter
    """
    from app.auth_helpers import generate_oauth_state

    # Default to mobile app scheme if no redirect_uri provided
    default_redirect = 'ecs-fc-scheme://auth'
    redirect_uri = request.args.get('redirect_uri', default_redirect)

    # Generate PKCE codes for enhanced security
    code_verifier, code_challenge = generate_pkce_codes()

    # Generate state parameter for CSRF protection
    state_value = generate_oauth_state()

    # Store both code verifier and state in session for later verification
    session['code_verifier'] = code_verifier
    session['oauth_state'] = state_value

    # Discord client ID
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']

    # Prepare parameters for the combined login+authorize URL
    quoted_redirect_uri = quote(redirect_uri)
    quoted_scope = quote('identify email guilds')

    # Use the direct login+authorize URL pattern that works more reliably
    discord_login_url = (
        f"https://discord.com/login?redirect_to=%2Foauth2%2Fauthorize"
        f"%3Fclient_id%3D{discord_client_id}"
        f"%26redirect_uri%3D{quoted_redirect_uri}"
        f"%26response_type%3Dcode"
        f"%26scope%3D{quoted_scope}"
        f"%26code_challenge%3D{code_challenge}"
        f"%26code_challenge_method%3DS256"
        f"%26state%3D{state_value}"
    )

    logger.debug(f"Generated combined login+auth URL for mobile app: {discord_login_url}")

    return jsonify({
        'auth_url': discord_login_url,
        'code_verifier': code_verifier,
        'state': state_value
    }), 200


@mobile_api_v2.route('/discord_callback', methods=['POST'])
def discord_callback():
    """
    Handle Discord OAuth callback for mobile app authentication.

    Expected JSON parameters:
        code: The authorization code from Discord
        redirect_uri: The redirect URI used in the auth request
        code_verifier: The PKCE code verifier
        state: The state parameter from the original auth request

    Returns:
        JSON with JWT access token on success
    """
    try:
        data = request.json
        if not data:
            return jsonify({"msg": "Missing request data"}), 400

        code = data.get('code')
        if 'redirect_uri' not in data:
            return jsonify({"msg": "Missing redirect_uri parameter from original authorization request"}), 400

        redirect_uri = data.get('redirect_uri')

        # For mobile apps, accept the state directly from the client
        received_state = data.get('state')
        if not received_state:
            return jsonify({"msg": "Missing state parameter from original authorization request"}), 400

        # The code_verifier MUST be the same one used in the original authorization request
        code_verifier = data.get('code_verifier')
        if not code_verifier:
            return jsonify({"msg": "Missing code_verifier parameter from original authorization request"}), 400

        if not code:
            return jsonify({"msg": "Missing authorization code"}), 400

        logger.info(
            f"Discord callback data - code length: {len(code) if code else 0}, "
            f"redirect_uri: {redirect_uri}, using mobile flow"
        )

        # Exchange the authorization code for an access token
        token_data = exchange_discord_code(code, redirect_uri, code_verifier)

        if not token_data or 'access_token' not in token_data:
            return jsonify({"msg": "Failed to exchange authorization code"}), 400

        # Get Discord user data with the access token
        discord_user = get_discord_user_data(token_data['access_token'])

        if not discord_user or 'id' not in discord_user:
            return jsonify({"msg": "Failed to get Discord user data"}), 400

        # Find or create user based on Discord data
        with managed_session() as session_db:
            user = process_discord_user(session_db, discord_user)

            if not user:
                return jsonify({"msg": "Failed to process Discord user"}), 500

            # Create JWT access token for the user
            access_token = create_access_token(identity=str(user.id))

            return jsonify({
                "access_token": access_token,
                "user_id": user.id,
                "username": user.username,
                "discord_id": discord_user['id']
            }), 200

    except Exception as e:
        logger.exception(f"Error in Discord callback: {e}")
        return jsonify({"msg": f"Error processing Discord login: {str(e)}"}), 500


@mobile_api_v2.route('/login', methods=['POST'])
def login():
    """
    Authenticate a user with email and password.

    Expected JSON parameters:
        email: User's email address
        password: User's password

    Returns:
        JSON with JWT access token on success, or 2FA prompt if enabled
    """
    email = request.json.get('email')
    password = request.json.get('password')

    if not email or not password:
        return jsonify({"msg": "Missing username or password"}), 400

    with managed_session() as session_db:
        user = session_db.query(User).filter_by(email=email.lower()).first()
        if not user or not user.check_password(password):
            return jsonify({"msg": "Bad username or password"}), 401

        if not user.is_approved:
            return jsonify({"msg": "Account not approved"}), 403

        # If 2FA is enabled, prompt for 2FA verification
        if user.is_2fa_enabled:
            return jsonify({"msg": "2FA required", "user_id": user.id}), 200

        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token), 200


@mobile_api_v2.route('/verify_2fa', methods=['POST'])
def verify_2fa():
    """
    Verify a user's 2FA token and return a JWT access token if valid.

    Expected JSON parameters:
        user_id: The user's ID
        token: The 2FA token from authenticator app

    Returns:
        JSON with JWT access token on success
    """
    user_id = request.json.get('user_id')
    token = request.json.get('token')
    logger.debug(f"Received user_id: {user_id}, token: {token}")

    if not user_id or not token:
        return jsonify({"msg": "Missing user_id or token"}), 400

    with managed_session() as session_db:
        user = session_db.query(User).get(user_id)
        if not user or not user.verify_totp(token):
            return jsonify({"msg": "Invalid 2FA token"}), 401

        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token), 200


@mobile_api_v2.route('/user_profile', methods=['GET'])
@jwt_required()
def get_user_profile():
    """
    Retrieve the profile of the currently authenticated user,
    including associated player data and optional stats.

    Query parameters:
        include_stats: If 'true', include player statistics

    Returns:
        JSON with user profile data
    """
    current_user_id = int(get_jwt_identity())
    logger.info(f"[MOBILE_API] get_user_profile called for user_id: {current_user_id}")
    logger.debug(f"[MOBILE_API] Request args: {dict(request.args)}")

    with managed_session() as session_db:
        # Query user with eager loading for roles to prevent N+1 queries
        user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()
        if not user:
            logger.error(f"[MOBILE_API] User not found for ID: {current_user_id}")
            return jsonify({"error": "User not found"}), 404

        logger.debug(f"[MOBILE_API] Found user: {user.username} (ID: {user.id})")
        # Query player with eager loading for related data
        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).filter_by(user_id=current_user_id).first()
        logger.debug(f"[MOBILE_API] Player found: {player.name if player else 'None'} (ID: {player.id if player else 'None'})")
        base_url = request.host_url.rstrip('/')

        response_data = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_approved": user.is_approved,
            "roles": [role.name for role in user.roles],
            "has_completed_onboarding": user.has_completed_onboarding,
            "has_completed_tour": user.has_completed_tour,
            "has_skipped_profile_creation": user.has_skipped_profile_creation,
            "league_id": user.league_id,
            "is_2fa_enabled": user.is_2fa_enabled,
            "email_notifications": user.email_notifications,
            "sms_notifications": user.sms_notifications,
            "discord_notifications": user.discord_notifications,
            "profile_visibility": user.profile_visibility,
            "last_login": user.last_login.isoformat() if user.last_login else None,
        }

        # Determine user capabilities for client-side enforcement
        user_roles = [role.name for role in user.roles]
        is_admin = any(r in ['Global Admin', 'Pub League Admin'] for r in user_roles)
        is_coach_role = 'Pub League Coach' in user_roles
        is_ref_role = 'Pub League Ref' in user_roles

        # Get team IDs where user is a coach (from player_teams table)
        coach_team_ids = []
        is_coach_on_team = False
        if player:
            coach_teams = session_db.execute(
                player_teams.select().where(
                    player_teams.c.player_id == player.id,
                    player_teams.c.is_coach == True
                )
            ).fetchall()
            coach_team_ids = [ct.team_id for ct in coach_teams]
            is_coach_on_team = len(coach_team_ids) > 0

        # Build capabilities object
        capabilities = {
            "can_draft": is_admin or is_coach_role or is_coach_on_team,
            "can_order": is_admin or is_coach_role or is_coach_on_team,
            "can_report_match": is_admin or is_coach_on_team,
            "can_assign_ref": 'Pub League Admin' in user_roles or 'Global Admin' in user_roles,
            "coach_team_ids": coach_team_ids,
            "is_ref": is_ref_role or (player.is_ref if player else False),
            "is_admin": is_admin,
            "is_coach": is_coach_role or is_coach_on_team
        }
        response_data["capabilities"] = capabilities

        if player:
            profile_picture_url = player.profile_picture_url
            if profile_picture_url:
                full_profile_picture_url = (
                    profile_picture_url if profile_picture_url.startswith('http')
                    else f"{base_url}{profile_picture_url}"
                )
            else:
                full_profile_picture_url = f"{base_url}/static/img/default_player.png"

            player_data = {
                "player_id": player.id,
                "player_name": player.name,
                "phone": player.phone,
                "is_phone_verified": player.is_phone_verified,
                "jersey_size": player.jersey_size,
                "jersey_number": player.jersey_number,
                "is_coach": player.is_coach,
                "is_ref": player.is_ref,
                "discord_id": player.discord_id,
                "pronouns": player.pronouns,
                "favorite_position": player.favorite_position,
                "other_positions": player.other_positions,
                "positions_not_to_play": player.positions_not_to_play,
                "expected_weeks_available": player.expected_weeks_available,
                "unavailable_dates": player.unavailable_dates,
                "willing_to_referee": player.willing_to_referee,
                "frequency_play_goal": player.frequency_play_goal,
                "additional_info": player.additional_info,
                "is_current_player": player.is_current_player,
                "profile_picture_url": full_profile_picture_url,
                "team_id": player.primary_team_id,
                "team_name": player.primary_team.name if player.primary_team else None,
                "league_name": player.league.name if player.league else None,
            }
            response_data.update(player_data)

            include_stats = request.args.get('include_stats', 'false').lower() == 'true'
            if include_stats:
                logger.debug(f"[MOBILE_API] Including stats for player {player.name}")
                current_season = session_db.query(Season).filter_by(is_current=True).first()
                logger.debug(f"[MOBILE_API] Current season: {current_season.name if current_season else 'None'}")
                response_data.update(get_player_stats(player, current_season, session=session_db))

        logger.info(f"[MOBILE_API] get_user_profile successful for user {user.username} - returning {len(response_data)} fields")

        # Return with ETag support - user profiles can change more frequently
        return make_etag_response(response_data, 'user_profile', CACHE_DURATIONS['user_profile'])
