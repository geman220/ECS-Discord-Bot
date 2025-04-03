# app/match_api.py

"""
Match API Module

This module defines the API endpoints for match-related live reporting and updates.
It provides endpoints to schedule live reporting for matches, process live updates,
send pre-match information, and manage match statuses. Asynchronous functions and
Celery tasks are leveraged for background processing, ensuring real-time updates
for live matches.
"""

import logging
from datetime import datetime

import aiohttp
import requests

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
from flask_wtf.csrf import CSRFProtect

from app.models import MLSMatch
from app.utils.match_events_utils import get_new_events
from app.core.session_manager import managed_session
from app.core import celery
from app.core.helpers import get_match

# Initialize CSRF protection for the blueprint
csrf = CSRFProtect()

# FIXME: Update TEAM_ID after testing
TEAM_ID = '9726'

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

match_api = Blueprint('match_api', __name__)
csrf.exempt(match_api)


async def process_live_match_updates(match_id, thread_id, match_data, last_status=None, last_score=None, last_event_keys=None):
    """
    Process live match updates for a given match.

    Parameters:
        match_id (str): The match identifier.
        thread_id (str): The Discord thread ID for updates.
        match_data (dict): The data for the current match.
        last_status (str, optional): The previous match status.
        last_score (str, optional): The previous score.
        last_event_keys (list, optional): Keys of previously processed events.

    Returns:
        tuple: (match_ended (bool), current_event_keys (list))
    """
    logger.info(f"Processing live match updates for match_id={match_id}")
    try:
        with managed_session() as session:
            last_event_keys = last_event_keys or []

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
                # Pass the full match_data so that pre-match details can be extracted
                await handle_status_change(thread_id, status_type, home_team, away_team, home_score, away_score, match_data)

            # Handle score changes
            if current_score != last_score:
                logger.info(f"Score changed from {last_score} to {current_score} for match_id={match_id}")
                await send_score_update(thread_id, home_team, away_team, home_score, away_score, current_time)

            # Process events
            events = competition.get("details", [])
            logger.debug(f"Total events fetched: {len(events)}")

            team_map = {
                home_team['id']: home_team,
                away_team['id']: away_team
            }

            new_events, current_event_keys = get_new_events(events, last_event_keys)
            logger.debug(f"Found {len(new_events)} new events to process")

            for event in new_events:
                logger.debug(f"Processing event: {event}")
                await process_match_event(thread_id, event, team_map, home_team, away_team, home_score, away_score)

            match_ended = status_type in ["STATUS_FULL_TIME", "STATUS_FINAL"]
            logger.info(f"Match ended: {match_ended} for match_id={match_id}")

            return match_ended, current_event_keys

    except Exception as e:
        logger.error(f"Error processing live match updates for match_id={match_id}: {str(e)}", exc_info=True)
        return False, last_event_keys


async def send_score_update(thread_id, home_team, away_team, home_score, away_score, current_time):
    """
    Send a score update to the bot.

    Parameters:
        thread_id (str): The Discord thread ID.
        home_team (dict): Home team information.
        away_team (dict): Away team information.
        home_score (str): Home team score.
        away_score (str): Away team score.
        current_time (str): Current match time.
    """
    update_data = {
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "time": current_time
    }
    await send_update_to_bot(thread_id, "score_update", update_data)


async def handle_status_change(thread_id, status_type, home_team, away_team, home_score, away_score, match_data=None):
    """
    Handle changes in match status by sending appropriate updates.

    Parameters:
        thread_id (str): The Discord thread ID.
        status_type (str): The new status of the match.
        home_team (dict): Home team information.
        away_team (dict): Away team information.
        home_score (str): Home team score.
        away_score (str): Away team score.
        match_data (dict, optional): Full match data for additional context.
    """
    if status_type == "STATUS_SCHEDULED":
        logger.info(f"Sending pre-match update to thread {thread_id}")
        await send_pre_match_info(thread_id, match_data)
    elif status_type == "STATUS_HALFTIME":
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
    """
    Process an individual match event and send an update to the bot.

    Parameters:
        thread_id (str): The Discord thread ID.
        event (dict): The match event data.
        team_map (dict): Mapping of team IDs to team data.
        home_team (dict): Home team information.
        away_team (dict): Away team information.
        home_score (str): Home team score.
        away_score (str): Away team score.
    """
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

    is_favorable = False
    if event_type == "Goal":
        if event_team_id == TEAM_ID:
            is_favorable = True
    elif event_type in ["Yellow Card", "Red Card"]:
        if event_team_id != TEAM_ID:
            is_favorable = True
        else:
            is_favorable = False
    else:
        is_favorable = False

    if is_favorable:
        logger.info(f"Hyping favorable event: {event_type} for team {event_team_name}")
        await send_update_to_bot(thread_id, "hype_event", event_data)
    else:
        logger.info(f"Reporting event: {event_type} for team {event_team_name}")
        await send_update_to_bot(thread_id, "match_event", event_data)


async def fetch_channel_id_from_webui(match_id):
    """
    Fetch the Discord channel ID for a match from the WebUI API.

    Parameters:
        match_id (str): The match identifier.

    Returns:
        str or None: The Discord channel ID or None if not found.
    """
    webui_url = current_app.config['WEBUI_API_URL']
    try:
        async with aiohttp.ClientSession() as asession:
            url = f"{webui_url}/match/{match_id}/channel"
            logger.info(f"Fetching channel ID from URL: {url}")
            async with asession.get(url) as response:
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
    """
    Prepare and send pre-match information to the bot.

    Parameters:
        thread_id (str): The Discord thread ID.
        match_data (dict): The match data.
    """
    logger.info("Preparing pre-match info")

    competition = match_data["competitions"][0]
    home_competitor = competition["competitors"][0]
    away_competitor = competition["competitors"][1]

    home_team = home_competitor["team"]
    away_team = away_competitor["team"]

    match_date_str = competition.get("date", match_data.get("date"))
    match_date = datetime.strptime(match_date_str, "%Y-%m-%dT%H:%MZ")
    match_date_formatted = match_date.strftime("%A, %B %d, %Y at %I:%M %p UTC")

    venue = competition.get("venue", {}).get("fullName", "Unknown Venue")
    home_form = home_competitor.get('form', 'N/A')
    away_form = away_competitor.get('form', 'N/A')

    odds_data = competition.get('odds', [{}])[0]
    home_odds = odds_data.get('moneyline', {}).get('home', {}).get('odds', 'N/A')
    draw_odds = odds_data.get('drawOdds', {}).get('moneyLine', 'N/A')
    away_odds = odds_data.get('moneyline', {}).get('away', {}).get('odds', 'N/A')

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
    """
    Send an update to the bot.

    Parameters:
        thread_id (str): The Discord thread ID.
        update_type (str): The type of update.
        update_data (dict): The data for the update.
    """
    logger.info(f"Sending {update_type} update to bot for thread {thread_id}")
    logger.debug(f"Update data: {update_data}")

    bot_api_url = "http://discord-bot:5001"
    endpoint = "/post_match_update"
    url = f"{bot_api_url}{endpoint}"
    payload = {
        "thread_id": thread_id,
        "update_type": update_type,
        "update_data": update_data
    }

    logger.info(f"Sending request to {url}")
    async with aiohttp.ClientSession() as asession:
        try:
            async with asession.post(url, json=payload) as response:
                response_text = await response.text()
                if response.status == 200:
                    logger.info(f"Successfully sent {update_type} update to bot for thread {thread_id}")
                else:
                    logger.error(f"Failed to send update to bot. Status: {response.status}, Error: {response_text}")
                    logger.debug(f"Payload sent: {payload}")
        except Exception as e:
            logger.error(f"Exception occurred while sending update to bot: {str(e)}", exc_info=True)


@match_api.route('/schedule_live_reporting', endpoint='schedule_live_reporting_route', methods=['POST'])
@login_required
def schedule_live_reporting_route():
    """
    Schedule live reporting for a match.

    Expects JSON payload with a match_id.
    Returns a JSON response indicating scheduling success or failure.
    """
    data = request.json
    match_id = data.get('match_id')

    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'error': 'Match not found'}), 404

            if match.live_reporting_scheduled:
                logger.warning(f"Live reporting already scheduled for match {match_id}")
                return jsonify({'error': 'Live reporting already scheduled'}), 400

            match.live_reporting_scheduled = True

            time_diff = match.date_time - datetime.utcnow()
            celery.send_task('app.tasks.start_live_reporting', args=[match_id], countdown=time_diff.total_seconds())

            logger.info(f"Live reporting scheduled for match {match_id}")
            return jsonify({'success': True, 'message': 'Live reporting scheduled'})
    except Exception as e:
        logger.error(f"Error scheduling live reporting for match {match_id}: {str(e)}")
        raise


@match_api.route('/start_live_reporting/<match_id>', endpoint='start_live_reporting_route', methods=['POST'])
@login_required
def start_live_reporting_route(match_id):
    """
    Start live reporting for a match.

    Returns a JSON response indicating success or failure and the task ID if started.
    """
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'success': False, 'error': 'Match not found'}), 404

            if match.live_reporting_status == 'running':
                logger.warning(f"Live reporting already running for match {match_id}")
                return jsonify({'success': False, 'error': 'Live reporting already running'}), 400

            task = celery.send_task('app.tasks.start_live_reporting', args=[match_id])
            match.live_reporting_status = 'running'
            match.live_reporting_started = True
            match.live_reporting_task_id = task.id

            logger.info(f"Live reporting started for match {match_id}")
            return jsonify({'success': True, 'message': 'Live reporting started successfully', 'task_id': task.id})
    except Exception as e:
        logger.error(f"Error starting live reporting for match {match_id}: {str(e)}")
        raise


@match_api.route('/stop_live_reporting/<match_id>', endpoint='stop_live_reporting_route', methods=['POST'])
@login_required
def stop_live_reporting_route(match_id):
    """
    Stop live reporting for a match.

    Returns a JSON response indicating success or failure.
    """
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'success': False, 'error': 'Match not found'}), 404

            if match.live_reporting_status != 'running':
                logger.warning(f"Live reporting is not running for match {match_id}")
                return jsonify({'success': False, 'error': 'Live reporting is not running for this match'}), 400

            # Update match status
            match.live_reporting_status = 'stopped'
            match.live_reporting_started = False
            
            # Revoke the current task if one exists
            if match.live_reporting_task_id:
                logger.info(f"Revoking task {match.live_reporting_task_id} for match {match_id}")
                try:
                    celery.control.revoke(match.live_reporting_task_id, terminate=True)
                except Exception as revoke_error:
                    logger.warning(f"Error revoking task {match.live_reporting_task_id}: {revoke_error}")
                
                # Clear the task ID to ensure no future updates attempt to process
                match.live_reporting_task_id = None

            logger.info(f"Live reporting stopped for match {match_id}")
            return jsonify({'success': True, 'message': 'Live reporting stopped successfully'})
    except Exception as e:
        logger.error(f"Error stopping live reporting for match {match_id}: {str(e)}")
        raise


@match_api.route('/get_match_status/<match_id>', endpoint='get_match_status', methods=['GET'])
def get_match_status(match_id):
    """
    Retrieve the current live reporting status of a match.

    Returns:
        JSON response with match status details.
    """
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
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
    except Exception as e:
        logger.error(f"Error retrieving match status for match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@match_api.route('/match/<int:match_id>/channel', endpoint='get_match_channel', methods=['GET'])
def get_match_channel(match_id):
    """
    Retrieve the Discord channel ID associated with a match.

    Returns:
        JSON response with the channel_id or an error message.
    """
    logger.info(f"Fetching channel ID for match {match_id}")
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
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