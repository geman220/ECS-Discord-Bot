from flask import g
from app.models import League
import re
import logging

logger = logging.getLogger(__name__)

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
    if ' - ' in product_name:
        return product_name.split(' - ')[-1].strip()
    return ""

def extract_jersey_size_from_product_name(product_name):
    """
    Extracts the jersey size from the product name.

    Args:
        product_name (str): The name of the product.

    Returns:
        str: The extracted jersey size, or 'N/A' if not found.
    """
    try:
        tokens = product_name.split(' - ')
        if tokens:
            last_token = tokens[-1].strip()
            if last_token.isupper() and len(last_token) <= 3:
                return last_token
        return 'N/A'
    except Exception as e:
        logger.error(f"Error extracting jersey size from product name '{product_name}': {e}", exc_info=True)
        return 'N/A'

def determine_league(product_name, current_seasons, session=None):
    if session is None:
        # When not in a request context, use the global session.
        from app.core import db
        session = db.session
    product_name = product_name.upper().strip()
    logger.debug(f"Determining league for product name: '{product_name}'")

    # Handle ECS FC products
    if product_name.startswith("ECS FC"):
        league_id = 14
        ecs_fc_league = session.query(League).get(league_id)
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
        pub_league = session.query(League).get(league_id)
        if pub_league:
            logger.debug(f"Product '{product_name}' mapped to Pub League '{pub_league.name}' with id={league_id}.")
            return pub_league
        else:
            logger.error(f"Pub League with id={league_id} not found in the database.")
            return None

    logger.warning(f"Could not determine league type from product name: '{product_name}'")
    return None

def get_league_by_product_name(product_name, current_seasons):
    """
    Get league with proper session management.

    Args:
        product_name (str): The product name.
        current_seasons (list): List of current Season objects.

    Returns:
        League: The League object if found, None otherwise.
    """
    if not hasattr(g, 'db_session'):
        logger.error("No db_session found in the request context.")
        return None

    session = g.db_session
    logger.debug(f"Parsing product name: '{product_name}'")

    pub_league_pattern = re.compile(r'ECS Pub League\s*-\s*(Premier|Classic)\s*Division', re.IGNORECASE)
    ecs_fc_pattern = re.compile(r'ECS FC\s*-\s*\w+\s*-\s*\w+', re.IGNORECASE)

    pub_league_match = pub_league_pattern.search(product_name)
    if pub_league_match:
        division = pub_league_match.group(1).capitalize()
        league_name = division
        for season in current_seasons:
            league = session.query(League).filter_by(name=league_name, season_id=season.id).first()
            if league:
                return league
        return None

    ecs_fc_match = ecs_fc_pattern.search(product_name)
    if ecs_fc_match:
        league_name = 'ECS FC'
        for season in current_seasons:
            league = session.query(League).filter_by(name=league_name, season_id=season.id).first()
            if league:
                return league
        return None

    return None