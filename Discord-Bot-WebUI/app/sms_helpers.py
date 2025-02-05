from flask import current_app, jsonify, g
from textmagic.rest import TextmagicRestClient
from datetime import datetime
from sqlalchemy import or_
from twilio.rest import Client
import random
import string
import logging

from app.models import User, Player, Match
# from app.core import db  # If you're no longer using db.session directly
logger = logging.getLogger(__name__)


def send_welcome_message(phone_number):
    """
    Send an introductory welcome message describing the available commands.
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
    Sends an SMS using Twilio.
    Returns (success_bool, message_or_error).
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
    Generates a 6-digit numeric code for confirming SMS subscription.
    """
    return ''.join(random.choices(string.digits, k=6))


def send_confirmation_sms(user):
    """
    1. Generate & store a random code for user.
    2. Send that code to user's phone.
    """
    session = g.db_session
    player = session.query(Player).filter_by(user_id=user.id).first()
    if not player or not player.phone:
        return False, "No phone number associated with this account."
    
    confirmation_code = generate_confirmation_code()
    user.sms_confirmation_code = confirmation_code
    # Optionally track when user opted in
    user.sms_opt_in_timestamp = datetime.utcnow()

    message = (
        f"Your ECS FC SMS verification code is: {confirmation_code}\n\n"
        "Reply END to opt-out. Message & data rates may apply."
    )
    success, msg_info = send_sms(player.phone, message)
    return success, msg_info


def verify_sms_confirmation(user, code):
    """
    1. Checks if the provided code matches user's stored code.
    2. On success, enable sms_notifications, clear the code, send welcome message.
    """
    session = g.db_session
    try:
        if user.sms_confirmation_code == code:
            # Confirm user
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
    Checks if phone_number is in TextMagic's unsubscribers list.
    Returns True if unsubscribed/blocked, else False.
    """
    try:
        client = TextmagicRestClient(
            current_app.config['TEXTMAGIC_USERNAME'],
            current_app.config['TEXTMAGIC_API_KEY']
        )
        response = client.unsubscribers.list(search=phone_number)
        
        # unsubscribers.list() returns { 'resources': [...] }
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
# Command Handling
# -------------------------------------------------------------------------

def handle_opt_out(player):
    """
    Sets player & user to unsubscribed from SMS notifications.
    Called when user sends "end".
    """
    session = g.db_session
    logger.info(f'Opt-out request received for player: {player.user_id}')
    player.sms_opt_out_timestamp = datetime.utcnow()
    if player.user:
        player.user.sms_notifications = False
    logger.info(f'Player {player.user_id} unsubscribed from SMS notifications')
    
    # Send final confirmation SMS (optional)
    send_sms(player.phone, "You have been unsubscribed. Reply START anytime to re-subscribe.")
    return True


def handle_re_subscribe(player):
    """
    Re-subscribes the user to SMS notifications.
    Called when user sends "start".
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
    Returns up to 2 upcoming matches for a phone number's player/team.
    If none, returns [].
    """
    session = g.db_session
    player = session.query(Player).filter_by(phone=phone_number).first()
    if not player or not player.team:
        return []

    current_date = datetime.utcnow().date()
    next_matches = (
        session.query(Match)
        .filter(
            or_(Match.home_team_id == player.team.id,
                Match.away_team_id == player.team.id),
            Match.date >= current_date
        )
        .order_by(Match.date, Match.time)
        .limit(2)
        .all()
    )

    match_list = []
    for m in next_matches:
        opponent = m.away_team if m.home_team_id == player.team.id else m.home_team
        match_info = {
            'date': m.date.strftime('%A, %B %d'),
            'time': m.time.strftime('%I:%M %p'),
            'opponent': opponent.name if opponent else 'Unknown',
            'location': m.location or 'TBD'
        }
        match_list.append(match_info)

    return match_list


def handle_next_match_request(player):
    """
    Replies with up to two upcoming matches for the player's phone/team.
    """
    next_matches = get_next_match(player.phone)
    if not next_matches:
        message = "You don't have any upcoming matches scheduled."
    else:
        message = "Your upcoming matches:\n"
        for i, match in enumerate(next_matches, 1):
            message += f"\n{i}. {match['date']} at {match['time']} vs {match['opponent']}"
            message += f"\n    Location: {match['location']}\n"

    send_sms(player.phone, message)
    return True


def send_help_message(phone_number):
    """
    Sends an SMS listing all available text commands.
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
#  Single Entry-Point for Incoming SMS Commands
# -------------------------------------------------------------------------

def handle_incoming_text_command(phone_number, message_text):
    """
    A single function to parse and handle incoming SMS commands.
    - Normalizes the command
    - Finds the player
    - Calls the appropriate function
    - Sends fallback if unrecognized
    """
    session = g.db_session
    player = session.query(Player).filter_by(phone=phone_number).first()
    if not player:
        # Unknown phone number
        send_sms(phone_number, "We couldn't match your phone number to a user.")
        return jsonify({'status': 'error', 'message': 'Unknown user phone'})

    # Convert message_text to lower-case and strip whitespace
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
        # Unrecognized command
        send_sms(phone_number, "Sorry, we didn't recognize that command. Reply HELP for options.")
        return jsonify({'status': 'success', 'message': 'Unrecognized command'})