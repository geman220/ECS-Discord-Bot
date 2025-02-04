from flask import current_app, url_for, render_template, g
from app.models import Player, PlayerOrderHistory, User, Progress
from app.routes import get_current_season_and_year
from werkzeug.utils import secure_filename
from sqlalchemy import func
import uuid
import secrets
import string
import re
from io import BytesIO
import os
import base64
import logging
from PIL import Image
from itsdangerous import URLSafeTimedSerializer
from app.core.session_manager import managed_session
from flask_mail import Message

logger = logging.getLogger(__name__)

def save_cropped_profile_picture(cropped_image_data, player_id):
    """Save profile picture with proper session management."""
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

        # Update player's profile_picture using the session
        player.profile_picture = profile_path
        return player.profile_picture

    except Exception as e:
        logger.error(f"Error saving profile picture: {str(e)}", exc_info=True)
        raise

def generate_random_password(length=16):
    """
    Generates a secure random password.
    
    Args:
        length (int, optional): Length of the password. Defaults to 16.
    
    Returns:
        str: The generated password.
    """
    if length < 12:
        raise ValueError("Password length should be at least 12 characters for security.")
    
    characters = string.ascii_letters + string.digits + string.punctuation
    ambiguous = {'"', "'", '\\', '`'}
    allowed_characters = ''.join(c for c in characters if c not in ambiguous)
    
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
    Creates or returns an existing User from the given player_info['email'].
    Ensures everything happens in the provided session.
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

    # Otherwise create new user
    try:
        random_password = ''.join(
            secrets.choice(string.ascii_letters + string.digits) 
            for _ in range(10)
        )
        new_user = User(
            email=player_info['email'],
            username=player_info['name'] or player_info['email'],
            is_approved=True
        )
        new_user.set_password(random_password)
        session.add(new_user)
        session.flush()  # to populate new_user.id
        logger.info(f"Created new user: id={new_user.id}, email={new_user.email}")
        return new_user

    except Exception as e:
        logger.exception("Error in create_user_for_player")
        raise

def generate_unique_name(base_name):
    session = g.db_session
    count = 1
    unique_name = base_name
    while session.query(Player).filter_by(name=unique_name).first():
        unique_name = f"{base_name} +{count}"
        count += 1
    return unique_name

def generate_unique_username(base_name):
    session = g.db_session
    unique_username = base_name[:50]  # Ensure it doesn't exceed length
    while session.query(User).filter_by(username=unique_username).first():
        unique_username = f"{base_name} ({str(uuid.uuid4())[:8]})"[:50]
    return unique_username

def generate_contact_info(player_data, is_placeholder):
    if is_placeholder:
        return f"placeholder_{uuid.uuid4()}@publeague.com", f"00000000{uuid.uuid4().int % 10000:04d}"
    return player_data['email'], player_data['phone']

def has_previous_season_order(player, season):
    session = g.db_session
    return session.query(PlayerOrderHistory).filter_by(
        player_id=player.id,
        season_id=season.id - 1
    ).first() is not None

def standardize_name(name):
    name_parts = name.split()
    standardized_name = ' '.join(
        part.capitalize() if '-' not in part else '-'.join(p.capitalize() for p in part.split('-')) 
        for part in name_parts
    )
    return standardized_name

def standardize_phone(phone):
    if phone:
        return ''.join(filter(str.isdigit, phone))
    return ''

def match_user(player_data):
    session = g.db_session
    email = player_data.get('email', '').lower()
    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))

    user = session.query(User).filter(func.lower(User.email) == email).first()
    if user:
        return user

    if name and phone:
        # Standardize phone in DB comparison
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
    Attempt to find an existing Player in this league using:
      1) The given 'user', if provided (check user_id + league_id).
      2) If 'user' not provided, try match_user(...) to find a user by email, etc.
      3) If still no user, fall back to name+phone matching.

    Returns a Player or None.
    """
    if session is None:
        from app.core import db
        session = db.session

    logger.debug("Entering match_player")
    logger.debug(f"Player data received: {player_data}")

    # 1) If we already have a user, check for a Player with (user_id, league.id)
    if user and user.id:
        logger.debug(f"User was passed in: {user} with id {user.id}. Checking for existing player in league {league.id}...")
        existing_player = session.query(Player).filter_by(
            user_id=user.id,
            league_id=league.id
        ).first()
        if existing_player:
            logger.debug(f"Found existing player by (user_id, league_id): {existing_player.id}")
            return existing_player
        else:
            logger.debug("No player found for this user in this league. Will fall back to name+phone matching if needed.")
    else:
        # 2) If no 'user' was supplied, see if there's a user in the DB based on this player's email/whatever.
        matched_user = match_user(player_data)  # your existing code for email-based lookup
        if matched_user:
            logger.debug(f"match_user returned: {matched_user} with id {matched_user.id}")
            player_by_user = session.query(Player).filter_by(user_id=matched_user.id, league_id=league.id).first()
            if player_by_user:
                logger.debug(f"Found player by user_id: {player_by_user.id}")
                return player_by_user
            else:
                logger.debug("No player found using matched_user in this league. Fall back to name+phone.")
                # We *could* set user = matched_user here if you want
                user = matched_user
        else:
            logger.debug("No matching user found from player data.")

    # 3) Finally, attempt name+phone matching if we either have no user
    #    or we didn't find a player with that user in this league.
    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))
    logger.debug(f"Standardized name: {name}, Standardized phone: {phone}")

    if name and phone:
        # Example of removing punctuation from phone in the DB
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
    from flask import current_app
    from flask_mail import Message
    from itsdangerous import URLSafeTimedSerializer

    try:
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = serializer.dumps(user.email, salt=current_app.config['SECURITY_PASSWORD_SALT'])

        reset_url = url_for('reset_password', token=token, _external=True)
        msg = Message('Set Your Password',
                      recipients=[user.email])
        msg.body = render_template('emails/password_setup.txt', reset_url=reset_url, username=user.username)
        msg.html = render_template('emails/password_setup.html', reset_url=reset_url, username=user.username)

        mail.send(msg)
        logger.info(f"Sent password setup email to '{user.email}'.")
    except Exception as e:
        logger.error(f"Error sending password setup email to '{user.email}': {e}", exc_info=True)

def hash_password(password):
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password, method='scrypt')

def clean_phone_number(phone):
    cleaned_phone = re.sub(r'\D', '', phone)
    return cleaned_phone[-10:] if len(cleaned_phone) >= 10 else cleaned_phone

def match_player_weighted(player_info, db_session):
    """
    Weighted matching for player identification.
    Returns matching player or None.
    """
    name = standardize_name(player_info.get('name', ''))
    email = player_info.get('email', '').lower()
    phone = standardize_phone(player_info.get('phone', ''))

    # Try exact email match first
    if email:
        player = db_session.query(Player).join(User).filter(
            func.lower(User.email) == email
        ).first()
        if player:
            return player

    # Try name + phone match
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
    """Use separate session for progress updates"""
    with managed_session() as session:
        progress = Progress(
            task_id='woo_sync',
            stage=data['stage'],
            message=data['message'],
            progress=data['progress']
        )
        session.merge(progress)