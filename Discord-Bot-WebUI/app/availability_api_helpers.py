# availability_api_helpers.py
from flask import jsonify, current_app
from app.models import Match, Availability, Team, Player, ScheduledMessage
from app.decorators import db_operation, query_operation
from app.tasks.tasks_rsvp import update_discord_rsvp_task
from datetime import datetime
from typing import Optional
import aiohttp
import re
import logging

logger = logging.getLogger(__name__)

def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_time(time_text):
    return re.match(r"^\d{2}:\d{2}(:\d{2})?$", time_text) is not None

@query_operation
def get_availability_results(match_id):
    availability = Availability.query.filter_by(match_id=match_id).all()
    return {
        "yes": sum(1 for a in availability if a.response == 'yes'),
        "no": sum(1 for a in availability if a.response == 'no'),
        "maybe": sum(1 for a in availability if a.response == 'maybe'),
        "responses": [{
            "player_id": a.player_id,
            "response": a.response
        } for a in availability]
    }

@db_operation
def store_message_ids_for_match(match_id, home_channel_id, home_message_id, 
                              away_channel_id, away_message_id):
    """
    Store message IDs with proper validation and error handling.
    """
    try:
        # First validate that the match exists
        match = Match.query.get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return None, "Match not found"

        scheduled_message = ScheduledMessage.query.filter_by(match_id=match_id).first()
        if not scheduled_message:
            scheduled_message = ScheduledMessage(match_id=match_id)
        
        scheduled_message.home_channel_id = home_channel_id
        scheduled_message.home_message_id = home_message_id
        scheduled_message.away_channel_id = away_channel_id
        scheduled_message.away_message_id = away_message_id
        
        return scheduled_message, "Message IDs stored successfully"
        
    except Exception as e:
        logger.error(f"Error storing message IDs for match {match_id}: {str(e)}")
        return None, str(e)

@query_operation
def verify_availability_data(match_id: int, team_id: Optional[int] = None) -> None:
    """
    Verify the state of availability data in the database
    """
    try:
        # Check match
        match = Match.query.get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found!")
            return
        
        logger.debug(f"Found match: {match_id}")

        # Check availabilities without any filters
        all_availabilities = Availability.query.filter(
            Availability.match_id == match_id
        ).all()
        
        logger.debug(f"All availabilities for match {match_id}:")
        for avail in all_availabilities:
            player = Player.query.get(avail.player_id)
            logger.debug(f"  Player {player.name} (ID: {player.id}, Team: {player.team_id}): {avail.response}")

        if team_id:
            # Check team exists
            team_players = Player.query.filter_by(team_id=team_id).all()
            logger.debug(f"Players on team {team_id}:")
            for player in team_players:
                logger.debug(f"  {player.name} (ID: {player.id})")

            # Check team availabilities
            team_availabilities = (Availability.query
                                 .join(Player)
                                 .filter(
                                     Availability.match_id == match_id,
                                     Player.team_id == team_id
                                 ).all())
            
            logger.debug(f"Availabilities for team {team_id}:")
            for avail in team_availabilities:
                player = Player.query.get(avail.player_id)
                logger.debug(f"  Player {player.name}: {avail.response}")

    except Exception as e:
        logger.error(f"Error verifying data: {str(e)}", exc_info=True)

@query_operation
def get_match_rsvp_data(match_id, team_id=None):
    """
    Get RSVP data with proper error handling and validation.
    """
    try:
        # First check if there are any availabilities at all for this match
        base_count = Availability.query.filter(
            Availability.match_id == match_id
        ).count()
        logger.debug(f"Total availability records for match {match_id}: {base_count}")

        # Build the query step by step with logging
        query = Availability.query.join(Player)
        logger.debug(f"Base query with Player join: {str(query)}")

        query = query.filter(Availability.match_id == match_id)
        logger.debug(f"After match_id filter: {str(query)}")
        
        # Log all availabilities before team filter
        all_avail = query.with_entities(
            Availability.response, 
            Player.name,
            Player.id,
            Player.team_id
        ).all()
        logger.debug(f"All availabilities before team filter: {all_avail}")
        
        if team_id:
            query = query.filter(Player.team_id == team_id)
            logger.debug(f"After team_id filter: {str(query)}")

            # Log filtered availabilities
            filtered_avail = query.with_entities(
                Availability.response, 
                Player.name,
                Player.id,
                Player.team_id
            ).all()
            logger.debug(f"Filtered availabilities for team {team_id}: {filtered_avail}")
        
        # Get final records
        availability_records = query.with_entities(
            Availability.response, 
            Player.name,
            Player.id
        ).all()
        
        logger.debug(f"Final availability records: {availability_records}")
        
        rsvp_data = {
            'yes': [], 
            'no': [], 
            'maybe': []
        }
        
        # Process records with logging
        for response, player_name, player_id in availability_records:
            logger.debug(f"Processing record: response={response}, player={player_name}, id={player_id}")
            if response in rsvp_data:
                rsvp_data[response].append({
                    'player_name': player_name,
                    'player_id': player_id
                })
                logger.debug(f"Added player {player_name} to {response} list")
        
        logger.debug(f"Final RSVP data for match {match_id}, team {team_id}: {rsvp_data}")
        return rsvp_data
        
    except Exception as e:
        logger.error(f"Error getting RSVP data for match {match_id}, team {team_id}: {str(e)}", 
                    exc_info=True)
        return {'yes': [], 'no': [], 'maybe': []}

@db_operation
async def update_discord_rsvp(match, player, new_response, old_response):
    scheduled_message = ScheduledMessage.query.filter_by(match_id=match.id).first()
    if not scheduled_message:
        logger.debug(f"No scheduled message found for match {match.id}")
        return {"status": "success", "message": "RSVP recorded; no Discord messages yet"}

    message_ids = []
    if scheduled_message.home_message_id and scheduled_message.home_channel_id:
        message_ids.append(f"{scheduled_message.home_channel_id}-{scheduled_message.home_message_id}")
    if scheduled_message.away_message_id and scheduled_message.away_channel_id:
        message_ids.append(f"{scheduled_message.away_channel_id}-{scheduled_message.away_message_id}")

    if not message_ids:
        logger.debug(f"No Discord messages to update for match {match.id}")
        return {"status": "success", "message": "RSVP recorded; no message IDs"}

    data = {
        "match_id": match.id,
        "discord_id": player.discord_id,
        "new_response": new_response,
        "old_response": old_response,
        "message_ids": message_ids
    }

    update_discord_rsvp_task.delay(data)
    return {"status": "success", "message": "RSVP update task queued"}

@db_operation
def process_availability_update(match_id, discord_id, response, responded_at=None):
    """
    Process an availability update for a player.
    Returns: Tuple[Optional[int], dict] where dict contains status and message
    """
    try:
        # Initial result structure
        result = {
            'status': 'success',
            'message': None
        }

        # Get player
        player = Player.query.filter_by(discord_id=str(discord_id)).first()
        if not player:
            return None, {
                'status': 'error',
                'message': 'Player not found'
            }

        # Get availability
        availability = Availability.query.filter_by(
            match_id=match_id,
            player_id=player.id
        ).first()

        # Handle no_response case
        if response == 'no_response':
            if availability:
                availability._delete = True
                result['message'] = 'Availability removed'
            else:
                result['message'] = 'No availability to remove'
            return player.id, result  # Return player.id instead of player instance

        # Handle create/update case
        if not availability:
            availability = Availability(
                match_id=match_id,
                player_id=player.id,
                discord_id=discord_id,
                response=response,
                responded_at=responded_at or datetime.utcnow()
            )
            result['message'] = 'Availability created'
        else:
            availability.response = response
            availability.responded_at = responded_at or datetime.utcnow()
            result['message'] = 'Availability updated'

        return player.id, result  # Return player.id instead of player instance

    except Exception as e:
        logger.error(f"Error in process_availability_update: {str(e)}")
        return None, {
            'status': 'error',
            'message': str(e)
        }

@query_operation
def get_message_data(match_id):
    """
    Get message data for a match with proper error handling and session management.
    """
    try:
        scheduled_message = ScheduledMessage.query\
            .join(Match)\
            .filter(ScheduledMessage.match_id == match_id)\
            .first()

        if not scheduled_message:
            logger.debug(f"No scheduled message found for match_id {match_id}")
            return None

        logger.debug(f"Found scheduled_message for match_id {match_id}: {scheduled_message}")

        # Ensure we have all required data
        if not (scheduled_message.match and 
                scheduled_message.match.home_team_id and 
                scheduled_message.match.away_team_id):
            logger.error(f"Incomplete match data for match_id {match_id}")
            return None

        data = {
            'home_message_id': scheduled_message.home_message_id,
            'home_channel_id': scheduled_message.home_channel_id,
            'home_team_id': scheduled_message.match.home_team_id,
            'away_message_id': scheduled_message.away_message_id,
            'away_channel_id': scheduled_message.away_channel_id,
            'away_team_id': scheduled_message.match.away_team_id
        }

        logger.debug(f"Message data for match_id {match_id}: {data}")

        # Validate all required fields are present
        if not all(data.values()):
            logger.error(f"Missing required message data for match_id {match_id}: {data}")
            return None

        return data

    except Exception as e:
        logger.exception(f"Error getting message data for match_id {match_id}")
        return None

@query_operation
def get_match_request_data(match_id):
    """
    Get match request data with proper error handling.
    """
    try:
        match = Match.query.get(match_id)
        if not match:
            logger.error(f"Match {match_id} not found")
            return None
            
        # Ensure we have all required related data
        if not (match.home_team and match.away_team):
            logger.error(f"Missing team data for match {match_id}")
            return None
            
        return {
            'match_id': match.id,
            'home_team_name': match.home_team.name,
            'away_team_name': match.away_team.name,
            'match_date': match.date.strftime('%Y-%m-%d'),
            'match_time': match.time.strftime('%H:%M:%S'),
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id
        }
        
    except Exception as e:
        logger.error(f"Error getting match request data for match {match_id}: {str(e)}")
        return None