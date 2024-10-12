# web match_api.py

from app import db, csrf, celery
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
from app.models import MLSMatch
from datetime import datetime, timedelta
import asyncio
import aiohttp
import hashlib
import requests
import time
import json
import logging

# FIX THIS AFTER TESTING
TEAM_ID = '9726'

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

match_api = Blueprint('match_api', __name__)
csrf.exempt(match_api)

last_events = {}
last_status = None
last_score = None
is_first_update = True

def event_key(event):
    event_type = event.get('type', {}).get('text', 'Unknown')
    clock = event.get('clock', {}).get('displayValue', 'Unknown')
    team_id = event.get('team', {}).get('id', 'Unknown')
    athlete_id = '0'
    athletes_involved = event.get('athletesInvolved', [])
    if athletes_involved:
        athlete_id = athletes_involved[0].get('id', '0')
    return f"{event_type}:{clock}:{team_id}:{athlete_id}"

async def process_live_match_updates(match_id, thread_id, match_data, last_status, last_score, last_events):
    logger.info(f"Processing live match updates for match_id={match_id}")

    try:
        competition = match_data["competitions"][0]
        status_type = competition["status"]["type"]["name"]
        home_competitor = competition["competitors"][0]
        away_competitor = competition["competitors"][1]
        home_team = home_competitor["team"]
        away_team = away_competitor["team"]
        home_score = home_competitor.get("score", "0")
        away_score = away_competitor.get("score", "0")
        current_time = competition["status"].get("displayClock", "N/A")
        current_score = f"{home_score}-{away_score}"

        logger.debug(f"Match status: {status_type}, Current score: {current_score}, Time: {current_time}")

        # Handle match status changes
        if status_type != last_status:
            logger.info(f"Match status changed from {last_status} to {status_type} for match_id={match_id}")
            await handle_status_change(thread_id, status_type, home_team, away_team, home_score, away_score)
            last_status = status_type

        # Handle score changes
        if current_score != last_score:
            logger.info(f"Score changed from {last_score} to {current_score} for match_id={match_id}")
            await send_score_update(thread_id, home_team, away_team, home_score, away_score, current_time)
            last_score = current_score

        # After fetching events
        events = competition.get("details", [])
        logger.debug(f"Total events fetched: {len(events)}")
        team_map = {
            home_team['id']: home_team,
            away_team['id']: away_team
        }

        # Log the number of events found
        logger.debug(f"Total events fetched: {len(events)}")

        # Identify new events that haven't been processed yet
        new_events = [event for event in events if event_key(event) not in last_events]
        logger.debug(f"Found {len(new_events)} new events to process")

        for event in new_events:
            logger.debug(f"Processing event: {event}")
            await process_match_event(thread_id, event, team_map, home_team, away_team, home_score, away_score)
            last_events[event_key(event)] = event

        match_ended = status_type in ["STATUS_FULL_TIME", "STATUS_FINAL"]
        logger.info(f"Match ended: {match_ended} for match_id={match_id}")
        return match_ended

    except Exception as e:
        logger.error(f"Error processing live match updates for match_id={match_id}: {str(e)}", exc_info=True)
        return False

async def send_score_update(thread_id, home_team, away_team, home_score, away_score, current_time):
    update_data = {
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "time": current_time
    }
    await send_update_to_bot(thread_id, "score_update", update_data)

async def handle_status_change(thread_id, status_type, home_team, away_team, home_score, away_score):
    if status_type == "STATUS_HALFTIME":
        logger.info(f"Sending halftime update to thread {thread_id}")
        await send_update_to_bot(thread_id, "halftime", {
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
        })
    elif status_type in ["STATUS_FULL_TIME", "STATUS_FINAL"]:
        logger.info(f"Sending fulltime update to thread {thread_id}")
        await send_update_to_bot(thread_id, "fulltime", {
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
        })

async def process_match_event(thread_id, event, team_map, home_team, away_team, home_score, away_score):
    event_type = event.get("type", {}).get("text", "Unknown Event")
    event_time = event.get("clock", {}).get("displayValue", "N/A")
    event_team_id = str(event.get("team", {}).get("id", ""))
    event_team = team_map.get(event_team_id, {})
    event_team_name = event_team.get("displayName", "Unknown Team")
    event_team_logo = event_team.get("logo", None)

    athletes_involved = event.get("athletesInvolved", [])
    event_player_data = athletes_involved[0] if athletes_involved else {}
    event_player = {
        'id': event_player_data.get("id", ""),
        'displayName': event_player_data.get("displayName", "Unknown Player"),
        'shortName': event_player_data.get("shortName", "Unknown Player"),
    }
    event_description = event.get("text", "No description available.")

    event_data = {
        "type": event_type,
        "team": {
            'id': event_team_id,
            'displayName': event_team_name,
            'logo': event_team_logo
        },
        "player": event_player,
        "time": event_time,
        "description": event_description,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score
    }

    # Determine if the event is favorable for our team
    is_favorable = False
    if event_type == "Goal":
        if event_team_id == TEAM_ID:
            # Our team scored
            is_favorable = True
    elif event_type in ["Yellow Card", "Red Card"]:
        if event_team_id != TEAM_ID:
            # Opponent received a card (good for us)
            is_favorable = True
        else:
            # Our team received a card (bad for us)
            is_favorable = False
    else:
        # Other events are not considered favorable
        is_favorable = False

    # Send the event to the bot
    if is_favorable:
        logger.info(f"Hyping favorable event: {event_type} for team {event_team_name}")
        await send_update_to_bot(thread_id, "hype_event", event_data)
    else:
        logger.info(f"Reporting event: {event_type} for team {event_team_name}")
        await send_update_to_bot(thread_id, "match_event", event_data)

async def fetch_channel_id_from_webui(match_id):
    webui_url = current_app.config['WEBUI_API_URL']
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{webui_url}/match/{match_id}/channel"
            logger.info(f"Fetching channel ID from URL: {url}")
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    channel_id = data.get('channel_id')
                    logger.info(f"Fetched channel ID: {channel_id}")
                    return channel_id
                else:
                    logger.error(f"Failed to fetch channel ID. Status: {response.status}, URL: {url}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching channel ID: {str(e)}", exc_info=True)
        return None

async def send_pre_match_info(thread_id, match_data):
    logger.info("Preparing pre-match info")

    competition = match_data["competitions"][0]
    home_competitor = competition["competitors"][0]
    away_competitor = competition["competitors"][1]

    home_team = home_competitor["team"]
    away_team = away_competitor["team"]

    # Parse match date and format it
    match_date_str = competition.get("date", match_data.get("date"))
    match_date = datetime.strptime(match_date_str, "%Y-%m-%dT%H:%MZ")
    match_date_formatted = match_date.strftime("%A, %B %d, %Y at %I:%M %p UTC")

    # Get venue information
    venue = competition.get("venue", {}).get("fullName", "Unknown Venue")

    # Get team forms
    home_form = home_competitor.get('form', 'N/A')
    away_form = away_competitor.get('form', 'N/A')

    # Get odds information
    odds_data = competition.get('odds', [{}])[0]
    home_odds = odds_data.get('moneyline', {}).get('home', {}).get('odds', 'N/A')
    draw_odds = odds_data.get('drawOdds', {}).get('moneyLine', 'N/A')
    away_odds = odds_data.get('moneyline', {}).get('away', {}).get('odds', 'N/A')

    # Prepare the pre-match info message
    pre_match_info = f"""
**Upcoming Match: {home_team['displayName']} vs {away_team['displayName']}**

📅 Date: {match_date_formatted}
🏟️ Venue: {venue}

**Team Information:**
🏠 Home: {home_team['displayName']} ({home_team['abbreviation']})
   Form: {home_form}
🛫 Away: {away_team['displayName']} ({away_team['abbreviation']})
   Form: {away_form}

**Odds:**
Home Win: {home_odds}
Draw: {draw_odds}
Away Win: {away_odds}
    """

    logger.info(f"Sending pre-match info to thread {thread_id}")
    await send_update_to_bot(thread_id, "pre_match_info", {
        "home_team": home_team,
        "away_team": away_team,
        "match_date_formatted": match_date_formatted,
        "venue": venue,
        "home_form": home_form,
        "away_form": away_form,
        "home_odds": home_odds,
        "draw_odds": draw_odds,
        "away_odds": away_odds,
    })

async def send_update_to_bot(thread_id, update_type, update_data):
    logger.info(f"Sending {update_type} update to bot for thread {thread_id}")
    logger.debug(f"Update data: {update_data}")

    bot_api_url = "http://discord-bot:5001"  # Base URL of your bot's API
    endpoint = "/post_match_update"
    url = f"{bot_api_url}{endpoint}"
    payload = {
        "thread_id": thread_id,
        "update_type": update_type,
        "update_data": update_data
    }

    logger.info(f"Sending request to {url}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                response_text = await response.text()
                if response.status == 200:
                    logger.info(f"Successfully sent {update_type} update to bot for thread {thread_id}")
                else:
                    logger.error(f"Failed to send update to bot. Status: {response.status}, Error: {response_text}")
                    logger.debug(f"Payload sent: {payload}")
        except Exception as e:
            logger.error(f"Exception occurred while sending update to bot: {str(e)}", exc_info=True)

@match_api.route('/schedule_live_reporting', methods=['POST'])
@login_required
def schedule_live_reporting_route():
    data = request.json
    match_id = data.get('match_id')
    
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.error(f"Match {match_id} not found")
        return jsonify({'error': 'Match not found'}), 404
    
    if match.live_reporting_scheduled:
        logger.warning(f"Live reporting already scheduled for match {match_id}")
        return jsonify({'error': 'Live reporting already scheduled'}), 400
    
    match.live_reporting_scheduled = True
    db.session.commit()
    
    # Schedule the task to start live reporting at match time
    time_diff = match.date_time - datetime.utcnow()
    celery.send_task('app.tasks.start_live_reporting', args=[match_id], countdown=time_diff.total_seconds())
    
    logger.info(f"Live reporting scheduled for match {match_id}")
    return jsonify({'success': True, 'message': 'Live reporting scheduled'})

@match_api.route('/start_live_reporting/<match_id>', methods=['POST'])
@login_required
def start_live_reporting_route(match_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.error(f"Match {match_id} not found")
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if match.live_reporting_status == 'running':
        logger.warning(f"Live reporting already running for match {match_id}")
        return jsonify({'success': False, 'error': 'Live reporting already running'}), 400
    
    # Start the live reporting process
    task = celery.send_task('app.tasks.start_live_reporting', args=[match_id])
    
    # Update the match status
    match.live_reporting_status = 'running'
    match.live_reporting_started = True
    match.live_reporting_task_id = task.id
    db.session.commit()
    
    logger.info(f"Live reporting started for match {match_id}")
    return jsonify({'success': True, 'message': 'Live reporting started successfully', 'task_id': task.id})

@match_api.route('/stop_live_reporting/<match_id>', methods=['POST'])
@login_required
def stop_live_reporting_route(match_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.error(f"Match {match_id} not found")
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if match.live_reporting_status != 'running':
        logger.warning(f"Live reporting is not running for match {match_id}")
        return jsonify({'success': False, 'error': 'Live reporting is not running for this match'}), 400
    
    match.live_reporting_status = 'stopped'
    match.live_reporting_started = False
    db.session.commit()

    celery.control.revoke(match.live_reporting_task_id, terminate=True)
    
    logger.info(f"Live reporting stopped for match {match_id}")
    return jsonify({'success': True, 'message': 'Live reporting stopped successfully'})

@match_api.route('/get_match_status/<match_id>', methods=['GET'])
def get_match_status(match_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.error(f"Match {match_id} not found")
        return jsonify({'error': 'Match not found'}), 404
    
    logger.info(f"Returning match status for match {match_id}")
    return jsonify({
        'match_id': match.match_id,
        'live_reporting_scheduled': match.live_reporting_scheduled,
        'live_reporting_started': match.live_reporting_started,
        'discord_thread_id': match.discord_thread_id
    })

@match_api.route('/match/<int:match_id>/channel', methods=['GET'])
def get_match_channel(match_id):
    logger.info(f"Fetching channel ID for match {match_id}")
    try:
        match = MLSMatch.query.filter_by(match_id=str(match_id)).first()
        if not match:
            logger.warning(f"No match found with match_id {match_id}")
            return jsonify({'error': 'Match not found'}), 404
        if not match.discord_thread_id:
            logger.warning(f"No discord_thread_id found for match {match_id}")
            return jsonify({'error': 'No channel ID found for this match'}), 404
        logger.info(f"Returning channel ID {match.discord_thread_id} for match {match_id}")
        return jsonify({'channel_id': match.discord_thread_id})
    except Exception as e:
        logger.error(f"Error fetching channel ID for match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500