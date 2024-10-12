from flask import current_app
from celery import shared_task
from celery.schedules import crontab
from app import create_app, db
from app.api_utils import fetch_espn_data
from app.match_api import process_live_match_updates
from app.models import Match, ScheduledMessage, Availability, MLSMatch
from datetime import datetime, timedelta
from app.discord_utils import create_match_thread
import aiohttp
import asyncio
import pytz
import requests
import time
import logging

logger = logging.getLogger(__name__)

async def send_discord_update(thread_id, update_type, update_data):
    bot_api_url = "http://discord-bot:5001"  # Base URL of your bot's API
    endpoint = "/post_match_update"
    url = f"{bot_api_url}{endpoint}"
    payload = {
        "thread_id": thread_id,
        "update_type": update_type,
        "update_data": update_data
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent {update_type} update to thread {thread_id}")
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send {update_type} update to thread {thread_id}. Status: {response.status}, Error: {error_text}")
                    raise Exception(f"Failed to send update. Status: {response.status}, Error: {error_text}")
        except Exception as e:
            logger.error(f"Exception occurred while sending update to bot: {str(e)}", exc_info=True)
            raise

def async_to_sync(coroutine):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coroutine)

@shared_task
def process_match_updates(match_id, match_data):
    app, _ = create_app()
    with app.app_context():
        match = MLSMatch.query.get(match_id)
        if not match:
            return f"No match found with ID {match_id}"

        # Extract match data (adjust as needed based on your ESPN API response)
        home_team = match_data['competitions'][0]['competitors'][0]['team']['displayName']
        away_team = match_data['competitions'][0]['competitors'][1]['team']['displayName']
        home_score = match_data['competitions'][0]['competitors'][0]['score']
        away_score = match_data['competitions'][0]['competitors'][1]['score']
        match_status = match_data['status']['type']['name']
        current_minute = match_data['status']['displayClock']

        # Create update message
        if match_status == 'STATUS_SCHEDULED':
            update_type = "pre_match_info"
            update_data = f"🚨 Match Alert: {home_team} vs {away_team} is about to start!"
        elif match_status in ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME']:
            update_type = "score_update"
            update_data = f"⚽ {home_team} {home_score} - {away_score} {away_team} ({current_minute})"
        elif match_status == 'STATUS_FINAL':
            update_type = "match_end"
            update_data = f"🏁 Full Time: {home_team} {home_score} - {away_score} {away_team}"
        else:
            update_type = "status_update"
            update_data = f"Match Status: {match_status}"

        try:
            asyncio.run(send_discord_update(match.discord_thread_id, update_type, update_data))
            return "Match update sent successfully"
        except Exception as e:
            logger.error(f"Failed to send match update for match {match_id}: {str(e)}")
            return f"Failed to send match update: {str(e)}"

@shared_task
def create_scheduled_mls_match_threads():
    app, _ = create_app()
    with app.app_context():
        now = datetime.utcnow()
        due_matches = MLSMatch.query.filter(
            MLSMatch.thread_creation_time <= now,
            MLSMatch.thread_created == False
        ).all()
        
        async def process_matches():
            tasks = [create_match_thread(match) for match in due_matches]
            results = await asyncio.gather(*tasks)
            for match, thread_id in zip(due_matches, results):
                if thread_id:
                    match.thread_created = True
                    match.discord_thread_id = thread_id
            db.session.commit()
        
        asyncio.run(process_matches())
        
        logger.info(f"Processed {len(due_matches)} MLS matches for thread creation.")
        return f"Processed {len(due_matches)} MLS matches for thread creation."

@shared_task
def create_mls_match_thread(match_id):
    app, _ = create_app()
    with app.app_context():
        match = MLSMatch.query.get(match_id)
        if match and not match.thread_created:
            thread_id = async_to_sync(create_match_thread(match))
            if thread_id:
                match.thread_created = True
                match.discord_thread_id = thread_id
                db.session.commit()
                logger.info(f"Thread created for match against {match.opponent}")
                return f"Thread created for match against {match.opponent}"
        logger.error("Failed to create thread or thread already exists")
        return "Failed to create thread or thread already exists"

@shared_task
def check_and_create_scheduled_threads():
    app, _ = create_app()
    with app.app_context():
        now = datetime.utcnow()
        due_matches = MLSMatch.query.filter(
            MLSMatch.thread_creation_time <= now,
            MLSMatch.thread_created == False
        ).all()
        
        for match in due_matches:
            create_mls_match_thread.delay(match.id)
        
        logger.info(f"Scheduled {len(due_matches)} MLS match threads for creation.")
        return f"Scheduled {len(due_matches)} MLS match threads for creation."

@shared_task
def schedule_live_reporting():
    app, _ = create_app()
    with app.app_context():
        # Get the current time
        now = datetime.now()
        # Query the matches that are within the next 24 hours and haven't started live reporting yet
        upcoming_matches = MLSMatch.query.filter(
            MLSMatch.date_time >= now,
            MLSMatch.date_time <= now + timedelta(hours=24),
            MLSMatch.live_reporting_started == False
        ).all()
        for match in upcoming_matches:
            # Calculate the time difference between now and the match start time
            time_diff = match.date_time - now
            # Schedule the start_live_reporting task to run at the match start time
            start_live_reporting.apply_async(args=[match.match_id], countdown=time_diff.total_seconds())
            # Update the match status to indicate that live reporting is scheduled
            match.live_reporting_scheduled = True
            db.session.commit()

@shared_task
def start_live_reporting(match_id):
    app, _ = create_app()
    with app.app_context():
        asyncio.run(start_live_reporting_coroutine(match_id))

@shared_task
async def start_live_reporting_coroutine(match_id):
    logger.info(f"Starting live reporting for match {match_id}")
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.error(f"Match {match_id} not found")
        return

    thread_id = match.discord_thread_id
    if not thread_id:
        logger.error(f"No Discord thread ID found for match {match_id}")
        return

    match.live_reporting_status = 'running'
    match.live_reporting_started = True
    db.session.commit()

    last_status = None
    last_score = None
    last_events = {}

    competition = match.competition  # Ensure 'competition' is a field in your MLSMatch model

    full_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition}/scoreboard/{match_id}"

    while True:
        match_data = await fetch_espn_data(full_url=full_url)
        if not match_data:
            logger.error(f"Failed to fetch data for match {match_id}")
            break

        match_ended = await process_live_match_updates(match_id, thread_id, match_data, last_status, last_score, last_events)

        if match_ended:
            logger.info(f"Match {match_id} has ended.")
            break

        last_status = match_data["competitions"][0]["status"]["type"]["name"]
        home_score = match_data['competitions'][0]['competitors'][0]['score']
        away_score = match_data['competitions'][0]['competitors'][1]['score']
        last_score = f"{home_score}-{away_score}"

        await asyncio.sleep(30)  # Adjust the interval as needed

    match.live_reporting_status = 'completed'
    match.live_reporting_started = False
    db.session.commit()

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