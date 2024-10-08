from celery import shared_task
from app import create_app, db
from app.models import Match, ScheduledMessage, Availability
import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

@shared_task
def schedule_season_availability():
    app, celery = create_app()
    with app.app_context():
        # Get matches for the next week
        start_date = datetime.utcnow().date()
        end_date = start_date + timedelta(days=7)
        matches = Match.query.filter(Match.date.between(start_date, end_date)).all()
        
        for match in matches:
            match_date = match.date  # Directly use the date object
            send_date = match_date - timedelta(days=match_date.weekday() + 1)  # Previous Monday
            send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)  # 9 AM
    
            # Check if a message is already scheduled
            existing_message = ScheduledMessage.query.filter_by(match_id=match.id).first()
            if not existing_message:
                scheduled_message = ScheduledMessage(
                    match_id=match.id,
                    scheduled_send_time=send_time,
                    status='PENDING'
                )
                db.session.add(scheduled_message)
        
        db.session.commit()
        return f"Scheduled {len(matches)} availability messages for the next week."

@shared_task
def send_scheduled_messages():
    app, celery = create_app()
    with app.app_context():
        now = datetime.utcnow()
        messages_to_send = ScheduledMessage.query.filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= now
        ).all()

        for scheduled_message in messages_to_send:
            try:
                result = send_availability_message(scheduled_message.id)
                if "success" in result.lower():
                    scheduled_message.status = 'SENT'
                else:
                    scheduled_message.status = 'FAILED'
                db.session.commit()
            except Exception as e:
                logger.error(f"Error sending message {scheduled_message.id}: {str(e)}")
                scheduled_message.status = 'FAILED'
                db.session.commit()

        return f"Processed {len(messages_to_send)} scheduled messages."

@shared_task
def send_availability_message(scheduled_message_id):
    app, celery = create_app()
    with app.app_context():
        scheduled_message = ScheduledMessage.query.get(scheduled_message_id)
        if not scheduled_message:
            return f"Scheduled message {scheduled_message_id} not found"
        
        match = scheduled_message.match
        url = "http://discord-bot:5001/api/post_availability"
        payload = {
            "match_id": match.id,
            "home_channel_id": match.home_team.discord_channel_id,
            "away_channel_id": match.away_team.discord_channel_id,
            "match_date": match.date.strftime('%Y-%m-%d'),  # Formatted date
            "match_time": match.time.strftime('%H:%M:%S'),  # Formatted time
            "home_team_name": match.home_team.name,
            "away_team_name": match.away_team.name
        }
        headers = {"Content-Type": "application/json"}
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            scheduled_message.discord_message_id = response.json().get('message_id')
            scheduled_message.status = 'SENT'
            db.session.commit()
            return "Availability request posted successfully"
        except requests.RequestException as e:
            logger.error(f"Failed to post availability for match {match.id}: {str(e)}")
            scheduled_message.status = 'FAILED'
            db.session.commit()
            return f"Failed to post availability: {str(e)}"

@shared_task
def process_rsvp(player_id, match_id, response, discord_id=None):
    app, celery = create_app()
    with app.app_context():
        availability = Availability.query.filter_by(player_id=player_id, match_id=match_id).first()
        
        if response not in ['yes', 'no', 'maybe', 'no_response']:
            return f"Invalid response for player {player_id} for match {match_id}: {response}"

        if availability:
            if response == 'no_response':
                db.session.delete(availability)
            else:
                availability.response = response
                availability.responded_at = datetime.utcnow()
        else:
            if response != 'no_response':
                availability = Availability(
                    player_id=player_id,
                    match_id=match_id,
                    response=response,
                    discord_id=discord_id,
                    responded_at=datetime.utcnow()
                )
                db.session.add(availability)

        db.session.commit()
        return f"RSVP processed for player {player_id} for match {match_id}: {response}"