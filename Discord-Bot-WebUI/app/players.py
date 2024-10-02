from flask import current_app, Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from app.models import Player, League, Season, PlayerSeasonStats, PlayerCareerStats, PlayerOrderHistory, User, Notification, Role, PlayerStatAudit, Match, PlayerEvent, PlayerEventType, user_roles
from app.decorators import role_required
from app import db
from app.woocommerce import fetch_orders_from_woocommerce
from app.routes import get_current_season_and_year
from app.teams import current_season_id
from app.forms import PlayerProfileForm, SeasonStatsForm, CareerStatsForm, SubmitForm, soccer_positions, goal_frequency_choices, availability_choices, pronoun_choices, willing_to_referee_choices
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import select
from PIL import Image
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
    # Logging the player ID and event type
    current_app.logger.info(f"Decrementing stats for Player ID: {player_id}, Event Type: {event_type}")
    
    player = Player.query.get(player_id)
    
    # Log if player is not found
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

    # Log current stats
    log_current_stats(season_stats, career_stats)

    # Map event types to corresponding stats
    event_stats_map = {
        PlayerEventType.GOAL: ('goals', 'Decremented goals'),
        PlayerEventType.ASSIST: ('assists', 'Decremented assists'),
        PlayerEventType.YELLOW_CARD: ('yellow_cards', 'Decremented yellow cards'),
        PlayerEventType.RED_CARD: ('red_cards', 'Decremented red cards')
    }

    # Decrement the corresponding stat if the event type matches
    if event_type in event_stats_map:
        stat_attr, log_msg = event_stats_map[event_type]
        decrement_stat(season_stats, career_stats, stat_attr, player_id, log_msg)
    else:
        current_app.logger.error(f"Unknown event type: {event_type} for Player ID: {player_id}")

    # Commit the changes and log it
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
    """Update existing player details."""
    if player:
        player.is_current_player = True
        player.phone = player_data['phone']
        player.jersey_size = player_data['jersey_size']
        db.session.add(player)
    return player

def create_user_for_player(player, email, name):
    """Create or link a user to a player."""
    existing_user = User.query.filter_by(email=email).first()
    
    if existing_user:
        logger.info(f"User with email {email} already exists. Linking existing user to the player.")
        player.user_id = existing_user.id
    else:
        new_user = User(
            username=generate_unique_username(name),
            email=email,
            is_approved=False
        )
        new_user.set_password(generate_random_password())
        db.session.add(new_user)
        db.session.flush()  # Ensure user ID is created before linking
        player.user_id = new_user.id
        logger.info(f"Created new user {new_user.username} for player {player.name}")
    
    db.session.add(player)

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
        jersey_size = billing.get('jersey_size', '').strip().upper()  # Ensure jersey_size is part of billing
        if not jersey_size:
            jersey_size = 'N/A'  # Default value if not provided
        return {
            'name': name,
            'email': billing.get('email', '').strip().lower(),
            'phone': phone,
            'jersey_size': jersey_size
        }
    except Exception as e:
        logger.error(f"Error extracting player info: {e}", exc_info=True)
        return None

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

def create_player_profile(player_info, league, user):
    """
    Creates a player profile linked to an existing user.
    
    Args:
        player_info (dict): Extracted player information.
        league (League): League object.
        user (User): Existing user object.
    
    Returns:
        Player: The created Player object, or None if failed.
    """
    try:
        new_player = Player(
            name=player_info['name'],
            email=player_info['email'],
            phone=player_info['phone'],
            jersey_size=player_info['jersey_size'],
            league_id=league.id,
            user_id=user.id,
            is_current_player=True,
            # Initialize other necessary fields
        )
        db.session.add(new_player)
        logger.info(f"Created new player profile for '{new_player.name}' with email '{new_player.email}'.")
        return new_player
    except Exception as e:
        logger.error(f"Error creating player profile for '{player_info['email']}': {e}", exc_info=True)
        return None

def create_user_and_player_profile(player_info, league):
    """
    Creates or updates user and player profile and marks players as current.
    All players will be assigned to the ECS FC league (league_id=14) if the product name contains 'ECS FC'.

    Args:
        player_info (dict): Extracted player information.
        league (League): League object.

    Returns:
        Player: The created or updated Player object, or None if failed.
    """
    try:
        # Override league to ensure they are placed in ECS FC league (league_id=14) if the product name starts with 'ECS FC'
        product_name = player_info.get('product_name', '').upper()
        if product_name.startswith("ECS FC"):
            logger.debug(f"Product '{product_name}' identified as ECS FC, assigning league_id=14.")
            league_id = 14  # ECS FC League
        else:
            league_id = league.id

        # Check if the User with this email already exists
        user = User.query.filter_by(email=player_info['email']).first()

        if not user:
            # Create a new user
            random_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(10))
            user = User(
                email=player_info['email'],
                username=player_info['name'],
                is_approved=True,  # Set is_approved to True for all unique users
            )
            user.set_password(random_password)
            db.session.add(user)
            db.session.flush()  # Ensure user is available for assigning user_id
            logger.info(f"Created new user '{user.email}' with username '{user.username}' and approved status.")

        # Check if a Player with this email already exists
        existing_player = Player.query.filter_by(email=player_info['email']).first()

        if existing_player:
            # Mark existing player as current
            existing_player.is_current_player = True
            db.session.commit()  # Commit the change for existing player
            logger.info(f"Marked existing player '{existing_player.name}' as CURRENT_PLAYER.")
            return existing_player

        else:
            # Create a new player profile if not existing
            new_player = Player(
                name=player_info['name'],
                email=player_info['email'],
                phone=player_info['phone'],
                jersey_size=player_info['jersey_size'],
                league_id=league_id,  # Assign ECS FC league (14) or provided league
                user_id=user.id,  # Link to the user
                is_current_player=True  # Mark new player as current player
            )
            db.session.add(new_player)
            db.session.flush()  # Ensure the player is available
            logger.info(f"Created new player profile for '{new_player.name}' with email '{new_player.email}'.")
            return new_player

    except IntegrityError as ie:
        logger.error(f"IntegrityError while creating player for '{player_info['email']}': {ie}", exc_info=True)
        db.session.rollback()
        return None

    except Exception as e:
        logger.error(f"Error creating player for '{player_info['email']}': {e}", exc_info=True)
        db.session.rollback()
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
        subquery = db.session.query(Player.id).join(League).filter(
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

# View Players
@players_bp.route('/', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def view_players():
    # Get the search term from the query parameters
    search_term = request.args.get('search', '').strip()

    # Get the current page numbers from the query string, default to 1
    classic_page = request.args.get('classic_page', 1, type=int)
    premier_page = request.args.get('premier_page', 1, type=int)
    ecsfc_page = request.args.get('ecsfc_page', 1, type=int)  # Added ECS FC pagination

    # Define how many players to display per page
    per_page = 10

    # Query players by league (Classic, Premier, ECS FC)
    classic_query = Player.query.join(League).filter(League.name == 'Classic')
    premier_query = Player.query.join(League).filter(League.name == 'Premier')
    ecsfc_query = Player.query.join(League).filter(League.name == 'ECS FC')  # Assuming ECS FC is the league name

    # If there is a search term, apply filters to the queries
    if search_term:
        search_filter = (
            Player.name.ilike(f'%{search_term}%') |
            Player.email.ilike(f'%{search_term}%') |
            Player.phone.ilike(f'%{search_term}%') |
            Player.jersey_size.ilike(f'%{search_term}%')
        )
        classic_query = classic_query.filter(search_filter)
        premier_query = premier_query.filter(search_filter)
        ecsfc_query = ecsfc_query.filter(search_filter)

    # Paginate the results
    classic_players = classic_query.paginate(page=classic_page, per_page=per_page, error_out=False)
    premier_players = premier_query.paginate(page=premier_page, per_page=per_page, error_out=False)
    ecsfc_players = ecsfc_query.paginate(page=ecsfc_page, per_page=per_page, error_out=False)  # Added ECS FC players

    # Debug logs to check the queries
    logger.debug(f"Classic players: {classic_players.items}")
    logger.debug(f"Premier players: {premier_players.items}")
    logger.debug(f"ECS FC players: {ecsfc_players.items}")

    return render_template(
        'view_players.html',
        classic_players=classic_players,
        premier_players=premier_players,
        ecsfc_players=ecsfc_players,  # Added ECS FC players to render
        search_term=search_term
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

        # Log current seasons and their leagues for debugging
        for season in current_seasons:
            logger.debug(f"Season: {season.name}, Leagues: {[league.name for league in season.leagues]}")

        # Step 2: Fetch orders from WooCommerce
        orders = fetch_orders_from_woocommerce(
            current_season_name='2024 Fall',
            filter_current_season=True,
            current_season_names=[season.name for season in current_seasons],
            max_pages=10  # Limit to 10 pages
        )

        detected_players = set()  # Track all detected player IDs

        # Step 3: Reset current players (mark all as inactive initially)
        reset_current_players(current_seasons)

        # Step 4: Group orders by email
        email_orders_map = {}
        for order in orders:
            email = order['billing'].get('email', '').lower()
            if not email:
                logger.warning(f"No email found for order ID {order['order_id']}. Skipping.")
                continue
            if email not in email_orders_map:
                email_orders_map[email] = []
            email_orders_map[email].append(order)

        # Step 5: Process each email group
        for email, email_orders in email_orders_map.items():
            for order in email_orders:
                product_name = order['product_name']
                quantity = order['quantity']

                # Extract player info
                player_info = extract_player_info(order['billing'])
                if not player_info:
                    logger.warning(f"Could not extract player info for email '{email}'. Skipping order ID {order['order_id']}.")
                    continue

                # Determine league using the updated function
                league = determine_league(product_name, current_seasons)
                if not league:
                    logger.warning(f"League not found for product '{product_name}'. Skipping order ID {order['order_id']}.")
                    continue

                # Initialize player to None for proper reference later
                player = None

                # Check if user exists
                user = User.query.filter_by(email=email).first()
                if user:
                    # Check if player profile exists for this league
                    existing_player = Player.query.filter_by(email=player_info['email'], league_id=league.id).first()
                    if existing_player:
                        # Mark existing player as current (active)
                        existing_player.is_current_player = True
                        detected_players.add(existing_player.id)
                        logger.info(f"Player profile already exists for user '{email}' in league '{league.name}'. Marking player as current for order ID {order['order_id']}.")
                        player = existing_player  # Set player to existing player
                    else:
                        # Create player profile if none exists
                        player = create_user_and_player_profile(player_info, league)
                        if player:
                            detected_players.add(player.id)
                else:
                    # Create user and player profile if none exists
                    player = create_user_and_player_profile(player_info, league)
                    if player:
                        detected_players.add(player.id)

                if player:  # Ensure player is not None before proceeding
                    # Record order history
                    record_order_history(
                        order_id=order['order_id'],
                        player_id=player.id,
                        league_id=league.id,
                        season_id=league.season_id,
                        profile_count=quantity
                    )
                else:
                    logger.error(f"Cannot record order history for order_id '{order['order_id']}' because player_id is None.")

        # Step 6: Mark all non-detected players as inactive
        # Correctly fetch league IDs from current seasons
        current_league_ids = [league.id for season in current_seasons for league in season.leagues]
        all_players = Player.query.filter(Player.league_id.in_(current_league_ids)).all()
        for player in all_players:
            if player.id not in detected_players:
                player.is_current_player = False
                logger.info(f"Marked player '{player.name}' as NOT CURRENT_PLAYER (inactive).")

        # Step 7: Commit all changes
        db.session.commit()
        logger.info("All players have been updated successfully.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"An error occurred while updating players: {e}", exc_info=True)
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('players.view_players'))

    flash("Players updated successfully.", "success")
    return redirect(url_for('players.view_players'))

@players_bp.route('/profile/<int:player_id>', methods=['GET', 'POST'])
@login_required
def player_profile(player_id):
    player = Player.query.options(joinedload(Player.team)).get_or_404(player_id)
    current_season_name, current_year = get_current_season_and_year()
    season = Season.query.filter_by(name=current_season_name).first()

    user = player.user

    # Query all matches that the player has participated in through PlayerEvent
    matches = Match.query.join(PlayerEvent).filter(PlayerEvent.player_id == player_id).all()

    if not season:
        flash('Current season not found.', 'danger')
        return redirect(url_for('home'))

    # Query distinct jersey sizes from the Player table
    distinct_jersey_sizes = db.session.query(Player.jersey_size).distinct().all()
    jersey_sizes = [(size[0], size[0]) for size in distinct_jersey_sizes if size[0]]

    # Fetch the Classic League
    classic_league = League.query.filter_by(name='Classic').first()
    if not classic_league:
        flash('Classic league not found', 'danger')
        return redirect(url_for('players.player_profile', player_id=player.id))

    # Ensure season stats exist
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season.id).first()
    if not season_stats:
        season_stats = PlayerSeasonStats(player_id=player_id, season_id=season.id)
        db.session.add(season_stats)
        db.session.commit()

    # Ensure career stats exist
    if not player.career_stats:  # Check if the career_stats collection is empty
        new_career_stats = PlayerCareerStats(player_id=player.id)
        player.career_stats.append(new_career_stats)  # Append the new object to the collection
        db.session.add(new_career_stats)
        db.session.commit()

    is_classic_league_player = player.league_id == classic_league.id
    is_player = player.user_id == current_user.id
    is_admin = current_user.has_role('Pub League Admin') or current_user.has_role('Global Admin')

    # Handle the coach status update (only if admin)
    if is_admin and request.method == 'POST' and 'update_coach_status' in request.form:
        try:
            # Update the player's coach status
            is_coach = 'is_coach' in request.form  # True if checkbox is checked
            
            # Update player.is_coach field
            player.is_coach = is_coach
            
            # Fetch the 'Pub League Coach' role
            coach_role = Role.query.filter_by(name='Pub League Coach').first()

            if is_coach:
                # Add 'Pub League Coach' role to the user's roles
                if coach_role not in user.roles:
                    user.roles.append(coach_role)
            else:
                # Remove 'Pub League Coach' role from the user's roles if unmarked
                if coach_role in user.roles:
                    user.roles.remove(coach_role)
            
            db.session.commit()
            flash(f"{player.name}'s coach status updated successfully.", 'success')
            return redirect(url_for('players.player_profile', player_id=player.id))

        except SQLAlchemyError as e:
            db.session.rollback()
            flash('An error occurred while updating the coach status. Please try again.', 'danger')
            current_app.logger.error(f"Error updating coach status for player {player_id}: {str(e)}")

    # Handle referee status update (new logic)
    if is_admin and request.method == 'POST' and 'update_ref_status' in request.form:
        try:
            is_ref = 'is_ref' in request.form  # True if checkbox is checked
            player.is_ref = is_ref

            # Fetch the 'Pub League Ref' role
            ref_role = Role.query.filter_by(name='Pub League Ref').first()

            if is_ref:
                # Add 'Pub League Ref' role to the user's roles if marked as ref
                if ref_role and ref_role not in user.roles:
                    user.roles.append(ref_role)
            else:
                # Remove 'Pub League Ref' role from the user's roles if unmarked
                if ref_role and ref_role in user.roles:
                    user.roles.remove(ref_role)

            db.session.commit()
            flash(f"{player.name}'s referee status updated successfully.", 'success')
            return redirect(url_for('players.player_profile', player_id=player.id))

        except SQLAlchemyError as e:
            db.session.rollback()
            flash('An error occurred while updating the referee status. Please try again.', 'danger')
            current_app.logger.error(f"Error updating referee status for player {player_id}: {str(e)}")

    form = PlayerProfileForm(obj=player) if is_player or is_admin else None
    if form:
        form.jersey_size.choices = jersey_sizes  # Populate jersey size choices

    season_stats_form = SeasonStatsForm(
        season_goals=season_stats.goals,
        season_assists=season_stats.assists,
        season_yellow_cards=season_stats.yellow_cards,
        season_red_cards=season_stats.red_cards
    ) if is_admin else None

    career_stats_form = CareerStatsForm(
        career_goals=player.get_career_goals(),
        career_assists=player.get_career_assists(),
        career_yellow_cards=player.get_career_yellow_cards(),
        career_red_cards=player.get_career_red_cards()
    ) if is_admin else None

    # Pre-populate the multi-select fields with data from the database
    if form:
        form.other_positions.data = player.other_positions.strip('{}').split(',') if player.other_positions else []
        form.positions_not_to_play.data = player.positions_not_to_play.strip('{}').split(',') if player.positions_not_to_play else []
        form.favorite_position.data = player.favorite_position
        if is_classic_league_player and hasattr(form, 'team_swap'):
            form.team_swap.data = player.team_swap

    # Handle profile update (only if allowed)
    if form and form.validate_on_submit() and 'update_profile' in request.form:
        try:
            form.favorite_position.data = request.form.get('favorite_position')
            form.other_positions.data = request.form.getlist('other_positions')
            form.positions_not_to_play.data = request.form.getlist('positions_not_to_play')

            form.populate_obj(player)

            player.favorite_position = form.favorite_position.data
            player.other_positions = "{" + ",".join(form.other_positions.data) + "}" if form.other_positions.data else None
            player.positions_not_to_play = "{" + ",".join(form.positions_not_to_play.data) + "}" if form.positions_not_to_play.data else None

            if is_classic_league_player and hasattr(form, 'team_swap'):
                player.team_swap = form.team_swap.data

            db.session.commit()

            flash('Profile updated successfully.', 'success')
            return redirect(url_for('players.player_profile', player_id=player.id))

        except SQLAlchemyError as e:
            db.session.rollback()
            flash('An error occurred while updating the profile. Please try again.', 'danger')
            current_app.logger.error(f"Error updating profile for player {player_id}: {str(e)}")

    # Handle season stats update (only if admin)
    if is_admin and season_stats_form and season_stats_form.validate_on_submit() and 'update_season_stats' in request.form:
        try:
            player.update_season_stats(season.id, {
                'goals': season_stats_form.season_goals.data,
                'assists': season_stats_form.season_assists.data,
                'yellow_cards': season_stats_form.season_yellow_cards.data,
                'red_cards': season_stats_form.season_red_cards.data,
            }, user_id=current_user.id)

            flash('Season stats updated successfully.', 'success')
            return redirect(url_for('players.player_profile', player_id=player.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash('An error occurred while updating season stats. Please try again.', 'danger')
            current_app.logger.error(f"Error updating season stats for player {player_id}: {str(e)}")

    # Handle career stats update (only if admin and manually triggered)
    if is_admin and career_stats_form and career_stats_form.validate_on_submit() and 'update_career_stats' in request.form:
        try:
            player.update_career_stats({
                'goals': career_stats_form.career_goals.data,
                'assists': career_stats_form.career_assists.data,
                'yellow_cards': career_stats_form.career_yellow_cards.data,
                'red_cards': career_stats_form.career_red_cards.data,
            }, user_id=current_user.id)

            flash('Career stats updated successfully.', 'success')
            return redirect(url_for('players.player_profile', player_id=player.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash('An error occurred while updating career stats. Please try again.', 'danger')
            current_app.logger.error(f"Error updating career stats for player {player_id}: {str(e)}")

    # Handle adding new match-specific stats (for admin only)
    if is_admin and request.method == 'POST' and 'add_stat_manually' in request.form:
        try:
            new_stat_data = {
                'match_id': request.form.get('match_id'),
                'goals': int(request.form.get('goals', 0)),
                'assists': int(request.form.get('assists', 0)),
                'yellow_cards': int(request.form.get('yellow_cards', 0)),
                'red_cards': int(request.form.get('red_cards', 0)),
            }
            player.add_stat_manually(new_stat_data, user_id=current_user.id)
            flash('Stat added successfully.', 'success')
            return redirect(url_for('players.player_profile', player_id=player.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash('An error occurred while adding stats. Please try again.', 'danger')
            current_app.logger.error(f"Error adding stats for player {player_id}: {str(e)}")

    # Fetch audit logs
    audit_logs = PlayerStatAudit.query.filter_by(player_id=player_id).order_by(PlayerStatAudit.timestamp.desc()).all()

    return render_template(
        'player_profile.html',
        player=player,
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
def upload_profile_picture(player_id):
    player = Player.query.get_or_404(player_id)

    # Check if the current user is authorized to update the profile
    if not (current_user.is_admin or current_user.id == player.user_id):
        flash('You do not have permission to update this profile.', 'danger')
        return redirect(url_for('players.player_profile', player_id=player_id))

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