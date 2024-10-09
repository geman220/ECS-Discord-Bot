from flask import current_app, jsonify
from textmagic.rest import TextmagicRestClient
from datetime import datetime
from sqlalchemy import or_
import random
import string
from app import db
from app.models import User, Player, Match
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def send_sms(phone_number, message):
    client = TextmagicRestClient(current_app.config['TEXTMAGIC_USERNAME'], current_app.config['TEXTMAGIC_API_KEY'])
    try:
        message = client.messages.create(phones=phone_number, text=message)
        return True, message.id
    except Exception as e:
        current_app.logger.error(f"Failed to send SMS: {e}")
        return False, str(e)

def generate_confirmation_code():
    return ''.join(random.choices(string.digits, k=6))

def send_confirmation_sms(user):
    player = Player.query.filter_by(user_id=user.id).first()
    if not player or not player.phone:
        return False, "No phone number associated with this account."
    
    confirmation_code = generate_confirmation_code()
    user.sms_confirmation_code = confirmation_code
    user.sms_opt_in_timestamp = datetime.utcnow()  # Record opt-in timestamp
    db.session.commit()

    message = (
        f"Your ECS FC SMS verification code is: {confirmation_code}\n\n"
        "Reply END to opt-out at any time. Message and data rates may apply."
    )
    success, message_id = send_sms(player.phone, message)
    
    return success, message_id

def verify_sms_confirmation(user, code):
    if user.sms_confirmation_code == code:
        user.sms_notifications = True
        user.sms_confirmation_code = None
        db.session.commit()
        return True
    return False

def send_match_reminders(match):
    for player in match.players:
        if player.user.sms_notifications and player.phone:
            message = f"Reminder: You have a match scheduled on {match.date.strftime('%Y-%m-%d %H:%M')}."
            success, _ = send_sms(player.phone, message)
            if not success:
                current_app.logger.error(f"Failed to send reminder SMS to user {player.user.id}")

def user_is_blocked_in_textmagic(phone_number):
    client = TextmagicRestClient(current_app.config['TEXTMAGIC_USERNAME'], current_app.config['TEXTMAGIC_API_KEY'])
    try:
        # Get the list of unsubscribers matching the phone number
        response = client.unsubscribers.list(search=phone_number)

        # Log the full response to inspect its structure
        current_app.logger.debug(f'Received unsubscribers response: {response}')

        # Handle tuple response (since it's a tuple, use indexing to access the list of results)
        unsubscribers_list = response[0]  # Assuming the first element of the tuple contains the data

        # Check if there are any matching unsubscribers
        if unsubscribers_list and len(unsubscribers_list) > 0:
            current_app.logger.info(f'Phone number {phone_number} is unsubscribed in TextMagic.')
            return True
        else:
            current_app.logger.info(f'Phone number {phone_number} is not unsubscribed in TextMagic.')
            return False
    except Exception as e:
        current_app.logger.error(f"Error checking if phone {phone_number} is unsubscribed: {e}")
        return False

def handle_opt_out(player):
    logger.info(f'Opt-out request received for player: {player.user_id}')
    player.sms_opt_out_timestamp = datetime.utcnow()
    player.user.sms_notifications = False
    db.session.commit()
    logger.info(f'Player {player.user_id} successfully unsubscribed from SMS notifications')
    return jsonify({'status': 'success', 'message': 'User unsubscribed from SMS notifications'})

def handle_re_subscribe(player, phone_number):
    logger.info(f'Re-subscription request received for player: {player.user_id}')
    player.sms_consent_given = True
    player.sms_consent_timestamp = datetime.utcnow()
    player.sms_opt_out_timestamp = None
    player.is_phone_verified = True
    player.user.sms_notifications = True
    db.session.commit()
    logger.info(f'Player {player.user_id} successfully re-subscribed to SMS notifications')
    success, message_id = send_sms(phone_number, 'You are re-subscribed to ECS FC notifications. Reply END at any time to opt-out')
    if success:
        logger.info(f'Successfully sent re-subscribe confirmation SMS to {player.user_id}')
    else:
        logger.error(f'Failed to send re-subscribe confirmation SMS to {player.user_id}')
    return jsonify({'status': 'success', 'message': 'User re-subscribed to SMS notifications'})

def handle_next_match_request(player, phone_number):
    next_matches = get_next_match(phone_number)
    if next_matches:
        message = "Your upcoming matches:\n\n"
        for i, match in enumerate(next_matches, 1):
            message += f"{i}. {match['date']} at {match['time']}\n"
            message += f"   vs {match['opponent']} at {match['location']}\n\n"
    else:
        message = "You don't have any upcoming matches scheduled at the moment."
    
    success, message_id = send_sms(phone_number, message)
    if success:
        logger.info(f'Successfully sent next match information to {player.user_id}')
    else:
        logger.error(f'Failed to send next match information to {player.user_id}')
    return jsonify({'status': 'success', 'message': 'Next match information sent'})

def send_help_message(phone_number):
    help_message = "Available commands:\n- 'next match': Get info about your next match\n- 'schedule': Same as 'next match'\n- 'end': Unsubscribe from notifications\n- 'start': Re-subscribe to notifications"
    success, message_id = send_sms(phone_number, help_message)
    if success:
        logger.info(f'Successfully sent help message to {phone_number}')
    else:
        logger.error(f'Failed to send help message to {phone_number}')
    return jsonify({'status': 'success', 'message': 'Help message sent'})

def get_next_match(phone_number):
    # Find the player based on the phone number
    player = Player.query.filter_by(phone=phone_number).first()
    if not player:
        return None

    # Get the player's team
    team = player.team
    if not team:
        return None

    # Find the next two matches for the team
    current_date = datetime.utcnow().date()
    next_matches = Match.query.filter(
        or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
        Match.date >= current_date
    ).order_by(Match.date, Match.time).limit(2).all()

    if not next_matches:
        return None

    # Prepare the response
    response = []
    for match in next_matches:
        opponent = match.away_team if match.home_team_id == team.id else match.home_team
        match_info = {
            'date': match.date.strftime('%A, %B %d'),
            'time': match.time.strftime('%I:%M %p'),
            'opponent': opponent.name,
            'location': match.location
        }
        response.append(match_info)

    return response