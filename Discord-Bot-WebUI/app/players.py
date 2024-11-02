from flask import current_app, Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from app.models import Player, League, Season, PlayerSeasonStats, PlayerCareerStats, PlayerOrderHistory, User, Notification, Role, PlayerStatAudit, Match, PlayerEvent, PlayerEventType, user_roles
from app.decorators import role_required, admin_or_owner_required
from app import db
from app.woocommerce import fetch_orders_from_woocommerce
from app.routes import get_current_season_and_year
from app.teams_helpers import current_season_id
from app.forms import PlayerProfileForm, SeasonStatsForm, CareerStatsForm, SubmitForm, CreatePlayerForm, EditPlayerForm, soccer_positions, goal_frequency_choices, availability_choices, pronoun_choices, willing_to_referee_choices
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import select, func, or_, and_
from PIL import Image
from app.profile_helpers import handle_add_stat_manually, handle_career_stats_update, handle_season_stats_update, check_email_uniqueness, handle_profile_update, handle_ref_status_update, handle_coach_status_update
from datetime import datetime
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

# Helper functions

def is_order_in_current_season(order, season_map):
    """
    Determine if the order belongs to any of the current seasons.

    Args:
        order (dict): The order data from WooCommerce.
        season_map (dict): Mapping of season names to Season objects.

    Returns:
        bool: True if the order is in a current season, False otherwise.
    """
    product_name = order['product_name']
    # Assuming the product name starts with the season name, e.g., "2024 Fall ECS Pub League - Premier Division - AM"
    season_name = extract_season_name(product_name)
    return season_name in season_map

def extract_season_name(product_name):
    """
    Extract the season name from the product name.

    Args:
        product_name (str): The product name from the order.

    Returns:
        str: The extracted season name (e.g., "2024 Fall") or empty string if not found.
    """
    # Regex to find patterns like "2024 Fall" or "Fall 2024"
    match = re.search(r'(\d{4})\s+(Spring|Fall)|\b(Spring|Fall)\s+(\d{4})\b', product_name, re.IGNORECASE)
    if match:
        if match.group(1) and match.group(2):
            year = match.group(1)
            season = match.group(2).capitalize()
        elif match.group(3) and match.group(4):
            season = match.group(3).capitalize()
            year = match.group(4)
        else:
            return ""
        return f"{year} {season}"
    return ""

def extract_jersey_size(product_name):
    """
    Extract the jersey size from the product name.

    Args:
        product_name (str): The product name from the order.

    Returns:
        str: The extracted jersey size.
    """
    # Adjust the delimiter based on your product name format
    if ' - ' in product_name:
        return product_name.split(' - ')[-1].strip()
    return ""

def save_cropped_profile_picture(cropped_image_data, player_id):
    header, encoded = cropped_image_data.split(",", 1)
    image_data = base64.b64decode(encoded)

    image = Image.open(BytesIO(image_data)).convert("RGBA")

    player = Player.query.get(player_id)
    player_name = player.name.replace(" ", "_")  # Replace spaces with underscores
    filename = secure_filename(f"{player_name}_{player_id}.png")

    upload_folder = os.path.join(current_app.root_path, 'static/img/uploads/profile_pictures')
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, filename)
    image.save(file_path, format='PNG')

    return f"/static/img/uploads/profile_pictures/{filename}"

def decrement_player_stats(player_id, event_type):
    current_app.logger.info(f"Decrementing stats for Player ID: {player_id}, Event Type: {event_type}")
    
    player = Player.query.get(player_id)
    
    if not player:
        current_app.logger.error(f"Player not found for Player ID: {player_id}")
        return
    
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=current_season_id()).first()
    career_stats = player.career_stats

    if not season_stats:
        current_app.logger.error(f"Season stats not found for Player ID: {player_id}")
        return

    if not career_stats:
        current_app.logger.error(f"Career stats not found for Player ID: {player_id}")
        return

    log_current_stats(season_stats, career_stats)

    event_stats_map = {
        PlayerEventType.GOAL: ('goals', 'Decremented goals'),
        PlayerEventType.ASSIST: ('assists', 'Decremented assists'),
        PlayerEventType.YELLOW_CARD: ('yellow_cards', 'Decremented yellow cards'),
        PlayerEventType.RED_CARD: ('red_cards', 'Decremented red cards')
    }

    if event_type in event_stats_map:
        stat_attr, log_msg = event_stats_map[event_type]
        decrement_stat(season_stats, career_stats, stat_attr, player_id, log_msg)
    else:
        current_app.logger.error(f"Unknown event type: {event_type} for Player ID: {player_id}")

    try:
        db.session.commit()
        current_app.logger.info(f"Successfully decremented stats for Player ID: {player_id}")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to commit decremented stats for Player ID: {player_id}. Error: {str(e)}")

def decrement_stat(season_stats, career_stats, stat_attr, player_id, log_msg):
    """Helper function to decrement a stat safely"""
    # Decrement season stat
    season_stat_value = getattr(season_stats, stat_attr)
    if season_stat_value > 0:
        setattr(season_stats, stat_attr, season_stat_value - 1)
        current_app.logger.info(f"{log_msg} for Player ID: {player_id} in season stats")

    # Decrement career stat
    career_stat_value = getattr(career_stats, stat_attr)
    if career_stat_value > 0:
        setattr(career_stats, stat_attr, career_stat_value - 1)
        current_app.logger.info(f"{log_msg} for Player ID: {player_id} in career stats")


def log_current_stats(season_stats, career_stats):
    """Log current stats before decrementing"""
    current_app.logger.info(f"Current Season Stats: Goals: {season_stats.goals}, Assists: {season_stats.assists}, Yellow Cards: {season_stats.yellow_cards}, Red Cards: {season_stats.red_cards}")
    current_app.logger.info(f"Current Career Stats: Goals: {career_stats.goals}, Assists: {career_stats.assists}, Yellow Cards: {career_stats.yellow_cards}, Red Cards: {career_stats.red_cards}")

# Password Generation
def generate_random_password(length=12):
    """Generate a random password of a given length."""
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(characters) for _ in range(length))

def fetch_existing_players(email):
    """Fetch the main player and their placeholders by email."""
    main_player = Player.query.filter_by(email=email.lower(), linked_primary_player_id=None).first()
    if not main_player:
        return None, []
    
    placeholders = Player.query.filter_by(linked_primary_player_id=main_player.id).all()
    return main_player, placeholders

def check_if_order_processed(order_id, player_id, league_id, season_id):
    """Check if the order has already been processed for a specific league."""
    return PlayerOrderHistory.query.filter_by(
        order_id=str(order_id),  # Ensure order_id is a string
        player_id=player_id,
        league_id=league_id,
        season_id=season_id
    ).first()

# Player Creation and Updating
def create_or_update_player(player_data, league, current_seasons, existing_main_player, existing_placeholders, total_line_items):
    """
    Create or update a player, handling placeholders if necessary.

    Args:
        player_data (dict): Data related to the player.
        league (League): The league object.
        current_seasons (list): List of current Season objects.
        existing_main_player (Player or None): Existing main player.
        existing_placeholders (list): List of existing placeholders.
        total_line_items (int): Total number of line items/orders for the player.

    Returns:
        Player: The main Player object.
    """
    # Standardize name and email
    player_data['name'] = standardize_name(player_data['name'])
    player_data['email'] = player_data['email'].lower()

    # Logging for debugging
    logger.info(f"Existing main player: {existing_main_player}")
    logger.info(f"Number of existing placeholders: {len(existing_placeholders)}")
    logger.info(f"Total line items: {total_line_items}")

    if existing_main_player:
        # Update main player's details
        update_player_details(existing_main_player, player_data)

        # Calculate how many placeholders are needed
        existing_count = 1 + len(existing_placeholders)  # 1 main player + placeholders
        placeholders_needed = total_line_items - existing_count

        if placeholders_needed > 0:
            for _ in range(placeholders_needed):
                create_new_player(
                    player_data,
                    league,
                    original_player_id=existing_main_player.id,
                    is_placeholder=True
                )
                logger.info(f"Created a new placeholder linked to {existing_main_player.name}")
        return existing_main_player
    else:
        # No existing main player; create one and necessary placeholders
        main_player = create_new_player(player_data, league, is_placeholder=False)
        logger.info(f"Created main player: {main_player.name}")

        placeholders_needed = total_line_items - 1  # Subtract the main player
        for _ in range(placeholders_needed):
            create_new_player(
                player_data,
                league,
                original_player_id=main_player.id,
                is_placeholder=True
            )
            logger.info(f"Created a new placeholder linked to {main_player.name}")

        return main_player

def create_new_player(player_data, league, original_player_id=None, is_placeholder=False):
    """
    Create a new player entry or placeholder with associated user.

    Args:
        player_data (dict): Data related to the player.
        league (League): The league object.
        original_player_id (int, optional): ID of the main player if creating a placeholder.
        is_placeholder (bool, optional): Indicates if the player is a placeholder.

    Returns:
        Player: The newly created Player object.
    """
    if is_placeholder:
        # Generate unique placeholder identifier
        placeholder_suffix = f"+{original_player_id}-{uuid.uuid4().hex[:6]}"
        name = f"{player_data['name']} {placeholder_suffix}"
        email = f"placeholder_{original_player_id}_{uuid.uuid4().hex[:6]}@publeague.com"
        phone = f"000{uuid.uuid4().int % 10000:04d}"
    else:
        # Use real player information
        name = player_data['name']
        email, phone = player_data['email'], player_data['phone']

    # Create or link User first
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        user = existing_user
    else:
        user = User(
            username=generate_unique_username(name),
            email=email,
            is_approved=False  # Set based on your approval logic
        )
        user.set_password(generate_random_password())
        db.session.add(user)
        db.session.flush()  # Assign user.id

    # Now create the Player with user_id set
    new_player = Player(
        name=name,
        email=email,
        phone=phone,
        jersey_size=player_data['jersey_size'],
        league_id=league.id,
        is_current_player=True,  # Mark as current player
        needs_manual_review=is_placeholder,
        linked_primary_player_id=original_player_id,
        order_id=player_data['order_id'],
        user_id=user.id  # Set user_id here
    )

    db.session.add(new_player)

    return new_player

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

def update_player_details(player, player_data):
    """Update existing player details without overwriting user's email."""
    if player:
        player.is_current_player = True
        player.phone = standardize_phone(player_data.get('phone', ''))
        player.jersey_size = player_data.get('jersey_size', '')
        
        # Do not update the user's email if it's different
        new_email = player_data.get('email', '').lower()
        if not player.user.email:
            # User's email is missing; update it
            player.user.email = new_email
            logger.info(f"Set email for user '{player.user.username}' to '{new_email}'.")
            db.session.add(player.user)
        elif player.user.email.lower() != new_email:
            # Emails are different; prefer the user's current email
            logger.info(
                f"Email from WooCommerce '{new_email}' does not match user's email '{player.user.email}'. "
                "Keeping the user's current email."
            )
            # Optionally, store the WooCommerce email in a separate field
        else:
            # Emails match; no action needed
            pass
        
        db.session.add(player)
    return player

def create_user_for_player(player_data):
    """
    Create or link a user to a player using composite matching.

    Args:
        player_data (dict): Data related to the player.

    Returns:
        User: The existing or newly created User object.
    """
    user = match_user(player_data)
    if user:
        logger.info(f"User '{user.email}' matched using composite criteria.")
        return user
    else:
        email = player_data.get('email', '').lower()
        name = standardize_name(player_data.get('name', ''))
        # Generate a unique username if necessary
        username = generate_unique_username(name)
        user = User(
            username=username,
            email=email,
            is_approved=False  # Adjust based on your logic
        )
        user.set_password(generate_random_password())
        db.session.add(user)
        db.session.flush()  # Assign user.id
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

def match_user(player_data):
    """
    Attempts to find an existing user based on email or by matching player's name and phone number.

    Args:
        player_data (dict): Data related to the player.

    Returns:
        User or None: The matched User object or None if not found.
    """
    email = player_data.get('email', '').lower()
    name = standardize_name(player_data.get('name', ''))
    phone = standardize_phone(player_data.get('phone', ''))

    # Try to find user by email (case-insensitive)
    user = User.query.filter(func.lower(User.email) == email).first()
    if user:
        return user

    # If email matching fails, try matching by Player.name and phone number
    if name and phone:
        # Standardize phone numbers in the database
        standardized_phone_db = func.replace(
            func.replace(
                func.replace(
                    func.replace(Player.phone, '-', ''), '(', ''
                ), ')', ''
            ), ' ', ''
        )
        player = Player.query.filter(
            func.lower(Player.name) == func.lower(name),
            standardized_phone_db == phone
        ).first()
        if player:
            return player.user  # Return the associated user

    return None

def match_player(player_data, league):
    user = match_user(player_data)
    if user:
        # Try to find player linked to the user
        player = Player.query.filter_by(user_id=user.id).first()
        if player:
            return player
    else:
        # Try to find player based on name and phone
        name = standardize_name(player_data.get('name', ''))
        phone = standardize_phone(player_data.get('phone', ''))
        if name and phone:
            standardized_phone_db = func.replace(func.replace(func.replace(func.replace(Player.phone, '-', ''), '(', ''), ')', ''), ' ', '')
            player = Player.query.filter(
                func.lower(Player.name) == func.lower(name),
                standardized_phone_db == phone
            ).first()
            if player:
                return player
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

def extract_jersey_size_from_product_name(product_name):
    """
    Extracts the jersey size from the product name.

    Assumes that the jersey size is the last token in the product name,
    separated by ' - ', and is typically a code like 'WL', 'WM', 'S', 'M', 'L', etc.

    Args:
        product_name (str): The name of the product.

    Returns:
        str: The extracted jersey size, or 'N/A' if not found.
    """
    try:
        # Split the product name by ' - ' and get the last part
        tokens = product_name.split(' - ')
        if tokens:
            last_token = tokens[-1].strip()
            # Check if the last token is a jersey size code
            if last_token.isupper() and len(last_token) <= 3:
                # Additional validation can be added if necessary
                return last_token
        return 'N/A'
    except Exception as e:
        logger.error(f"Error extracting jersey size from product name '{product_name}': {e}", exc_info=True)
        return 'N/A'

def determine_league(product_name, current_seasons):
    """
    Determines the league based on the product name.

    Args:
        product_name (str): The name of the product.
        current_seasons (list): List of current Season objects.

    Returns:
        League: The corresponding League object, or None if not found.
    """
    product_name = product_name.upper().strip()
    logger.debug(f"Determining league for product name: '{product_name}'")

    # Handle ECS FC products
    if product_name.startswith("ECS FC"):
        league_id = 14
        ecs_fc_league = League.query.get(league_id)
        if ecs_fc_league:
            logger.debug(f"Product '{product_name}' mapped to ECS FC league '{ecs_fc_league.name}' with id={league_id}.")
            return ecs_fc_league
        else:
            logger.error(f"ECS FC League with id={league_id} not found in the database.")
            return None

    # Handle ECS Pub League products
    elif "ECS PUB LEAGUE" in product_name:
        if "PREMIER DIVISION" in product_name:
            league_id = 10  # Premier Division
        elif "CLASSIC DIVISION" in product_name:
            league_id = 11  # Classic Division
        else:
            logger.error(f"Unknown division in product name: '{product_name}'.")
            return None

        logger.debug(f"Product '{product_name}' identified as Division ID {league_id}, assigning league_id={league_id}.")
        pub_league = League.query.get(league_id)
        if pub_league:
            logger.debug(f"Product '{product_name}' mapped to Pub League '{pub_league.name}' with id={league_id}.")
            return pub_league
        else:
            logger.error(f"Pub League with id={league_id} not found in the database.")
            return None

    # Add additional league determination logic here if needed
    # Example for other leagues:
    # elif product_name.startswith("OTHER LEAGUE PREFIX"):
    #     return League.query.filter_by(name="Other League").first()

    logger.warning(f"Could not determine league type from product name: '{product_name}'")
    return None

def create_player_profile(player_data, league, user):
    player = match_player(player_data, league)
    if player:
        # Update existing player details
        update_player_details(player, player_data)
        
        # Check if the player-league association already exists
        if league not in player.other_leagues:
            player.other_leagues.append(league)
        
        # Set primary league if not set or based on priority
        if not player.primary_league:
            player.primary_league = league
        else:
            current_priority = ['Classic', 'Premier', 'ECS FC']
            if current_priority.index(league.name) < current_priority.index(player.primary_league.name):
                player.primary_league = league
        
        logger.info(f"Updated existing player '{player.name}' for user '{user.email}'.")
    else:
        # Create new player profile
        player = Player(
            name=standardize_name(player_data.get('name', '')),
            phone=standardize_phone(player_data.get('phone', '')),
            jersey_size=player_data.get('jersey_size', ''),
            primary_league=league,
            user_id=user.id,
            is_current_player=True
        )
        player.other_leagues.append(league)
        db.session.add(player)
        db.session.flush()
        logger.info(f"Created new player profile '{player.name}' for user '{user.email}'.")
    return player

def create_user_and_player_profile(player_info, league):
    try:
        user = User.query.filter(func.lower(User.email) == func.lower(player_info['email'])).first()

        if not user:
            random_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(10))
            user = User(
                email=player_info['email'].lower(),
                username=player_info['name'],
                is_approved=True
            )
            user.set_password(random_password)
            db.session.add(user)
            db.session.flush()
            logger.info(f"Created new user '{user.email}' with username '{user.username}' and approved status.")

        existing_player = Player.query.filter_by(user_id=user.id, league_id=league.id).first()

        if existing_player:
            existing_player.is_current_player = True
            db.session.commit()
            logger.info(f"Marked existing player '{existing_player.name}' as CURRENT_PLAYER.")
            return existing_player

        new_player = Player(
            name=player_info['name'],
            phone=player_info['phone'],
            jersey_size=player_info['jersey_size'],
            league_id=league.id,
            user_id=user.id,
            is_current_player=True
        )
        db.session.add(new_player)
        db.session.commit()  # Commit user and player creation
        logger.info(f"Created new player profile for '{new_player.name}' with email '{user.email}'.")

        return new_player

    except IntegrityError as ie:
        db.session.rollback()
        logger.error(f"IntegrityError while creating player for '{user.email}': {ie}", exc_info=True)
        return None
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating player for '{user.email}': {e}", exc_info=True)
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

def record_order_history(order_id, player_id, league_id, season_id, profile_count):
    """
    Record an entry in the player_order_history table.

    Args:
        order_id (str): The WooCommerce order ID.
        player_id (int): The Player's ID.
        league_id (int): The League's ID.
        season_id (int): The Season's ID.
        profile_count (int): Number of profiles associated with the order.
    """
    if not player_id:
        logger.error(f"Cannot record order history for order_id '{order_id}' because player_id is None.")
        return

    try:
        order_history = PlayerOrderHistory(
            player_id=player_id,
            order_id=str(order_id),  # Ensure order_id is a string
            season_id=season_id,
            league_id=league_id,
            profile_count=profile_count,
            created_at=datetime.utcnow()  # Correct usage
        )

        db.session.add(order_history)
        logger.debug(f"Recorded order history for order_id '{order_id}' and player_id '{player_id}'.")
    except Exception as e:
        logger.error(f"Error recording order history for order_id '{order_id}': {e}", exc_info=True)

def get_league_by_product_name(product_name, current_seasons):
    """
    Determines the league based on the product name and current seasons.

    Args:
        product_name (str): The name of the product from the order.
        current_seasons (list): List of current Season objects.

    Returns:
        League: The corresponding League object if found, else None.
    """
    logger.debug(f"Parsing product name: '{product_name}'")

    # Patterns to extract division or ECS FC from product name
    # Example product names:
    # "2024 Fall ECS Pub League - Premier Division - AXXL"
    # "2024 Fall ECS Pub League - Classic Division - AL"
    # "2024 Fall ECS FC - Black Team - AXL"

    # Pattern for Pub League divisions
    pub_league_pattern = re.compile(r'ECS Pub League\s*-\s*(Premier|Classic)\s*Division', re.IGNORECASE)
    # Pattern for ECS FC
    ecs_fc_pattern = re.compile(r'ECS FC\s*-\s*\w+\s*-\s*\w+', re.IGNORECASE)

    league = None

    # Check for Pub League
    pub_league_match = pub_league_pattern.search(product_name)
    if pub_league_match:
        division = pub_league_match.group(1).capitalize()  # 'Premier' or 'Classic'
        league_name = division  # 'Premier' or 'Classic'
        logger.debug(f"Identified Pub League Division: '{league_name}'")

        # Fetch the league from the database based on division and season
        for season in current_seasons:
            league = League.query.filter_by(
                name=league_name,
                season_id=season.id
            ).first()
            if league:
                logger.debug(f"Found league: '{league}' for division '{league_name}' in season '{season.name}'")
                return league
        logger.warning(f"No league found for division '{league_name}' in season '{current_season_formatted}'")
        return None

    # Check for ECS FC
    ecs_fc_match = ecs_fc_pattern.search(product_name)
    if ecs_fc_match:
        league_name = 'ECS FC'
        logger.debug(f"Identified ECS FC League")

        # Fetch the ECS FC league from the database
        for season in current_seasons:
            league = League.query.filter_by(
                name=league_name,
                season_id=season.id
            ).first()
            if league:
                logger.debug(f"Found league: '{league}' for ECS FC in season '{season.name}'")
                return league
        logger.warning(f"No league found for league type '{league_name}' in season '{current_season_formatted}'")
        return None

    logger.warning(f"Could not determine league type from product name: '{product_name}'")
    return None

def reset_current_players(current_seasons):
    """
    Resets the is_current_player flag for all players in the current seasons.

    Args:
        current_seasons (list): List of current Season objects.
    """
    try:
        # Extract season IDs from the current_seasons list
        season_ids = [season.id for season in current_seasons]
        logger.debug(f"Resetting players for seasons with IDs: {season_ids}")

        # Subquery to select Player IDs linked to leagues in current_seasons and currently active
        subquery = db.session.query(Player.id).join(League, Player.league_id == League.id).filter(
            League.season_id.in_(season_ids),
            Player.is_current_player == True
        ).subquery()

        # Perform bulk update on Players where id is in subquery
        updated_rows = Player.query.filter(Player.id.in_(subquery)).update(
            {Player.is_current_player: False},
            synchronize_session=False
        )

        db.session.commit()
        logger.info(f"Successfully reset {updated_rows} players.")
    except Exception as e:
        logger.error(f"Error resetting current players: {e}", exc_info=True)
        db.session.rollback()
        raise  # Re-raise the exception to be handled by the calling function

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

@players_bp.route('/', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def view_players():
    search_term = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    base_query = db.session.query(Player).join(User)

    if search_term:
        base_query = base_query.filter(or_(
            Player.name.ilike(f'%{search_term}%'),
            func.lower(User.email).ilike(f'%{search_term.lower()}%'),
            and_(Player.phone.isnot(None), Player.phone.ilike(f'%{search_term}%')),
            and_(Player.jersey_size.isnot(None), Player.jersey_size.ilike(f'%{search_term}%'))
        ))

    players = base_query.paginate(page=page, per_page=per_page, error_out=False)

    # Fetch leagues and jersey sizes
    leagues = League.query.all()
    jersey_sizes = sorted(set(size[0] for size in db.session.query(Player.jersey_size).distinct().all() if size[0]))

    return render_template(
        'view_players.html',
        players=players,
        search_term=search_term,
        leagues=leagues,
        jersey_sizes=jersey_sizes
    )

@players_bp.route('/update', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_players():
    try:
        # Step 1: Fetch current seasons
        current_seasons = Season.query.filter_by(is_current=True).all()
        if not current_seasons:
            raise Exception("No current seasons found in the database.")

        # Step 2: Fetch orders from WooCommerce
        orders = fetch_orders_from_woocommerce(
            current_season_name='2024 Fall',
            filter_current_season=True,
            current_season_names=[season.name for season in current_seasons],
            max_pages=10
        )

        detected_players = set()  # Track all detected player IDs

        # Step 3: Reset current players (mark all as inactive initially)
        reset_current_players(current_seasons)

        # Step 4: Process each order individually
        for order in orders:
            # Extract player info
            player_info = extract_player_info(order['billing'])
            if not player_info:
                logger.warning(f"Could not extract player info for order ID {order['order_id']}. Skipping.")
                continue

            # Determine league
            product_name = order['product_name']
            league = determine_league(product_name, current_seasons)
            if not league:
                logger.warning(f"League not found for product '{product_name}'. Skipping order ID {order['order_id']}.")
                continue

            # Extract jersey size from product name
            jersey_size = extract_jersey_size_from_product_name(product_name)
            player_info['jersey_size'] = jersey_size

            # Create or update user
            user = create_user_for_player(player_info)

            try:
                # Create or update player profile
                player = create_player_profile(player_info, league, user)
                detected_players.add(player.id)

                # Update player's primary league and other leagues
                if not player.primary_league:
                    player.primary_league = league
                elif league.name in ['Classic', 'Premier', 'ECS FC']:
                    if player.primary_league.name != league.name:
                        if player.primary_league not in player.other_leagues:
                            player.other_leagues.append(player.primary_league)
                        player.primary_league = league
                else:
                    if league not in player.other_leagues:
                        player.other_leagues.append(league)

                db.session.add(player)

            except IntegrityError as ie:
                db.session.rollback()
                logger.warning(f"Duplicate player-league association for player '{player_info['name']}' and league '{league.name}'. Skipping.")
                continue

            # Record order history
            if player:
                record_order_history(
                    order_id=order['order_id'],
                    player_id=player.id,
                    league_id=league.id,
                    season_id=league.season_id,
                    profile_count=order['quantity']
                )

        # Step 5: Mark all non-detected players as inactive
        current_league_ids = [league.id for season in current_seasons for league in season.leagues]
        all_players = Player.query.filter(Player.league_id.in_(current_league_ids)).all()
        for player in all_players:
            if player.id not in detected_players:
                player.is_current_player = False
                logger.info(f"Marked player '{player.name}' as NOT CURRENT_PLAYER (inactive).")

        # Step 6: Commit all changes
        db.session.commit()
        logger.info("All players have been updated successfully.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"An error occurred while updating players: {e}", exc_info=True)
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('players.view_players'))

    flash("Players updated successfully.", "success")
    return redirect(url_for('players.view_players'))

@players_bp.route('/create_player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_player():
    form = CreatePlayerForm()
    # Manually populate form data since we're not using Flask-WTF in the modal
    form.name.data = request.form.get('name')
    form.email.data = request.form.get('email')
    form.phone.data = request.form.get('phone')
    form.jersey_size.data = request.form.get('jersey_size')
    form.league_id.data = request.form.get('league_id')

    # Set the choices for the SelectFields
    leagues = League.query.all()
    distinct_jersey_sizes = db.session.query(Player.jersey_size).distinct().all()
    jersey_sizes = sorted(set(size[0] for size in distinct_jersey_sizes if size[0]))

    form.jersey_size.choices = [(size, size) for size in jersey_sizes]
    form.league_id.choices = [(str(league.id), league.name) for league in leagues]

    if form.validate():
        try:
            # Get form data
            player_data = {
                'name': form.name.data,
                'email': form.email.data.lower(),
                'phone': form.phone.data,
                'jersey_size': form.jersey_size.data
            }
            league_id = form.league_id.data
            league = League.query.get(league_id)

            # Create or update user using composite matching
            user = create_user_for_player(player_data)

            # Create or update player profile using composite matching
            player = create_player_profile(player_data, league, user)

            db.session.commit()

            flash('Player created or updated successfully.', 'success')
            return redirect(url_for('players.view_players'))

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating or updating player: {str(e)}")
            flash('An error occurred while creating or updating the player. Please try again.', 'danger')

    else:
        flash('Form validation failed. Please check your inputs.', 'danger')

    # If form validation fails or an error occurs, redirect back to the player list
    return redirect(url_for('players.view_players'))

@players_bp.route('/profile/<int:player_id>', methods=['GET', 'POST'])
@login_required
def player_profile(player_id):
    logger.info(f"Accessing profile for player_id: {player_id} by user_id: {current_user.id}")
    
    player = Player.query.options(joinedload(Player.team)).get_or_404(player_id)
    logger.debug(f"Fetched player: {player}")
    
    user = player.user
    logger.debug(f"Associated user: {user}")
    
    current_season_name, current_year = get_current_season_and_year()
    logger.debug(f"Current season: {current_season_name}, Year: {current_year}")
    
    season = Season.query.filter_by(name=current_season_name).first()
    if not season:
        logger.error(f"Current season '{current_season_name}' not found in the database.")
        flash('Current season not found.', 'danger')
        return redirect(url_for('home'))
    logger.debug(f"Fetched season: {season}")
    
    matches = Match.query.join(PlayerEvent).filter(PlayerEvent.player_id == player_id).all()
    logger.debug(f"Fetched {len(matches)} matches for player {player_id}")
    
    distinct_jersey_sizes = db.session.query(Player.jersey_size).distinct().all()
    jersey_sizes = [(size[0], size[0]) for size in distinct_jersey_sizes if size[0]]
    logger.debug(f"Distinct jersey sizes: {jersey_sizes}")
    
    classic_league = League.query.filter_by(name='Classic').first()
    if not classic_league:
        logger.error("Classic league not found in the database.")
        flash('Classic league not found', 'danger')
        return redirect(url_for('players.player_profile', player_id=player.id))
    logger.debug(f"Fetched classic league: {classic_league}")
    
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season.id).first()
    if not season_stats:
        logger.debug(f"No season stats found for player {player_id} in season {season.id}. Creating new entry.")
        season_stats = PlayerSeasonStats(player_id=player_id, season_id=season.id)
        db.session.add(season_stats)
        db.session.commit()
    
    if not player.career_stats:
        logger.debug(f"No career stats found for player {player.id}. Creating new entry.")
        new_career_stats = PlayerCareerStats(player_id=player.id)
        player.career_stats.append(new_career_stats)
        db.session.add(new_career_stats)
        db.session.commit()
    
    is_classic_league_player = player.league_id == classic_league.id
    is_player = player.user_id == current_user.id
    is_admin = current_user.has_role('Pub League Admin') or current_user.has_role('Global Admin')
    
    logger.debug(f"is_classic_league_player: {is_classic_league_player}, is_player: {is_player}, is_admin: {is_admin}")
    
    # Instantiate the form based on the request method
    if request.method == 'POST':
        form = PlayerProfileForm()
        logger.debug("Instantiated form for POST request.")
    else:
        form = PlayerProfileForm(obj=player)
        logger.debug("Instantiated form for GET request with obj=player.")
    
    if form:
        # Set jersey_size choices
        form.jersey_size.choices = jersey_sizes
        logger.debug(f"Set jersey_size choices to: {form.jersey_size.choices}")
        
        if request.method == 'GET':
            form.email.data = user.email
            logger.debug(f"Pre-populated form.email with {user.email}")
        
        form.other_positions.data = player.other_positions.split(',') if player.other_positions else []
        form.positions_not_to_play.data = player.positions_not_to_play.split(',') if player.positions_not_to_play else []
        logger.debug(f"Set form.other_positions to {form.other_positions.data}")
        logger.debug(f"Set form.positions_not_to_play to {form.positions_not_to_play.data}")
        
        if is_classic_league_player and hasattr(form, 'team_swap'):
            # No need to set choices dynamically as they are predefined
            form.team_swap.data = player.team_swap if player.team_swap else ''
            logger.debug(f"Pre-populated form.team_swap with {player.team_swap}")
    
    season_stats_form = SeasonStatsForm(obj=season_stats) if is_admin else None
    if season_stats_form:
        logger.debug("Initialized SeasonStatsForm")
    career_stats_form = CareerStatsForm(obj=player.career_stats[0]) if is_admin and player.career_stats else None
    if career_stats_form:
        logger.debug("Initialized CareerStatsForm")
    
    if request.method == 'POST':
        logger.info("Received POST request on player_profile")
        if is_admin and 'update_coach_status' in request.form:
            logger.debug("Detected 'update_coach_status' in form submission.")
            handle_coach_status_update(player, user)
        elif is_admin and 'update_ref_status' in request.form:
            logger.debug("Detected 'update_ref_status' in form submission.")
            handle_ref_status_update(player, user)
        elif form and form.validate_on_submit() and 'update_profile' in request.form:
            logger.debug("Form validated successfully for 'update_profile'.")
            handle_profile_update(form, player, user)
        elif is_admin and season_stats_form and season_stats_form.validate_on_submit() and 'update_season_stats' in request.form:
            logger.debug("Form validated successfully for 'update_season_stats'.")
            handle_season_stats_update(player, season_stats_form, season.id)
        elif is_admin and career_stats_form and career_stats_form.validate_on_submit() and 'update_career_stats' in request.form:
            logger.debug("Form validated successfully for 'update_career_stats'.")
            handle_career_stats_update(player, career_stats_form)
        elif is_admin and 'add_stat_manually' in request.form:
            logger.debug("Detected 'add_stat_manually' in form submission.")
            handle_add_stat_manually(player)
        else:
            logger.warning("POST request did not match any known form submissions.")
            if form:
                logger.debug(f"Form validation errors: {form.errors}")
            else:
                logger.debug("No form available for validation.")
    
    audit_logs = PlayerStatAudit.query.filter_by(player_id=player_id).order_by(PlayerStatAudit.timestamp.desc()).all()
    logger.debug(f"Fetched {len(audit_logs)} audit logs for player {player_id}")
    
    return render_template(
        'player_profile.html',
        player=player,
        user=user,
        matches=matches,
        season=season,
        is_admin=is_admin,
        is_player=is_player,
        is_classic_league_player=is_classic_league_player,
        form=form,
        season_stats_form=season_stats_form,
        career_stats_form=career_stats_form,
        audit_logs=audit_logs
    )

@players_bp.route('/add_stat_manually/<int:player_id>', methods=['POST'])
@login_required
def add_stat_manually(player_id):
    player = Player.query.get_or_404(player_id)
    
    # Ensure the user is an admin
    if not current_user.has_role('Pub League Admin') and not current_user.has_role('Global Admin'):
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('players.player_profile', player_id=player_id))

    # Collect stat data from the form
    try:
        new_stat_data = {
            'match_id': request.form.get('match_id'),
            'goals': int(request.form.get('goals', 0)),
            'assists': int(request.form.get('assists', 0)),
            'yellow_cards': int(request.form.get('yellow_cards', 0)),
            'red_cards': int(request.form.get('red_cards', 0)),
        }

        # Add stats manually to the player
        player.add_stat_manually(new_stat_data, user_id=current_user.id)

        flash('Stat added successfully.', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('An error occurred while adding stats. Please try again.', 'danger')
        current_app.logger.error(f"Error adding stats for player {player_id}: {str(e)}")

    return redirect(url_for('players.player_profile', player_id=player_id))

@players_bp.route('/api/player_profile/<int:player_id>', methods=['GET'])
@login_required
def api_player_profile(player_id):
    player = Player.query.get_or_404(player_id)
    current_season_name, current_year = get_current_season_and_year()
    season = Season.query.filter_by(name=current_season_name).first()

    # Fetch the season stats for the current season
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season.id).first()

    # Helper function to get the friendly value from choices
    def get_friendly_value(value, choices):
        return dict(choices).get(value, value)

    # Constructing the profile data with friendly values
    profile_data = {
        'profile_picture_url': player.profile_picture_url,
        'name': player.name,
        'goals': season_stats.goals if season_stats else 0,
        'assists': season_stats.assists if season_stats else 0,
        'yellow_cards': season_stats.yellow_cards if season_stats else 0,
        'red_cards': season_stats.red_cards if season_stats else 0,
        'player_notes': player.player_notes,
        'favorite_position': get_friendly_value(player.favorite_position, soccer_positions),
        'other_positions': player.other_positions.strip('{}').replace(',', ', ') if player.other_positions else None,
        'goal_frequency': get_friendly_value(player.frequency_play_goal, goal_frequency_choices),
        'positions_to_avoid': player.positions_not_to_play.strip('{}').replace(',', ', ') if player.positions_not_to_play else None,
        'expected_availability': get_friendly_value(player.expected_weeks_available, availability_choices)
    }

    return jsonify(profile_data)

@players_bp.route('/get_needs_review_count', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_needs_review_count():
    count = Player.query.filter_by(needs_manual_review=True).count()
    return jsonify({'count': count})

@players_bp.route('/admin/review', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def admin_review():
    # Fetch the players needing manual review
    players_needing_review = Player.query.filter_by(needs_manual_review=True).all()
    
    # Explicitly join User and Role tables using user_roles association table
    admins = User.query.join(user_roles).join(Role).filter(Role.name.in_(['Pub League Admin', 'Global Admin'])).all()
    
    # Generate a notification for each admin
    for admin in admins:
        notification = Notification(
            user_id=admin.id,
            content=f"{len(players_needing_review)} player(s) need manual review.",
            notification_type='warning',
            icon='ti-alert-triangle'  # Explicitly set the icon here
        )
        db.session.add(notification)
    db.session.commit()

    return render_template('admin_review.html', players=players_needing_review)

@players_bp.route('/create-profile', methods=['POST'])
@login_required
def create_profile():
    form = PlayerProfileForm()
    if form.validate_on_submit():
        # Handle profile creation logic
        player = Player(
            user_id=current_user.id,
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            jersey_size=form.jersey_size.data,
            jersey_number=form.jersey_number.data,
            pronouns=form.pronouns.data,
            expected_weeks_available=form.expected_weeks_available.data,
            unavailable_dates=form.unavailable_dates.data,
            willing_to_referee=form.willing_to_referee.data,
            favorite_position=form.favorite_position.data,
            other_positions="{" + ",".join(form.other_positions.data) + "}" if form.other_positions.data else None,
            positions_not_to_play="{" + ",".join(form.positions_not_to_play.data) + "}" if form.positions_not_to_play.data else None,
            frequency_play_goal=form.frequency_play_goal.data,
            additional_info=form.additional_info.data,
            player_notes=form.player_notes.data,
            team_swap=form.team_swap.data,
            team_id=form.team_id.data,
            league_id=form.league_id.data
        )
        db.session.add(player)
        db.session.commit()
        flash('Player profile created successfully!', 'success')
        return redirect(url_for('main.index'))

    # If the form doesn't validate, flash an error and redirect back to the index.
    flash('Error creating player profile. Please check your inputs.', 'danger')
    return redirect(url_for('main.index'))

@players_bp.route('/edit_match_stat/<int:stat_id>', methods=['GET', 'POST'])
@login_required
def edit_match_stat(stat_id):
    match_stat = PlayerEvent.query.get_or_404(stat_id)

    if request.method == 'GET':
        # Return stat data for the edit modal (AJAX response)
        return jsonify({
            'goals': match_stat.goals,
            'assists': match_stat.assists,
            'yellow_cards': match_stat.yellow_cards,
            'red_cards': match_stat.red_cards,
        })

    if request.method == 'POST':
        try:
            match_stat.goals = request.form.get('goals', 0)  # Default to 0 if not provided
            match_stat.assists = request.form.get('assists', 0)
            match_stat.yellow_cards = request.form.get('yellow_cards', 0)
            match_stat.red_cards = request.form.get('red_cards', 0)
            db.session.commit()
            return jsonify({'success': True})
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing match stat {stat_id}: {str(e)}")
            return jsonify({'success': False}), 500

@players_bp.route('/remove_match_stat/<int:stat_id>', methods=['POST'])
@login_required
def remove_match_stat(stat_id):
    match_stat = PlayerEvent.query.get_or_404(stat_id)
    
    try:
        # Capture the player ID and event type before deleting the event
        player_id = match_stat.player_id
        event_type = match_stat.event_type

        # Log which stat is being removed
        current_app.logger.info(f"Removing stat for Player ID: {player_id}, Event Type: {event_type}, Stat ID: {stat_id}")

        # Decrement the player's stats before removing the event
        decrement_player_stats(player_id, event_type)

        # Now, delete the match stat itself
        db.session.delete(match_stat)
        db.session.commit()

        current_app.logger.info(f"Successfully removed stat for Player ID: {player_id}, Stat ID: {stat_id}")
        return jsonify({'success': True})
    
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting match stat {stat_id}: {str(e)}")
        return jsonify({'success': False}), 500

@players_bp.route('/player/<int:player_id>/upload_profile_picture', methods=['POST'])
@login_required
@admin_or_owner_required
def upload_profile_picture(player_id):
    player = Player.query.get_or_404(player_id)

    cropped_image_data = request.form.get('cropped_image_data')
    if not cropped_image_data:
        flash('No image data provided.', 'danger')
        return redirect(url_for('players.player_profile', player_id=player_id))

    try:
        image_url = save_cropped_profile_picture(cropped_image_data, player_id)
        player.profile_picture_url = image_url
        db.session.commit()
        flash('Profile picture updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while uploading the image: {str(e)}', 'danger')

    return redirect(url_for('players.player_profile', player_id=player_id))

@players_bp.route('/delete_player/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_player(player_id):
    try:
        player = Player.query.get_or_404(player_id)
        user = player.user

        # Delete the player
        db.session.delete(player)

        # Delete the user
        db.session.delete(user)

        db.session.commit()

        flash('Player and user account deleted successfully.', 'success')
        return redirect(url_for('players.view_players'))

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting player {player_id}: {str(e)}")
        flash('An error occurred while deleting the player. Please try again.', 'danger')
        return redirect(url_for('players.view_players'))

@players_bp.route('/edit_player/<int:player_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_player(player_id):
    player = Player.query.get_or_404(player_id)
    form = EditPlayerForm(obj=player)

    if form.validate_on_submit():
        try:
            # Update player fields
            form.populate_obj(player)
            db.session.commit()

            flash('Player updated successfully.', 'success')
            return redirect(url_for('players.view_players'))

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating player {player_id}: {str(e)}")
            flash('An error occurred while updating the player. Please try again.', 'danger')

    return render_template('edit_player.html', form=form, player=player)
