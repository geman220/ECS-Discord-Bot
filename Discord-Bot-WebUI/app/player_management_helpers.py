from flask import g
from app.models import Player, League, PlayerOrderHistory, User
from app.routes import get_current_season_and_year
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from datetime import datetime
import uuid
import secrets
import string
import logging

from app.players_helpers import (
    generate_random_password,
    generate_unique_username,
    standardize_name,
    standardize_phone,
    match_player,
)

logger = logging.getLogger(__name__)

def create_or_update_player(player_data, league, current_seasons, existing_main_player, existing_placeholders, total_line_items):
    """Create or update player with proper session management."""
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None

    session = g.db_session
    player_data['name'] = standardize_name(player_data['name'])
    player_data['email'] = player_data['email'].lower()

    logger.info(f"Existing main player: {existing_main_player}")
    logger.info(f"Number of existing placeholders: {len(existing_placeholders)}")
    logger.info(f"Total line items: {total_line_items}")

    if existing_main_player:
        update_player_details(existing_main_player, player_data)
        existing_count = 1 + len(existing_placeholders)
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
        main_player = create_new_player(player_data, league, is_placeholder=False)
        logger.info(f"Created main player: {main_player.name}")

        placeholders_needed = total_line_items - 1
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
    """Create new player with proper session management."""
    session = g.db_session
    if is_placeholder:
        placeholder_suffix = f"+{original_player_id}-{uuid.uuid4().hex[:6]}"
        name = f"{player_data['name']} {placeholder_suffix}"
        email = f"placeholder_{original_player_id}_{uuid.uuid4().hex[:6]}@publeague.com"
        phone = f"000{uuid.uuid4().int % 10000:04d}"
    else:
        name = player_data['name']
        email, phone = player_data['email'], player_data['phone']

    existing_user = session.query(User).filter_by(email=email).first()
    if not existing_user:
        existing_user = User(
            username=generate_unique_username(name),
            email=email,
            is_approved=False
        )
        existing_user.set_password(generate_random_password())
        session.add(existing_user)
        session.flush()  # To get the user.id

    new_player = Player(
        name=name,
        email=email,
        phone=phone,
        jersey_size=player_data['jersey_size'],
        league_id=league.id,
        is_current_player=True,
        needs_manual_review=is_placeholder,
        linked_primary_player_id=original_player_id,
        order_id=player_data['order_id'],
        user=existing_user
    )
    session.add(new_player)
    session.flush()
    return new_player

def update_player_details(player, player_data):
    """Update player details with proper session management."""
    if not player:
        return None

    session = g.db_session
    player.is_current_player = True
    player.phone = standardize_phone(player_data.get('phone', ''))
    player.jersey_size = player_data.get('jersey_size', '')

    new_email = player_data.get('email', '').lower()
    if not player.user.email:
        player.user.email = new_email
        logger.info(f"Set email for user '{player.user.username}' to '{new_email}'.")
    elif player.user.email.lower() != new_email:
        logger.info(
            f"Email from WooCommerce '{new_email}' does not match user's email '{player.user.email}'. "
            "Keeping the user's current email."
        )

    return player

def create_player_profile(player_data, league, user):
    """Create player profile with proper session management."""
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None

    session = g.db_session

    def find_existing_player():
        return match_player(player_data, league)

    player = find_existing_player()
    if player:
        # Update existing player
        player = update_player_details(player, player_data)
        
        if league not in player.other_leagues:
            player.other_leagues.append(league)
        
        if not player.primary_league:
            player.primary_league = league
        else:
            current_priority = ['Classic', 'Premier', 'ECS FC']
            if current_priority.index(league.name) < current_priority.index(player.primary_league.name):
                player.primary_league = league
        
        logger.info(f"Updated existing player '{player.name}' for user '{user.email}'.")
    else:
        # Create new player
        player = Player(
            name=standardize_name(player_data.get('name', '')),
            phone=standardize_phone(player_data.get('phone', '')),
            jersey_size=player_data.get('jersey_size', ''),
            primary_league=league,
            user=user,
            is_current_player=True
        )
        player.other_leagues.append(league)
        session.add(player)
        session.flush()
        logger.info(f"Created new player profile '{player.name}' for user '{user.email}'.")

    return player

def create_user_and_player_profile(player_info, league):
    """Create user and player profile with proper session management."""
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None

    session = g.db_session

    try:
        def get_existing_user():
            return session.query(User).filter(
                func.lower(User.email) == func.lower(player_info['email'])
            ).first()

        user = get_existing_user()
        if not user:
            # Create new user
            random_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(10))
            user = User(
                email=player_info['email'].lower(),
                username=player_info['name'],
                is_approved=True
            )
            user.set_password(random_password)
            session.add(user)
            session.flush()
            logger.info(f"Created new user '{user.email}' with username '{user.username}'")

        def get_existing_player():
            return session.query(Player).filter_by(
                user_id=user.id, 
                league_id=league.id
            ).first()

        existing_player = get_existing_player()
        if existing_player:
            existing_player.is_current_player = True
            logger.info(f"Marked existing player '{existing_player.name}' as current")
            return existing_player

        new_player = Player(
            name=player_info['name'],
            phone=player_info['phone'],
            jersey_size=player_info['jersey_size'],
            league_id=league.id,
            user_id=user.id,
            is_current_player=True
        )
        session.add(new_player)
        session.flush()
        logger.info(f"Created new player profile for '{new_player.name}'")
        return new_player

    except IntegrityError as ie:
        logger.error(f"IntegrityError while creating player: {ie}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error creating player: {e}", exc_info=True)
        raise

def reset_current_players(current_seasons):
    """Reset current players with proper session management."""
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return 0

    session = g.db_session
    try:
        season_ids = [season.id for season in current_seasons]
        logger.debug(f"Resetting players for seasons: {season_ids}")

        updated_rows = (session.query(Player)
                        .join(League, Player.league_id == League.id)
                        .filter(League.season_id.in_(season_ids), Player.is_current_player == True)
                        .update({Player.is_current_player: False}, synchronize_session=False))

        logger.info(f"Reset {updated_rows} players")
        return updated_rows
    except Exception as e:
        logger.error(f"Error resetting players: {str(e)}", exc_info=True)
        raise

def fetch_existing_players(email):
    """Fetch players with proper session management."""
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None, []

    session = g.db_session
    main_player = session.query(Player).filter_by(
        email=email.lower(), 
        linked_primary_player_id=None
    ).first()
    
    if not main_player:
        return None, []
    
    placeholders = session.query(Player).filter_by(
        linked_primary_player_id=main_player.id
    ).all()
    
    return main_player, placeholders

def check_if_order_processed(order_id, player_id, league_id, season_id):
    """Check order processing status with proper session management."""
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None

    session = g.db_session
    return session.query(PlayerOrderHistory).filter_by(
        order_id=str(order_id),
        player_id=player_id,
        league_id=league_id,
        season_id=season_id
    ).first()

def record_order_history(order_id, player_id, league_id, season_id, profile_count):
    """Record order history with proper session management."""
    if not player_id:
        logger.error("Cannot record order history: player_id is None")
        return None

    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None

    session = g.db_session
    try:
        order_history = PlayerOrderHistory(
            player_id=player_id,
            order_id=str(order_id),
            season_id=season_id,
            league_id=league_id,
            profile_count=profile_count,
            created_at=datetime.utcnow()
        )
        session.add(order_history)
        session.flush()
        return order_history
    except Exception as e:
        logger.error(f"Error recording order history: {str(e)}", exc_info=True)
        raise
