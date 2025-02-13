# app/sms_helpers.py

"""
SMS Helpers Module

This module provides functions to send SMS messages using Twilio, generate and verify
SMS confirmation codes, check subscription status via TextMagic, and handle incoming
SMS commands for the ECS FC application.
"""

import logging
import random
import string
from datetime import datetime

from flask import current_app, jsonify, g
from sqlalchemy import or_
from textmagic.rest import TextmagicRestClient
from twilio.rest import Client

from app.models import Player, Match

logger = logging.getLogger(__name__)


def send_welcome_message(phone_number):
    """
    Send an introductory welcome message describing the available commands.

    Args:
        phone_number (str): The recipient's phone number.

    Returns:
        The result of sending the SMS.
    """
    welcome_message = (
        "Welcome to ECS FC! You're now signed up for match notifications and reminders.\n\n"
        "Available commands:\n"
        "- 'next match' or 'schedule': Get info about your next match(es)\n"
        "- 'help': See all available commands\n"
        "- 'end': Unsubscribe\n"
        "Message & data rates may apply."
    )
    return send_sms(phone_number, welcome_message)


def send_sms(phone_number, message):
    """
    Send an SMS using Twilio.

    Args:
        phone_number (str): The recipient's phone number.
        message (str): The message to send.

    Returns:
        tuple: (success (bool), message SID or error string).
    """
    client = Client(
        current_app.config['TWILIO_SID'],
        current_app.config['TWILIO_AUTH_TOKEN']
    )
    try:
        msg = client.messages.create(
            body=message,
            from_=current_app.config['TWILIO_PHONE_NUMBER'],
            to=phone_number
        )
        return True, msg.sid
    except Exception as e:
        current_app.logger.error(f"Failed to send SMS: {e}")
        return False, str(e)


def generate_confirmation_code():
    """
    Generate a 6-digit numeric code for confirming SMS subscription.

    Returns:
        str: A 6-digit numeric confirmation code.
    """
    return ''.join(random.choices(string.digits, k=6))


def send_confirmation_sms(user):
    """
    Generate and send an SMS confirmation code to the user.

    This function:
      1. Generates a random confirmation code.
      2. Stores the code and opt-in timestamp on the user object.
      3. Sends the code to the user's phone.

    Args:
        user: The user object.

    Returns:
        tuple: (success (bool), message SID or error string).
    """
    session = g.db_session
    player = session.query(Player).filter_by(user_id=user.id).first()
    if not player or not player.phone:
        return False, "No phone number associated with this account."
    
    confirmation_code = generate_confirmation_code()
    user.sms_confirmation_code = confirmation_code
    # Optionally track when the user opted in.
    user.sms_opt_in_timestamp = datetime.utcnow()

    message = (
        f"Your ECS FC SMS verification code is: {confirmation_code}\n\n"
        "Reply END to opt-out. Message & data rates may apply."
    )
    success, msg_info = send_sms(player.phone, message)
    return success, msg_info


def verify_sms_confirmation(user, code):
    """
    Verify that the provided SMS confirmation code matches the user's stored code.

    On success, enables SMS notifications, clears the confirmation code,
    and sends a welcome message.

    Args:
        user: The user object.
        code (str): The confirmation code provided by the user.

    Returns:
        bool: True if the confirmation is successful; otherwise, False.
    """
    session = g.db_session
    try:
        if user.sms_confirmation_code == code:
            user.sms_notifications = True
            user.sms_confirmation_code = None

            player = session.query(Player).filter_by(user_id=user.id).first()
            if player and player.phone:
                success, _ = send_welcome_message(player.phone)
                if not success:
                    logger.error(f"Failed to send welcome message to user {user.id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error verifying SMS confirmation for user {user.id}: {e}")
        return False


def user_is_blocked_in_textmagic(phone_number):
    """
    Check if a phone number is unsubscribed/blocked in TextMagic.

    Args:
        phone_number (str): The phone number to check.

    Returns:
        bool: True if the phone number is unsubscribed; otherwise, False.
    """
    try:
        client = TextmagicRestClient(
            current_app.config['TEXTMAGIC_USERNAME'],
            current_app.config['TEXTMAGIC_API_KEY']
        )
        response = client.unsubscribers.list(search=phone_number)
        # The response should include a 'resources' list.
        unsubscribers_list = response.get('resources', [])
        if unsubscribers_list:
            current_app.logger.info(f'Phone number {phone_number} is unsubscribed in TextMagic.')
            return True
        else:
            current_app.logger.info(f'Phone number {phone_number} is not unsubscribed in TextMagic.')
            return False
    except Exception as e:
        current_app.logger.error(f"Error checking if phone {phone_number} is unsubscribed: {e}")
        return False


# -------------------------------------------------------------------------
# Command Handling Functions
# -------------------------------------------------------------------------

def handle_opt_out(player):
    """
    Process an opt-out request by marking the player and user as unsubscribed.

    Sends a confirmation SMS indicating the user has been unsubscribed.

    Args:
        player: The player object.

    Returns:
        bool: True upon completion.
    """
    session = g.db_session
    logger.info(f'Opt-out request received for player: {player.user_id}')
    player.sms_opt_out_timestamp = datetime.utcnow()
    if player.user:
        player.user.sms_notifications = False
    logger.info(f'Player {player.user_id} unsubscribed from SMS notifications')
    
    # Optionally send a final confirmation SMS.
    send_sms(player.phone, "You have been unsubscribed. Reply START anytime to re-subscribe.")
    return True


def handle_re_subscribe(player):
    """
    Re-subscribe a user to SMS notifications.

    Updates consent fields and sends a re-subscription confirmation SMS.

    Args:
        player: The player object.

    Returns:
        bool: True upon successful re-subscription.
    """
    session = g.db_session
    logger.info(f'Re-subscription request for player: {player.user_id}')
    player.sms_consent_given = True
    player.sms_consent_timestamp = datetime.utcnow()
    player.sms_opt_out_timestamp = None
    player.is_phone_verified = True

    if player.user:
        player.user.sms_notifications = True
    
    success, _ = send_sms(
        player.phone, 
        "You are re-subscribed to ECS FC notifications. Reply END to unsubscribe."
    )
    if success:
        logger.info(f'Re-subscribe confirmation SMS sent to {player.user_id}')
    else:
        logger.error(f'Failed to send re-subscribe confirmation SMS to {player.user_id}')
    
    return True


def get_next_match(phone_number):
    """
    Retrieve upcoming match information for the player associated with a phone number.

    Searches for the player's teams and retrieves up to two upcoming matches per team.
    Each match dictionary contains formatted date, time, opponent name, and location.

    Args:
        phone_number (str): The player's phone number.

    Returns:
        list: A list of dictionaries, each containing team and match details.
    """
    session = g.db_session
    player = session.query(Player).filter_by(phone=phone_number).first()
    if not player:
        return []

    # Collect teams from primary and many-to-many relationships.
    teams = []
    if player.primary_team:
        teams.append(player.primary_team)
    for team in player.teams:
        if team not in teams:
            teams.append(team)
    
    if not teams:
        return []

    current_date = datetime.utcnow().date()
    matches_by_team = []
    for team in teams:
        next_matches = (
            session.query(Match)
            .filter(
                or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
                Match.date >= current_date
            )
            .order_by(Match.date, Match.time)
            .limit(2)
            .all()
        )
        
        if next_matches:
            match_list = []
            for m in next_matches:
                # Determine opponent based on which side the team is on.
                opponent = m.away_team if m.home_team_id == team.id else m.home_team
                match_info = {
                    'date': m.date.strftime('%A, %B %d'),
                    'time': m.time.strftime('%I:%M %p'),
                    'opponent': opponent.name if opponent else 'Unknown',
                    'location': m.location or 'TBD'
                }
                match_list.append(match_info)
            matches_by_team.append({'team': team, 'matches': match_list})
    return matches_by_team


def handle_next_match_request(player):
    """
    Handle an SMS request for upcoming match information.

    Retrieves upcoming matches for the player's teams and sends an SMS
    summarizing the match details.

    Args:
        player: The player object.

    Returns:
        bool: True after processing the request.
    """
    next_matches_by_team = get_next_match(player.phone)
    
    if not next_matches_by_team:
        message = "You don't have any upcoming matches scheduled."
    else:
        message_parts = []
        for entry in next_matches_by_team:
            team = entry['team']
            matches = entry['matches']
            # Add a header for each team.
            message_parts.append(f"Team {team.name} upcoming matches:")
            for i, match in enumerate(matches, 1):
                message_parts.append(
                    f"{i}. {match['date']} at {match['time']} vs {match['opponent']} - Location: {match['location']}"
                )
        message = "\n\n".join(message_parts)
    
    send_sms(player.phone, message)
    return True


def send_help_message(phone_number):
    """
    Send an SMS listing all available text commands.

    Args:
        phone_number (str): The recipient's phone number.

    Returns:
        bool: True after sending the help message.
    """
    help_message = (
        "Available commands:\n"
        "- 'next match' or 'schedule': Upcoming matches\n"
        "- 'end': Unsubscribe\n"
        "- 'start': Re-subscribe\n"
        "- 'help': This help message"
    )
    send_sms(phone_number, help_message)
    return True


# -------------------------------------------------------------------------
# Single Entry-Point for Incoming SMS Commands
# -------------------------------------------------------------------------

def handle_incoming_text_command(phone_number, message_text):
    """
    Parse and handle an incoming SMS command.

    Normalizes the command text, locates the corresponding player, and
    calls the appropriate function. Sends a fallback message if the command
    is unrecognized.

    Args:
        phone_number (str): The sender's phone number.
        message_text (str): The received text command.

    Returns:
        A JSON response indicating the status and message.
    """
    session = g.db_session
    player = session.query(Player).filter_by(phone=phone_number).first()
    if not player:
        # Unknown phone number: notify the sender.
        send_sms(phone_number, "We couldn't match your phone number to a user.")
        return jsonify({'status': 'error', 'message': 'Unknown user phone'})

    # Normalize command text.
    cmd = message_text.strip().lower()

    if cmd in ['end', 'stop', 'unsubscribe']:
        handle_opt_out(player)
        return jsonify({'status': 'success', 'message': 'Opted out'})
    elif cmd in ['start', 'subscribe']:
        handle_re_subscribe(player)
        return jsonify({'status': 'success', 'message': 'Re-subscribed'})
    elif cmd in ['help']:
        send_help_message(phone_number)
        return jsonify({'status': 'success', 'message': 'Help sent'})
    elif cmd in ['next match', 'schedule']:
        handle_next_match_request(player)
        return jsonify({'status': 'success', 'message': 'Next match info sent'})
    else:
        # Unrecognized command fallback.
        send_sms(phone_number, "Sorry, we didn't recognize that command. Reply HELP for options.")
        return jsonify({'status': 'success', 'message': 'Unrecognized command'})