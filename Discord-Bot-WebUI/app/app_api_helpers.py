# app/app_api_helpers.py

"""
Helper Functions for the Mobile API

This module contains utility functions for:
- Generating PKCE codes for OAuth flows.
- Exchanging Discord authorization codes for access tokens and retrieving Discord user data.
- Processing Discord user data to create/update local user records.
- Building response payloads for players, matches, and events.
- Querying and updating player statistics, availability, and match details.
- Notifying external systems of updates (e.g., via background tasks).

These functions are used throughout the mobile API endpoints.
"""

# Standard library imports
import base64
import hashlib
import logging
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
import requests
from sqlalchemy import func, or_
from sqlalchemy.orm.query import Query

# Local application imports
from flask import current_app, request, g
from app.models import (
    User, Player, Match, Season, PlayerSeasonStats, PlayerCareerStats, Availability,
    PlayerEvent, PlayerEventType
)

logger = logging.getLogger(__name__)


def generate_pkce_codes() -> Tuple[str, str]:
    """
    Generate PKCE codes for the OAuth flow.

    Returns:
        Tuple[str, str]: A tuple containing the code_verifier and the code_challenge.
    """
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip('=')
    return code_verifier, code_challenge


def exchange_discord_code(code: str, redirect_uri: str, code_verifier: str) -> Dict:
    """
    Exchange a Discord authorization code for an access token.

    Args:
        code (str): The authorization code received from Discord.
        redirect_uri (str): The redirect URI used in the OAuth flow.
        code_verifier (str): The PKCE code verifier.

    Returns:
        Dict: The JSON response from Discord containing the access token and related data.

    Raises:
        requests.RequestException: If the token exchange request fails.
    """
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
        response = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Discord token exchange failed: {str(e)}")
        raise


def get_discord_user_data(access_token: str) -> Dict:
    """
    Retrieve Discord user data using an access token.

    Args:
        access_token (str): The access token for Discord.

    Returns:
        Dict: The JSON response containing user data.

    Raises:
        requests.RequestException: If the request fails.
    """
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get('https://discord.com/api/users/@me', headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Discord user data: {str(e)}")
        raise


def process_discord_user(user_data: Dict) -> User:
    """
    Process Discord user data and create or update a local User record.

    Args:
        user_data (Dict): The user data obtained from Discord.

    Returns:
        User: The created or updated User instance.
    """
    session = g.db_session
    email = user_data.get('email', '').lower()
    discord_id = user_data.get('id')

    # Try to find an existing user by email
    user = session.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        user = User(
            email=email,
            username=user_data.get('username'),
            is_approved=False
        )
        session.add(user)

    # If a player record exists but is missing the Discord ID, update it.
    player = session.query(Player).filter_by(user_id=user.id).first()
    if player and not player.discord_id:
        player.discord_id = discord_id

    return user


def build_player_response(player: Player) -> Dict[str, Any]:
    """
    Build response data for a player.

    Args:
        player (Player): The player instance.

    Returns:
        Dict[str, Any]: A dictionary containing player response data.
    """
    base_url = request.host_url.rstrip('/')
    profile_picture = (
        f"{base_url}{player.profile_picture_url}"
        if player.profile_picture_url
        else f"{base_url}/static/img/default_player.png"
    )
    return {
        'id': player.id,
        'name': player.name,
        'profile_picture_url': profile_picture,
        'team_name': player.team.name if player.team else None,
        'league_name': player.league.name if player.league else None,
    }


def get_player_stats(player: Player, season: Season, session=None) -> Dict[str, Any]:
    """
    Retrieve the player's season and career statistics.

    Args:
        player (Player): The player instance.
        season (Season): The season for which to retrieve stats.
        session: The database session (defaults to g.db_session).

    Returns:
        Dict[str, Any]: A dictionary with season and career stats.
    """
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
    """
    Update match details such as scores and notes.

    Args:
        match (Match): The match instance.
        data (Dict): A dictionary containing updated match details.
        session: The database session (defaults to g.db_session).
    """
    if session is None:
        session = g.db_session

    logger.info(f"Updating match {match.id} details")
    match.home_team_score = data.get('home_team_score')
    match.away_team_score = data.get('away_team_score')
    match.notes = data.get('notes')


def add_match_events(match: Match, events: List[Dict], session=None) -> None:
    """
    Add events to a match.

    Args:
        match (Match): The match instance.
        events (List[Dict]): A list of event data dictionaries.
        session: The database session (defaults to g.db_session).
    """
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
    """
    Update or create a player's availability record for a match.

    Args:
        match_id (int): The match ID.
        player_id (int): The player ID.
        discord_id (Optional[str]): The player's Discord ID.
        response (str): The availability response.
        session: The database session (defaults to g.db_session).

    Returns:
        Availability: The updated or newly created availability record.
    """
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
    """
    Build detailed match response data.

    Args:
        match (Match): The match instance.
        include_events (bool): Whether to include match events.
        include_teams (bool): Whether to include team data.
        include_players (bool): Whether to include player availability data.
        current_player (Optional[Player]): The current player making the request.
        session: The database session (defaults to g.db_session).

    Returns:
        Dict: A dictionary with match details.
    """
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
    """
    Retrieve the availability status for a list of team players for a given match.

    Args:
        match (Match): The match instance.
        players (List[Player]): A list of players.
        session: The database session (defaults to g.db_session).

    Returns:
        List[Dict]: A list of dictionaries containing each player's ID, name, and availability.
    """
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
    """
    Get summary statistics of events for a match.

    Args:
        match (Match): The match instance.

    Returns:
        Dict[str, int]: A dictionary with counts of yellow and red cards for home and away teams.
    """
    events = match.events  # Assumes events are already loaded.
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
    """
    Retrieve a player's availability for a specific match.

    Args:
        match (Match): The match instance.
        player (Player): The player instance.
        session: The database session (defaults to g.db_session).

    Returns:
        Optional[Dict]: The availability record as a dictionary, or None if not found.
    """
    if session is None:
        session = g.db_session

    availability = session.query(Availability).filter_by(
        match_id=match.id,
        player_id=player.id
    ).first()
    return availability.to_dict() if availability else None


def build_matches_query(team_id: Optional[int], player: Optional[Player], 
                        upcoming: bool = False, session=None) -> Query:
    """
    Build a SQLAlchemy query for matches based on filters.

    Args:
        team_id (Optional[int]): Filter by a specific team ID.
        player (Optional[Player]): Filter by player's team if team_id is not provided.
        upcoming (bool): If True, only include matches scheduled in the future.
        session: The database session (defaults to g.db_session).

    Returns:
        Query: A SQLAlchemy query object for matches.
    """
    if session is None:
        session = g.db_session

    query = session.query(Match)
    if team_id:
        query = query.filter(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
        )
    elif player and player.team_id:
        query = query.filter(
            or_(Match.home_team_id == player.team_id, Match.away_team_id == player.team_id)
        )

    if upcoming:
        query = query.filter(Match.date >= datetime.utcnow())

    return query


def process_matches_data(matches: List[Match], player: Optional[Player], 
                         include_events: bool = False, 
                         include_availability: bool = False, session=None) -> List[Dict]:
    """
    Process a list of match objects into dictionaries with optional events and availability.

    Args:
        matches (List[Match]): A list of match instances.
        player (Optional[Player]): The player for whom availability is to be checked.
        include_events (bool): Whether to include event data.
        include_availability (bool): Whether to include player's availability.
        session: The database session (defaults to g.db_session).

    Returns:
        List[Dict]: A list of dictionaries representing match data.
    """
    if session is None:
        session = g.db_session

    matches_data = []
    for match in matches:
        match_data = match.to_dict(include_teams=True)

        if include_events:
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
    """
    Notify external systems of an availability update.

    Args:
        match_id (int): The match ID.
        player_id (int): The player ID.
        response (str): The new availability response.
        session: The database session (defaults to g.db_session).
    """
    logger.info(f"Processing availability update notifications for match {match_id}, player {player_id}")
    # Import tasks locally to avoid circular imports.
    from app.tasks import notify_discord_of_rsvp_change_task, notify_frontend_of_rsvp_change_task
    notify_discord_of_rsvp_change_task.delay(match_id)
    notify_frontend_of_rsvp_change_task.delay(match_id, player_id, response)


def update_player_match_availability(match_id: int, player_id: int, 
                                     new_response: str, session=None) -> bool:
    """
    Update a player's match availability.

    Args:
        match_id (int): The match ID.
        player_id (int): The player ID.
        new_response (str): The new availability response.
        session: The database session (defaults to g.db_session).

    Returns:
        bool: True if the update was successful, False otherwise.
    """
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
    """
    Retrieve upcoming matches for a specific team.

    Args:
        team_id (int): The team ID.
        session: The database session (defaults to g.db_session).

    Returns:
        List[Dict]: A list of dictionaries representing upcoming matches.
    """
    if session is None:
        session = g.db_session

    upcoming_matches = session.query(Match).filter(
        ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)) &
        (Match.date >= datetime.utcnow())
    ).order_by(Match.date).limit(5).all()

    return [match.to_dict() for match in upcoming_matches]

def get_player_response_data(player: Player, full: bool, session=None) -> Dict[str, Any]:
    """
    Build detailed response data for a player.
    
    Args:
        player (Player): The player instance.
        full (bool): Whether to include full profile details.
        session: The database session (defaults to g.db_session).
    
    Returns:
        Dict[str, Any]: A dictionary containing detailed player data.
    """
    # Start with the basic response built by build_player_response
    data = build_player_response(player)
    
    if full:
        # Include additional player details if full profile is requested.
        data.update({
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
        })
    return data