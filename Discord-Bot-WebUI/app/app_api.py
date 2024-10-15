# app/app_api.py

from app import csrf, db
from flask import Blueprint, jsonify, request, current_app, url_for, session
from flask_jwt_extended import jwt_required, create_access_token, get_jwt_identity
from app.models import User, Player, Team, Match, League, Season, PlayerSeasonStats, PlayerCareerStats, Availability, Feedback, Standings, PlayerEvent, Notification, PlayerEventType
from app.decorators import jwt_role_required, jwt_permission_required, jwt_admin_or_owner_required
from datetime import datetime, timedelta
from urllib.parse import urlencode
import requests
import secrets
import hashlib
import base64

mobile_api = Blueprint('mobile_api', __name__)
csrf.exempt(mobile_api)

def generate_pkce_codes():
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip('=')
    return code_verifier, code_challenge

@mobile_api.route('/login', methods=['POST'])
def login():
    email = request.json.get('email', None)
    password = request.json.get('password', None)

    user = User.query.filter_by(email=email.lower()).first()

    if not user or not user.check_password(password):
        return jsonify({"msg": "Bad username or password"}), 401

    if not user.is_approved:
        return jsonify({"msg": "Account not approved"}), 403

    if user.is_2fa_enabled:
        return jsonify({"msg": "2FA required", "user_id": user.id}), 200

    access_token = create_access_token(identity=user.id)
    return jsonify(access_token=access_token), 200

@mobile_api.route('/verify_2fa', methods=['POST'])
def verify_2fa():
    user_id = request.json.get('user_id', None)
    token = request.json.get('token', None)
    print(f"Received user_id: {user_id}, token: {token}")

    user = User.query.get(user_id)
    if not user or not user.verify_totp(token):
        return jsonify({"msg": "Invalid 2FA token"}), 401

    access_token = create_access_token(identity=user.id)
    return jsonify(access_token=access_token), 200

@mobile_api.route('/user_profile', methods=['GET'])
@jwt_required()
def get_user_profile():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if not user:
        current_app.logger.error(f"User not found for ID: {current_user_id}")
        return jsonify({"error": "User not found"}), 404

    player = Player.query.filter_by(user_id=current_user_id).first()

    # Get the base URL dynamically
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
            # Check if the URL is already absolute
            if profile_picture_url.startswith('http'):
                full_profile_picture_url = profile_picture_url
            else:
                full_profile_picture_url = f"{base_url}{profile_picture_url}"
        else:
            # Provide a default profile picture URL
            full_profile_picture_url = f"{base_url}/static/img/default_player.png"

        response_data.update({
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
        })

        include_stats = request.args.get('include_stats', 'false').lower() == 'true'
        if include_stats:
            current_season = Season.query.filter_by(is_current=True).first()
            season_stats = PlayerSeasonStats.query.filter_by(player_id=player.id, season_id=current_season.id).first()
            career_stats = PlayerCareerStats.query.filter_by(player_id=player.id).first()

            response_data['season_stats'] = season_stats.to_dict() if season_stats else None
            response_data['career_stats'] = career_stats.to_dict() if career_stats else None

    current_app.logger.info(f"User profile fetched: {response_data}")
    return jsonify(response_data), 200

@mobile_api.route('/player/update', methods=['PUT'])
@jwt_required()
def update_player_profile():
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()
    if not player:
        return jsonify({"msg": "Player not found"}), 404

    data = request.json
    allowed_fields = ['name', 'phone', 'jersey_size', 'jersey_number', 'pronouns',
                      'favorite_position', 'other_positions', 'positions_not_to_play',
                      'frequency_play_goal', 'expected_weeks_available', 'unavailable_dates',
                      'willing_to_referee', 'additional_info']
    for field in allowed_fields:
        if field in data:
            setattr(player, field, data[field])

    db.session.commit()
    return jsonify({"msg": "Profile updated successfully", "player": player.to_dict()}), 200

@mobile_api.route('/players/<int:player_id>', methods=['GET'])
@jwt_required()
def get_player(player_id):
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    player = Player.query.get(player_id)

    if not player:
        return jsonify({"msg": "Player not found"}), 404

    # Get current season
    current_season = Season.query.filter_by(is_current=True).first()

    # Fetch season stats for the current season
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player.id, season_id=current_season.id).first()
    
    # Fetch career stats
    career_stats = PlayerCareerStats.query.filter_by(player_id=player.id).first()

    # Determine if the current user has permission to view full profile
    is_full_profile = current_user.has_role('Coach') or current_user.has_role('Admin') or current_user_id == player.user_id

    player_data = player.to_dict()
    player_data.update({
        'team_name': player.team.name if player.team else None,
        'league_name': player.league.name if player.league else None,
        'season_stats': season_stats.to_dict() if season_stats else None,
        'career_stats': career_stats.to_dict() if career_stats else None,
    })

    if is_full_profile:
        # Include additional fields for full profile view
        player_data.update({
            'email': player.user.email,
            'phone': player.phone,
            'is_phone_verified': player.is_phone_verified,
            'pronouns': player.pronouns,
            'unavailable_dates': player.unavailable_dates,
            'willing_to_referee': player.willing_to_referee,
            'positions_not_to_play': player.positions_not_to_play,
            'additional_info': player.additional_info,
        })

    return jsonify(player_data), 200

@mobile_api.route('/teams', methods=['GET'])
@jwt_required()
def get_teams():
    teams = Team.query.all()
    teams_data = []
    
    for team in teams:
        team_data = team.to_dict()
        
        # Add the league_name to the team data
        if team.league:
            team_data['league_name'] = team.league.name
        else:
            team_data['league_name'] = "Unknown League"
        
        teams_data.append(team_data)
    
    return jsonify(teams_data), 200

@mobile_api.route('/teams/<int:team_id>', methods=['GET'])
@jwt_required()
def get_team_details(team_id):
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"msg": "Team not found"}), 404

    include_players = request.args.get('include_players', 'false').lower() == 'true'
    team_data = team.to_dict(include_players=include_players)

    # Get the base URL dynamically
    base_url = request.host_url.rstrip('/')

    # Update any image URLs in the team data to be absolute URLs
    if team_data.get('logo_url'):
        if not team_data['logo_url'].startswith('http'):
            team_data['logo_url'] = f"{base_url}{team_data['logo_url']}"

    # Include upcoming matches if requested
    include_matches = request.args.get('include_matches', 'false').lower() == 'true'
    if include_matches:
        upcoming_matches = Match.query.filter(
            ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)) &
            (Match.date >= datetime.utcnow())
        ).order_by(Match.date).limit(5).all()
        team_data['upcoming_matches'] = [match.to_dict() for match in upcoming_matches]

    return jsonify(team_data), 200

@mobile_api.route('/teams/my_team', methods=['GET'])
@jwt_required()
def get_my_team():
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()
    if not player or not player.team:
        return jsonify({"msg": "Team not found"}), 404
    return get_team_details(player.team.id)

@mobile_api.route('/matches', methods=['GET'])
@jwt_required()
def get_matches():
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()

    team_id = request.args.get('team_id')
    upcoming = request.args.get('upcoming', 'false').lower() == 'true'

    query = Match.query
    if team_id:
        query = query.filter(
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
        )
    elif player and player.team_id:
        query = query.filter(
            (Match.home_team_id == player.team_id) | (Match.away_team_id == player.team_id)
        )
    if upcoming:
        query = query.filter(Match.date >= datetime.utcnow())

    matches = query.order_by(Match.date).all()

    include_events = request.args.get('include_events', 'false').lower() == 'true'
    include_availability = request.args.get('include_availability', 'false').lower() == 'true'

    matches_data = []
    for match in matches:
        match_data = match.to_dict(include_teams=True)
        if include_events:
            match_data['events'] = [event.to_dict() for event in match.events]
        if include_availability and player:
            availability = Availability.query.filter_by(match_id=match.id, player_id=player.id).first()
            match_data['availability'] = availability.to_dict() if availability else None
        matches_data.append(match_data)

    return jsonify(matches_data), 200

@mobile_api.route('/matches/<int:match_id>', methods=['GET'])
@jwt_required()
def get_match_details(match_id):
    match = Match.query.get(match_id)
    if not match:
        return jsonify({"msg": "Match not found"}), 404

    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()

    include_events = request.args.get('include_events', 'true').lower() == 'true'
    include_teams = request.args.get('include_teams', 'true').lower() == 'true'
    include_players = request.args.get('include_players', 'true').lower() == 'true'

    match_data = match.to_dict(include_teams=include_teams, include_events=include_events)
    
    if include_players:
        match_data['home_team']['players'] = [
            {
                'id': p.id,
                'name': p.name,
                'availability': Availability.query.filter_by(match_id=match.id, player_id=p.id).first().response if Availability.query.filter_by(match_id=match.id, player_id=p.id).first() else 'Not responded'
            } for p in match.home_team.players
        ]
        match_data['away_team']['players'] = [
            {
                'id': p.id,
                'name': p.name,
                'availability': Availability.query.filter_by(match_id=match.id, player_id=p.id).first().response if Availability.query.filter_by(match_id=match.id, player_id=p.id).first() else 'Not responded'
            } for p in match.away_team.players
        ]

    # Add card statistics
    home_yellow_cards = sum(1 for event in match.events if event.event_type == PlayerEventType.YELLOW_CARD and event.player.team_id == match.home_team_id)
    away_yellow_cards = sum(1 for event in match.events if event.event_type == PlayerEventType.YELLOW_CARD and event.player.team_id == match.away_team_id)
    home_red_cards = sum(1 for event in match.events if event.event_type == PlayerEventType.RED_CARD and event.player.team_id == match.home_team_id)
    away_red_cards = sum(1 for event in match.events if event.event_type == PlayerEventType.RED_CARD and event.player.team_id == match.away_team_id)

    match_data.update({
        'home_team_yellow_cards': home_yellow_cards,
        'away_team_yellow_cards': away_yellow_cards,
        'home_team_red_cards': home_red_cards,
        'away_team_red_cards': away_red_cards,
    })

    # Add current user's availability
    if player:
        availability = Availability.query.filter_by(match_id=match.id, player_id=player.id).first()
        match_data['availability'] = availability.to_dict() if availability else None

    return jsonify(match_data), 200

@mobile_api.route('/update_availability', methods=['POST'])
@jwt_required()
def update_availability():
    current_user_id = get_jwt_identity()
    player = Player.query.filter_by(user_id=current_user_id).first()
    if not player:
        return jsonify({"msg": "Player not found"}), 404

    match_id = request.json.get('match_id')
    availability_status = request.json.get('availability')

    if not match_id or not availability_status:
        return jsonify({"msg": "Missing match_id or availability status"}), 400

    match = Match.query.get(match_id)
    if not match:
        return jsonify({"msg": "Match not found"}), 404

    availability = Availability.query.filter_by(match_id=match_id, player_id=player.id).first()
    if availability:
        availability.response = availability_status
        availability.responded_at = datetime.utcnow()
    else:
        availability = Availability(
            match_id=match_id,
            player_id=player.id,
            discord_id=player.discord_id,
            response=availability_status,
            responded_at=datetime.utcnow()
        )
        db.session.add(availability)

    db.session.commit()
    return jsonify({"msg": "Availability updated successfully"}), 200

@mobile_api.route('/report_match/<int:match_id>', methods=['POST'])
@jwt_required()
@jwt_role_required('Coach')
def report_match(match_id):
    match = Match.query.get(match_id)
    if not match:
        return jsonify({"msg": "Match not found"}), 404

    data = request.json
    match.home_team_score = data.get('home_team_score')
    match.away_team_score = data.get('away_team_score')
    match.notes = data.get('notes')

    # Add match events
    for event in data.get('events', []):
        new_event = PlayerEvent(
            player_id=event['player_id'],
            match_id=match_id,
            event_type=event['event_type'],
            minute=event.get('minute')
        )
        db.session.add(new_event)

    db.session.commit()
    return jsonify({"msg": "Match reported successfully", "match": match.to_dict()}), 200

@mobile_api.route('/draft_player', methods=['POST'])
@jwt_required()
@jwt_role_required('Coach')
def draft_player():
    data = request.json
    player_id = data.get('player_id')
    team_id = data.get('team_id')

    player = Player.query.get(player_id)
    team = Team.query.get(team_id)

    if not player or not team:
        return jsonify({"msg": "Player or team not found"}), 404

    player.team_id = team_id
    db.session.commit()

    return jsonify({"msg": "Player drafted successfully", "player": player.to_dict()}), 200

@mobile_api.route('/standings', methods=['GET'])
@jwt_required()
def get_standings():
    season_id = request.args.get('season_id')
    if not season_id:
        current_season = Season.query.filter_by(is_current=True).first()
        if not current_season:
            return jsonify({"msg": "No current season found"}), 404
        season_id = current_season.id

    standings = Standings.query.filter_by(season_id=season_id).order_by(Standings.points.desc()).all()
    return jsonify([standing.to_dict() for standing in standings]), 200

@mobile_api.route('/feedback', methods=['POST'])
@jwt_required()
def submit_feedback():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    data = request.json
    new_feedback = Feedback(
        user_id=user.id,
        category=data.get('category'),
        title=data.get('title'),
        description=data.get('description'),
        priority=data.get('priority', 'Low')
    )

    db.session.add(new_feedback)
    db.session.commit()

    return jsonify({"msg": "Feedback submitted successfully", "feedback": new_feedback.to_dict()}), 201

@mobile_api.route('/leagues', methods=['GET'])
@jwt_required()
def get_leagues():
    leagues = League.query.all()
    return jsonify([league.to_dict() for league in leagues]), 200

@mobile_api.route('/leagues/<int:league_id>', methods=['GET'])
@jwt_required()
def get_league_details(league_id):
    league = League.query.get(league_id)
    if not league:
        return jsonify({"msg": "League not found"}), 404
    include_teams = request.args.get('include_teams', 'false').lower() == 'true'
    league_data = league.to_dict(include_teams=include_teams)
    return jsonify(league_data), 200

@mobile_api.route('/seasons', methods=['GET'])
@jwt_required()
def get_seasons():
    seasons = Season.query.all()
    return jsonify([season.to_dict() for season in seasons]), 200

@mobile_api.route('/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    current_user_id = get_jwt_identity()
    notifications = Notification.query.filter_by(user_id=current_user_id).order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify([notification.to_dict() for notification in notifications]), 200

@mobile_api.route('/get_discord_auth_url', methods=['GET'])
def get_discord_auth_url():
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
    return jsonify({'auth_url': discord_auth_url})

@mobile_api.route('/discord_callback', methods=['POST'])
def discord_callback():
    current_app.logger.info("Received request at /discord_callback")
    code = request.json.get('code')
    redirect_uri = request.json.get('redirect_uri')
    code_verifier = session.get('code_verifier')
    current_app.logger.info(f"Code: {code}, Redirect URI: {redirect_uri}, Code Verifier: {code_verifier}")
    
    if not code or not redirect_uri or not code_verifier:
        current_app.logger.error("Missing required parameters")
        return jsonify({'error': 'Missing required parameters'}), 400

    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    discord_client_secret = current_app.config['DISCORD_CLIENT_SECRET']

    data = {
        'client_id': discord_client_id,
        'client_secret': discord_client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'code_verifier': code_verifier,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    try:
        current_app.logger.info("Sending request to Discord API")
        response = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
        response.raise_for_status()
        current_app.logger.info("Received response from Discord API")

        # Rest of the code...

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Discord API error: {str(e)}")
        current_app.logger.error(f"Request data: {data}")
        current_app.logger.error(f"Response text: {e.response.text}")
        return jsonify({'error': 'Error communicating with Discord'}), 500

    except Exception as e:
        current_app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@mobile_api.route('/players', methods=['GET'])
@jwt_required()
def get_players():
    search_query = request.args.get('search', '').lower()
    
    # Filter players based on search query (name or team)
    players_query = Player.query.filter(
        (Player.name.ilike(f"%{search_query}%")) |
        (Player.team.has(Team.name.ilike(f"%{search_query}%")))
    )
    
    players = players_query.all()
    players_data = []

    for player in players:
        player_data = {
            'id': player.id,
            'name': player.name,
            'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
            'team_name': player.team.name if player.team else None,
            'league_name': player.league.name if player.league else None,
        }
        players_data.append(player_data)
    
    return jsonify(players_data), 200
