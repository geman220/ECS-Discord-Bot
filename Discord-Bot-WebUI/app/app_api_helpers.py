from flask import current_app, request, g, abort
from app.models import (
    User, Player, Team, Match, League, Season,
    PlayerSeasonStats, PlayerCareerStats, Availability,
    PlayerEvent, PlayerEventType
)
from datetime import datetime
from sqlalchemy import func, or_
from typing import Optional, Dict, Any, List, Tuple, Union
from sqlalchemy.orm.query import Query
import secrets
import hashlib
import base64
import requests
import logging

logger = logging.getLogger(__name__)

def generate_pkce_codes() -> Tuple[str, str]:
    """Generate PKCE codes for OAuth flow."""
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip('=')
    return code_verifier, code_challenge

def exchange_discord_code(code: str, redirect_uri: str, code_verifier: str) -> Dict:
    """Exchange Discord authorization code for access token."""
    try:
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
        response = requests.post('https://discord.com/api/oauth2/token', 
                               data=data, headers=headers)
        response.raise_for_status()
        
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Discord token exchange failed: {str(e)}")
        raise

def get_discord_user_data(access_token: str) -> Dict:
    """Get Discord user data using access token."""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get('https://discord.com/api/users/@me', headers=headers)
        response.raise_for_status()
        
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Discord user data: {str(e)}")
        raise

def process_discord_user(user_data: Dict) -> User:
    """Process Discord user data and create/update user."""
    session = g.db_session
    email = user_data.get('email', '').lower()
    discord_id = user_data.get('id')
    
    user = session.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        user = User(
            email=email,
            username=user_data.get('username'),
            is_approved=False
        )
        session.add(user)

    # Once user is persisted, ensure we have their player
    player = session.query(Player).filter_by(user_id=user.id).first()
    if player and not player.discord_id:
        player.discord_id = discord_id

    return user

def build_player_response(player: Player) -> Dict[str, Any]:
    """Build player response data."""
    base_url = request.host_url.rstrip('/')
    return {
        'id': player.id,
        'name': player.name,
        'profile_picture_url': (
            f"{base_url}{player.profile_picture_url}" 
            if player.profile_picture_url 
            else f"{base_url}/static/img/default_player.png"
        ),
        'team_name': player.team.name if player.team else None,
        'league_name': player.league.name if player.league else None,
    }

def get_player_stats(player: Player, season: Season, session=None) -> Dict[str, Any]:
    """Get player's season and career stats."""
    if session is None:
        session = g.db_session

    season_stats = session.query(PlayerSeasonStats).filter_by(
        player_id=player.id, 
        season_id=season.id
    ).first()
    
    career_stats = session.query(PlayerCareerStats).filter_by(
        player_id=player.id
    ).first()

    return {
        'season_stats': season_stats.to_dict() if season_stats else None,
        'career_stats': career_stats.to_dict() if career_stats else None
    }

def update_match_details(match: Match, data: Dict, session=None) -> None:
    """Update match scores and notes."""
    if session is None:
        session = g.db_session

    logger.info(f"Updating match {match.id} details")
    match.home_team_score = data.get('home_team_score')
    match.away_team_score = data.get('away_team_score')
    match.notes = data.get('notes')

def add_match_events(match: Match, events: List[Dict], session=None) -> None:
    """Add events to match."""
    if session is None:
        session = g.db_session

    logger.info(f"Adding {len(events)} events to match {match.id}")
    for event_data in events:
        event = PlayerEvent(
            player_id=event_data['player_id'],
            match_id=match.id,
            event_type=event_data['event_type'],
            minute=event_data.get('minute')
        )
        session.add(event)

def update_player_availability(match_id: int, player_id: int, 
                               discord_id: Optional[str], response: str, session=None) -> Availability:
    """Update or create player availability record."""
    if session is None:
        session = g.db_session

    logger.info(f"Updating availability for player {player_id} in match {match_id}")
    availability = session.query(Availability).filter_by(
        match_id=match_id,
        player_id=player_id
    ).first()
    if availability:
        availability.response = response
        availability.responded_at = datetime.utcnow()
    else:
        availability = Availability(
            match_id=match_id,
            player_id=player_id,
            discord_id=discord_id,
            response=response,
            responded_at=datetime.utcnow()
        )
        session.add(availability)
    return availability

def build_match_response(match: Match, include_events: bool, 
                         include_teams: bool, include_players: bool, 
                         current_player: Optional[Player], session=None) -> Dict:
    """Build detailed match response data."""
    if session is None:
        session = g.db_session

    match_data = match.to_dict(include_teams=include_teams)

    if include_players and include_teams:
        if match.home_team:
            match_data['home_team']['players'] = get_team_players_availability(
                match, match.home_team.players, session=session)
        if match.away_team:
            match_data['away_team']['players'] = get_team_players_availability(
                match, match.away_team.players, session=session)

    if include_events:
        match_data.update(get_match_events(match))

    if current_player:
        match_data['availability'] = get_player_availability(match, current_player, session=session)

    return match_data

def get_team_players_availability(match: Match, players: List[Player], session=None) -> List[Dict]:
    """Get availability status for team players."""
    if session is None:
        session = g.db_session

    player_ids = [p.id for p in players]
    availabilities = {
        avail.player_id: avail.response
        for avail in session.query(Availability).filter(
            Availability.match_id == match.id,
            Availability.player_id.in_(player_ids)
        )
    }
    
    return [{
        'id': player.id,
        'name': player.name,
        'availability': availabilities.get(player.id, 'Not responded')
    } for player in players]

def get_match_events(match: Match) -> Dict[str, int]:
    """Get all events for a match with statistics."""
    # match.events should be already loaded or accessible
    events = match.events
    return {
        'home_yellow_cards': sum(1 for event in events
            if event.event_type == PlayerEventType.YELLOW_CARD 
            and event.player.team_id == match.home_team_id),
        'away_yellow_cards': sum(1 for event in events
            if event.event_type == PlayerEventType.YELLOW_CARD 
            and event.player.team_id == match.away_team_id),
        'home_red_cards': sum(1 for event in events
            if event.event_type == PlayerEventType.RED_CARD 
            and event.player.team_id == match.home_team_id),
        'away_red_cards': sum(1 for event in events
            if event.event_type == PlayerEventType.RED_CARD 
            and event.player.team_id == match.away_team_id)
    }

def get_player_availability(match: Match, player: Player, session=None) -> Optional[Dict]:
    """Get player's availability for a match."""
    if session is None:
        session = g.db_session

    availability = session.query(Availability).filter_by(
        match_id=match.id,
        player_id=player.id
    ).first()
    return availability.to_dict() if availability else None

def build_matches_query(team_id: Optional[int], player: Optional[Player], 
                        upcoming: bool = False, session=None) -> Query:
    """Build query for matches based on filters."""
    if session is None:
        session = g.db_session

    query = session.query(Match)
    if team_id:
        query = query.filter(
            or_(Match.home_team_id == team_id, 
                Match.away_team_id == team_id)
        )
    elif player and player.team_id:
        query = query.filter(
            or_(Match.home_team_id == player.team_id,
                Match.away_team_id == player.team_id)
        )
    
    if upcoming:
        query = query.filter(Match.date >= datetime.utcnow())
    
    return query

def process_matches_data(matches: List[Match], player: Optional[Player], 
                         include_events: bool = False, 
                         include_availability: bool = False, session=None) -> List[Dict]:
    """Process matches data with optional includes."""
    if session is None:
        session = g.db_session

    matches_data = []
    for match in matches:
        match_data = match.to_dict(include_teams=True)
        
        if include_events:
            # ensure events are loaded or accessible
            match_data['events'] = [event.to_dict() for event in match.events]
            
        if include_availability and player:
            availability = session.query(Availability).filter_by(
                match_id=match.id, 
                player_id=player.id
            ).first()
            match_data['availability'] = availability.to_dict() if availability else None
            
        matches_data.append(match_data)
    
    return matches_data

def notify_availability_update(match_id: int, player_id: int, 
                               response: str, session=None) -> None:
    """Notify relevant systems of availability update."""
    logger.info(f"Processing availability update notifications for "
                f"match {match_id}, player {player_id}")
    
    from app.tasks import notify_discord_of_rsvp_change_task
    from app.tasks import notify_frontend_of_rsvp_change_task
    
    # These tasks likely do not need direct session
    notify_discord_of_rsvp_change_task.delay(match_id)
    notify_frontend_of_rsvp_change_task.delay(match_id, player_id, response)

def update_player_match_availability(match_id: int, player_id: int, 
                                     new_response: str, session=None) -> bool:
    if session is None:
        session = g.db_session

    try:
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return False

        update_player_availability(
            match_id=match_id,
            player_id=player_id, 
            discord_id=player.discord_id,
            response=new_response,
            session=session
        )
        
        logger.info(f"Updated availability for player {player_id} to {new_response}")
        return True

    except Exception as e:
        logger.error(f"Error updating availability: {str(e)}")
        raise

def get_team_upcoming_matches(team_id: int, session=None) -> List[Dict]:
    """Get upcoming matches for a team."""
    if session is None:
        session = g.db_session

    upcoming_matches = session.query(Match).filter(
        ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)) &
        (Match.date >= datetime.utcnow())
    ).order_by(Match.date).limit(5).all()
    
    return [match.to_dict() for match in upcoming_matches]
