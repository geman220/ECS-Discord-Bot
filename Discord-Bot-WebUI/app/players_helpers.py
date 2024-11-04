from flask import current_app, Blueprint, render_template, url_for
from app.models import Player, PlayerOrderHistory, User
from app.decorators import db_operation, query_operation
from app import db
from app.routes import get_current_season_and_year
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload
from sqlalchemy import func
import uuid
import secrets
import string
import re
from io import BytesIO
import os
import base64
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

players_bp = Blueprint('players', __name__)

@db_operation
def save_cropped_profile_picture(cropped_image_data, player_id):
    """Save profile picture with proper session management."""
    try:
        header, encoded = cropped_image_data.split(",", 1)
        image_data = base64.b64decode(encoded)
        image = Image.open(BytesIO(image_data)).convert("RGBA")

        @query_operation
        def get_player():
            return Player.query.get(player_id)

        player = get_player()
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

        @db_operation
        def update_player_profile():
            player = Player.query.get(player_id)
            if player:
                player.profile_picture = profile_path
            return player.profile_picture if player else None

        return update_player_profile()

    except Exception as e:
        logger.error(f"Error saving profile picture: {str(e)}", exc_info=True)
        raise

# Password Generation
def generate_random_password(length=12):
    """Generate a random password of a given length."""
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(characters) for _ in range(length))

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
    
    import secrets
    import string
    
    # Define the character set: letters, digits, and punctuation
    characters = string.ascii_letters + string.digits + string.punctuation
    
    # Remove ambiguous characters if necessary
    ambiguous = {'"', "'", '\\', '`'}
    allowed_characters = ''.join(c for c in characters if c not in ambiguous)
    
    # Ensure the password has at least one character from each category
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(string.punctuation)
    ]
    
    # Fill the rest of the password length
    password += [secrets.choice(allowed_characters) for _ in range(length - 4)]
    
    # Shuffle to prevent predictable sequences
    secrets.SystemRandom().shuffle(password)
    
    return ''.join(password)

@db_operation
def create_user_for_player(player_data):
    """Create user for player with proper session management."""
    @query_operation
    def find_existing_user():
        return match_user(player_data)

    user = find_existing_user()
    if user:
        logger.info(f"User '{user.email}' matched using composite criteria.")
        return user

    email = player_data.get('email', '').lower()
    name = standardize_name(player_data.get('name', ''))
    username = generate_unique_username(name)
    
    user = User(
        username=username,
        email=email,
        is_approved=False
    )
    user.set_password(generate_random_password())
    db.session.add(user)
    logger.info(f"Created new user '{user.username}' with email '{user.email}'.")
    
    return user

# Helper Functions
def generate_unique_name(base_name):
    """Generate a unique name by appending a numeric suffix if necessary."""
    count = 1
    unique_name = base_name
    while Player.query.filter_by(name=unique_name).first():
        unique_name = f"{base_name} +{count}"
        count += 1
    return unique_name

def generate_unique_username(base_name):
    """Generate a unique username within 50 characters."""
    unique_username = base_name
    while User.query.filter_by(username=unique_username).first():
        unique_username = f"{base_name} ({str(uuid.uuid4())[:8]})"[:50]
    return unique_username

def generate_contact_info(player_data, is_placeholder):
    """Generate contact information, handling placeholders if needed."""
    if is_placeholder:
        return f"placeholder_{uuid.uuid4()}@publeague.com", f"00000000{uuid.uuid4().int % 10000:04d}"
    return player_data['email'], player_data['phone']

def has_previous_season_order(player, season):
    """Check if there was an order in the previous season."""
    return PlayerOrderHistory.query.filter_by(
        player_id=player.id,
        season_id=season.id - 1
    ).first() is not None

def standardize_name(name):
    """Standardize a player's name to 'Firstname Middlename Lastname' format if possible."""
    name_parts = name.split()
    # Capitalize each part of the name and handle hyphenated last names
    standardized_name = ' '.join(
        part.capitalize() if '-' not in part else '-'.join(p.capitalize() for p in part.split('-')) 
        for part in name_parts
    )
    return standardized_name

def standardize_phone(phone):
    """Standardize phone number by keeping only digits."""
    if phone:
        return ''.join(filter(str.isdigit, phone))
    return ''

@query_operation
def match_user(player_data):
    """Match user with proper session management."""
    email = player_data.get('email', '').lower()
    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))

    user = User.query.filter(func.lower(User.email) == email).first()
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
        player = Player.query.filter(
            func.lower(Player.name) == func.lower(name),
            standardized_phone_db == phone
        ).first()
        if player and player.user:
            return player.user

    return None

@query_operation
def match_player(player_data, league):
    """Match player with proper session handling."""
    user = match_user(player_data)
    if user:
        player = Player.query.filter_by(user_id=user.id).first()
        if player:
            return player

    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))
    
    if name and phone:
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(Player.phone, '-', ''), 
                    '(', ''
                ), ')', ''
            ), ' ', ''
        )
        return Player.query.filter(
            func.lower(Player.name) == func.lower(name),
            standardized_phone_db == phone
        ).first()
    
    return None

def extract_player_info(billing):
    """
    Extracts player information from billing details.

    Args:
        billing (dict): Billing details from the order.

    Returns:
        dict: Extracted player information.
    """
    try:
        name = f"{billing.get('first_name', '').strip()} {billing.get('last_name', '').strip()}".title()
        phone = re.sub(r'\D', '', billing.get('phone', ''))
        email = billing.get('email', '').strip().lower()
        jersey_size = 'N/A'  # We'll set the actual jersey size later
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
    Sends a password setup email to the user with a secure token.
    
    Args:
        user (User): The User object to send the email to.
    """
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
    """
    Hashes a password using a secure algorithm.
    
    Args:
        password (str): The plain-text password.
    
    Returns:
        str: The hashed password.
    """
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password, method='scrypt')

def clean_phone_number(phone):
    """Clean phone number to digits only, keeping last 10 digits."""
    cleaned_phone = re.sub(r'\D', '', phone)  # Remove all non-digit characters
    return cleaned_phone[-10:] if len(cleaned_phone) >= 10 else cleaned_phone  # Keep last 10 digits or the entire cleaned string if shorter