# availability_api_helpers.py
from flask import jsonify, current_app
from app import db
from app.models import Match, Availability, Team, Player, ScheduledMessage
from app.decorators import db_operation, query_operation
from app.tasks.tasks_rsvp import update_discord_rsvp_task
from datetime import datetime
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
    scheduled_message = ScheduledMessage.query.filter_by(match_id=match_id).first()
    if not scheduled_message:
        scheduled_message = ScheduledMessage(match_id=match_id)
        db.session.add(scheduled_message)
    
    scheduled_message.home_channel_id = home_channel_id
    scheduled_message.home_message_id = home_message_id
    scheduled_message.away_channel_id = away_channel_id
    scheduled_message.away_message_id = away_message_id
    return scheduled_message

@query_operation
def get_match_rsvp_data(match_id, team_id=None):
    query = db.session.query(
        Availability.response, Player.name
    ).join(Player).filter(
        Availability.match_id == match_id
    )

    if team_id:
        query = query.filter(Player.team_id == team_id)

    availability_records = query.all()
    rsvp_data = {'yes': [], 'no': [], 'maybe': []}
    
    for response, player_name in availability_records:
        if response in rsvp_data:
            rsvp_data[response].append({'player_name': player_name})
            
    return rsvp_data

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
    player = Player.query.filter_by(discord_id=str(discord_id)).first()
    if not player:
        return None, "Player not found"
        
    availability = Availability.query.filter_by(
        match_id=match_id, 
        player_id=player.id
    ).first()

    if response == 'no_response' and availability:
        db.session.delete(availability)
        return player, "Availability removed"
        
    if not availability and response != 'no_response':
        availability = Availability(
            match_id=match_id,
            player_id=player.id,
            discord_id=discord_id,
            response=response,
            responded_at=responded_at or datetime.utcnow()
        )
        db.session.add(availability)
    elif availability:
        availability.response = response
        availability.responded_at = responded_at or datetime.utcnow()
        
    return player, "Availability updated"

@query_operation
def get_message_data(match_id):
    scheduled_message = db.session.query(ScheduledMessage)\
        .filter_by(match_id=match_id)\
        .first()

    if not scheduled_message:
        return None
        
    return {
        'home_message_id': scheduled_message.home_message_id,
        'home_channel_id': scheduled_message.home_channel_id,
        'home_team_id': scheduled_message.match.home_team_id,
        'away_message_id': scheduled_message.away_message_id,
        'away_channel_id': scheduled_message.away_channel_id,
        'away_team_id': scheduled_message.match.away_team_id
    }

@query_operation
def get_match_request_data(match_id):
    match = Match.query.get(match_id)
    if not match:
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