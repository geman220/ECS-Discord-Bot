# app/order_helpers.py

"""
Order Helpers Module

This module provides utility functions to extract order details such as season names,
jersey sizes, and to determine the correct league based on product names. It assists in
processing WooCommerce orders by mapping product details to application-specific models.
"""

from flask import g
from app.core import db
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
            if last_token.isupper() and len(last_token) <= 4:
                return last_token
        return 'N/A'
    except Exception as e:
        logger.error(f"Error extracting jersey size from product name '{product_name}': {e}", exc_info=True)
        return 'N/A'


def determine_league(product_name, current_seasons, session=None):
    """
    Determine the league based on the product name and current seasons.

    Uses dynamic lookup via SeasonSyncService to get CURRENT SEASON league IDs
    instead of hardcoded IDs that may point to old seasons.

    Args:
        product_name (str): The product name.
        current_seasons (list): List of current Season objects.
        session (SQLAlchemy Session, optional): Database session to use.

    Returns:
        League: The League object if determined, or None otherwise.
    """
    from app.services.season_sync_service import SeasonSyncService

    if session is None:
        # When not in a request context, use the global session.
        session = g.db_session
    product_name = product_name.upper().strip()
    logger.debug(f"Determining league for product name: '{product_name}'")

    # Handle ECS FC products - use dynamic lookup for current season
    if product_name.startswith("ECS FC"):
        ecs_fc_league = SeasonSyncService.get_current_league_by_name(session, 'ECS FC', 'ECS FC')
        if ecs_fc_league:
            logger.debug(f"Product '{product_name}' mapped to ECS FC league '{ecs_fc_league.name}' with id={ecs_fc_league.id}.")
            return ecs_fc_league
        else:
            logger.error(f"Current season ECS FC League not found in the database.")
            return None

    # Handle ECS Pub League products (check for both "ECS PUB LEAGUE" and "PUB LEAGUE" patterns)
    elif "ECS PUB LEAGUE" in product_name or "PUB LEAGUE" in product_name:
        if "PREMIER DIVISION" in product_name or "PREMIER" in product_name:
            # Use dynamic lookup for current season Premier league
            pub_league = SeasonSyncService.get_current_league_by_name(session, 'Premier', 'Pub League')
            if pub_league:
                logger.debug(f"Product '{product_name}' mapped to current season Premier league with id={pub_league.id}.")
                return pub_league
            else:
                logger.error(f"Current season Premier league not found in the database.")
                return None
        elif "CLASSIC DIVISION" in product_name or "CLASSIC" in product_name:
            # Use dynamic lookup for current season Classic league
            pub_league = SeasonSyncService.get_current_league_by_name(session, 'Classic', 'Pub League')
            if pub_league:
                logger.debug(f"Product '{product_name}' mapped to current season Classic league with id={pub_league.id}.")
                return pub_league
            else:
                logger.error(f"Current season Classic league not found in the database.")
                return None
        else:
            logger.error(f"Unknown division in product name: '{product_name}'.")
            return None

    logger.warning(f"Could not determine league type from product name: '{product_name}'")
    return None


def determine_league_cached(product_name, current_seasons, league_cache):
    """
    Optimized version of determine_league that uses cached league objects.

    The league_cache should contain leagues from CURRENT SEASONS only.
    This function looks up leagues by name from the cache instead of using
    hardcoded IDs.

    Args:
        product_name (str): The product name.
        current_seasons (list): List of current Season objects.
        league_cache (dict): Dictionary mapping league_id to League objects.
            Should contain only leagues from current seasons.

    Returns:
        League: The League object if determined, or None otherwise.
    """
    product_name = product_name.upper().strip()

    # Build a name-to-league mapping from the cache for efficient lookup
    # This ensures we use current season leagues even if the cache has mixed seasons
    league_by_name = {}
    for league in league_cache.values():
        # Only include leagues from current seasons
        if league.season and league.season.is_current:
            league_by_name[league.name.upper()] = league

    # Handle ECS FC products
    if product_name.startswith("ECS FC"):
        ecs_fc_league = league_by_name.get('ECS FC')
        if ecs_fc_league:
            return ecs_fc_league
        else:
            logger.error(f"Current season ECS FC League not found in the cache.")
            return None

    # Handle ECS Pub League products (check for both "ECS PUB LEAGUE" and "PUB LEAGUE" patterns)
    elif "ECS PUB LEAGUE" in product_name or "PUB LEAGUE" in product_name:
        if "PREMIER DIVISION" in product_name or "PREMIER" in product_name:
            pub_league = league_by_name.get('PREMIER')
            if pub_league:
                return pub_league
            else:
                logger.error(f"Current season Premier league not found in the cache.")
                return None
        elif "CLASSIC DIVISION" in product_name or "CLASSIC" in product_name:
            pub_league = league_by_name.get('CLASSIC')
            if pub_league:
                return pub_league
            else:
                logger.error(f"Current season Classic league not found in the cache.")
                return None
        else:
            logger.error(f"Unknown division in product name: '{product_name}'.")
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