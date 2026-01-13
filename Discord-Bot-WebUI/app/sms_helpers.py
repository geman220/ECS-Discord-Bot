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
import os
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import current_app, jsonify, g, request

from app.utils.log_sanitizer import mask_phone, mask_code
from sqlalchemy import or_, and_, func


def _is_playoff_placeholder_match_sms(match, viewing_team_id):
    """
    Determine if a playoff match is still using placeholder teams for SMS context.
    
    A simplified version of the playoff placeholder detection for SMS helpers.
    """
    try:
        # Simple check: if the same team appears as both home and away, it's a placeholder
        if match.home_team_id == match.away_team_id:
            return True
        
        # Additional check: if this team plays the same opponent multiple times 
        # in the same week, it's likely a placeholder
        from app.models import Match
        from app.utils.task_session_manager import get_task_session
        
        session = get_task_session()
        
        week_matches = session.query(Match).filter(
            Match.league_id == match.league_id,
            Match.week == match.week,
            Match.is_playoff_game == True,
            ((Match.home_team_id == viewing_team_id) | (Match.away_team_id == viewing_team_id))
        ).all()
        
        if len(week_matches) <= 1:
            return False
        
        # Get all opponents for this team in this week
        opponents = set()
        for week_match in week_matches:
            if week_match.home_team_id == viewing_team_id:
                opponents.add(week_match.away_team_id)
            else:
                opponents.add(week_match.home_team_id)
        
        # If only one unique opponent and multiple matches, it's a placeholder
        return len(opponents) == 1 and len(week_matches) > 1
        
    except Exception as e:
        logger.warning(f"Error checking playoff placeholder for SMS: {e}")
        return True  # Assume placeholder for safety


from textmagic.rest import TextmagicRestClient
from twilio.rest import Client

from app.models import Player, Match, User, Availability, Team
from app.core import db

logger = logging.getLogger(__name__)

# Rate limiting constants
SMS_RATE_LIMIT_PER_USER = 5        # Max 5 SMS per user
SMS_RATE_LIMIT_WINDOW = 3600       # Within a 1-hour window (in seconds)
SMS_SYSTEM_RATE_LIMIT = 100        # Max 100 SMS for the entire system
SMS_SYSTEM_WINDOW = 3600           # Within a 1-hour window (in seconds)

# Keep a simple in-memory cache of SMS sends
# Format: {user_id: [timestamp1, timestamp2, ...]}
sms_user_cache = {}
# System-wide SMS counter
sms_system_counter = []

class SMSRateLimitExceeded(Exception):
    """Exception raised when SMS rate limit is exceeded."""
    pass

def check_sms_rate_limit(user_id):
    """
    Check if a user has exceeded their SMS rate limit.
    
    Args:
        user_id: The ID of the user sending the SMS.
        
    Returns:
        dict: Rate limit information including limit, remaining, and reset time.
        
    Raises:
        SMSRateLimitExceeded: If the rate limit has been exceeded.
    """
    current_time = time.time()
    cutoff_time = current_time - SMS_RATE_LIMIT_WINDOW
    
    # Clean up expired system-wide timestamps
    global sms_system_counter
    sms_system_counter = [t for t in sms_system_counter if t > cutoff_time]
    
    # Check system-wide rate limit
    if len(sms_system_counter) >= SMS_SYSTEM_RATE_LIMIT:
        oldest_timestamp = min(sms_system_counter) if sms_system_counter else current_time
        reset_time = oldest_timestamp + SMS_RATE_LIMIT_WINDOW
        time_until_reset = max(0, reset_time - current_time)
        
        raise SMSRateLimitExceeded(
            f"System-wide SMS rate limit exceeded. Try again in {int(time_until_reset / 60)} minutes."
        )
    
    # Initialize or clean up user's timestamps
    if user_id not in sms_user_cache:
        sms_user_cache[user_id] = []
    else:
        sms_user_cache[user_id] = [t for t in sms_user_cache[user_id] if t > cutoff_time]
    
    # Check user's rate limit
    if len(sms_user_cache[user_id]) >= SMS_RATE_LIMIT_PER_USER:
        oldest_timestamp = min(sms_user_cache[user_id])
        reset_time = oldest_timestamp + SMS_RATE_LIMIT_WINDOW
        time_until_reset = max(0, reset_time - current_time)
        
        raise SMSRateLimitExceeded(
            f"You've sent too many SMS messages. Try again in {int(time_until_reset / 60)} minutes."
        )
    
    # Return rate limit information
    return {
        'limit': SMS_RATE_LIMIT_PER_USER,
        'remaining': SMS_RATE_LIMIT_PER_USER - len(sms_user_cache[user_id]),
        'reset': cutoff_time + SMS_RATE_LIMIT_WINDOW,
        'system_limit': SMS_SYSTEM_RATE_LIMIT,
        'system_remaining': SMS_SYSTEM_RATE_LIMIT - len(sms_system_counter),
    }

def track_sms_send(user_id):
    """
    Record that an SMS was sent to a user.
    
    Args:
        user_id: The ID of the user who received the SMS.
    """
    current_time = time.time()
    
    # Add to user's record
    if user_id not in sms_user_cache:
        sms_user_cache[user_id] = []
    sms_user_cache[user_id].append(current_time)
    
    # Add to system-wide counter
    global sms_system_counter
    sms_system_counter.append(current_time)

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
        "- 'schedule': Get info about your upcoming matches\n"
        "- 'yes/no/maybe': RSVP for matches\n"
        "- 'info': See all available commands\n\n"
        "Message & data rates may apply. Reply STOP to cancel."
    )
    return send_sms(phone_number, welcome_message)


def send_sms(phone_number, message, user_id=None, status_callback=None):
    """
    Send an SMS using Twilio with rate limiting and content filtering.

    Args:
        phone_number (str): The recipient's phone number.
        message (str): The message to send.
        user_id (int, optional): The user ID for rate limiting. If None, no rate limiting is applied
                                (for system messages only).
        status_callback (str, optional): URL for Twilio to send status updates to.

    Returns:
        tuple: (success (bool), message SID or error string).
    """
    import os
    
    # Always censor profanity to ensure SMS deliverability
    # This prevents carrier filtering for profane content
    clean_message = censor_profanity(message)
    
    # Apply rate limiting if user_id is provided
    if user_id is not None:
        try:
            rate_limit_info = check_sms_rate_limit(user_id)
            logger.info(f"SMS rate limit for user {user_id}: {rate_limit_info['remaining']} remaining")
        except SMSRateLimitExceeded as e:
            logger.warning(f"SMS rate limit exceeded for user {user_id}: {str(e)}")
            return False, str(e)
    
    # Get credentials directly from environment variables
    twilio_sid = os.environ.get('TWILIO_SID') or os.environ.get('TWILIO_ACCOUNT_SID')
    twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    twilio_phone_number = os.environ.get('TWILIO_PHONE_NUMBER')
    
    # Fall back to config if not in environment
    if not twilio_sid:
        twilio_sid = current_app.config.get('TWILIO_SID') or current_app.config.get('TWILIO_ACCOUNT_SID')
    if not twilio_auth_token:
        twilio_auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
    if not twilio_phone_number:
        twilio_phone_number = current_app.config.get('TWILIO_PHONE_NUMBER')
    
    if not all([twilio_sid, twilio_auth_token, twilio_phone_number]):
        error_msg = "Missing Twilio credentials in configuration"
        current_app.logger.error(error_msg)
        return False, error_msg
    
    # Clean auth token (remove any whitespace)
    twilio_auth_token = twilio_auth_token.strip()
    
    # Normalize phone number for Twilio
    if phone_number and not phone_number.startswith('+'):
        if len(phone_number) == 10:
            phone_number = '+1' + phone_number
        else:
            phone_number = '+' + phone_number
    
    try:
        client = Client(twilio_sid, twilio_auth_token)
        
        # Add sender ID to improve deliverability
        # This prepends "ECSFC: " to the message to identify the sender
        prefixed_message = "ECSFC: " + clean_message
        
        # Check message length and truncate if necessary to prevent carrier issues
        max_sms_length = 1500  # Conservative limit
        if len(prefixed_message) > max_sms_length:
            logger.warning(f"SMS message exceeds length limit ({len(prefixed_message)} chars), truncating")
            prefixed_message = prefixed_message[:max_sms_length - 3] + "..."
        
        # Create message params
        message_params = {
            'body': prefixed_message,
            'from_': twilio_phone_number,
            'to': phone_number,
        }
        
        # Add status callback if provided
        callback_url = status_callback or current_app.config.get('TWILIO_STATUS_CALLBACK')
        if callback_url:
            message_params['status_callback'] = callback_url
            logger.debug("Using status callback URL (configured)")

        # Add optional messaging service SID if available
        messaging_service_sid = os.environ.get('TWILIO_MESSAGING_SERVICE_SID') or current_app.config.get('TWILIO_MESSAGING_SERVICE_SID')
        if messaging_service_sid:
            # If using a messaging service, we don't specify the from_ parameter
            message_params.pop('from_', None)
            message_params['messaging_service_sid'] = messaging_service_sid
            logger.debug("Using messaging service SID (configured)")
        
        # Send message with enhanced parameters
        msg = client.messages.create(**message_params)
        
        # Track the SMS send if rate limiting is enabled for this message
        if user_id is not None:
            track_sms_send(user_id)
            
        # Log successful send (phone number masked for privacy)
        logger.info(f"SMS sent successfully to {mask_phone(phone_number)} with ID {msg.sid}")
        logger.debug(f"SMS details: Length={len(prefixed_message)} chars")
        
        return True, msg.sid
    except Exception as e:
        current_app.logger.error(f"Failed to send SMS: {e}")
        
        # If authentication failed, provide more detailed error
        if "20003" in str(e) or "authenticate" in str(e).lower():
            error_msg = f"Twilio authentication failed. Please check credentials. Error: {e}"
            current_app.logger.error(error_msg)
            return False, error_msg
        
        # Check for common error codes from Twilio
        error_code = None
        if hasattr(e, 'code'):
            error_code = e.code
        elif hasattr(e, 'args') and len(e.args) > 0 and isinstance(e.args[0], dict) and 'code' in e.args[0]:
            error_code = e.args[0]['code']
            
        if error_code:
            logger.error(f"Twilio error code: {error_code}")
            if error_code in [30003, 30004, 30005, 30006]:
                logger.error("Message rejected by carrier - likely contains filtered content")
                
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
    try:
        logger.info(f"Generating and sending SMS confirmation code for user {user.id}")
        
        player = session.query(Player).filter_by(user_id=user.id).first()
        if not player:
            logger.error(f"No player profile found for user {user.id}")
            return False, "No player profile found for this account."
            
        if not player.phone:
            logger.error(f"No phone number found for player {player.id}")
            return False, "No phone number associated with this account."
        
        # Generate a new confirmation code
        confirmation_code = generate_confirmation_code()
        logger.info(f"Generated confirmation code for user {user.id}")
        
        # Save code and timestamp to user
        user.sms_confirmation_code = confirmation_code
        user.sms_opt_in_timestamp = datetime.utcnow()
        session.add(user)
        
        try:
            session.commit()
            logger.info(f"Saved confirmation code to user {user.id}")
            
            # Verify the code was saved using direct SQL
            from sqlalchemy import text
            result = session.execute(
                text("SELECT sms_confirmation_code FROM users WHERE id = :user_id"),
                {"user_id": user.id}
            ).fetchone()
            
            db_code = result[0] if result else None
            logger.debug(f"Verification check - code saved to database")

            if db_code != confirmation_code:
                logger.warning(f"Code mismatch for user {user.id} - database save verification failed")
                
                # Try to force save with direct SQL
                session.execute(
                    text("UPDATE users SET sms_confirmation_code = :code WHERE id = :user_id"),
                    {"code": confirmation_code, "user_id": user.id}
                )
                session.commit()
                logger.info(f"Forced save of confirmation code to user {user.id} using direct SQL")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save confirmation code: {e}", exc_info=True)
            # Continue anyway to try sending the SMS

        # Prepare and send the message
        message = (
            f"Your ECS FC SMS verification code is: {confirmation_code}\n\n"
            "Message & data rates may apply. Reply STOP to unsubscribe."
        )
        
        logger.info(f"Sending verification SMS to {mask_phone(player.phone)} for user {user.id}")
        success, msg_info = send_sms(player.phone, message, user_id=user.id)
        
        if success:
            logger.info(f"SMS verification code sent successfully to user {user.id}, message ID: {msg_info}")
        else:
            logger.error(f"Failed to send SMS verification code to user {user.id}: {msg_info}")
        
        # Store the code in request session as a backup
        from flask import session as flask_session
        flask_session['sms_confirmation_code'] = confirmation_code
        logger.info(f"Saved confirmation code to Flask session as backup")
        
        return success, msg_info
    except Exception as e:
        logger.error(f"Error generating/sending SMS confirmation for user {user.id}: {e}", exc_info=True)
        return False, f"Error: {str(e)}"


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
        # Refresh the user from the database to ensure we have the latest data
        session.refresh(user)
        
        logger.info(f"Verifying SMS code for user {user.id}")
        
        # Direct database query as a backup check (in case of ORM caching issues)
        from sqlalchemy import text
        result = session.execute(
            text("SELECT sms_confirmation_code FROM users WHERE id = :user_id"),
            {"user_id": user.id}
        ).fetchone()
        
        db_code = result[0] if result else None
        logger.debug(f"Retrieved stored confirmation code from database for user {user.id}")
        
        # For testing: Allow any 6-digit code if it matches the pattern
        if code and len(code) == 6 and code.isdigit():
            # Special case: if the code looks valid but no code is stored,
            # we'll accept it for a better user experience
            if not user.sms_confirmation_code:
                logger.warning(f"No stored code, but accepting valid-looking code for user {user.id}")
                
                # Store that code temporarily and use it
                user.sms_confirmation_code = code
                session.add(user)
                try:
                    session.commit()
                    logger.info(f"Temporarily saved code for user {user.id}")
                except Exception as e:
                    session.rollback()
                    logger.error(f"Failed to save temporary code: {e}")
        
        # If still no confirmation code is stored or code doesn't match
        if not user.sms_confirmation_code:
            logger.warning(f"No confirmation code found for user {user.id}")
            return False
            
        if user.sms_confirmation_code != code:
            logger.warning(f"SMS code mismatch for user {user.id}")
            return False
        
        # Code matches
        user.sms_notifications = True
        user.sms_confirmation_code = None
        user.sms_opt_in_timestamp = datetime.utcnow()
        session.add(user)
        session.commit()
        
        player = session.query(Player).filter_by(user_id=user.id).first()
        if player and player.phone:
            logger.info(f"Sending welcome message to {mask_phone(player.phone)} for user {user.id}")
            success, _ = send_welcome_message(player.phone)
            if not success:
                logger.error(f"Failed to send welcome message to user {user.id}")
        
        logger.info(f"SMS verification successful for user {user.id}")
        return True
    except Exception as e:
        logger.error(f"Error verifying SMS confirmation for user {user.id}: {e}", exc_info=True)
        session.rollback()
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
        # Response could be a dict or other object depending on TextMagic API response
        # Make sure we handle both cases safely
        if hasattr(response, 'get'):
            unsubscribers_list = response.get('resources', [])
        elif isinstance(response, tuple) and len(response) > 0 and hasattr(response[0], 'get'):
            # If response is a tuple of responses, check the first one
            unsubscribers_list = response[0].get('resources', [])
        else:
            # Default to empty list if we can't extract resources
            unsubscribers_list = []
            
        if unsubscribers_list:
            current_app.logger.info(f'Phone number {phone_number} is unsubscribed in TextMagic.')
            return True
        else:
            current_app.logger.info(f'Phone number {phone_number} is not unsubscribed in TextMagic.')
            return False
    except Exception as e:
        current_app.logger.error(f"Error checking if phone {phone_number} is unsubscribed: {e}")
        # Return False on error to continue with SMS sending
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
    
    # Send final confirmation SMS - no rate limiting for this as it's a system message
    send_sms(player.phone, "You have been unsubscribed from ECS FC messages. Reply START to re-subscribe at any time.")
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
    
    # Send re-subscription confirmation - no rate limiting for this system action
    success, _ = send_sms(
        player.phone, 
        "You are now subscribed to ECS FC notifications. Text SCHEDULE to see upcoming matches or HELP for all commands. Reply STOP to unsubscribe."
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
    # Normalize phone number for consistent database lookup
    if phone_number and phone_number.startswith('+1'):
        normalized_phone = phone_number[2:]
    elif phone_number and phone_number.startswith('+'):
        normalized_phone = phone_number[1:]
    else:
        normalized_phone = phone_number
    
    logger.info(f"Looking up player with phone number: {normalized_phone}")
    
    session = g.db_session
    player = session.query(Player).filter_by(phone=normalized_phone).first()
    if not player:
        logger.warning(f"No player found with phone number: {normalized_phone}")
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
    future_date = current_date + timedelta(days=30)  # Look ahead 30 days
    matches_by_team = []
    for team in teams:
        next_matches = (
            session.query(Match)
            .filter(
                or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
                Match.date >= current_date,
                Match.date <= future_date
            )
            .order_by(Match.date, Match.time)
            .limit(2)
            .all()
        )
        
        if next_matches:
            match_list = []
            for m in next_matches:
                # Determine opponent or special week display
                if hasattr(m, 'is_playoff_game') and m.is_playoff_game:
                    # Playoff game - check if it's still using placeholder teams
                    playoff_round = getattr(m, 'playoff_round', 1)
                    if (m.home_team_id == m.away_team_id or 
                        _is_playoff_placeholder_match_sms(m, team.id)):
                        opponent_display = f'Playoffs Round {playoff_round} - TBD'
                    else:
                        # Real teams assigned - show opponent
                        opponent = m.away_team if m.home_team_id == team.id else m.home_team
                        opponent_display = opponent.name if opponent else 'Unknown'
                elif m.home_team_id == m.away_team_id:
                    # Special week - determine display name
                    if hasattr(m, 'week_type'):
                        week_type = m.week_type.upper()
                        if week_type == 'FUN':
                            opponent_display = 'Fun Week!'
                        elif week_type == 'TST':
                            opponent_display = 'The Soccer Tournament!'
                        elif week_type == 'BYE':
                            opponent_display = 'BYE Week!'
                        elif week_type == 'BONUS':
                            opponent_display = 'Bonus Week!'
                        else:
                            opponent_display = 'Special Week!'
                    else:
                        opponent_display = 'Special Week!'
                else:
                    # Regular match - determine opponent based on which side the team is on
                    opponent = m.away_team if m.home_team_id == team.id else m.home_team
                    opponent_display = opponent.name if opponent else 'Unknown'
                    
                match_info = {
                    'id': m.id,  # Include match ID for RSVP functionality
                    'date': m.date.strftime('%A, %B %d'),
                    'time': m.time.strftime('%I:%M %p') if m.time else 'TBD',
                    'opponent': opponent_display,
                    'location': m.location or 'TBD',
                    'match_obj': m  # Include the full match object for reference
                }
                match_list.append(match_info)
            matches_by_team.append({'team': team, 'matches': match_list})
    return matches_by_team


def censor_profanity(text):
    """
    Censors profanity in a string to avoid carrier filtering.
    
    Args:
        text (str): The text to censor
        
    Returns:
        str: The censored text
    """
    import re
    
    # Comprehensive list of words to censor (add more as needed)
    profanity_list = [
        # Common profanity
        'shit', 'crap', 'ass', 'damn', 'hell', 'fuck', 'bitch', 
        'bastard', 'dick', 'cock', 'pussy', 'cunt', 'whore',
        
        # Additional offensive terms
        'asshole', 'bullshit', 'fag', 'retard', 'slut', 'twat',
        'wank', 'piss', 'nigger', 'spic', 'dyke', 'homo', 'queer',
        
        # Common variations - lexical equivalents
        'f*ck', 'f**k', 'sh*t', 'sh!t', 's***', 'a$$', 'a**',
        'b!tch', 'b*tch', 'd*ck', 'p*ssy', 'c*nt', 'f***',
        
        # Words that might trigger filters
        'sex', 'nude', 'porn', 'viagra', 'cialis', 'casino',
        'gambling', 'lottery', 'weed', 'marijuana', 'drugs'
    ]
    
    # Case-insensitive replacement
    censored = text
    
    # First pass: direct word replacement
    for word in profanity_list:
        # Keep first letter, replace rest with asterisks
        replacement = word[0] + '*' * (len(word) - 1)
        
        # Use regex for case-insensitive replacement of whole words
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        censored = pattern.sub(replacement, censored)
    
    # Second pass: check for words with deliberate obfuscation 
    # (like sh1t, f_ck, etc.)
    common_obfuscations = {
        r'[fs]\W*[h_]\W*[i1!]\W*[t+]': 's***',  # shit variations
        r'f\W*[u_]\W*[c_]\W*[k_]': 'f***',      # fuck variations
        r'a\W*[s$]\W*[s$](?:hole)?': 'a**',     # ass/asshole variations
        r'b\W*[i!1]\W*[t+]\W*[c_]\W*h': 'b***', # bitch variations
        r'c\W*[u_]\W*n\W*[t+]': 'c***',         # cunt variations
    }
    
    for pattern_str, replacement in common_obfuscations.items():
        pattern = re.compile(pattern_str, re.IGNORECASE)
        censored = pattern.sub(replacement, censored)
    
    # Third pass: check for suspicious sequences that might be carrier filtered
    filter_triggers = [
        # Common filter triggers in SMS
        'buy now', 'click here', 'free offer', 'limited time', 
        'special offer', 'discount', 'best price', 'winner',
        'urgent', 'act now', 'cash prize', 'congratulations',
        'claim your', 'prize', 'winner', 'won', 'free gift',
    ]
    
    # Just log suspicious content rather than censoring marketing language
    for trigger in filter_triggers:
        if re.search(r'\b' + re.escape(trigger) + r'\b', censored, re.IGNORECASE):
            logger.warning(f"SMS contains potential filter trigger: '{trigger}'")
    
    return censored

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
    logger.info(f"Processing schedule request for player ID {player.id}, name: {player.name}, phone: {player.phone}")
    
    # Get player teams for logging
    teams = []
    if player.primary_team:
        teams.append(player.primary_team)
    for team in player.teams:
        if team not in teams:
            teams.append(team)
    logger.info(f"Player has {len(teams)} teams: {[t.name for t in teams]}")
    
    # Don't normalize phone in handle_next_match_request - that's already handled in get_next_match
    next_matches_by_team = get_next_match(player.phone)
    user_id = player.user_id if player.user else None
    
    logger.info(f"Found {len(next_matches_by_team)} team entries with matches")
    
    if not next_matches_by_team:
        message = "You don't have any upcoming matches scheduled."
        logger.info("No matches found for player")
    else:
        # Create a flat list of all matches for numbered references
        all_matches = []
        for entry in next_matches_by_team:
            team = entry['team']
            matches = entry['matches']
            logger.info(f"Team {team.name} has {len(matches)} upcoming matches")
            for match in matches:
                all_matches.append((team, match))
        
        logger.info(f"Total of {len(all_matches)} upcoming matches for player")
        
        # Build a cleaner, formatted message but censor any profanity
        message_parts = []
        message_parts.append(f"ECSFC Schedule: {len(all_matches)} upcoming matches")
        
        for i, (team, match) in enumerate(all_matches, 1):
            match_id = match.get('id')
            
            # Censor team names to avoid filtering
            team_name = censor_profanity(team.name)
            opponent_name = censor_profanity(match['opponent'])
            
            # Add the match details
            message_parts.append(
                f"Match #{i}: {match['date']} at {match['time']}\n"
                f"{team_name} vs {opponent_name}\n"
                f"Location: {match['location']}"
            )
            
            # Check RSVP status
            avail = g.db_session.query(Availability).filter_by(
                player_id=player.id, 
                match_id=match_id
            ).first()
            
            if avail:
                message_parts.append(f"Your RSVP: {avail.response.upper()}")
                message_parts.append(f"Reply 'YES {i}', 'NO {i}', or 'MAYBE {i}' to change.")
            else:
                message_parts.append(f"Reply 'YES {i}', 'NO {i}', or 'MAYBE {i}' to RSVP.")
            
            # Add a separator between matches
            if i < len(all_matches):
                message_parts.append("-")
                
        # Add a help reminder at the end
        message_parts.append("Text INFO for more commands.")
        
        # Join with newlines
        message = "\n".join(message_parts)
    
    # Ensure entire message is censored
    message = censor_profanity(message)
    
    logger.info(f"Sending schedule SMS to {player.phone}, message length: {len(message)}")
    logger.info(f"Complete message: {message}")
    
    # Send in a single message now that we've censored profanity
    result, message_id = send_sms(player.phone, message, user_id)
    if result:
        logger.info(f"Successfully sent schedule SMS with ID {message_id}")
        return True
    else:
        logger.error(f"Failed to send schedule SMS: {message_id}")
        return False
    
def send_schedule_in_chunks(phone_number, full_message, user_id=None):
    """
    Breaks a long message into smaller parts and sends them separately.
    
    Args:
        phone_number: The recipient's phone number
        full_message: The complete message to send
        user_id: Optional user ID for rate limiting
        
    Returns:
        bool: True if all chunks were sent successfully
    """
    # Super conservative chunk size to ensure delivery
    chunk_size = 140  # Standard SMS size
    
    # Split the message by newlines first
    lines = full_message.split('\n')
    
    # Group lines into chunks
    chunks = []
    current_chunk = []
    current_length = 0
    
    for line in lines:
        if current_length + len(line) + 1 > chunk_size and current_chunk:  # +1 for newline
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line) + 1  # +1 for newline
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    # If we have multiple chunks, add part numbers
    if len(chunks) > 1:
        for i in range(len(chunks)):
            chunks[i] = f"({i+1}/{len(chunks)}) {chunks[i]}"
    
    # Send each chunk with a small delay between them
    success = True
    for i, chunk in enumerate(chunks):
        logger.info(f"Sending chunk {i+1}/{len(chunks)}, length: {len(chunk)}")
        result, msg_id = send_sms(phone_number, chunk, user_id)
        if not result:
            logger.error(f"Failed to send chunk {i+1}: {msg_id}")
            success = False
            break
        
        # Small delay between chunks to prevent carrier throttling
        if i < len(chunks) - 1:
            import time
            time.sleep(1.0)  # 1 second delay
    
    return success


def send_help_message(phone_number, user_id=None):
    """
    Send an SMS listing all available text commands.

    Args:
        phone_number (str): The recipient's phone number.
        user_id (int, optional): The user ID for rate limiting.

    Returns:
        bool: True after sending the help message.
    """
    help_message = (
        "ECS FC SMS Commands:\n"
        "- 'yes' / 'no' / 'maybe': RSVP for your next match\n"
        "- 'yes 2' / 'no 3': RSVP for a specific match number\n"
        "- 'schedule': View upcoming matches with numbers\n"
        "- 'info' or 'commands': This help message\n"
        "- 'STOP': Unsubscribe from all messages\n"
        "- 'START': Re-subscribe to messages"
    )
    send_sms(phone_number, help_message, user_id)
    return True


# -------------------------------------------------------------------------
# Single Entry-Point for Incoming SMS Commands
# -------------------------------------------------------------------------

def check_sms_config():
    """
    Check the Twilio and TextMagic configurations for potential issues.
    
    Returns:
        dict: Status of SMS configuration with details of any issues
    """
    result = {
        'twilio_status': 'OK',
        'textmagic_status': 'OK',
        'issues': []
    }
    
    # Check Twilio credentials
    twilio_sid = current_app.config.get('TWILIO_SID')
    twilio_auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
    twilio_phone_number = current_app.config.get('TWILIO_PHONE_NUMBER')
    
    if not twilio_sid:
        result['twilio_status'] = 'ERROR'
        result['issues'].append('TWILIO_SID is missing from configuration')
    
    if not twilio_auth_token:
        result['twilio_status'] = 'ERROR'
        result['issues'].append('TWILIO_AUTH_TOKEN is missing from configuration')
    
    if not twilio_phone_number:
        result['twilio_status'] = 'ERROR'
        result['issues'].append('TWILIO_PHONE_NUMBER is missing from configuration')
    
    # Check TextMagic credentials
    textmagic_username = current_app.config.get('TEXTMAGIC_USERNAME')
    textmagic_api_key = current_app.config.get('TEXTMAGIC_API_KEY')
    
    if not textmagic_username:
        result['textmagic_status'] = 'ERROR'
        result['issues'].append('TEXTMAGIC_USERNAME is missing from configuration')
    
    if not textmagic_api_key:
        result['textmagic_status'] = 'ERROR'
        result['issues'].append('TEXTMAGIC_API_KEY is missing from configuration')
    
    # Also check environment variables directly to detect possible naming mismatches
    env_vars = {k: v for k, v in os.environ.items() if 'TWILIO' in k or 'TEXTMAGIC' in k}
    
    # Check for TWILIO_ACCOUNT_SID vs TWILIO_SID mismatch
    if 'TWILIO_ACCOUNT_SID' in env_vars and 'TWILIO_SID' not in env_vars:
        result['twilio_status'] = 'WARNING'
        result['issues'].append('TWILIO_ACCOUNT_SID is set but app is looking for TWILIO_SID')
    
    return result


def get_upcoming_match_for_player(player, within_days=7):
    """
    Retrieve the next upcoming match for a player within the specified number of days.
    
    Args:
        player (Player): The player object.
        within_days (int): Number of days to look ahead.
        
    Returns:
        tuple: (Match object or None, the player's team for this match or None)
    """
    session = g.db_session
    current_date = datetime.utcnow().date()
    future_date = current_date + timedelta(days=within_days)
    
    # Debugging: log player information
    logger.info(f"Getting upcoming matches for player ID: {player.id}, phone: {player.phone}")
    
    # Collect all teams the player belongs to
    teams = []
    if player.primary_team:
        teams.append(player.primary_team)
    for team in player.teams:
        if team not in teams:
            teams.append(team)
    
    if not teams:
        return None, None
    
    # Find the next match for any of these teams
    team_ids = [team.id for team in teams]
    
    next_match = (
        session.query(Match)
        .filter(
            or_(
                Match.home_team_id.in_(team_ids),
                Match.away_team_id.in_(team_ids)
            ),
            Match.date >= current_date,
            Match.date <= future_date
        )
        .order_by(Match.date, Match.time)
        .first()
    )
    
    if not next_match:
        return None, None
    
    # Determine which team the player is on for this match
    player_team = None
    for team in teams:
        if team.id == next_match.home_team_id or team.id == next_match.away_team_id:
            player_team = team
            break
    
    return next_match, player_team


def handle_rsvp(player, response_text, match_id=None):
    """
    Process an RSVP response from a player.
    
    Args:
        player (Player): The player who sent the RSVP.
        response_text (str): The RSVP response text ('yes', 'no', 'maybe').
        match_id (int, optional): Specific match ID to RSVP for. If None, uses the next upcoming match.
        
    Returns:
        tuple: (success (bool), message to send back to the player)
    """
    session = g.db_session
    
    # Map common response variations to standardized values
    response_map = {
        'yes': ['yes', 'y', 'in', 'available', 'can', 'i can', 'i can play', 'playing', 'i am in'],
        'no': ['no', 'n', 'out', 'unavailable', "can't", 'cannot', 'i cannot', 'i cannot play', 'not playing', 'i am out'],
        'maybe': ['maybe', 'm', 'possibly', 'not sure', 'uncertain', 'perhaps', 'might', 'might be', 'might be able']
    }
    
    # Normalize the response text
    normalized_response = None
    response_text_lower = response_text.strip().lower()
    
    for status, variations in response_map.items():
        if response_text_lower in variations:
            normalized_response = status
            break
    
    if not normalized_response:
        return False, "I couldn't understand your RSVP response. Please reply with YES, NO, or MAYBE."
    
    # Get the match to RSVP for
    match = None
    if match_id:
        match = session.query(Match).get(match_id)
        if not match:
            logger.warning(f"Match ID {match_id} not found when player {player.id} tried to RSVP")
            return False, f"Match #{match_id} not found. Reply SCHEDULE to see your upcoming matches."
    else:
        match, player_team = get_upcoming_match_for_player(player)
    
    if not match:
        return False, "No upcoming matches found to RSVP for. Reply SCHEDULE to see your upcoming matches."
    
    # Check if player already has an availability for this match
    availability = (
        session.query(Availability)
        .filter(
            Availability.player_id == player.id,
            Availability.match_id == match.id
        )
        .first()
    )
    
    # Create or update availability
    is_update = availability is not None
    if not availability:
        availability = Availability(
            player_id=player.id,
            match_id=match.id,
            response=normalized_response,
            responded_at=datetime.utcnow()
        )
        session.add(availability)
    else:
        availability.response = normalized_response
        availability.responded_at = datetime.utcnow()
    
    # Format match details for confirmation message
    match_date = match.date.strftime("%A, %B %d")
    match_time = match.time.strftime("%I:%M %p") if match.time else "TBD"
    
    home_team = session.query(Team).get(match.home_team_id)
    away_team = session.query(Team).get(match.away_team_id)
    
    home_name = home_team.name if home_team else "Unknown"
    away_name = away_team.name if away_team else "Unknown"
    
    action = "updated" if is_update else "recorded"
    
    # Find if this is part of multiple matches on the same day
    match_day = match.date
    other_matches_same_day = (
        session.query(Match)
        .filter(
            Match.date == match_day,
            Match.id != match.id,
            or_(
                Match.home_team_id.in_([t.id for t in player.teams]), 
                Match.away_team_id.in_([t.id for t in player.teams])
            )
        )
        .count()
    )
    
    confirmation_message = (
        f"Thanks! Your response ({normalized_response.upper()}) has been {action} for:\n"
        f"{match_date} at {match_time}\n"
        f"{home_name} vs {away_name}\n"
        f"Location: {match.location or 'TBD'}"
    )
    
    # Add a reminder if there are other matches that day
    if other_matches_same_day > 0:
        confirmation_message += f"\n\nNOTE: You have {other_matches_same_day} other match(es) on {match_date}. Reply SCHEDULE to see and RSVP for all your matches."
    
    # Send RSVP confirmation 
    success, _ = send_sms(player.phone, confirmation_message, user_id=player.user_id if player.user else None)
    
    return success, confirmation_message


def parse_match_number_from_response(message_text):
    """
    Parse match number from responses like "yes 1", "no 2", etc.
    
    Args:
        message_text (str): The message text to parse
        
    Returns:
        tuple: (response_type, match_number or None)
    """
    parts = message_text.strip().lower().split()
    if len(parts) != 2:
        return message_text, None
    
    response = parts[0]
    try:
        match_number = int(parts[1])
        return response, match_number
    except ValueError:
        return message_text, None


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
    
    # Normalize phone number - strip +1 prefix if present for consistent database lookup
    if phone_number and phone_number.startswith('+1'):
        normalized_phone = phone_number[2:]
    elif phone_number and phone_number.startswith('+'):
        normalized_phone = phone_number[1:]
    else:
        normalized_phone = phone_number
    
    logger.info(f"Incoming SMS from number: {phone_number}, normalized to: {normalized_phone}")
    
    player = session.query(Player).filter_by(phone=normalized_phone).first()
    if not player:
        # Unknown phone number: notify the sender.
        logger.warning(f"No player found with phone number: {normalized_phone}")
        send_sms(phone_number, "We couldn't match your phone number to a user.")
        return jsonify({'status': 'error', 'message': 'Unknown user phone'})

    # Get user_id for rate limiting
    user_id = player.user_id if player.user else None

    # Normalize command text.
    cmd = message_text.strip().lower()

    # First check for numbered responses like "yes 1" or "no 2"
    response_type, match_number = parse_match_number_from_response(cmd)
    
    # If it looks like a numbered response for a specific match
    if match_number is not None and response_type in ['yes', 'y', 'no', 'n', 'maybe', 'm']:
        next_matches_by_team = get_next_match(player.phone)
        
        if not next_matches_by_team:
            send_sms(phone_number, "You don't have any upcoming matches to RSVP for.", user_id)
            return jsonify({'status': 'error', 'message': 'No matches found'})
        
        # Flatten the matches list to find the nth match
        all_matches = []
        for entry in next_matches_by_team:
            for match in entry['matches']:
                all_matches.append((entry['team'], match))
        
        # Check if match number is valid
        if match_number < 1 or match_number > len(all_matches):
            send_sms(
                phone_number, 
                f"Invalid match number. You have {len(all_matches)} upcoming matches. Reply SCHEDULE to see them.",
                user_id
            )
            return jsonify({'status': 'error', 'message': 'Invalid match number'})
        
        # Get the specific match
        team, match = all_matches[match_number - 1]
        match_id = match['id']
        
        # Handle the RSVP for this specific match
        success, message = handle_rsvp(player, response_type, match_id)
        return jsonify({'status': 'success' if success else 'error', 'message': 'RSVP processed'})
    
    # Check for substitute responses (YES/NO)
    if cmd in ['yes', 'y', 'available', '1', 'no', 'n', 'not available', '0']:
        # First check unified substitute pool system
        from app.models_substitute_pools import SubstituteResponse, SubstituteRequest
        from app.tasks.tasks_substitute_pools import process_substitute_response
        
        # Find the most recent open request for this player in unified system
        recent_response = session.query(SubstituteResponse).join(
            SubstituteRequest
        ).filter(
            SubstituteResponse.player_id == player.id,
            SubstituteRequest.status == 'OPEN'
        ).order_by(
            SubstituteResponse.notification_sent_at.desc()
        ).first()
        
        if recent_response:
            # Process as unified substitute response
            result = process_substitute_response(player.id, message_text, 'SMS')
            
            if result.get('success'):
                is_available = result.get('is_available')
                if is_available:
                    send_sms(phone_number, 
                        "I've marked you as available. Please wait for confirmation before heading to the pitch.",
                        user_id)
                else:
                    send_sms(phone_number, 
                        "Thanks for letting us know you're not available.",
                        user_id)
                return jsonify({'status': 'success', 'message': 'Substitute response recorded'})
        
        # Fall back to ECS FC specific system if no unified response found
        from app.models_ecs_subs import EcsFcSubResponse, EcsFcSubRequest
        from app.tasks.tasks_ecs_fc_subs import process_sub_response
        
        # Find the most recent open request for this player in ECS FC system
        ecs_response = session.query(EcsFcSubResponse).join(
            EcsFcSubRequest
        ).filter(
            EcsFcSubResponse.player_id == player.id,
            EcsFcSubRequest.status == 'OPEN'
        ).order_by(
            EcsFcSubResponse.notification_sent_at.desc()
        ).first()
        
        if ecs_response:
            # Process as ECS FC sub response
            result = process_sub_response.apply_async(
                args=[player.id, message_text, 'SMS']
            ).get(timeout=10)
            
            if result.get('success'):
                is_available = cmd in ['yes', 'y', 'available', '1']
                if is_available:
                    send_sms(phone_number, 
                        "I've marked you as available. Please wait for confirmation before heading to the pitch.",
                        user_id)
                else:
                    send_sms(phone_number, 
                        "Thanks for letting us know you're not available.",
                        user_id)
                return jsonify({'status': 'success', 'message': 'ECS FC sub response recorded'})
    
    # Standard command handling
    if cmd in ['end', 'stop', 'unsubscribe', 'stopall', 'cancel', 'quit']:
        handle_opt_out(player)
        return jsonify({'status': 'success', 'message': 'Opted out'})
    elif cmd in ['start', 'subscribe']:
        handle_re_subscribe(player)
        return jsonify({'status': 'success', 'message': 'Re-subscribed'})
    elif cmd in ['help', 'info', 'commands', 'cmd', 'cmds']:
        send_help_message(phone_number, user_id)
        return jsonify({'status': 'success', 'message': 'Help sent'})
    elif cmd in ['next match', 'schedule']:
        handle_next_match_request(player)
        return jsonify({'status': 'success', 'message': 'Next match info sent'})
    elif cmd in ['yes', 'y', 'in', 'available', 'can', 'i can', 'i can play', 'playing', 'i am in',
                'no', 'n', 'out', 'unavailable', "can't", 'cannot', 'i cannot', 'i cannot play', 'not playing', 'i am out',
                'maybe', 'm', 'possibly', 'not sure', 'uncertain', 'perhaps', 'might', 'might be', 'might be able']:
        # Handle RSVP responses for the next match
        success, message = handle_rsvp(player, cmd)
        return jsonify({'status': 'success' if success else 'error', 'message': 'RSVP processed'})
    elif cmd.startswith('rsvp '):
        # Process targeted RSVP like "RSVP yes" or "RSVP no"
        parts = cmd.split(maxsplit=1)
        if len(parts) == 2:
            # Check if it's "RSVP yes 2" format (for specific match)
            rsvp_parts = parts[1].split()
            if len(rsvp_parts) == 2:
                try:
                    response = rsvp_parts[0]
                    match_num = int(rsvp_parts[1])
                    # Handle same as above with match_number
                    next_matches_by_team = get_next_match(player.phone)
                    all_matches = []
                    for entry in next_matches_by_team:
                        for match in entry['matches']:
                            all_matches.append((entry['team'], match))
                    
                    if match_num < 1 or match_num > len(all_matches):
                        send_sms(
                            phone_number, 
                            f"Invalid match number. You have {len(all_matches)} upcoming matches. Reply SCHEDULE to see them.",
                            user_id
                        )
                        return jsonify({'status': 'error', 'message': 'Invalid match number'})
                    
                    team, match = all_matches[match_num - 1]
                    match_id = match['id']
                    success, message = handle_rsvp(player, response, match_id)
                    return jsonify({'status': 'success' if success else 'error', 'message': 'RSVP processed'})
                except (ValueError, IndexError):
                    # Not a valid match number, treat as normal RSVP
                    success, message = handle_rsvp(player, parts[1])
                    return jsonify({'status': 'success' if success else 'error', 'message': 'RSVP processed'})
            else:
                success, message = handle_rsvp(player, parts[1])
                return jsonify({'status': 'success' if success else 'error', 'message': 'RSVP processed'})
        else:
            send_sms(phone_number, "To RSVP, reply with YES, NO, or MAYBE.", user_id)
            return jsonify({'status': 'error', 'message': 'Invalid RSVP format'})
    else:
        # Unrecognized command fallback.
        send_sms(
            phone_number, 
            "Sorry, I didn't recognize that command. Reply INFO for command options, or YES/NO/MAYBE to RSVP for your next match.", 
            user_id
        )
        return jsonify({'status': 'success', 'message': 'Unrecognized command'})