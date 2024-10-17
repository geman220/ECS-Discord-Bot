# tasks.py

from flask import current_app
from celery import shared_task
from celery.schedules import crontab
from app import create_app, db, socketio
from app.api_utils import fetch_espn_data
from app.match_api import process_live_match_updates
from app.models import Match, ScheduledMessage, Availability, MLSMatch, Player
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

def update_rsvp(match_id, player_id, new_response, discord_id=None):
    """
    Centralized function to update RSVP status and trigger necessary actions.
    """
    try:
        match = Match.query.get_or_404(match_id)
        player = Player.query.get_or_404(player_id)
        availability = Availability.query.filter_by(match_id=match_id, player_id=player_id).first()
        
        old_response = availability.response if availability else None
        
        if availability:
            if new_response == 'no_response':
                db.session.delete(availability)
            else:
                availability.response = new_response
                availability.responded_at = datetime.utcnow()
        else:
            if new_response != 'no_response':
                availability = Availability(
                    match_id=match_id,
                    player_id=player_id,
                    response=new_response,
                    discord_id=discord_id,
                    responded_at=datetime.utcnow()
                )
                db.session.add(availability)
        
        if discord_id:
            player.discord_id = discord_id
        
        db.session.commit()
        
        # Trigger Discord and frontend updates after successful commit
        if player.discord_id:
            update_discord_rsvp_task.delay({
                "match_id": match_id,
                "discord_id": player.discord_id,
                "new_response": new_response,
                "old_response": old_response
            })
        
        notify_frontend_of_rsvp_change_task.delay(match_id, player_id, new_response)
        
        return True, "RSVP updated successfully"
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating RSVP for match {match_id}, player {player_id}: {e}")
        return False, str(e)
    finally:
        db.session.close()

async def async_send_availability_message(scheduled_message_id):
    scheduled_message = ScheduledMessage.query.get(scheduled_message_id)
    if not scheduled_message:
        return f"Scheduled message {scheduled_message_id} not found"

    match = scheduled_message.match
    home_channel_id = match.home_team.discord_channel_id
    away_channel_id = match.away_team.discord_channel_id

    url = "http://discord-bot:5001/api/post_availability"
    payload = {
        "match_id": match.id,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "home_channel_id": str(home_channel_id),
        "away_channel_id": str(away_channel_id),
        "match_date": match.date.strftime('%Y-%m-%d'),
        "match_time": match.time.strftime('%H:%M:%S'),
        "home_team_name": match.home_team.name,
        "away_team_name": match.away_team.name
    }

    logger.debug(f"Payload being sent: {payload}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                result = await response.json()
                home_message_id = result.get('home_message_id')
                away_message_id = result.get('away_message_id')

                # Store both message IDs
                scheduled_message.home_discord_message_id = home_message_id
                scheduled_message.away_discord_message_id = away_message_id
                scheduled_message.status = 'SENT'
                db.session.commit()

                logger.info(f"Stored message IDs - Home: {home_message_id}, Away: {away_message_id}")

        return "Availability request posted successfully"
    except aiohttp.ClientError as e:
        logger.error(f"Failed to post availability for match {match.id}: {e}")
        scheduled_message.status = 'FAILED'
        db.session.rollback()
        return f"Failed to post availability: {e}"
    finally:
        db.session.close()

async def _notify_discord_of_rsvp_change(match_id):
    bot_api_url = f"http://discord-bot:5001/api/update_availability_embed/{match_id}"
    try:
        logger.info(f"Sending request to update Discord embed for match {match_id} to {bot_api_url}")
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to update Discord embed. Status: {response.status}, Response: {await response.text()}")
                else:
                    logger.info(f"Discord embed updated for match {match_id}")
    except aiohttp.ClientError as e:
        logger.error(f"Failed to update Discord embed. RequestException: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while updating Discord embed: {str(e)}")

async def _update_discord_rsvp(data):
    bot_api_url = "http://discord-bot:5001/api/update_user_reaction"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(bot_api_url, json=data) as response:
                if response.status != 200:
                    print(f"Failed to update Discord RSVP. Status: {response.status}, Response: {await response.text()}")
                    return {"status": "error", "message": "Failed to update Discord RSVP."}
                print("Discord RSVP update successful")
                return {"status": "success", "message": "Discord RSVP updated successfully"}
    except aiohttp.ClientError as e:
        print(f"Failed to update Discord RSVP: {str(e)}")
        return {"status": "error", "message": f"Failed to update Discord RSVP: {str(e)}"}

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

        try:
            asyncio.run(process_matches())
            logger.info(f"Processed {len(due_matches)} MLS matches for thread creation.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating match threads: {e}")
        finally:
            db.session.close()
        
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
    app, _ = create_app()
    with app.app_context():
        try:
            start_date = datetime.utcnow().date()
            end_date = start_date + timedelta(days=7)
            matches = Match.query.filter(Match.date.between(start_date, end_date)).all()

            for match in matches:
                send_date = match.date - timedelta(days=match.date.weekday() + 1)
                send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)

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
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error scheduling season availability: {e}")
        finally:
            db.session.close()

@shared_task
def send_scheduled_messages():
    app, _ = create_app()
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
                db.session.rollback()
                logger.error(f"Error sending message {scheduled_message.id}: {e}")
                scheduled_message.status = 'FAILED'
                db.session.commit()  # Ensure message status is updated even on failure

        return f"Processed {len(messages_to_send)} scheduled messages."

@shared_task
def send_availability_message(scheduled_message_id):
    app, celery = create_app()
    with app.app_context():
        return asyncio.run(async_send_availability_message(scheduled_message_id))

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

@shared_task
def update_discord_rsvp_task(data):
    app, _ = create_app()
    with app.app_context():
        asyncio.run(_update_discord_rsvp(data))

@shared_task
def notify_discord_of_rsvp_change_task(match_id):
    app, _ = create_app()
    with app.app_context():
        asyncio.run(_notify_discord_of_rsvp_change(match_id))

@shared_task
def notify_frontend_of_rsvp_change_task(match_id, player_id, response):
    app, _ = create_app()
    with app.app_context():
        from app import socketio
        socketio.emit('rsvp_update', {
            'match_id': match_id,
            'player_id': player_id,
            'response': response
        }, namespace='/availability')
        print(f"Frontend notified of RSVP change for match {match_id}, player {player_id}, response {response}")

@shared_task
def fetch_match_and_team_id_task(message_id, channel_id):
    app, _ = create_app()
    with app.app_context():
        try:
            logger.info(f"Fetching match and team ID in background for message_id: {message_id}, channel_id: {channel_id}")
            scheduled_message = ScheduledMessage.query.filter(
                ((ScheduledMessage.home_channel_id == channel_id) & (ScheduledMessage.home_message_id == message_id)) |
                ((ScheduledMessage.away_channel_id == channel_id) & (ScheduledMessage.away_message_id == message_id))
            ).first()

            if not scheduled_message:
                logger.error(f"No scheduled message found for message_id: {message_id}, channel_id: {channel_id}")
                return {'error': 'Message ID not found'}

            if scheduled_message.home_channel_id == channel_id and scheduled_message.home_message_id == message_id:
                team_id = scheduled_message.match.home_team_id
            elif scheduled_message.away_channel_id == channel_id and scheduled_message.away_message_id == message_id:
                team_id = scheduled_message.match.away_team_id
            else:
                logger.error(f"Team ID not found for message_id: {message_id}, channel_id: {channel_id}")
                return {'error': 'Team ID not found'}

            logger.info(f"Found match_id: {scheduled_message.match_id}, team_id: {team_id}")
            return {'match_id': scheduled_message.match_id, 'team_id': team_id}
        except Exception as e:
            logger.exception(f"Error fetching match and team ID: {str(e)}")
            return {"error": "Internal Server Error"}