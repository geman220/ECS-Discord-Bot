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
    PlayerSeasonStats
)
from app.decorators import (
    jwt_role_required
)
from app.app_api_helpers import (
    build_player_response, get_player_response_data, exchange_discord_code,
    get_discord_user_data, process_discord_user, build_match_response,
    get_team_players_availability, get_match_events, get_player_availability,
    build_matches_query, process_matches_data, get_player_stats, generate_pkce_codes,
    update_match_details, add_match_events, update_player_availability,
    notify_availability_update, update_player_match_availability, get_team_upcoming_matches
)

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


@mobile_api.route('/get_discord_auth_url', endpoint='get_discord_auth_url', methods=['GET'])
def get_discord_auth_url():
    """
    Generate and return a Discord OAuth2 authorization URL for mobile app.
    
    Optional query parameters:
        redirect_uri: The URI to redirect to after authorization
        
    Returns:
        JSON with Discord authorization URL and PKCE code verifier
    """
    # Default to mobile app scheme if no redirect_uri provided
    default_redirect = 'ecs-fc-scheme://auth'
    redirect_uri = request.args.get('redirect_uri', default_redirect)
    
    # Generate PKCE codes for enhanced security
    code_verifier, code_challenge = generate_pkce_codes()
    
    # Store code verifier in session for later verification
    session['code_verifier'] = code_verifier
    
    # Discord OAuth2 parameters
    params = {
        'client_id': current_app.config['DISCORD_CLIENT_ID'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'identify email guilds',
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'prompt': 'consent'
    }
    
    # Build the authorization URL
    discord_auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    
    # Return the URL and code verifier to the mobile app
    return jsonify({
        'auth_url': discord_auth_url,
        'code_verifier': code_verifier
    }), 200


@mobile_api.route('/discord_callback', endpoint='discord_callback', methods=['POST'])
def discord_callback():
    """
    Handle Discord OAuth callback for mobile app authentication.
    
    Expected JSON parameters:
        code: The authorization code from Discord
        redirect_uri: The redirect URI used in the auth request
        code_verifier: The PKCE code verifier
        
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
        
        # The code_verifier MUST be the same one used in the original authorization request
        code_verifier = data.get('code_verifier')
        if not code_verifier:
            return jsonify({"msg": "Missing code_verifier parameter from original authorization request"}), 400
            
        if not code:
            return jsonify({"msg": "Missing authorization code"}), 400
            
# Line deleted - redundant check is now handled above
        
        # Log the data we're using for the OAuth exchange
        logger.info(f"Discord callback data - code length: {len(code) if code else 0}, redirect_uri: {redirect_uri}")
        
        # Exchange the authorization code for an access token
        token_data = exchange_discord_code(code, redirect_uri, code_verifier)
        
        if not token_data or 'access_token' not in token_data:
            return jsonify({"msg": "Failed to exchange authorization code"}), 400
            
        # Get Discord user data with the access token
        discord_user = get_discord_user_data(token_data['access_token'])
        
        if not discord_user or 'id' not in discord_user:
            return jsonify({"msg": "Failed to get Discord user data"}), 400
            
        # Find or create user based on Discord data
        session_db = g.db_session
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
    session_db = g.db_session
    email = request.json.get('email')
    password = request.json.get('password')

    if not email or not password:
        return jsonify({"msg": "Missing username or password"}), 400

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
    session_db = g.db_session
    user_id = request.json.get('user_id')
    token = request.json.get('token')
    logger.debug(f"Received user_id: {user_id}, token: {token}")

    if not user_id or not token:
        return jsonify({"msg": "Missing user_id or token"}), 400

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
    session_db = g.db_session
    current_user_id = get_jwt_identity()
    user = session_db.query(User).get(current_user_id)
    if not user:
        logger.error(f"User not found for ID: {current_user_id}")
        return jsonify({"error": "User not found"}), 404

    player = session_db.query(Player).filter_by(user_id=current_user_id).first()
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
            current_season = session_db.query(Season).filter_by(is_current=True).first()
            response_data.update(get_player_stats(player, current_season, session=session_db))

    return jsonify(response_data), 200


@mobile_api.route('/player/update', endpoint='update_player_profile', methods=['PUT'])
@jwt_required()
def update_player_profile():
    """
    Update the profile of the currently authenticated player.
    """
    session_db = g.db_session
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
        # Changes will be committed at teardown.
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
    session_db = g.db_session
    current_user_id = get_jwt_identity()
    safe_current_user = session_db.query(User).get(current_user_id)
    player = session_db.query(Player).get(player_id)

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
    session_db = g.db_session

    # Retrieve current seasons for Pub League and ECS FC.
    current_pub_season = session_db.query(Season).filter_by(is_current=True, league_type='Pub League').first()
    current_ecs_season = session_db.query(Season).filter_by(is_current=True, league_type='ECS FC').first()

    # Build conditions based on which current seasons exist.
    conditions = []
    if current_pub_season:
        conditions.append(League.season_id == current_pub_season.id)
    if current_ecs_season:
        conditions.append(League.season_id == current_ecs_season.id)

    # Query teams by joining with League and applying the conditions.
    teams_query = session_db.query(Team).join(League, Team.league_id == League.id)
    if len(conditions) == 1:
        teams_query = teams_query.filter(conditions[0])
    elif len(conditions) == 2:
        teams_query = teams_query.filter(or_(*conditions))

    teams = teams_query.order_by(Team.name).all()

    teams_data = [
        {
            **team.to_dict(),
            'league_name': team.league.name if team.league else "Unknown League"
        }
        for team in teams
    ]
    return jsonify(teams_data), 200


@mobile_api.route('/teams/<int:team_id>', endpoint='get_team_details', methods=['GET'])
@jwt_required()
def get_team_details(team_id: int):
    """
    Retrieve details for a specific team. Optionally includes players
    and upcoming matches.
    """
    session_db = g.db_session
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
    session_db = g.db_session
    team = session_db.query(Team).get(team_id)
    if not team:
        return jsonify({"msg": "Team not found"}), 404

    # Fetch players for this team
    players = (session_db.query(Player)
              .join(player_teams)
              .filter(player_teams.c.team_id == team_id)
              .order_by(Player.name)
              .all())
    
    base_url = request.host_url.rstrip('/')
    default_image = f"{base_url}/static/img/default_player.png"
    
    # Build detailed player list with role information
    detailed_players = []
    for player in players:
        # Get coach status for this specific team
        is_coach = session_db.query(player_teams.c.is_coach).filter(
            player_teams.c.player_id == player.id,
            player_teams.c.team_id == team_id
        ).scalar() or False
        
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
            "is_coach": is_coach,
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
    session_db = g.db_session
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
    
    # Build match query
    query = session_db.query(Match).filter(
        or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
    )
    
    # Apply upcoming/completed filters
    if upcoming:
        query = query.filter(Match.date >= datetime.now().date())
    if completed:
        query = query.filter(Match.date < datetime.now().date())
        
    # Order by date
    query = query.order_by(Match.date)
    
    # Apply limit if specified
    if limit:
        query = query.limit(limit)
        
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
    session_db = g.db_session
    current_user_id = get_jwt_identity()
    safe_current_user = session_db.query(User).get(current_user_id)
    match = session_db.query(Match).get(match_id)
    
    if not match:
        return jsonify({"msg": "Match not found"}), 404
    
    # Check if user has appropriate roles or is on one of the teams
    user_roles = [r.name for r in safe_current_user.roles]
    is_admin_or_coach = any(r in ['Coach', 'Admin'] for r in user_roles)
    
    player = session_db.query(Player).filter_by(user_id=current_user_id).first()
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
    session_db = g.db_session
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
    
    # Get player statistics for this team
    players_stats = []
    team_players = session_db.query(Player).join(
        player_teams
    ).filter(
        player_teams.c.team_id == team_id
    ).all()
    
    for player in team_players:
        if current_season:
            player_stats = session_db.query(PlayerSeasonStats).filter_by(
                player_id=player.id,
                season_id=current_season.id
            ).first()
            
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
    
    return jsonify(stats), 200


@mobile_api.route('/teams/my_team', endpoint='get_my_team', methods=['GET'])
@jwt_required()
def get_my_team():
    """
    Retrieve the team of the currently authenticated player.
    """
    session_db = g.db_session
    current_user_id = get_jwt_identity()
    player = session_db.query(Player).filter_by(user_id=current_user_id).first()

    if not player or not player.primary_team:
        return jsonify({"msg": "Team not found"}), 404

    return get_team_details(player.primary_team.id)


@mobile_api.route('/teams/my_teams', endpoint='get_my_teams', methods=['GET'])
@jwt_required()
def get_my_teams():
    """
    Retrieve all teams the currently authenticated player is associated with.
    """
    session_db = g.db_session
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
    session_db = g.db_session
    current_user_id = get_jwt_identity()
    player = session_db.query(Player).filter_by(user_id=current_user_id).first()

    # Get optional limit parameter
    limit = request.args.get('limit')
    if limit and limit.isdigit():
        limit = int(limit)
    else:
        limit = None

    query = build_matches_query(
        team_id=request.args.get('team_id'),
        player=player,
        upcoming=request.args.get('upcoming', 'false').lower() == 'true',
        completed=request.args.get('completed', 'false').lower() == 'true',
        all_teams=request.args.get('all_teams', 'false').lower() == 'true',
        session=session_db
    )
    
    # Apply limit if provided
    if limit:
        matches = query.order_by(Match.date).limit(limit).all()
    else:
        matches = query.order_by(Match.date).all()

    matches_data = process_matches_data(
        matches=matches,
        player=player,
        include_events=request.args.get('include_events', 'false').lower() == 'true',
        include_availability=request.args.get('include_availability', 'false').lower() == 'true',
        session=session_db
    )

    return jsonify(matches_data), 200


@mobile_api.route('/matches/schedule', endpoint='get_match_schedule', methods=['GET'])
@jwt_required()
def get_match_schedule():
    """
    Retrieve the schedule of upcoming matches, grouped by date.
    """
    session_db = g.db_session
    current_user_id = get_jwt_identity()
    player = session_db.query(Player).filter_by(user_id=current_user_id).first()
    
    # Build query for upcoming matches
    query = build_matches_query(
        team_id=request.args.get('team_id'),
        player=player,
        upcoming=True,
        session=session_db
    )
    
    # Order by date and get matches
    matches = query.order_by(Match.date).all()
    
    # Group matches by date
    schedule = {}
    for match in matches:
        match_date = match.date.strftime('%Y-%m-%d')
        if match_date not in schedule:
            schedule[match_date] = []
        
        match_data = match.to_dict(include_teams=True)
        # Add availability if requested and player exists
        if player and request.args.get('include_availability', 'true').lower() == 'true':
            availability = session_db.query(Availability).filter_by(
                match_id=match.id, 
                player_id=player.id
            ).first()
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
    
    return jsonify(schedule_list), 200


@mobile_api.route('/matches/<int:match_id>', endpoint='get_single_match_details', methods=['GET'])
@jwt_required()
def get_single_match_details(match_id: int):
    """
    Retrieve detailed information for a single match.
    """
    session_db = g.db_session
    match = session_db.query(Match).get(match_id)
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

    return jsonify(match_data), 200


@mobile_api.route('/update_availability', endpoint='update_availability', methods=['POST'])
@jwt_required()
def update_availability():
    """
    Update a player's availability status for a specific match.
    """
    session_db = g.db_session
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
@jwt_role_required('Coach')
def report_match(match_id: int):
    """
    Report match details and add any related events.
    """
    session_db = g.db_session
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
    session_db = g.db_session
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
    session_db = g.db_session
    search_query = request.args.get('search', '').lower()

    players_query = session_db.query(Player).join(Team, isouter=True).filter(
        (Player.name.ilike(f"%{search_query}%")) |
        (Team.name.ilike(f"%{search_query}%"))
    )

    players_data = [build_player_response(player) for player in players_query.all()]
    return jsonify(players_data), 200