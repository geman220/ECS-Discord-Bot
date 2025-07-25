# app/app_api.py

"""
API Endpoints for Mobile Clients

This module provides a collection of endpoints for user authentication,
profile management, team and match data retrieval, availability updates,
Discord authentication, and more.

All endpoints are protected by JWT where applicable.
"""

# Standard library imports
from urllib.parse import urlencode
import logging
import ipaddress

# Third-party imports
import requests
from sqlalchemy import func, or_

# Flask and extensions
from flask import (
    Blueprint, jsonify, request, current_app, session, abort, g
)
from flask_jwt_extended import jwt_required, create_access_token, get_jwt_identity


from datetime import datetime

# Local application imports
from app import csrf
from app.models import (
    User, Player, Team, Match, Season, League, player_teams, Standings,
    PlayerSeasonStats, Availability
)
from app.decorators import (
    jwt_role_required
)
from app.core.session_manager import managed_session
import signal
from app.app_api_helpers import (
    build_player_response, get_player_response_data, exchange_discord_code,
    get_discord_user_data, process_discord_user, build_match_response,
    get_team_players_availability, get_match_events, get_player_availability,
    build_matches_query, process_matches_data, get_player_stats, generate_pkce_codes,
    update_match_details, add_match_events, update_player_availability,
    notify_availability_update, update_player_match_availability, get_team_upcoming_matches
)
from app.etag_utils import make_etag_response, CACHE_DURATIONS

logger = logging.getLogger(__name__)
mobile_api = Blueprint('mobile_api', __name__)
csrf.exempt(mobile_api)


@mobile_api.before_request
def limit_remote_addr():
    """
    Restrict API access to allowed hosts and mobile devices.
    
    This function allows access from:
    1. Mobile devices with valid API key (from any IP)
    2. Specific development hosts
    3. IP ranges using CIDR notation (from config)
    """
    # First, check for API key in headers (for mobile app)
    # This allows access from any IP if the API key is valid
    api_key = request.headers.get('X-API-Key')
    if api_key and api_key == current_app.config.get('MOBILE_API_KEY', 'ecs-soccer-mobile-key'):
        return
    
    # Development hosts that are always allowed
    allowed_dev_hosts = [
        '127.0.0.1:5000', 
        'localhost:5000', 
        'webui:5000', 
        '192.168.1.112:5000',
        '10.0.2.2:5000',      # Android emulator default
    ]
    
    # Check if host is in the allowed development hosts list
    if request.host in allowed_dev_hosts:
        return
    
    # Get allowed networks from configuration
    allowed_networks_str = current_app.config.get('MOBILE_APP_ALLOWED_NETWORKS', '')
    allowed_networks = [net.strip() for net in allowed_networks_str.split(',') if net.strip()]
    
    # Check IP ranges (CIDR notation)
    if allowed_networks:
        client_ip = request.host.split(':')[0]  # Remove port if present
        for network_cidr in allowed_networks:
            try:
                network = ipaddress.ip_network(network_cidr)
                if ipaddress.ip_address(client_ip) in network:
                    return
            except (ValueError, ipaddress.AddressValueError):
                # Skip invalid IP addresses or networks
                logger.warning(f"Invalid network CIDR in config: {network_cidr}")
                continue
    
    # If we get here, access is denied
    logger.warning(f"API access denied for host: {request.host}")
    return "Access Denied", 403


@mobile_api.route('/test-connection', endpoint='test_connection', methods=['GET'])
def test_connection():
    """
    Simple endpoint to test mobile app connection to the API.
    Returns basic API status information.
    """
    return jsonify({
        "status": "success",
        "message": "Connection to ECS Soccer API successful",
        "api_version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "server": "Flask API"
    }), 200


@mobile_api.route('/ping', endpoint='ping', methods=['GET'])
def ping():
    """
    Simple ping endpoint for connectivity testing.
    
    Returns:
        JSON response with status and timestamp
    """
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'server': 'ECS Soccer API',
        'version': current_app.config.get('VERSION', '1.0')
    }), 200


@mobile_api.route('/get_discord_auth_url', endpoint='get_discord_auth_url', methods=['GET'])
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
    from urllib.parse import quote
    
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
    
    # Log the complete URL for debugging
    logger.debug(f"Generated combined login+auth URL for mobile app: {discord_login_url}")
    
    # Return the URL, code verifier, and state to the mobile app
    return jsonify({
        'auth_url': discord_login_url,
        'code_verifier': code_verifier,
        'state': state_value
    }), 200


@mobile_api.route('/discord_callback', endpoint='discord_callback', methods=['POST'])
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
        # Get parameters from request body
        data = request.json
        if not data:
            return jsonify({"msg": "Missing request data"}), 400
            
        code = data.get('code')
        # Mobile app should explicitly pass the same redirect URI used during authorization
        if 'redirect_uri' not in data:
            return jsonify({"msg": "Missing redirect_uri parameter from original authorization request"}), 400
            
        redirect_uri = data.get('redirect_uri')
        
        # For mobile apps, we accept the state directly from the client
        # This is necessary because mobile apps often lose session context between requests
        received_state = data.get('state')
        
        if not received_state:
            return jsonify({"msg": "Missing state parameter from original authorization request"}), 400
        
        # For web-based flows (non-mobile), we would validate against the session
        # But for mobile clients, we skip this validation since they need to store 
        # and return the state themselves
        
        # The code_verifier MUST be the same one used in the original authorization request
        code_verifier = data.get('code_verifier')
        if not code_verifier:
            return jsonify({"msg": "Missing code_verifier parameter from original authorization request"}), 400
            
        if not code:
            return jsonify({"msg": "Missing authorization code"}), 400
            
        # Log the data we're using for the OAuth exchange
        logger.info(f"Discord callback data - code length: {len(code) if code else 0}, redirect_uri: {redirect_uri}, using mobile flow")
        
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
            access_token = create_access_token(identity=user.id)
            
            # Return the token to the mobile app
            return jsonify({
                "access_token": access_token,
                "user_id": user.id,
                "username": user.username,
                "discord_id": discord_user['id']
            }), 200
        
    except Exception as e:
        logger.exception(f"Error in Discord callback: {e}")
        return jsonify({"msg": f"Error processing Discord login: {str(e)}"}), 500


@mobile_api.route('/login', endpoint='login', methods=['POST'])
def login():
    """
    Authenticate a user and return a JWT access token.
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

        access_token = create_access_token(identity=user.id)
        return jsonify(access_token=access_token), 200


@mobile_api.route('/verify_2fa', endpoint='verify_2fa', methods=['POST'])
def verify_2fa():
    """
    Verify a user's 2FA token and return a JWT access token if valid.
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

        access_token = create_access_token(identity=user.id)
        return jsonify(access_token=access_token), 200


@mobile_api.route('/user_profile', endpoint='get_user_profile', methods=['GET'])
@jwt_required()
def get_user_profile():
    """
    Retrieve the profile of the currently authenticated user,
    including associated player data and optional stats.
    """
    current_user_id = get_jwt_identity()
    logger.info(f"🔵 [MOBILE_API] get_user_profile called for user_id: {current_user_id}")
    logger.debug(f"🔵 [MOBILE_API] Request args: {dict(request.args)}")
    
    with managed_session() as session_db:
        # Query user with eager loading for roles to prevent N+1 queries
        from sqlalchemy.orm import joinedload
        user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()
        if not user:
            logger.error(f"🔴 [MOBILE_API] User not found for ID: {current_user_id}")
            return jsonify({"error": "User not found"}), 404

        logger.debug(f"🔵 [MOBILE_API] Found user: {user.username} (ID: {user.id})")
        # Query player with eager loading for related data
        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).filter_by(user_id=current_user_id).first()
        logger.debug(f"🔵 [MOBILE_API] Player found: {player.name if player else 'None'} (ID: {player.id if player else 'None'})")
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
                logger.debug(f"🔵 [MOBILE_API] Including stats for player {player.name}")
                current_season = session_db.query(Season).filter_by(is_current=True).first()
                logger.debug(f"🔵 [MOBILE_API] Current season: {current_season.name if current_season else 'None'}")
                response_data.update(get_player_stats(player, current_season, session=session_db))

        logger.info(f"🟢 [MOBILE_API] get_user_profile successful for user {user.username} - returning {len(response_data)} fields")
        
        # Return with ETag support - user profiles can change more frequently
        return make_etag_response(response_data, 'user_profile', CACHE_DURATIONS['user_profile'])


@mobile_api.route('/player/update', endpoint='update_player_profile', methods=['PUT'])
@jwt_required()
def update_player_profile():
    """
    Update the profile of the currently authenticated player.
    """
    with managed_session() as session_db:
        current_user_id = get_jwt_identity()
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        data = request.json
        allowed_fields = [
            'name', 'phone', 'jersey_size', 'jersey_number', 'pronouns',
            'favorite_position', 'other_positions', 'positions_not_to_play',
            'frequency_play_goal', 'expected_weeks_available', 'unavailable_dates',
            'willing_to_referee', 'additional_info'
        ]

        try:
            for field in allowed_fields:
                if field in data:
                    setattr(player, field, data[field])
            return jsonify({
                "msg": "Profile updated successfully",
                "player": player.to_dict()
            }), 200
        except Exception as e:
            logger.error(f"Error updating player profile: {str(e)}")
            return jsonify({"msg": f"Error updating profile: {str(e)}"}), 500


@mobile_api.route('/players/<int:player_id>', endpoint='get_player', methods=['GET'])
@jwt_required()
def get_player(player_id: int):
    """
    Retrieve details for a specific player, ensuring proper access
    based on user roles and ownership.
    """
    with managed_session() as session_db:
        current_user_id = get_jwt_identity()
        # Query user and player with eager loading to prevent N+1 queries
        from sqlalchemy.orm import joinedload, selectinload
        safe_current_user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()
        
        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league),
            selectinload(Player.teams)
        ).filter(Player.id == player_id).first()

        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Check viewing permissions: Admin/Coach or owner can view full profile.
        user_roles = [r.name for r in safe_current_user.roles]
        is_admin = any(r in ['Coach', 'Admin'] for r in user_roles)
        is_owner = current_user_id == player.user_id
        is_full_profile = is_admin or is_owner

        # Get include_stats parameter
        include_stats = request.args.get('include_stats', 'false').lower() == 'true'
        
        # Get the player profile data
        response_data = get_player_response_data(player, is_full_profile, session=session_db)
        
        # Add stats if requested
        if include_stats:
            current_season = session_db.query(Season).filter_by(is_current=True).first()
            response_data.update(get_player_stats(player, current_season, session=session_db))
            
        return jsonify(response_data), 200


@mobile_api.route('/teams', endpoint='get_teams', methods=['GET'])
@jwt_required()
def get_teams():
    """
    Retrieve a list of teams for the current season with associated league names.
    """
    with managed_session() as session_db:
        # Retrieve current seasons for Pub League and ECS FC.
        current_pub_season = session_db.query(Season).filter_by(is_current=True, league_type='Pub League').first()
        current_ecs_season = session_db.query(Season).filter_by(is_current=True, league_type='ECS FC').first()

        # Build conditions based on which current seasons exist.
        conditions = []
        if current_pub_season:
            conditions.append(League.season_id == current_pub_season.id)
        if current_ecs_season:
            conditions.append(League.season_id == current_ecs_season.id)

        # Query teams with eager loading to prevent N+1 queries
        from sqlalchemy.orm import joinedload
        teams_query = session_db.query(Team).join(League, Team.league_id == League.id).options(
            joinedload(Team.league)
        )
        if len(conditions) == 1:
            teams_query = teams_query.filter(conditions[0])
        elif len(conditions) == 2:
            teams_query = teams_query.filter(or_(*conditions))

        teams = teams_query.order_by(Team.name).all()

        # Check cache first
        from app.performance_cache import cache_match_results, set_match_results_cache
        import hashlib
        
        # Create cache key based on query parameters
        cache_key_data = f"{request.args.get('league_id', 'all')}:{request.args.get('season_id', 'current')}"
        cache_hash = hashlib.md5(cache_key_data.encode()).hexdigest()
        
        cached_teams = cache_match_results(league_id=f"teams_{cache_hash}")
        
        if cached_teams:
            teams_data = cached_teams
        else:
            # Preload team stats to avoid N+1 queries
            from app.team_performance_helpers import preload_team_stats_for_request
            team_ids = [team.id for team in teams]
            preload_team_stats_for_request(team_ids)

            teams_data = [
                {
                    **team.to_dict(),
                    'league_name': team.league.name if team.league else "Unknown League"
                }
                for team in teams
            ]
            
            # Cache the results for 10 minutes
            set_match_results_cache(teams_data, league_id=f"teams_{cache_hash}", ttl=600)
        
        # Return with ETag support for mobile app caching
        return make_etag_response(teams_data, 'team_list', CACHE_DURATIONS['team_list'])


@mobile_api.route('/teams/<int:team_id>', endpoint='get_team_details', methods=['GET'])
@jwt_required()
def get_team_details(team_id: int):
    """
    Retrieve details for a specific team. Optionally includes players
    and upcoming matches.
    """
    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404

        include_players = request.args.get('include_players', 'false').lower() == 'true'
        team_data = team.to_dict(include_players=include_players)

        base_url = request.host_url.rstrip('/')
        if team_data.get('logo_url') and not team_data['logo_url'].startswith('http'):
            team_data['logo_url'] = f"{base_url}{team_data['logo_url']}"

        if request.args.get('include_matches', 'false').lower() == 'true':
            team_data['upcoming_matches'] = get_team_upcoming_matches(team_id, session=session_db)

        return jsonify(team_data), 200


@mobile_api.route('/teams/<int:team_id>/players', endpoint='get_team_players', methods=['GET'])
@jwt_required()
def get_team_players(team_id: int):
    """
    Retrieve roster details for a specific team.
    """
    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404

        # Fetch players for this team with coach status in single query (prevents N+1)
        players_with_coach_status = (session_db.query(Player, player_teams.c.is_coach)
                                    .join(player_teams)
                                    .filter(player_teams.c.team_id == team_id)
                                    .order_by(Player.name)
                                    .all())
        
        base_url = request.host_url.rstrip('/')
        default_image = f"{base_url}/static/img/default_player.png"
        
        # Build detailed player list with role information
        detailed_players = []
        for player, is_coach in players_with_coach_status:
            
            profile_picture_url = player.profile_picture_url
            if profile_picture_url:
                full_profile_picture_url = (
                    profile_picture_url if profile_picture_url.startswith('http')
                    else f"{base_url}{profile_picture_url}"
                )
            else:
                full_profile_picture_url = default_image
                
            player_data = {
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "is_coach": bool(is_coach),  # Convert to boolean (was already loaded in single query)
                "is_ref": player.is_ref,
                "is_current_player": player.is_current_player,
                "favorite_position": player.favorite_position,
                "profile_picture_url": full_profile_picture_url,
                "discord_id": player.discord_id,
                # Add primary if this is the player's primary team
                "is_primary_team": (player.primary_team_id == team_id)
            }
            
            detailed_players.append(player_data)
        
        return jsonify({
            "team": {
                "id": team.id,
                "name": team.name,
                "logo_url": team.kit_url if team.kit_url and team.kit_url.startswith('http') else 
                          f"{base_url}{team.kit_url}" if team.kit_url else None
            },
            "players": detailed_players
        }), 200


@mobile_api.route('/teams/<int:team_id>/matches', endpoint='get_team_matches', methods=['GET'])
@jwt_required()
def get_team_matches(team_id: int):
    """
    Retrieve matches for a specific team.
    """
    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404
        
        # Get optional parameters
        upcoming = request.args.get('upcoming', 'false').lower() == 'true'
        completed = request.args.get('completed', 'false').lower() == 'true'
        include_events = request.args.get('include_events', 'false').lower() == 'true'
        limit = request.args.get('limit')
        if limit and limit.isdigit():
            limit = int(limit)
        
        # Build match query with eager loading to prevent N+1 queries
        from sqlalchemy.orm import joinedload
        query = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).filter(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
        )
        
        # Apply upcoming/completed filters
        if upcoming:
            query = query.filter(Match.date >= datetime.now().date())
        if completed:
            query = query.filter(Match.date < datetime.now().date())
            
        # Order by date
        query = query.order_by(Match.date)
        
        # Apply reasonable limit for mobile performance
        if not limit:
            limit = 15 if upcoming else 10  # Smaller default limits for mobile
        query = query.limit(min(limit, 25))  # Cap at 25 for performance
            
        matches = query.all()
        
        # Build response with match details
        matches_data = []
        for match in matches:
            match_data = match.to_dict(include_teams=True)
            
            # Add event data if requested
            if include_events:
                match_data['events'] = [event.to_dict(include_player=True) for event in match.events]
                
            matches_data.append(match_data)
        
        return jsonify(matches_data), 200


@mobile_api.route('/matches/<int:match_id>/availability', endpoint='get_match_availability', methods=['GET'])
@jwt_required()
def get_match_availability(match_id: int):
    """
    Retrieve availability data for a specific match. Optionally filter for a specific team.
    """
    with managed_session() as session_db:
        current_user_id = get_jwt_identity()
        # Query user and match with eager loading to prevent N+1 queries
        from sqlalchemy.orm import joinedload, selectinload
        safe_current_user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()
        
        match = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).filter(Match.id == match_id).first()
        
        if not match:
            return jsonify({"msg": "Match not found"}), 404
        
        # Check if user has appropriate roles or is on one of the teams
        user_roles = [r.name for r in safe_current_user.roles]
        is_admin_or_coach = any(r in ['Coach', 'Admin'] for r in user_roles)
        
        player = session_db.query(Player).options(
            selectinload(Player.teams)
        ).filter_by(user_id=current_user_id).first()
        is_on_team = False
        
        if player:
            player_team_ids = [team.id for team in player.teams]
            is_on_team = match.home_team_id in player_team_ids or match.away_team_id in player_team_ids
        
        # Only allow access if user is admin/coach or on one of the teams
        if not (is_admin_or_coach or is_on_team):
            return jsonify({"msg": "Not authorized to view match availability"}), 403
        
        # Get optional team_id parameter
        team_id = request.args.get('team_id', type=int)
        if team_id:
            # If team_id is provided, verify it's one of the teams in the match
            if team_id not in [match.home_team_id, match.away_team_id]:
                return jsonify({"msg": "Invalid team ID for this match"}), 400
        
        # Import functions from availability_api_helpers
        from app.availability_api_helpers import get_match_rsvp_data, verify_availability_data
        
        # Log detailed data for debugging
        verify_availability_data(match_id, team_id, session=session_db)
        
        # Get RSVP data
        rsvp_data = get_match_rsvp_data(match_id, team_id, session=session_db)
        
        # Add counts for easy reference
        response_data = {
            "match_id": match_id,
            "team_id": team_id,
            "yes": rsvp_data['yes'],
            "yes_count": len(rsvp_data['yes']),
            "no": rsvp_data['no'],
            "no_count": len(rsvp_data['no']),
            "maybe": rsvp_data['maybe'],
            "maybe_count": len(rsvp_data['maybe']),
            "total_responses": len(rsvp_data['yes']) + len(rsvp_data['no']) + len(rsvp_data['maybe'])
        }
        
        return jsonify(response_data), 200


@mobile_api.route('/teams/<int:team_id>/stats', endpoint='get_team_stats', methods=['GET'])
@jwt_required()
def get_team_stats(team_id: int):
    """
    Retrieve detailed statistics for a specific team, including standings.
    """
    with managed_session() as session_db:
        team = session_db.query(Team).get(team_id)
        if not team:
            return jsonify({"msg": "Team not found"}), 404
        
        # Find current season - first check team's league's season
        current_season = None
        if team.league and team.league.season:
            current_season = team.league.season
        
        # If not found through team's league, find any current season
        if not current_season:
            current_season = session_db.query(Season).filter_by(is_current=True).first()
        
        # Get standings data
        standings = session_db.query(Standings).filter_by(
            team_id=team_id,
            season_id=current_season.id if current_season else None
        ).first()
        
        # Preload team stats to avoid N+1 queries
        from app.team_performance_helpers import preload_team_stats_for_request
        preload_team_stats_for_request([team.id])

        # Get team stats from model properties
        stats = {
            "name": team.name,
            "league": team.league.name if team.league else None,
            "season": current_season.name if current_season else None,
            "top_scorer": team.top_scorer,
            "top_assist": team.top_assist,
            "avg_goals_per_match": team.avg_goals_per_match,
        }
        
        # Add recent form information
        recent_matches = session_db.query(Match).filter(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).order_by(Match.date.desc()).limit(5).all()
        
        form = []
        for match in recent_matches:
            if match.home_team_id == team_id:
                if match.home_team_score > match.away_team_score:
                    form.append("W")
                elif match.home_team_score < match.away_team_score:
                    form.append("L")
                else:
                    form.append("D")
            else:  # Away team
                if match.away_team_score > match.home_team_score:
                    form.append("W")
                elif match.away_team_score < match.home_team_score:
                    form.append("L")
                else:
                    form.append("D")
        
        stats["recent_form"] = form
        
        # Add standings data if available
        if standings:
            stats.update({
                "standings": {
                    "played": standings.played,
                    "wins": standings.wins,
                    "draws": standings.draws,
                    "losses": standings.losses,
                    "goals_for": standings.goals_for,
                    "goals_against": standings.goals_against,
                    "goal_difference": standings.goal_difference,
                    "points": standings.points,
                }
            })
        else:
            stats["standings"] = None
        
        # Get total goals scored by team's players
        total_goals = session_db.query(func.sum(PlayerSeasonStats.goals)).join(
            player_teams, PlayerSeasonStats.player_id == player_teams.c.player_id
        ).filter(
            player_teams.c.team_id == team_id,
            PlayerSeasonStats.season_id == current_season.id if current_season else None
        ).scalar() or 0
        
        stats["total_goals"] = total_goals
        
        # Get player statistics for this team (bulk load to prevent N+1)
        players_stats = []
        if current_season:
            # Single query to get all player stats for the team
            player_stats_query = session_db.query(Player, PlayerSeasonStats).join(
                player_teams, Player.id == player_teams.c.player_id
            ).outerjoin(
                PlayerSeasonStats, 
                (PlayerSeasonStats.player_id == Player.id) & 
                (PlayerSeasonStats.season_id == current_season.id)
            ).filter(
                player_teams.c.team_id == team_id
            ).all()
            
            for player, player_stats in player_stats_query:
                if player_stats and (player_stats.goals > 0 or player_stats.assists > 0):
                    players_stats.append({
                        "id": player.id,
                        "name": player.name,
                        "goals": player_stats.goals,
                        "assists": player_stats.assists,
                        "yellow_cards": player_stats.yellow_cards,
                        "red_cards": player_stats.red_cards
                    })
    
        # Sort by goals, then assists
        players_stats.sort(key=lambda x: (x.get("goals", 0), x.get("assists", 0)), reverse=True)
        stats["players_stats"] = players_stats
        
        # Return with ETag support for mobile app caching
        return make_etag_response(stats, 'team_stats', CACHE_DURATIONS['team_stats'])


@mobile_api.route('/teams/my_team', endpoint='get_my_team', methods=['GET'])
@jwt_required()
def get_my_team():
    """
    Retrieve the team of the currently authenticated player.
    Returns the primary team if set, otherwise returns the first team the player is associated with.
    """
    try:
        with managed_session() as session_db:
            current_user_id = get_jwt_identity()
            logger.info(f"🔵 [MOBILE_API] get_my_team called for user_id: {current_user_id}")
            
            player = session_db.query(Player).filter_by(user_id=current_user_id).first()

            if not player:
                logger.warning(f"🟡 [MOBILE_API] Player not found for user_id: {current_user_id}")
                return jsonify({"msg": "Team not found"}), 404

            # First try to use primary team
            if player.primary_team:
                logger.info(f"🟢 [MOBILE_API] Using primary team for {player.name}: {player.primary_team.name}")
                return get_team_details(player.primary_team.id)
            
            # If no primary team, get the first team from player_teams association
            first_team = session_db.query(Team).join(player_teams).filter(
                player_teams.c.player_id == player.id
            ).first()
            
            if not first_team:
                logger.warning(f"🟡 [MOBILE_API] No teams found for player {player.name}")
                return jsonify({"msg": "Team not found"}), 404

            logger.info(f"🟢 [MOBILE_API] Using first team for {player.name}: {first_team.name}")
            return get_team_details(first_team.id)
            
    except Exception as e:
        logger.error(f"🔴 [MOBILE_API] Error in get_my_team: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api.route('/teams/my_teams', endpoint='get_my_teams', methods=['GET'])
@jwt_required()
def get_my_teams():
    """
    Retrieve all teams the currently authenticated player is associated with.
    """
    with managed_session() as session_db:
        current_user_id = get_jwt_identity()
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        if not player:
            return jsonify({"msg": "Player not found"}), 404
        
        # Query all teams for this player using the player_teams association table
        teams_query = session_db.query(Team).join(player_teams).filter(
            player_teams.c.player_id == player.id
        )
        
        teams = teams_query.all()
        
        if not teams:
            return jsonify({"msg": "No teams found for this player"}), 404

        # Preload team stats to avoid N+1 queries
        from app.team_performance_helpers import preload_team_stats_for_request
        team_ids = [team.id for team in teams]
        preload_team_stats_for_request(team_ids)

        base_url = request.host_url.rstrip('/')
        teams_data = []
        
        for team in teams:
            team_data = team.to_dict()
            
            # Add is_primary flag
            team_data['is_primary'] = (team.id == player.primary_team_id)
            
            # Add is_coach flag
            is_coach = session_db.query(player_teams.c.is_coach).filter(
                player_teams.c.player_id == player.id,
                player_teams.c.team_id == team.id
            ).scalar()
            team_data['is_coach'] = bool(is_coach)
            
            # Handle team logo URLs
            if team_data.get('logo_url') and not team_data['logo_url'].startswith('http'):
                team_data['logo_url'] = f"{base_url}{team_data['logo_url']}"
                
            teams_data.append(team_data)
        
        # Sort teams with primary team first, then alphabetically
        teams_data.sort(key=lambda t: (not t['is_primary'], t['name'].lower()))
        
        return jsonify(teams_data), 200


@mobile_api.route('/matches', endpoint='get_all_matches', methods=['GET'])
@jwt_required()
def get_all_matches():
    """
    Retrieve a list of matches based on query parameters, including
    optional event and availability details.
    """
    current_user_id = get_jwt_identity()
    logger.info(f"🔵 [MOBILE_API] get_all_matches called for user_id: {current_user_id}")
    logger.debug(f"🔵 [MOBILE_API] Request args: {dict(request.args)}")
    
    with managed_session() as session_db:
        # Get user with roles for access level determination
        from sqlalchemy.orm import joinedload
        user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()
        
        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).filter_by(user_id=current_user_id).first()
        logger.debug(f"🔵 [MOBILE_API] Player found: {player.name if player else 'None'}")

        # Get query parameters with performance defaults
        upcoming = request.args.get('upcoming', 'false').lower() == 'true'
        completed = request.args.get('completed', 'false').lower() == 'true'
        all_teams = request.args.get('all_teams', 'false').lower() == 'true'
        team_id = request.args.get('team_id', type=int)
        
        # Determine user access level for smart limits
        user_roles = [r.name for r in user.roles] if user.roles else []
        is_admin = any(r in ['Global Admin', 'Admin'] for r in user_roles)
        is_league_admin = any('admin' in r.lower() for r in user_roles)
        is_coach = 'Coach' in user_roles or (player and player.is_coach)
        
        # Set reasonable default limits for performance based on role and context
        limit = request.args.get('limit')
        if limit and limit.isdigit():
            limit = min(int(limit), 200 if is_admin else 100)  # Cap based on role
        else:
            # Smart defaults based on role and query type
            if team_id:
                # Viewing specific team - allow more matches
                limit = 50
            elif is_admin:
                if completed:
                    limit = 50  # Admins need more history for management
                elif upcoming:
                    limit = 40
                elif all_teams:
                    limit = 60
                else:
                    limit = 45
            elif is_league_admin or is_coach:
                if completed:
                    limit = 30  # Coaches need match history for their oversight
                elif upcoming:
                    limit = 25
                elif all_teams:
                    limit = 35
                else:
                    limit = 25
            else:
                # Regular players - focused on their relevant matches
                if completed:
                    limit = 15
                elif upcoming:
                    limit = 10
                elif all_teams:
                    limit = 20
                else:
                    limit = 15

        logger.debug(f"🔵 [MOBILE_API] User roles: {user_roles}, query type: {('upcoming' if upcoming else 'completed' if completed else 'all')}, limit: {limit}")
        
        query = build_matches_query(
            team_id=request.args.get('team_id'),
            player=player,
            upcoming=upcoming,
            completed=completed,
            all_teams=all_teams,
            limit=limit,
            session=session_db
        )
        
        logger.debug(f"🔵 [MOBILE_API] Query built, executing with limit: {limit}")
        matches = query.all()

        logger.info(f"🔵 [MOBILE_API] Found {len(matches)} matches")
        
        include_events = request.args.get('include_events', 'false').lower() == 'true'
        include_availability = request.args.get('include_availability', 'false').lower() == 'true'
        logger.debug(f"🔵 [MOBILE_API] Processing matches - include_events: {include_events}, include_availability: {include_availability}")

        matches_data = process_matches_data(
            matches=matches,
            player=player,
            include_events=include_events,
            include_availability=include_availability,
            session=session_db
        )

        logger.info(f"🟢 [MOBILE_API] get_all_matches successful - returning {len(matches_data)} matches")
        
        # Return with ETag support - use shorter cache for match lists that might update
        cache_duration = CACHE_DURATIONS['match_list'] if not include_availability else 3600  # 1 hour if personalized
        return make_etag_response(matches_data, 'match_list', cache_duration)


@mobile_api.route('/matches/schedule', endpoint='get_match_schedule', methods=['GET'])
@jwt_required()
def get_match_schedule():
    """
    Retrieve the schedule of upcoming matches, grouped by date.
    """
    current_user_id = get_jwt_identity()
    logger.info(f"🔵 [MOBILE_API] get_match_schedule called for user_id: {current_user_id}")
    logger.debug(f"🔵 [MOBILE_API] Request args: {dict(request.args)}")
    
    with managed_session() as session_db:
        # Get user with roles for access level determination
        from sqlalchemy.orm import joinedload
        user = session_db.query(User).options(
            joinedload(User.roles)
        ).filter(User.id == current_user_id).first()
        
        player = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).filter_by(user_id=current_user_id).first()
        logger.debug(f"🔵 [MOBILE_API] Player found: {player.name if player else 'None'}")
        
        # Determine user access level and appropriate limits
        user_roles = [r.name for r in user.roles] if user.roles else []
        is_admin = any(r in ['Global Admin', 'Admin'] for r in user_roles)
        is_league_admin = any('admin' in r.lower() for r in user_roles)
        is_coach = 'Coach' in user_roles or (player and player.is_coach)
        
        # Smart limits based on user role and request context
        team_id = request.args.get('team_id', type=int)
        requested_limit = request.args.get('limit', type=int)
        
        if requested_limit:
            # User explicitly requested a limit - respect it but cap for performance
            limit = min(requested_limit, 200 if is_admin else 100)
        elif team_id:
            # Viewing specific team - allow more matches for that team
            limit = 50
        elif is_admin:
            # Global admin default - more matches for management
            limit = 75
        elif is_league_admin or is_coach:
            # League admin/coach - moderate amount for their oversight duties
            limit = 50
        else:
            # Regular player - focused on their relevant matches
            limit = 25
        
        logger.debug(f"🔵 [MOBILE_API] User roles: {user_roles}, using limit: {limit}")
        
        # Check cache first for non-personalized queries
        cache_key = None
        cached_matches = None
        if not (player and request.args.get('include_availability', 'true').lower() == 'true'):
            # Only cache if not including personal availability data
            from app.performance_cache import cache_match_results
            import hashlib
            cache_params = f"schedule_{team_id or 'all'}_{limit}_{request.args.get('upcoming', 'true')}"
            cache_key = hashlib.md5(cache_params.encode()).hexdigest()
            cached_matches = cache_match_results(league_id=f"schedule_{cache_key}")
            
            if cached_matches:
                logger.debug(f"🔵 [MOBILE_API] Returning cached schedule data")
                return jsonify(cached_matches), 200
        
        # Build query for upcoming matches
        query = build_matches_query(
            team_id=team_id,
            player=player,
            upcoming=True,
            session=session_db
        )
        
        # Order by date and apply limit
        matches = query.order_by(Match.date).limit(limit).all()
        logger.debug(f"🔵 [MOBILE_API] Found {len(matches)} matches (limit: {limit})")
        
        # Bulk load availability data to prevent N+1 queries
        availability_dict = {}
        if player and request.args.get('include_availability', 'true').lower() == 'true' and matches:
            match_ids = [match.id for match in matches]
            availabilities = session_db.query(Availability).filter(
                Availability.match_id.in_(match_ids),
                Availability.player_id == player.id
            ).all()
            availability_dict = {av.match_id: av for av in availabilities}
        
        # Group matches by date
        schedule = {}
        for match in matches:
            match_date = match.date.strftime('%Y-%m-%d')
            if match_date not in schedule:
                schedule[match_date] = []
            
            match_data = match.to_dict(include_teams=True)
            # Add availability if requested and player exists
            if player and request.args.get('include_availability', 'true').lower() == 'true':
                availability = availability_dict.get(match.id)
                match_data['availability'] = availability.to_dict() if availability else None
            
            schedule[match_date].append(match_data)
        
        # Convert to list of objects with date and matches
        schedule_list = [
            {
                'date': date,
                'matches': matches_data
            }
            for date, matches_data in schedule.items()
        ]
        
        # Sort by date
        schedule_list.sort(key=lambda x: x['date'])
        
        # Cache the result if it's not personalized (no availability data)
        # Use long cache since match schedules rarely change (maybe once per season)
        if cache_key and not (player and request.args.get('include_availability', 'true').lower() == 'true'):
            from app.performance_cache import set_match_results_cache
            set_match_results_cache(league_id=f"schedule_{cache_key}", results=schedule_list, ttl_minutes=10080)  # 7 days
            logger.debug(f"🔵 [MOBILE_API] Cached schedule data for {cache_key} (7 day TTL)")
        
        logger.info(f"🟢 [MOBILE_API] get_match_schedule successful - returning {len(schedule_list)} dates with matches (limit: {limit})")
        
        # Return with ETag support for mobile app caching
        return make_etag_response(schedule_list, 'match_schedule', CACHE_DURATIONS['match_schedule'])


@mobile_api.route('/matches/<int:match_id>', endpoint='get_single_match_details', methods=['GET'])
@jwt_required()
def get_single_match_details(match_id: int):
    """
    Retrieve detailed information for a single match.
    """
    with managed_session() as session_db:
        # Query match with eager loading to prevent N+1 queries
        from sqlalchemy.orm import joinedload, selectinload
        match = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            selectinload(Match.events)
        ).filter(Match.id == match_id).first()
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        current_user_id = get_jwt_identity()
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        match_data = build_match_response(
            match=match,
            include_events=request.args.get('include_events', 'true').lower() == 'true',
            include_teams=request.args.get('include_teams', 'true').lower() == 'true',
            include_players=request.args.get('include_players', 'true').lower() == 'true',
            current_player=player,
            session=session_db
        )

        # Return with ETag support for mobile app caching
        return make_etag_response(match_data, 'match_details', CACHE_DURATIONS['match_details'])


@mobile_api.route('/update_availability', endpoint='update_availability', methods=['POST'])
@jwt_required()
def update_availability():
    """
    Update a player's availability status for a specific match.
    """
    with managed_session() as session_db:
        current_user_id = get_jwt_identity()
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        if not player:
            return jsonify({"msg": "Player not found"}), 404

        data = request.json
        match_id = data.get('match_id')
        availability_status = data.get('availability')

        if not match_id or not availability_status:
            return jsonify({"msg": "Missing match_id or availability status"}), 400

        if availability_status not in ['yes', 'no', 'maybe']:
            return jsonify({"msg": "Invalid availability status"}), 400

        match = session_db.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        try:
            update_player_availability(
                match_id=match_id,
                player_id=player.id,
                discord_id=player.discord_id,
                response=availability_status,
                session=session_db
            )
            return jsonify({"msg": "Availability updated successfully"}), 200
        except Exception as e:
            logger.error(f"Error updating availability: {str(e)}")
            return jsonify({"msg": "An error occurred while updating availability"}), 500


@mobile_api.route('/report_match/<int:match_id>', endpoint='report_match', methods=['POST'])
@jwt_required()
@jwt_role_required(['Coach', 'Pub League Admin', 'Pub League Ref'])
def report_match(match_id: int):
    """
    Report match details and add any related events.
    """
    with managed_session() as session_db:
        match = session_db.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404

        try:
            data = request.json
            update_match_details(match, data, session=session_db)
            add_match_events(match, data.get('events', []), session=session_db)

            return jsonify({
                "msg": "Match reported successfully",
                "match": match.to_dict()
            }), 200
        except Exception as e:
            logger.error(f"Error reporting match: {str(e)}")
            return jsonify({"msg": f"Error reporting match: {str(e)}"}), 500






@mobile_api.route('/update_availability_web', endpoint='update_availability_web', methods=['POST'])
@jwt_required()
def update_availability_web():
    """
    Update a player's match availability via a web interface and send a notification.
    """
    with managed_session() as session_db:
        data = request.json
        logger.info(f"Received web update data: {data}")

        match_id = data.get('match_id')
        player_id = data.get('player_id')
        new_response = data.get('response')

        if not all([match_id, player_id, new_response]):
            logger.error("Invalid data received from web")
            return jsonify({"error": "Invalid data"}), 400

        success = update_player_match_availability(match_id, player_id, new_response, session=session_db)

        if success:
            notify_availability_update(match_id, player_id, new_response, session=session_db)
            return jsonify({"message": "Availability updated successfully"}), 200

    return jsonify({"error": "Failed to update availability"}), 500




@mobile_api.route('/players', endpoint='get_players', methods=['GET'])
@jwt_required()
def get_players():
    """
    Retrieve a list of players, optionally filtered by a search query
    on player or team names.
    """
    with managed_session() as session_db:
        search_query = request.args.get('search', '').lower()
        limit = request.args.get('limit', 25, type=int)  # Default limit for mobile performance
        limit = min(limit, 50)  # Cap at 50 for performance

        # Query with eager loading and performance limits
        from sqlalchemy.orm import joinedload
        players_query = session_db.query(Player).options(
            joinedload(Player.primary_team),
            joinedload(Player.league)
        ).join(Team, isouter=True).filter(
            (Player.name.ilike(f"%{search_query}%")) |
            (Team.name.ilike(f"%{search_query}%"))
        ).limit(limit)

        players_data = [build_player_response(player) for player in players_query.all()]
        return jsonify(players_data), 200


# TEMPORARILY DISABLED DUE TO SESSION MANAGEMENT ISSUES
# @mobile_api.route('/players/<int:player_id>/profile_picture', endpoint='upload_player_profile_picture', methods=['POST'])
# @jwt_required()
def upload_player_profile_picture_disabled(player_id: int):
    """
    Upload and update a player's profile picture via mobile API.
    
    Supports both multipart form data and JSON with base64 image data.
    The user can only update their own profile picture unless they are an admin.
    
    Request formats:
    1. Multipart form with 'file' and crop parameters (x, y, width, height, scale)
    2. JSON with base64 'image_data' and crop parameters
    
    Args:
        player_id (int): The ID of the player whose profile picture to update
        
    Returns:
        JSON response with success/error message and new profile picture URL
    """
    from app.players_helpers import save_cropped_profile_picture
    from werkzeug.utils import secure_filename
    from PIL import Image
    import base64
    from io import BytesIO
    import os
    
    try:
        with managed_session() as session_db:
            current_user_id = get_jwt_identity()
            
            # Get the player
            player = session_db.query(Player).filter(Player.id == player_id).first()
            if not player:
                return jsonify({"error": "Player not found"}), 404
        
        # Get current user to check authorization
        current_user = session_db.query(User).filter(User.id == current_user_id).first()
        if not current_user:
            return jsonify({"error": "User not found"}), 404
        
        # Authorization check: user can only update their own profile picture
        # unless they are an admin or coach
        if (player.user_id != current_user_id and 
            not any(role.name in ['Pub League Admin', 'Coach'] for role in current_user.roles)):
            return jsonify({"error": "Unauthorized to update this player's profile picture"}), 403
        
        # Handle different content types
        content_type = request.content_type or ''
        
        if 'multipart/form-data' in content_type:
            # Handle multipart form data (file upload)
            if 'file' not in request.files:
                return jsonify({"error": "No file provided"}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({"error": "No file selected"}), 400
            
            # Get crop parameters
            try:
                x = float(request.form.get('x', 0))
                y = float(request.form.get('y', 0))
                width = float(request.form.get('width', 0))
                height = float(request.form.get('height', 0))
                scale = float(request.form.get('scale', 1))
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid crop parameters"}), 400
            
            # Validate file type
            allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
            file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            if file_ext not in allowed_extensions:
                return jsonify({"error": "Invalid file type. Allowed types: PNG, JPG, JPEG, GIF, WEBP"}), 400
            
            # Process the uploaded image
            try:
                image = Image.open(file.stream).convert("RGBA")
                
                # Apply cropping if parameters provided
                if width > 0 and height > 0:
                    # Apply scale if provided
                    if scale != 1:
                        new_width = int(image.width * scale)
                        new_height = int(image.height * scale)
                        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Apply crop
                    crop_box = (int(x), int(y), int(x + width), int(y + height))
                    image = image.crop(crop_box)
                
                # Convert to base64 for saving
                output = BytesIO()
                image.save(output, format='PNG')
                image_data = output.getvalue()
                image_b64 = base64.b64encode(image_data).decode('utf-8')
                cropped_image_data = f"data:image/png;base64,{image_b64}"
                
            except Exception as e:
                logger.error(f"Error processing uploaded image: {str(e)}")
                return jsonify({"error": "Failed to process image"}), 400
                
        elif 'application/json' in content_type:
            # Handle JSON with base64 image data
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data provided"}), 400
            
            cropped_image_data = data.get('image_data')
            if not cropped_image_data:
                return jsonify({"error": "No image_data provided"}), 400
            
            # Validate base64 image data format
            if not cropped_image_data.startswith('data:image/'):
                return jsonify({"error": "Invalid image data format"}), 400
                
        else:
            return jsonify({"error": "Unsupported content type. Use multipart/form-data or application/json"}), 400
        
        # Save the cropped profile picture using existing helper
        try:
            profile_picture_url = save_cropped_profile_picture(cropped_image_data, player_id)
            if not profile_picture_url:
                return jsonify({"error": "Failed to save profile picture"}), 500
            
            # Update player's profile picture URL
            player.profile_picture_url = profile_picture_url
            session_db.commit()
            
            # Build full URL for response
            base_url = request.host_url.rstrip('/')
            full_profile_url = f"{base_url}{profile_picture_url}"
            
            logger.info(f"Profile picture updated for player {player_id} by user {current_user_id}")
            
            return jsonify({
                "message": "Profile picture updated successfully",
                "profile_picture_url": full_profile_url,
                "player_id": player_id
            }), 200
            
        except Exception as e:
            logger.error(f"Error saving profile picture for player {player_id}: {str(e)}")
            session_db.rollback()
            return jsonify({"error": "Failed to save profile picture"}), 500
            
    except Exception as e:
        logger.error(f"Error in upload_player_profile_picture: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route('/players/<int:player_id>/profile_picture', endpoint='get_player_profile_picture', methods=['GET'])
@jwt_required()
def get_player_profile_picture(player_id: int):
    """
    Get a player's current profile picture URL and metadata.
    
    Args:
        player_id (int): The ID of the player
        
    Returns:
        JSON response with profile picture information
    """
    try:
        with managed_session() as session_db:
            # Get the player
            player = session_db.query(Player).filter(Player.id == player_id).first()
            if not player:
                return jsonify({"error": "Player not found"}), 404
            
            # Build response
            base_url = request.host_url.rstrip('/')
            default_image = f"{base_url}/static/img/default_player.png"
            current_image = f"{base_url}{player.profile_picture_url}" if player.profile_picture_url else default_image
            
            return jsonify({
                "player_id": player_id,
                "player_name": player.name,
                "profile_picture_url": current_image,
                "has_custom_picture": bool(player.profile_picture_url),
                "last_updated": player.profile_last_updated.isoformat() if player.profile_last_updated else None
            }), 200
        
    except Exception as e:
        logger.error(f"Error getting profile picture for player {player_id}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route('/matches/<int:match_id>/live_updates', endpoint='get_match_live_updates', methods=['GET'])
@jwt_required()
def get_match_live_updates(match_id: int):
    """
    Get live match updates for mobile apps that can't maintain WebSocket connections.
    Returns the current state of the match including score, time, and recent events.
    """
    try:
        with managed_session() as session_db:
            current_user_id = get_jwt_identity()
        
        # Get the match
        match = session_db.query(Match).get(match_id)
        if not match:
            return jsonify({"msg": "Match not found"}), 404
        
        # Check if user has permission to view this match
        safe_current_user = session_db.query(User).get(current_user_id)
        user_roles = [r.name for r in safe_current_user.roles]
        is_admin_or_coach = any(r in ['Coach', 'Admin'] for r in user_roles)
        
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        is_on_team = False
        
        if player:
            player_team_ids = [team.id for team in player.teams]
            is_on_team = match.home_team_id in player_team_ids or match.away_team_id in player_team_ids
        
        if not (is_admin_or_coach or is_on_team):
            return jsonify({"msg": "Not authorized to view match updates"}), 403
        
        # Get live match data if it exists
        from app.database.db_models import LiveMatch, MatchEvent
        live_match = session_db.query(LiveMatch).filter_by(match_id=match_id).first()
        
        # Get recent events (last 10 minutes worth)
        recent_events = session_db.query(MatchEvent).filter_by(match_id=match_id).order_by(MatchEvent.timestamp.desc()).limit(10).all()
        
        response_data = {
            "match_id": match_id,
            "match_status": "live" if live_match and live_match.is_active else "scheduled",
            "home_team": {
                "id": match.home_team.id,
                "name": match.home_team.name,
                "score": match.home_team_score or 0
            },
            "away_team": {
                "id": match.away_team.id,
                "name": match.away_team.name,
                "score": match.away_team_score or 0
            },
            "current_time": live_match.current_minute if live_match else 0,
            "period": live_match.period if live_match else "Not Started",
            "last_updated": live_match.last_updated.isoformat() if live_match and live_match.last_updated else None,
            "recent_events": [
                {
                    "id": event.id,
                    "type": event.event_type,
                    "minute": event.minute,
                    "player_name": event.player_name,
                    "team": "home" if event.team == match.home_team.name else "away",
                    "timestamp": event.timestamp.isoformat()
                }
                for event in recent_events
            ]
        }
        
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error getting live updates for match {match_id}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route('/notifications/register', endpoint='register_device', methods=['POST'])
@jwt_required()
def register_device():
    """
    Register a mobile device for push notifications.
    """
    try:
        with managed_session() as session_db:
            current_user_id = get_jwt_identity()
        data = request.json
        
        device_token = data.get('device_token')
        device_type = data.get('device_type')  # 'ios' or 'android'
        app_version = data.get('app_version', '1.0')
        
        if not device_token or not device_type:
            return jsonify({"msg": "Missing device_token or device_type"}), 400
        
        if device_type not in ['ios', 'android']:
            return jsonify({"msg": "Invalid device_type. Must be 'ios' or 'android'"}), 400
        
        # Check if device already exists
        from app.models import DeviceToken
        device = session_db.query(DeviceToken).filter_by(
            user_id=current_user_id,
            device_token=device_token
        ).first()
        
        if device:
            # Update existing device
            device.device_type = device_type
            device.app_version = app_version
            device.is_active = True
            device.updated_at = datetime.utcnow()
        else:
            # Create new device registration
            device = DeviceToken(
                user_id=current_user_id,
                device_token=device_token,
                device_type=device_type,
                app_version=app_version,
                is_active=True
            )
            session_db.add(device)
        
        return jsonify({"msg": "Device registered successfully"}), 200
        
    except Exception as e:
        logger.error(f"Error registering device: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route('/notifications/preferences', endpoint='notification_preferences', methods=['GET', 'PUT'])
@jwt_required()
def notification_preferences():
    """
    Get or update notification preferences for the current user.
    """
    try:
        with managed_session() as session_db:
            current_user_id = get_jwt_identity()
        user = session_db.query(User).get(current_user_id)
        
        if not user:
            return jsonify({"msg": "User not found"}), 404
        
        if request.method == 'GET':
            return jsonify({
                "email_notifications": user.email_notifications,
                "sms_notifications": user.sms_notifications,
                "discord_notifications": user.discord_notifications,
                "push_notifications": getattr(user, 'push_notifications', True),
                "match_reminders": getattr(user, 'match_reminders', True),
                "availability_requests": getattr(user, 'availability_requests', True),
                "team_updates": getattr(user, 'team_updates', True)
            }), 200
        
        elif request.method == 'PUT':
            data = request.json
            
            # Update preferences that exist in the User model
            if 'email_notifications' in data:
                user.email_notifications = bool(data['email_notifications'])
            if 'sms_notifications' in data:
                user.sms_notifications = bool(data['sms_notifications'])
            if 'discord_notifications' in data:
                user.discord_notifications = bool(data['discord_notifications'])
            
            # For additional preferences, you might want to add columns to User model
            # or create a separate UserPreferences table
            
            return jsonify({"msg": "Preferences updated successfully"}), 200
            
    except Exception as e:
        logger.error(f"Error handling notification preferences: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route('/matches/availability/bulk', endpoint='bulk_availability_update', methods=['POST'])
@jwt_required()
def bulk_availability_update():
    """
    Update availability for multiple matches at once (useful for offline sync).
    """
    try:
        with managed_session() as session_db:
            current_user_id = get_jwt_identity()
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        
        if not player:
            return jsonify({"msg": "Player not found"}), 404
        
        data = request.json
        updates = data.get('updates', [])
        
        if not updates or not isinstance(updates, list):
            return jsonify({"msg": "Missing or invalid updates array"}), 400
        
        successful_updates = []
        failed_updates = []
        
        for update in updates:
            try:
                match_id = update.get('match_id')
                availability_status = update.get('availability')
                
                if not match_id or not availability_status:
                    failed_updates.append({
                        "match_id": match_id,
                        "error": "Missing match_id or availability"
                    })
                    continue
                
                if availability_status not in ['yes', 'no', 'maybe']:
                    failed_updates.append({
                        "match_id": match_id,
                        "error": "Invalid availability status"
                    })
                    continue
                
                # Verify match exists
                match = session_db.query(Match).get(match_id)
                if not match:
                    failed_updates.append({
                        "match_id": match_id,
                        "error": "Match not found"
                    })
                    continue
                
                # Update availability
                update_player_availability(
                    match_id=match_id,
                    player_id=player.id,
                    discord_id=player.discord_id,
                    response=availability_status,
                    session=session_db
                )
                
                successful_updates.append({
                    "match_id": match_id,
                    "availability": availability_status
                })
                
            except Exception as e:
                failed_updates.append({
                    "match_id": update.get('match_id'),
                    "error": str(e)
                })
        
        return jsonify({
            "msg": "Bulk update completed",
            "successful_updates": len(successful_updates),
            "failed_updates": len(failed_updates),
            "successes": successful_updates,
            "failures": failed_updates
        }), 200
        
    except Exception as e:
        logger.error(f"Error in bulk availability update: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500