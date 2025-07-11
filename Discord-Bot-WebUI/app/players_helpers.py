# app/players_helpers.py

"""
Players Helpers Module

This module provides helper functions for player management,
including profile picture processing, user creation, matching,
data extraction, email notifications, and progress updates.
"""

# Standard library imports
import os
import re
import uuid
import base64
import secrets
import string
import logging
from io import BytesIO

# Third-party imports
from flask import current_app, url_for, render_template, g
from flask_mail import Message, Mail
from itsdangerous import URLSafeTimedSerializer
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from PIL import Image

# Local application imports
from app.models import Player, PlayerOrderHistory, User, Progress
from app.core.session_manager import managed_session
from app.core import db

logger = logging.getLogger(__name__)


def save_cropped_profile_picture(cropped_image_data, player_id):
    """
    Save the cropped profile picture for a player.
    
    Decodes the provided base64 image data, saves the image as a PNG file,
    updates the player's profile picture path, and returns the new path.
    
    Args:
        cropped_image_data (str): The base64 encoded image data.
        player_id (int): The ID of the player.
    
    Returns:
        str: The file path to the saved profile picture.
    
    Raises:
        Exception: Propagates any error encountered during the process.
    """
    try:
        header, encoded = cropped_image_data.split(",", 1)
        image_data = base64.b64decode(encoded)
        image = Image.open(BytesIO(image_data)).convert("RGBA")

        session = g.db_session
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return None

        player_name = player.name.replace(" ", "_")
        filename = secure_filename(f"{player_name}_{player_id}.png")
        upload_folder = os.path.join(current_app.root_path, 'static/img/uploads/profile_pictures')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)

        image.save(file_path, format='PNG')
        profile_path = f"/static/img/uploads/profile_pictures/{filename}"

        player.profile_picture = profile_path
        return player.profile_picture

    except Exception as e:
        logger.error(f"Error saving profile picture: {str(e)}", exc_info=True)
        raise


def generate_random_password(length=16):
    """
    Generates a secure random password.
    
    Ensures the password includes at least one lowercase letter, one uppercase letter,
    one digit, and one punctuation character, excluding ambiguous characters.
    
    Args:
        length (int, optional): Desired length of the password. Must be at least 12. Defaults to 16.
    
    Returns:
        str: The generated password.
    
    Raises:
        ValueError: If the requested length is less than 12.
    """
    if length < 12:
        raise ValueError("Password length should be at least 12 characters for security.")
    
    characters = string.ascii_letters + string.digits + string.punctuation
    ambiguous = {'"', "'", '\\', '`'}
    allowed_characters = ''.join(c for c in characters if c not in ambiguous)
    
    # Ensure each character type is represented
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(string.punctuation)
    ]
    password += [secrets.choice(allowed_characters) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(password)
    
    return ''.join(password)


def create_user_for_player(player_info, session):
    """
    Create or return an existing User based on the player's email.
    
    Searches for an existing user by email (case-insensitive). If found, returns the user;
    otherwise, creates a new user with a random password.
    
    Args:
        player_info (dict): Dictionary containing at least 'email' and 'name'.
        session (Session): Database session to use for queries and commits.
    
    Returns:
        User: The existing or newly created user.
    """
    logger.debug(f"create_user_for_player called with {player_info}")
    logger.debug("Querying for existing user by email...")
    
    existing_user = session.query(User).filter(
        func.lower(User.email) == func.lower(player_info['email'])
    ).first()
    logger.debug(f"existing_user={existing_user}")
    
    if existing_user:
        logger.debug("Returning existing_user.")
        return existing_user

    try:
        random_password = ''.join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(10)
        )
        new_user = User(
            email=player_info['email'],
            username=player_info['name'] or player_info['email'],
            is_approved=True
        )
        new_user.set_password(random_password)
        session.add(new_user)
        session.flush()
        logger.info(f"Created new user: id={new_user.id}, email={new_user.email}")
        return new_user

    except Exception as e:
        logger.exception("Error in create_user_for_player")
        raise


def generate_unique_name(base_name):
    """
    Generate a unique player name by appending a counter if necessary.
    
    Args:
        base_name (str): The original name to start with.
    
    Returns:
        str: A unique name that does not conflict with existing player names.
    """
    session = g.db_session
    count = 1
    unique_name = base_name
    while session.query(Player).filter_by(name=unique_name).first():
        unique_name = f"{base_name} +{count}"
        count += 1
    return unique_name


def generate_unique_username(base_name):
    """
    Generate a unique username based on a base name.
    
    Args:
        base_name (str): The base name for the username.
    
    Returns:
        str: A unique username limited to 50 characters.
    """
    session = g.db_session
    unique_username = base_name[:50]
    while session.query(User).filter_by(username=unique_username).first():
        unique_username = f"{base_name} ({str(uuid.uuid4())[:8]})"[:50]
    return unique_username


def generate_contact_info(player_data, is_placeholder):
    """
    Generate contact information for a player.
    
    If is_placeholder is True, returns a placeholder email and phone number.
    Otherwise, extracts the email and phone from the provided player data.
    
    Args:
        player_data (dict): Dictionary containing player information.
        is_placeholder (bool): Flag indicating whether to generate placeholder info.
    
    Returns:
        tuple: (email, phone)
    """
    if is_placeholder:
        return f"placeholder_{uuid.uuid4()}@publeague.com", f"00000000{uuid.uuid4().int % 10000:04d}"
    return player_data['email'], player_data['phone']


def has_previous_season_order(player, season):
    """
    Check if a player has an order history from the previous season.
    
    Args:
        player (Player): The player object.
        season (Season): The current season object.
    
    Returns:
        bool: True if there is a previous season order, False otherwise.
    """
    session = g.db_session
    return session.query(PlayerOrderHistory).filter_by(
        player_id=player.id,
        season_id=season.id - 1
    ).first() is not None


def standardize_name(name):
    """
    Standardize a name by capitalizing each part.
    
    Handles hyphenated names by capitalizing each segment.
    
    Args:
        name (str): The name to standardize.
    
    Returns:
        str: The standardized name.
    """
    name_parts = name.split()
    standardized_name = ' '.join(
        part.capitalize() if '-' not in part else '-'.join(p.capitalize() for p in part.split('-'))
        for part in name_parts
    )
    return standardized_name


def standardize_phone(phone):
    """
    Standardize a phone number by removing all non-digit characters.
    
    Args:
        phone (str): The phone number string.
    
    Returns:
        str: The cleaned phone number containing only digits.
    """
    if phone:
        return ''.join(filter(str.isdigit, phone))
    return ''


def match_user(player_data):
    """
    Attempt to match a user based on player data.
    
    First, matches by email (case-insensitive). If no user is found,
    attempts to match by standardized name and phone number.
    
    Args:
        player_data (dict): Dictionary containing player details.
    
    Returns:
        User or None: The matched user, or None if no match is found.
    """
    session = g.db_session
    email = player_data.get('email', '').lower()
    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))

    user = session.query(User).filter(func.lower(User.email) == email).first()
    if user:
        return user

    if name and phone:
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(Player.phone, '-', ''), 
                    '(', ''
                ), ')', ''
            ), ' ', ''
        )
        player = session.query(Player).filter(
            func.lower(Player.name) == func.lower(name),
            standardized_phone_db == phone
        ).first()
        if player and player.user:
            return player.user

    return None


def match_player(player_data, league, user=None, session=None):
    """
    Attempt to find an existing Player in a league using weighted matching.
    
    The function first checks:
      1) If a user is provided, looks for a player with that user_id in the league.
      2) Otherwise, attempts to match a user by email, then looks up the player.
      3) Falls back to matching by standardized name and phone.
    
    Args:
        player_data (dict): Player information dictionary.
        league (League): The league to search within.
        user (User, optional): A pre-matched user. Defaults to None.
        session (Session, optional): Database session. Defaults to None.
    
    Returns:
        Player or None: The matching player, or None if no match is found.
    """
    if session is None:
        session = g.db_session

    logger.debug("Entering match_player")
    logger.debug(f"Player data received: {player_data}")

    if user and user.id:
        logger.debug(f"User passed in: {user} with id {user.id}. Checking for existing player in league {league.id}...")
        existing_player = session.query(Player).filter_by(
            user_id=user.id,
            league_id=league.id
        ).first()
        if existing_player:
            logger.debug(f"Found existing player by (user_id, league_id): {existing_player.id}")
            return existing_player
        else:
            logger.debug("No player found for this user in this league; falling back to name+phone matching.")
    else:
        matched_user = match_user(player_data)
        if matched_user:
            logger.debug(f"match_user returned: {matched_user} with id {matched_user.id}")
            player_by_user = session.query(Player).filter_by(user_id=matched_user.id, league_id=league.id).first()
            if player_by_user:
                logger.debug(f"Found player by user_id: {player_by_user.id}")
                return player_by_user
            else:
                logger.debug("No player found using matched_user in this league; falling back to name+phone.")
                user = matched_user
        else:
            logger.debug("No matching user found from player data.")

    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))
    logger.debug(f"Standardized name: {name}, Standardized phone: {phone}")

    if name and phone:
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(Player.phone, '-', ''), 
                    '(', ''
                ), ')', ''
            ), ' ', ''
        )
        player_by_phone = session.query(Player).filter(
            func.lower(Player.name) == func.lower(name),
            standardized_phone_db == phone
        ).first()
        if player_by_phone:
            logger.debug(f"Found player by name and phone: {player_by_phone.id}")
            return player_by_phone
        else:
            logger.debug("No player found matching standardized name+phone.")
    else:
        logger.debug("Either name or phone is empty after standardization.")

    logger.debug("match_player returning None")
    return None


def extract_player_info(billing):
    """
    Extract player information from a billing dictionary.
    
    Combines first and last names, cleans the phone number, and standardizes the email.
    Defaults jersey_size to 'N/A'.
    
    Args:
        billing (dict): Billing information containing keys 'first_name', 'last_name', 'phone', and 'email'.
    
    Returns:
        dict or None: Dictionary with keys 'name', 'email', 'phone', 'jersey_size' or None if an error occurs.
    """
    try:
        name = f"{billing.get('first_name', '').strip()} {billing.get('last_name', '').strip()}".title()
        phone = re.sub(r'\D', '', billing.get('phone', ''))
        email = billing.get('email', '').strip().lower()
        jersey_size = 'N/A'
        return {
            'name': name,
            'email': email,
            'phone': phone,
            'jersey_size': jersey_size
        }
    except Exception as e:
        logger.error(f"Error extracting player info: {e}", exc_info=True)
        return None


def send_password_setup_email(user):
    """
    Send a password setup email to the user.
    
    Generates a secure token for password setup and sends an email using Flask-Mail.
    
    Args:
        user (User): The user to send the email to.
    """
    try:
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = serializer.dumps(user.email, salt=current_app.config['SECURITY_PASSWORD_SALT'])
        reset_url = url_for('reset_password', token=token, _external=True)
        msg = Message('Set Your Password', recipients=[user.email])
        msg.body = render_template('emails/password_setup.txt', reset_url=reset_url, username=user.username)
        msg.html = render_template('emails/password_setup.html', reset_url=reset_url, username=user.username)
        mail.send(msg)
        logger.info(f"Sent password setup email to '{user.email}'.")
    except Exception as e:
        logger.error(f"Error sending password setup email to '{user.email}': {e}", exc_info=True)


def hash_password(password):
    """
    Hash the provided password using the scrypt method.
    
    Args:
        password (str): The plaintext password.
    
    Returns:
        str: The hashed password.
    """
    return generate_password_hash(password, method='scrypt')


def clean_phone_number(phone):
    """
    Clean a phone number by removing non-digit characters and returning the last 10 digits if possible.
    
    Args:
        phone (str): The phone number string.
    
    Returns:
        str: The cleaned phone number.
    """
    cleaned_phone = re.sub(r'\D', '', phone)
    return cleaned_phone[-10:] if len(cleaned_phone) >= 10 else cleaned_phone


def match_player_weighted(player_info, db_session):
    """
    Perform weighted matching to identify an existing player.
    
    First attempts to match by email, then by standardized name and phone.
    
    Args:
        player_info (dict): Dictionary containing 'name', 'email', and 'phone'.
        db_session (Session): Database session for querying.
    
    Returns:
        Player or None: The matching player, or None if no match is found.
    """
    name = standardize_name(player_info.get('name', ''))
    email = player_info.get('email', '').lower()
    phone = standardize_phone(player_info.get('phone', ''))

    if email:
        player = db_session.query(Player).join(User).filter(
            func.lower(User.email) == email
        ).first()
        if player:
            return player

    if name and phone:
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(Player.phone, '-', ''),
                    '(', ''
                ), ')', ''
            ), ' ', ''
        )
        player = db_session.query(Player).filter(
            func.lower(Player.name) == func.lower(name),
            standardized_phone_db == phone
        ).first()
        if player:
            return player

    return None


def set_progress(data):
    """
    Update progress for an ongoing task using a managed session.
    
    Args:
        data (dict): Dictionary containing 'stage', 'message', and 'progress' keys.
    """
    with managed_session() as session:
        progress = Progress(
            task_id='woo_sync',
            stage=data['stage'],
            message=data['message'],
            progress=data['progress']
        )
        session.merge(progress)