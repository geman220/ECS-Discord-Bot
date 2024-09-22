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
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
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
def save_cropped_profile_picture(cropped_image_data, player_id):
    header, encoded = cropped_image_data.split(",", 1)
    image_data = base64.b64decode(encoded)

    image = Image.open(BytesIO(image_data))

    player = Player.query.get(player_id)
    player_name = player.name.replace(" ", "_")  # Replace spaces with underscores
    filename = secure_filename(f"{player_name}_{player_id}.png")

    file_path = os.path.join(current_app.root_path, 'static/img/uploads/profile_pictures', filename)

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    image.save(file_path)

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
    """Fetch existing players by email."""
    return Player.query.filter_by(email=email.lower()).all()  # Ensure email is compared in a case-insensitive manner

def check_if_order_processed(order_id, player_id, league_id, season_id):
    """Check if the order has already been processed for a specific league."""
    return PlayerOrderHistory.query.filter_by(
        order_id=order_id,
        player_id=player_id,
        league_id=league_id,
        season_id=season_id
    ).first()

# Player Creation and Updating
def create_or_update_player(player_data, league, season, existing_players, current_season_name):
    """Create or update a player, handling placeholders if necessary."""
    # Standardize name and email for comparison
    player_data['name'] = standardize_name(player_data['name'])
    player_data['email'] = player_data['email'].lower()

    # Fetch existing players by email
    existing_players_by_email = Player.query.filter_by(email=player_data['email']).all()

    # Separate placeholders from real entries
    existing_real_players = [p for p in existing_players_by_email if not p.needs_manual_review]
    existing_placeholders = [p for p in existing_players_by_email if p.needs_manual_review]

    # Count how many entries are already in DB for this email
    existing_count = len(existing_real_players) + len(existing_placeholders)

    # Count how many items/orders exist for this player
    total_items_count = player_data['total_items_count']

    # Logging the counts for debugging
    logger.info(f"Existing count in DB for {player_data['email']}: {existing_count}")
    logger.info(f"Total items count from orders for {player_data['email']}: {total_items_count}")

    # Update "is_current_player" for any existing players matching the current season
    for player in existing_real_players + existing_placeholders:
        # If the order or product matches the current season, mark as active
        if player.order_id and current_season_name in player.order_id:
            player.is_current_player = True
        elif current_season_name in player_data['product_name']:
            player.is_current_player = True
        else:
            # Mark as inactive if not matching the current season
            player.is_current_player = False
        db.session.add(player)

    # Commit updates to the existing players' statuses
    db.session.commit()

    # If we have fewer existing entries than needed, add new ones
    if existing_count < total_items_count:
        # Create the first entry with real info if no real entries exist
        if not existing_real_players:
            real_player = create_new_player(player_data, league, is_placeholder=False)  # Correctly set to False
            existing_real_players.append(real_player)
            existing_count += 1

        # Create placeholders for any additional items
        placeholders_needed = total_items_count - existing_count
        for i in range(placeholders_needed):
            create_new_player(
                player_data,
                league,
                original_player_id=existing_real_players[0].id if existing_real_players else None,
                is_placeholder=True  # Only set True for placeholders
            )

    # Ensure the first entry is updated with the correct details
    if existing_real_players:
        update_player_details(existing_real_players[0], player_data)

    return existing_real_players[0] if existing_real_players else None

def create_new_player(player_data, league, original_player_id=None, is_placeholder=False):
    """Create a new player entry or placeholder."""
    # Generate contact info - use real info for the first entry, placeholders for duplicates
    if is_placeholder:
        # Generate unique placeholder email and phone number
        email, phone = generate_contact_info(player_data, is_placeholder=True)
    else:
        # Use real player information for the first entry
        email, phone = player_data['email'], player_data['phone']

    new_player = Player(
        name=generate_unique_name(player_data['name']) if is_placeholder else player_data['name'],
        email=email,
        phone=phone,
        jersey_size=player_data['jersey_size'],
        league_id=league.id,
        is_current_player=True,
        needs_manual_review=is_placeholder,  # Set flag for placeholders correctly
        linked_primary_player_id=original_player_id,
        order_id=str(player_data['order_id'])
    )

    db.session.add(new_player)
    db.session.flush()  # Ensure the ID is generated before linking user
    create_user_for_player(new_player, email, new_player.name)  # Create a user for the player
    return new_player

def update_player_details(player, player_data):
    """Update existing player details."""
    if player:
        player.is_current_player = True
        player.phone = player_data['phone']
        player.jersey_size = player_data['jersey_size']
        db.session.add(player)
    return player


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

def record_order_history(order_id, player_id, league_id, season_id, profile_count):
    """Record order history."""
    new_processed_order = PlayerOrderHistory(
        order_id=order_id,
        player_id=player_id,
        league_id=league_id,
        season_id=season_id,
        profile_count=profile_count
    )
    db.session.add(new_processed_order)

def get_league_by_product_name(product_name, existing_leagues):
    """Determine league based on the product name."""
    league_name = 'Classic' if 'Classic Division' in product_name else 'Premier' if 'Premier Division' in product_name else None
    if not league_name:
        logger.warning(f"Unrecognized product name format: {product_name}. Skipping player.")
        return None
    return next((l for l in existing_leagues if l.name == league_name), None)

def clean_phone_number(phone):
    """Clean phone number to digits only, keeping last 10 digits."""
    cleaned_phone = re.sub(r'\D', '', phone)  # Remove all non-digit characters
    return cleaned_phone[-10:] if len(cleaned_phone) >= 10 else cleaned_phone  # Keep last 10 digits or the entire cleaned string if shorter

# View Players
@players_bp.route('/', methods=['GET', 'POST'])
@login_required
def view_players():
    # Get the search term from the form
    search_term = request.form.get('search', '')

    # Get the current page numbers from the query string, default to 1
    classic_page = request.args.get('classic_page', 1, type=int)
    premier_page = request.args.get('premier_page', 1, type=int)

    # Define how many players to display per page
    per_page = 10

    # Query players with search functionality
    classic_query = Player.query.join(League).filter(League.name == 'Classic')
    premier_query = Player.query.join(League).filter(League.name == 'Premier')

    # If there is a search term, apply filters to the queries
    if search_term:
        search_filter = Player.name.ilike(f'%{search_term}%') | \
                        Player.email.ilike(f'%{search_term}%') | \
                        Player.phone.ilike(f'%{search_term}%') | \
                        Player.jersey_size.ilike(f'%{search_term}%')
        classic_query = classic_query.filter(search_filter)
        premier_query = premier_query.filter(search_filter)

    # Paginate the results
    classic_players = classic_query.paginate(page=classic_page, per_page=per_page)
    premier_players = premier_query.paginate(page=premier_page, per_page=per_page)

    return render_template('view_players.html', 
                           classic_players=classic_players, 
                           premier_players=premier_players, 
                           search_term=search_term)

# Update Players from WooCommerce
@players_bp.route('/update', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_players():
    try:
        current_season_name, current_year = get_current_season_and_year()
        logger.info(f"Fetching players for season: {current_season_name}")

        # Fetch the current season from the database
        season = Season.query.filter_by(name=current_season_name).first()
        if not season:
            raise Exception(f"Season '{current_season_name}' not found in the database.")

        existing_leagues = season.leagues

        # Fetch orders from WooCommerce
        orders = fetch_orders_from_woocommerce(current_season_name)

        # Reset `is_current_player` for all players to False for the current season
        Player.query.filter(Player.league.has(season_id=season.id)).update({Player.is_current_player: False})
        db.session.commit()

        # Group orders by email
        email_orders_map = {}
        for order_data in orders:
            email = order_data['billing']['email'].lower()
            if email not in email_orders_map:
                email_orders_map[email] = []
            email_orders_map[email].append(order_data)

        # Process each player based on grouped orders by email
        with db.session.no_autoflush:
            for email, email_orders in email_orders_map.items():
                # Combine orders for this email
                total_items_count = sum(order['quantity'] for order in email_orders)

                # Extract basic player info from the first order
                first_order = email_orders[0]
                billing = first_order['billing']
                full_name = f"{billing['first_name']} {billing['last_name']}"
                phone = clean_phone_number(billing['phone'])
                jersey_size = first_order['product_name'].split(' - ')[-1].strip()

                # Determine the league for the first order item
                product_name = first_order['product_name']
                league = get_league_by_product_name(product_name, existing_leagues)  # Ensure league is determined
                if not league:
                    continue  # If the league is not found, skip processing

                # Prepare player data including aggregated order information
                player_data = {
                    'name': full_name,
                    'email': email,
                    'phone': phone,
                    'jersey_size': jersey_size,
                    'product_name': product_name,
                    'order_id': str(first_order['order_id']),
                    'total_items_count': total_items_count,
                    'orders': email_orders  # Include all orders for this email
                }

                existing_players = fetch_existing_players(email)

                # Process the player creation or updating logic, now including current_season_name
                master_player = create_or_update_player(player_data, league, season, existing_players, current_season_name)

                # Record order history for all orders
                for order in email_orders:
                    record_order_history(order['order_id'], master_player.id, league.id, season.id, order['quantity'])

            db.session.commit()
            logger.info("All players have been updated successfully.")
            flash('Players updated successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating players: {str(e)}", exc_info=True)
        flash(f'Error updating players: {str(e)}', 'danger')

    return redirect(url_for('players.view_players'))

@players_bp.route('/profile/<int:player_id>', methods=['GET', 'POST'])
@login_required
def player_profile(player_id):
    player = Player.query.options(joinedload(Player.team)).get_or_404(player_id)
    current_season_name, current_year = get_current_season_and_year()
    season = Season.query.filter_by(name=current_season_name).first()

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
    if not player.career_stats:
        player.career_stats = PlayerCareerStats(player_id=player.id)
        db.session.add(player.career_stats)
        db.session.commit()

    is_classic_league_player = player.league_id == classic_league.id
    is_player = player.user_id == current_user.id
    is_admin = current_user.has_role('Pub League Admin') or current_user.has_role('Global Admin')

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