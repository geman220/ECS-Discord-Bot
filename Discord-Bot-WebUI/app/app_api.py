# app_api.py

from flask import Blueprint, jsonify, request, current_app, url_for, session
from flask_jwt_extended import jwt_required, create_access_token, get_jwt_identity
from app import csrf, db
from app.models import (
    User, Player, Team, Match, League, Season,
    PlayerSeasonStats, PlayerCareerStats, Availability,
    Feedback, Standings, PlayerEvent, PlayerEventType, Notification
)
from app.decorators import (
    jwt_role_required, jwt_permission_required,
    jwt_admin_or_owner_required, db_operation, query_operation
)
from app.app_api_helpers import (
    build_player_response, exchange_discord_code,
    get_discord_user_data, process_discord_user,
    build_match_response, get_team_players_availability,
    get_match_events, get_player_availability,
    build_matches_query, process_matches_data,
    get_player_stats, generate_pkce_codes,
    update_match_details, add_match_events,
    update_player_availability, notify_availability_update,
    update_player_match_availability, get_team_upcoming_matches
)
from datetime import datetime, timedelta
from urllib.parse import urlencode
import hashlib
import base64
import requests
import logging

logger = logging.getLogger(__name__)

mobile_api = Blueprint('mobile_api', __name__)
csrf.exempt(mobile_api)

@mobile_api.before_request
def limit_remote_addr():
    """Restrict API access to allowed hosts."""
    allowed_hosts = ['127.0.0.1:5000', 'localhost:5000', 'webui:5000']
    if request.host not in allowed_hosts:
        return "Access Denied", 403

@mobile_api.route('/login', methods=['POST'])
@db_operation
def login():
    """
    Handle user login and return JWT token.
    
    Returns:
        tuple: JSON response and status code
    """
    email = request.json.get('email')
    password = request.json.get('password')

    if not email or not password:
        return jsonify({"msg": "Missing username or password"}), 400

    user = User.query.filter_by(email=email.lower()).first()

    if not user or not user.check_password(password):
        return jsonify({"msg": "Bad username or password"}), 401

    if not user.is_approved:
        return jsonify({"msg": "Account not approved"}), 403

    if user.is_2fa_enabled:
        return jsonify({
            "msg": "2FA required", 
            "user_id": user.id
        }), 200

    access_token = create_access_token(identity=user.id)
    return jsonify(access_token=access_token), 200

@mobile_api.route('/verify_2fa', methods=['POST'])
@db_operation
def verify_2fa():
    """
    Verify 2FA token and complete login process.
    
    Returns:
        tuple: JSON response and status code
    """
    user_id = request.json.get('user_id')
    token = request.json.get('token')
    logger.debug(f"Received user_id: {user_id}, token: {token}")

    if not user_id or not token:
        return jsonify({"msg": "Missing user_id or token"}), 400

    user = User.query.get(user_id)
    if not user or not user.verify_totp(token):
        return jsonify({"msg": "Invalid 2FA token"}), 401

    access_token = create_access_token(identity=user.id)
    return jsonify(access_token=access_token), 200

@mobile_api.route('/user_profile', methods=['GET'])
@jwt_required()
@query_operation
def get_user_profile():
    """
    Get current user's profile information.
    
    Returns:
        tuple: JSON response and status code
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if not user:
        logger.error(f"User not found for ID: {current_user_id}")
        return jsonify({"error": "User not found"}), 404

    player = Player.query.filter_by(user_id=current_user_id).first()
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
            "team_id": player.team_id,
            "team_name": player.team.name if player.team else None,
            "league_name": player.league.name if player.league else None,
        }
        response_data.update(player_data)

        include_stats = request.args.get('include_stats', 'false').lower() == 'true'
        if include_stats:
            current_season = Season.query.filter_by(is_current=True).first()
            response_data.update(get_player_stats(player, current_season))

    return jsonify(response_data), 200

@mobile_api.route('/player/update', methods=['PUT'])
@jwt_required()
@db_operation
def update_player_profile():
    """Update player profile information."""
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()
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
        return jsonify({
            "msg": f"Error updating profile: {str(e)}"
        }), 500

@mobile_api.route('/players/<int:player_id>', methods=['GET'])
@jwt_required()
@query_operation
def get_player(player_id: int):
    """Get player details with stats."""
    current_user_id = get_jwt_identity()
    safe_current_user = User.query.get(current_user_id)
    player = Player.query.get(player_id)

    if not player:
        return jsonify({"msg": "Player not found"}), 404

    # Check viewing permissions
    is_admin = any(role.name in ['Coach', 'Admin'] for role in safe_current_user.roles)
    is_owner = current_user_id == player.user_id
    is_full_profile = is_admin or is_owner

    response_data = get_player_response_data(player, is_full_profile)
    return jsonify(response_data), 200

@mobile_api.route('/teams', methods=['GET'])
@jwt_required()
@query_operation
def get_teams():
    """Get all teams with league information."""
    teams = Team.query.all()
    return jsonify([
        {
            **team.to_dict(),
            'league_name': team.league.name if team.league else "Unknown League"
        } for team in teams
    ]), 200

@mobile_api.route('/teams/<int:team_id>', methods=['GET'])
@jwt_required()
@query_operation
def get_team_details(team_id: int):
    """
    Get detailed team information including players and matches.
    
    Args:
        team_id: Team ID
    """
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"msg": "Team not found"}), 404

    include_players = request.args.get('include_players', 'false').lower() == 'true'
    team_data = team.to_dict(include_players=include_players)

    # Update image URLs to be absolute
    base_url = request.host_url.rstrip('/')
    if team_data.get('logo_url'):
        if not team_data['logo_url'].startswith('http'):
            team_data['logo_url'] = f"{base_url}{team_data['logo_url']}"

    # Include upcoming matches if requested
    if request.args.get('include_matches', 'false').lower() == 'true':
        team_data['upcoming_matches'] = get_team_upcoming_matches(team_id)

    return jsonify(team_data), 200

@mobile_api.route('/teams/my_team', methods=['GET'])
@jwt_required()
@query_operation
def get_my_team():
    """Get current user's team details."""
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()
    
    if not player or not player.team:
        return jsonify({"msg": "Team not found"}), 404
    
    return get_team_details(player.team.id)

@mobile_api.route('/matches', methods=['GET'])
@jwt_required()
@query_operation
def get_all_matches():
    """Get all matches based on filters."""
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()

    # Apply filters
    query = build_matches_query(
        team_id=request.args.get('team_id'),
        player=player,
        upcoming=request.args.get('upcoming', 'false').lower() == 'true'
    )

    matches = query.order_by(Match.date).all()
    
    # Process match data with optional includes
    matches_data = process_matches_data(
        matches=matches,
        player=player,
        include_events=request.args.get('include_events', 'false').lower() == 'true',
        include_availability=request.args.get('include_availability', 'false').lower() == 'true'
    )

    return jsonify(matches_data), 200

@mobile_api.route('/matches/<int:match_id>', methods=['GET'])
@jwt_required()
@query_operation
def get_single_match_details(match_id: int):
    """Get detailed match information for a specific match."""
    match = Match.query.get(match_id)
    if not match:
        return jsonify({"msg": "Match not found"}), 404

    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()

    match_data = build_match_response(
        match=match,
        include_events=request.args.get('include_events', 'true').lower() == 'true',
        include_teams=request.args.get('include_teams', 'true').lower() == 'true',
        include_players=request.args.get('include_players', 'true').lower() == 'true',
        current_player=player
    )

    return jsonify(match_data), 200

@mobile_api.route('/update_availability', methods=['POST'])
@jwt_required()
@db_operation
def update_availability():
    """Update player's availability for a match."""
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()
    if not player:
        return jsonify({"msg": "Player not found"}), 404

    data = request.json
    match_id = data.get('match_id')
    availability_status = data.get('availability')

    if not match_id or not availability_status:
        return jsonify({"msg": "Missing match_id or availability status"}), 400

    if availability_status not in ['yes', 'no', 'maybe']:
        return jsonify({"msg": "Invalid availability status"}), 400

    match = Match.query.get(match_id)
    if not match:
        return jsonify({"msg": "Match not found"}), 404

    try:
        availability = update_player_availability(
            match_id=match_id,
            player_id=player.id,
            discord_id=player.discord_id,
            response=availability_status
        )
        return jsonify({"msg": "Availability updated successfully"}), 200
    except Exception as e:
        logger.error(f"Error updating availability: {str(e)}")
        return jsonify({
            "msg": "An error occurred while updating availability"
        }), 500

@mobile_api.route('/report_match/<int:match_id>', methods=['POST'])
@jwt_required()
@jwt_role_required('Coach')
@db_operation
def report_match(match_id: int):
    """Report match results and events."""
    match = Match.query.get(match_id)
    if not match:
        return jsonify({"msg": "Match not found"}), 404

    try:
        data = request.json
        update_match_details(match, data)
        add_match_events(match, data.get('events', []))
        
        return jsonify({
            "msg": "Match reported successfully",
            "match": match.to_dict()
        }), 200
    except Exception as e:
        logger.error(f"Error reporting match: {str(e)}")
        return jsonify({"msg": f"Error reporting match: {str(e)}"}), 500

@mobile_api.route('/matches', methods=['GET'])
@jwt_required()
@query_operation
def get_matches():
    """Get filtered matches with optional includes."""
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()

    team_id = request.args.get('team_id')
    upcoming = request.args.get('upcoming', 'false').lower() == 'true'

    matches_query = build_matches_query(team_id, player, upcoming)
    matches = matches_query.order_by(Match.date).all()

    matches_data = process_matches_data(
        matches=matches,
        player=player,
        include_events=request.args.get('include_events', 'false').lower() == 'true',
        include_availability=request.args.get('include_availability', 'false').lower() == 'true'
    )

    return jsonify(matches_data), 200

@mobile_api.route('/matches/<int:match_id>', methods=['GET'])
@jwt_required()
@query_operation
def get_match_details(match_id: int):
    """Get detailed match information."""
    match = Match.query.get_or_404(match_id)
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()

    match_data = build_match_response(
        match=match,
        include_events=True,
        include_teams=True,
        include_players=True,
        current_player=player
    )

    return jsonify(match_data), 200

@mobile_api.route('/update_availability_web', methods=['POST'])
@jwt_required()
@db_operation
def update_availability_web():
    """Update match availability through web interface."""
    data = request.json
    logger.info(f"Received web update data: {data}")
    
    match_id = data.get('match_id')
    player_id = data.get('player_id')
    new_response = data.get('response')
    
    if not all([match_id, player_id, new_response]):
        logger.error("Invalid data received from web")
        return jsonify({"error": "Invalid data"}), 400
    
    success = update_player_match_availability(match_id, player_id, new_response)
    
    if success:
        notify_availability_update(match_id, player_id, new_response)
        return jsonify({"message": "Availability updated successfully"}), 200
    
    return jsonify({"error": "Failed to update availability"}), 500

@mobile_api.route('/get_discord_auth_url', methods=['GET'])
@query_operation
def get_discord_auth_url():
    """Generate Discord OAuth URL with PKCE flow."""
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = request.args.get('redirect_uri', 'ecs-fc-scheme://auth')
    code_verifier, code_challenge = generate_pkce_codes()
    
    params = {
        'client_id': discord_client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'identify email',
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
    }
    
    discord_auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    session['code_verifier'] = code_verifier
    
    logger.info(f"Generated Discord auth URL with PKCE for redirect_uri: {redirect_uri}")
    return jsonify({'auth_url': discord_auth_url})

@mobile_api.route('/discord_callback', methods=['POST'])
@db_operation
def discord_callback():
    """Handle Discord OAuth callback and create/update user."""
    code = request.json.get('code')
    redirect_uri = request.json.get('redirect_uri')
    code_verifier = session.get('code_verifier')
    
    if not all([code, redirect_uri, code_verifier]):
        logger.error("Missing required OAuth parameters")
        return jsonify({'error': 'Missing required parameters'}), 400

    try:
        token_data = exchange_discord_code(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier
        )
        
        user_data = get_discord_user_data(token_data['access_token'])
        user = process_discord_user(user_data)
        
        if user.is_2fa_enabled:
            return jsonify({"msg": "2FA required", "user_id": user.id}), 200
        
        access_token = create_access_token(identity=user.id)
        session.pop('code_verifier', None)
        
        return jsonify(access_token=access_token), 200
    
    except Exception as e:
        logger.error(f"Discord authentication error: {str(e)}")
        return jsonify({'error': 'Error processing Discord authentication'}), 500

@mobile_api.route('/players', methods=['GET'])
@jwt_required()
@query_operation
def get_players():
    """Get filtered list of players."""
    search_query = request.args.get('search', '').lower()
    
    players_query = Player.query.filter(
        (Player.name.ilike(f"%{search_query}%")) |
        (Player.team.has(Team.name.ilike(f"%{search_query}%")))
    )
    
    players_data = [build_player_response(player) for player in players_query.all()]
    return jsonify(players_data), 200
