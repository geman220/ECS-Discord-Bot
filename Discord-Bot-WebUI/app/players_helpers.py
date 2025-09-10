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
    Save the cropped profile picture for a player with enhanced security.
    
    Decodes the provided base64 image data, validates the image format,
    saves the image as a PNG file, and returns the new path.
    
    Args:
        cropped_image_data (str): The base64 encoded image data.
        player_id (int): The ID of the player.
    
    Returns:
        str: The file path to the saved profile picture.
    
    Raises:
        ValueError: If image validation fails.
        Exception: Propagates any error encountered during the process.
    """
    try:
        # Validate base64 header
        if not cropped_image_data.startswith('data:image/'):
            raise ValueError("Invalid image data format - missing data:image/ header")
        
        # Extract header and validate image type
        header, encoded = cropped_image_data.split(",", 1)
        mime_type = header.split(':')[1].split(';')[0]
        
        # Whitelist allowed image types
        allowed_types = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp']
        if mime_type not in allowed_types:
            raise ValueError(f"Unsupported image type: {mime_type}. Allowed: {', '.join(allowed_types)}")
        
        # Decode and validate image data
        image_data = base64.b64decode(encoded)
        
        # Check file size (5MB limit for profile pictures)
        max_size = 5 * 1024 * 1024  # 5MB
        if len(image_data) > max_size:
            raise ValueError(f"Image too large: {len(image_data)} bytes. Maximum: {max_size} bytes")
        
        # Open and validate image using PIL
        image = Image.open(BytesIO(image_data))
        
        # Verify image is actually an image (not a malicious file)
        image.verify()
        
        # Re-open for processing (verify() closes the image)
        image = Image.open(BytesIO(image_data)).convert("RGBA")
        
        # Validate image dimensions (reasonable limits)
        max_dimension = 2048  # 2048x2048 max
        if image.width > max_dimension or image.height > max_dimension:
            raise ValueError(f"Image dimensions too large: {image.width}x{image.height}. Maximum: {max_dimension}x{max_dimension}")

        session = g.db_session
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return None

        # Generate secure filename
        player_name = re.sub(r'[^a-zA-Z0-9_-]', '_', player.name)  # More secure sanitization
        filename = secure_filename(f"{player_name}_{player_id}.png")
        upload_folder = os.path.join(current_app.root_path, 'static/img/uploads/profile_pictures')
        os.makedirs(upload_folder, mode=0o755, exist_ok=True)  # Set secure permissions
        file_path = os.path.join(upload_folder, filename)

        # Always save as PNG to strip potentially malicious metadata
        image.save(file_path, format='PNG', optimize=True)
        
        # Set secure file permissions
        os.chmod(file_path, 0o644)
        
        profile_path = f"/static/img/uploads/profile_pictures/{filename}"

        player.profile_picture = profile_path
        logger.info(f"Profile picture saved for player {player_id}: {filename}")
        return player.profile_picture

    except ValueError as e:
        logger.warning(f"Image validation failed for player {player_id}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error saving profile picture for player {player_id}: {str(e)}", exc_info=True)
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
    
    from app.utils.pii_encryption import create_hash
    email_hash = create_hash(player_info['email'].lower())
    existing_user = session.query(User).filter(User.email_hash == email_hash).first()
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


def is_username_style_name(name):
    """
    Detect if a name looks like a username rather than a real name.
    
    Patterns that suggest username:
    - Contains numbers (e.g., "thewitt18", "coyg21")
    - Contains common username patterns
    - All lowercase or mixed case in unusual ways
    - Single word without proper capitalization
    
    Args:
        name (str): The name to check.
    
    Returns:
        bool: True if name appears to be a username-style name.
    """
    if not name:
        return False
    
    name = name.strip()
    
    # Contains numbers - likely a username
    if any(char.isdigit() for char in name):
        return True
    
    # Common username suffixes/patterns
    username_patterns = [
        'jr', 'sr', '1', '2', '3', 'x', 'xx', 'xxx',
        'the', 'fc', 'united', 'city', 'town'
    ]
    
    name_lower = name.lower()
    
    # Starts with "the" (like "thewitt")
    if name_lower.startswith('the') and len(name) > 3:
        return True
    
    # Single word that's all lowercase (proper names should be capitalized)
    if ' ' not in name and name.islower() and len(name) > 2:
        return True
    
    # Ends with common username patterns
    for pattern in username_patterns:
        if name_lower.endswith(pattern) and len(name) > len(pattern):
            return True
    
    # Contains typical gaming/username abbreviations
    if any(abbrev in name_lower for abbrev in ['fc', 'utd', 'city', 'town', 'coyg']):
        return True
    
    return False


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
    Standardize a phone number by removing all non-digit characters and normalizing US numbers.
    
    Handles US country code by treating both "3109930763" and "13109930763" as equivalent.
    
    Args:
        phone (str): The phone number string.
    
    Returns:
        str: The cleaned and normalized phone number containing only digits.
    """
    if not phone:
        return ''
    
    # Remove all non-digit characters
    clean_phone = ''.join(filter(str.isdigit, phone))
    
    # If phone starts with '1' and is 11 digits, remove the leading '1' (US country code)
    if len(clean_phone) == 11 and clean_phone.startswith('1'):
        clean_phone = clean_phone[1:]
    
    return clean_phone


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

    from app.utils.pii_encryption import create_hash
    email_hash = create_hash(email)
    user = session.query(User).filter(User.email_hash == email_hash).first()
    if user:
        return user

    if name and phone:
        # Standardize database phone: remove formatting and handle US country code
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(
                        func.replace(
                            func.replace(Player.phone, '-', ''), 
                            '(', ''
                        ), ')', ''
                    ), ' ', ''
                ), '+', ''
            ), '.', ''
        )
        # Handle US country code: if 11 digits starting with 1, remove the 1
        standardized_phone_db = func.case(
            (func.and_(func.length(standardized_phone_db) == 11, 
                      func.left(standardized_phone_db, 1) == '1'),
             func.right(standardized_phone_db, 10)),
            else_=standardized_phone_db
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
        # Standardize database phone: remove formatting and handle US country code
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(
                        func.replace(
                            func.replace(Player.phone, '-', ''), 
                            '(', ''
                        ), ')', ''
                    ), ' ', ''
                ), '+', ''
            ), '.', ''
        )
        # Handle US country code: if 11 digits starting with 1, remove the 1
        standardized_phone_db = func.case(
            (func.and_(func.length(standardized_phone_db) == 11, 
                      func.left(standardized_phone_db, 1) == '1'),
             func.right(standardized_phone_db, 10)),
            else_=standardized_phone_db
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


def calculate_name_similarity(name1, name2):
    """
    Calculate similarity between two names with enhanced fuzzy matching.
    Handles cases like "Hayley C Serres" vs "Hayley Serres".
    """
    if not name1 or not name2:
        return 0.0
    
    # Normalize names - remove extra spaces, convert to lowercase
    name1_clean = ' '.join(name1.lower().split())
    name2_clean = ' '.join(name2.lower().split())
    
    # If names are identical after normalization, perfect match
    if name1_clean == name2_clean:
        return 1.0
    
    # Split into parts
    name1_parts = name1_clean.split()
    name2_parts = name2_clean.split()
    
    if len(name1_parts) == 0 or len(name2_parts) == 0:
        return 0.0
    
    # Check for subset relationships (handles middle initials/names)
    # "Hayley Serres" should match "Hayley C Serres"
    name1_set = set(name1_parts)
    name2_set = set(name2_parts)
    
    # If one name is a subset of the other (ignoring single letters/initials)
    # Filter out single character parts (likely initials)
    name1_substantial = {part for part in name1_set if len(part) > 1}
    name2_substantial = {part for part in name2_set if len(part) > 1}
    
    # If all substantial parts of one name are in the other
    if name1_substantial and name2_substantial:
        if name1_substantial.issubset(name2_substantial) or name2_substantial.issubset(name1_substantial):
            return 0.95  # Very high similarity for subset matches
    
    # Calculate intersection and union
    intersection = name1_set.intersection(name2_set)
    union = name1_set.union(name2_set)
    
    # Basic Jaccard similarity
    basic_similarity = len(intersection) / len(union)
    
    # Bonus scoring
    similarity = basic_similarity
    
    # Bonus for matching first and last names (most important parts)
    if len(name1_parts) >= 2 and len(name2_parts) >= 2:
        # First name match
        if name1_parts[0] == name2_parts[0]:
            similarity += 0.3
        # Last name match  
        if name1_parts[-1] == name2_parts[-1]:
            similarity += 0.3
    
    # Bonus for having most important parts match
    important_matches = 0
    total_important = 0
    
    # Check first names
    if len(name1_parts) >= 1 and len(name2_parts) >= 1:
        total_important += 1
        if name1_parts[0] == name2_parts[0]:
            important_matches += 1
    
    # Check last names  
    if len(name1_parts) >= 1 and len(name2_parts) >= 1:
        total_important += 1
        if name1_parts[-1] == name2_parts[-1]:
            important_matches += 1
    
    # If most important parts match, boost similarity
    if total_important > 0 and important_matches / total_important >= 0.5:
        similarity += 0.2
    
    return min(similarity, 1.0)


def score_player_match(player_info, player, user):
    """
    Score a potential player match using "2 out of 3" criteria.
    Returns a score from 0.0 to 1.0 and details about the match.
    """
    name = standardize_name(player_info.get('name', ''))
    email = player_info.get('email', '').lower() if player_info.get('email') else None
    phone = standardize_phone(player_info.get('phone', ''))
    
    # Calculate individual match scores
    name_score = 0.0
    email_score = 0.0  
    phone_score = 0.0
    
    # Name matching
    if name and player.name:
        name_score = calculate_name_similarity(name, player.name)
    
    # Email matching
    if email and user.email:
        if email == user.email.lower():
            email_score = 1.0
    
    # Phone matching
    if phone and player.phone:
        player_phone = standardize_phone(player.phone)
        if phone == player_phone:
            phone_score = 1.0
    
    # Count how many factors have good matches
    strong_matches = 0
    match_details = []
    flags = []
    
    # Strong name match (0.7+ similarity)
    if name_score >= 0.7:
        strong_matches += 1
        match_details.append(f"name_match_{int(name_score * 100)}%")
        if name_score < 1.0:
            flags.append('name_variation')
    
    # Email match
    if email_score >= 1.0:
        strong_matches += 1
        match_details.append("email_exact")
    elif email and not email_score:
        flags.append('email_mismatch')
    
    # Phone match
    if phone_score >= 1.0:
        strong_matches += 1
        match_details.append("phone_exact")
    
    # Special case: If name + phone match strongly, accept even with email mismatch
    # This handles cases where user may have updated their email in WooCommerce
    if name_score >= 0.7 and phone_score >= 1.0:
        # Strong name + exact phone match = high confidence match regardless of email
        confidence = 0.9
        match_type = "name_phone_match"
        if email and not email_score:
            # Remove email_mismatch flag since we're accepting this match
            flags = [f for f in flags if f != 'email_mismatch']
            flags.append('email_differs_but_accepted')  # For logging purposes
    else:
        # Calculate overall confidence based on "2 out of 3" principle
        if strong_matches >= 3:
            # All 3 match - perfect
            confidence = 0.98
            match_type = "triple_match"
        elif strong_matches >= 2:
            # 2 out of 3 match - very good
            confidence = 0.85 + (max(name_score, email_score, phone_score) * 0.1)
            match_type = "double_match"
        elif strong_matches == 1:
            # Only 1 strong match - lower confidence
            if name_score >= 0.9 or email_score >= 1.0 or phone_score >= 1.0:
                confidence = 0.6 + (max(name_score, email_score, phone_score) * 0.2)
                match_type = "single_strong_match"
            else:
                confidence = 0.3 + (max(name_score, email_score, phone_score) * 0.3)
                match_type = "weak_match"
        else:
            confidence = 0.0
            match_type = "no_match"
    
    # Special handling for subset name matches (like "Hayley Serres" vs "Hayley C Serres")
    if name_score >= 0.95 and strong_matches >= 1:
        confidence = max(confidence, 0.85)
        if 'name_variation' not in flags:
            flags.append('likely_same_person')
    
    return {
        'confidence': confidence,
        'match_type': match_type,
        'strong_matches': strong_matches,
        'name_score': name_score,
        'email_score': email_score,
        'phone_score': phone_score,
        'match_details': match_details,
        'flags': flags
    }


def match_player_with_details(player_info, db_session):
    """
    Enhanced matching using "2 out of 3" scoring system.
    
    Returns:
        dict with 'player', 'match_type', 'confidence', 'flags'
    """
    name = standardize_name(player_info.get('name', ''))
    email = player_info.get('email', '').lower() if player_info.get('email') else None
    phone = standardize_phone(player_info.get('phone', ''))
    
    if not name and not email and not phone:
        return {
            'player': None,
            'match_type': 'no_data',
            'confidence': 0.0,
            'flags': ['insufficient_data']
        }
    
    # Get all players with their users
    all_players = db_session.query(Player).join(User).all()
    
    best_match = None
    best_score = None
    best_confidence = 0.0
    
    # Score each player
    for player in all_players:
        score_result = score_player_match(player_info, player, player.user)
        
        if score_result['confidence'] > best_confidence:
            best_confidence = score_result['confidence']
            best_match = player
            best_score = score_result
    
    # Return result if we have a good enough match
    if best_match and best_confidence >= 0.6:  # Lowered threshold for 2-of-3 matching
        return {
            'player': best_match,
            'match_type': best_score['match_type'],
            'confidence': best_confidence,
            'flags': best_score['flags'],
            'match_details': best_score['match_details'],
            'scores': {
                'name': best_score['name_score'],
                'email': best_score['email_score'], 
                'phone': best_score['phone_score']
            }
        }
    
    return {
        'player': None,
        'match_type': 'no_sufficient_match',
        'confidence': best_confidence,
        'flags': ['new_player_candidate'] + (best_score['flags'] if best_score else [])
    }


def match_player_with_details_cached(player_info, cached_players):
    """
    Optimized version of match_player_with_details that uses pre-cached player data.
    
    Args:
        player_info (dict): Player information dictionary
        cached_players (list): Pre-loaded list of Player objects with joined User objects
    
    Returns:
        dict with 'player', 'match_type', 'confidence', 'flags'
    """
    name = standardize_name(player_info.get('name', ''))
    email = player_info.get('email', '').lower() if player_info.get('email') else None
    phone = standardize_phone(player_info.get('phone', ''))
    
    if not name and not email and not phone:
        return {
            'player': None,
            'match_type': 'no_data',
            'confidence': 0.0,
            'flags': ['insufficient_data']
        }
    
    # Score each player using the cached list instead of querying database
    best_match = None
    best_score = None
    best_confidence = 0.0
    
    for player in cached_players:
        score_result = score_player_match(player_info, player, player.user)
        
        if score_result['confidence'] > best_confidence:
            best_confidence = score_result['confidence']
            best_match = player
            best_score = score_result
    
    # Return result if we have a good enough match
    if best_match and best_confidence >= 0.6:  # Lowered threshold for 2-of-3 matching
        return {
            'player': best_match,
            'match_type': best_score['match_type'],
            'confidence': best_confidence,
            'flags': best_score['flags'],
            'match_details': best_score['match_details'],
            'scores': {
                'name': best_score['name_score'],
                'email': best_score['email_score'], 
                'phone': best_score['phone_score']
            }
        }
    
    return {
        'player': None,
        'match_type': 'no_sufficient_match',
        'confidence': best_confidence,
        'flags': ['new_player_candidate'] + (best_score['flags'] if best_score else [])
    }


def match_player_weighted(player_info, db_session):
    """
    Legacy function for backward compatibility.
    Returns the player if confidence >= 0.8, otherwise None.
    """
    result = match_player_with_details(player_info, db_session)
    if result['confidence'] >= 0.8:
        return result['player']
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