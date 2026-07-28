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
    # Terms beyond Spring/Fall. ECS only ran two terms for years, so the
    # original pattern hardcoded them -- and a product like
    # "2026 ECS Pub League - Summer Sprint Season" returned "" for its season
    # name, leaving the order bound to NO season at all (silent: an empty
    # string, not an exception).
    _TERMS = r'Spring|Summer|Fall|Autumn|Winter'

    # ONE alternation for both adjacent forms, so the LEFTMOST match wins --
    # matching the original behaviour. Searching "YEAR TERM" across the whole
    # string first would flip precedence: "Fall 2024 to 2025 Spring Combo Pass"
    # returned '2024 Fall' before and would return '2025 Spring'.
    match = re.search(
        rf'(\d{{4}})\s+({_TERMS})\b|\b({_TERMS})\s+(\d{{4}})\b',
        product_name, re.IGNORECASE)
    if match:
        if match.group(1):
            return f"{match.group(1)} {match.group(2).capitalize()}"
        return f"{match.group(4)} {match.group(3).capitalize()}"

    # Non-adjacent year + term, e.g. "2026 ECS Pub League - Summer Sprint Season".
    #
    # ⚠️ Deliberately gated on the product being a LEAGUE product. Without that
    # gate this invents seasons for anything with a year and a season-ish word:
    # "Fall Ball 2025 Registration" -> '2025 Fall', "2026 Summerville Cup" ->
    # '2026 Summer', "Order #2025 Summer merch bundle" -> '2025 Summer'.
    # Callers use this to bind a purchase to a Season, so a merch or sub-fee
    # product would attach an order to an unrelated season.
    #
    # The \b after the term is what stops "Summerville" matching "Summer".
    if re.search(r'\bpub\s+league\b', product_name, re.IGNORECASE):
        year_m = re.search(r'\b(20\d{2})\b', product_name)
        term_m = re.search(rf'\b({_TERMS})\b', product_name, re.IGNORECASE)
        if year_m and term_m:
            return f"{year_m.group(1)} {term_m.group(1).capitalize()}"

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
        # Registry FIRST, substrings second.
        #
        # WARNING: the order is load-bearing for renames. Only a program given
        # an explicit woo_name_pattern matches here, so ordinary Premier/Classic
        # titles fall straight through to the tokens below. But once pl_third is
        # renamed to something like "Premier Plus" -- the documented rename
        # example -- `"PREMIER" in product_name` is TRUE for its product, and
        # checking tokens first filed every Premier Plus buyer into the PREMIER
        # league. extract_pub_league_items (registry-first) resolved the same
        # order correctly, so a single order was split across two divisions by
        # two parsers that disagreed.
        _prog = _program_for_product_name(product_name)
        if _prog:
            _lg = SeasonSyncService.get_current_league_by_name(
                session, _prog.league_name, _prog.season_league_type)
            if _lg:
                logger.debug(f"Product '{product_name}' mapped via registry "
                             f"to {_prog.league_name} league id={_lg.id}.")
                return _lg
            logger.error(f"Current season league '{_prog.league_name}' not found.")
            return None
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
            # No PREMIER/CLASSIC token. Ask the registry, which matches on Woo
            # product ID first and a per-program name pattern second -- the 2026
            # Summer product has neither a season nor a division token, so this
            # branch used to just log "Unknown division" and drop the order.
            prog = _program_for_product_name(product_name)
            if prog:
                lg = SeasonSyncService.get_current_league_by_name(
                    session, prog.league_name, prog.season_league_type)
                if lg:
                    logger.debug(f"Product '{product_name}' mapped via registry "
                                 f"to {prog.league_name} league id={lg.id}.")
                    return lg
                logger.error(f"Current season league '{prog.league_name}' not found.")
                return None
            logger.error(f"Unknown division in product name: '{product_name}'.")
            return None

    # Last resort before giving up entirely: a registry match on the whole name.
    prog = _program_for_product_name(product_name)
    if prog:
        lg = SeasonSyncService.get_current_league_by_name(
            session, prog.league_name, prog.season_league_type)
        if lg:
            return lg

    logger.warning(f"Could not determine league type from product name: '{product_name}'")
    return None


def _program_for_product_name(product_name, product_id=None):
    """Registry lookup for a Woo product, or None."""
    try:
        from app.services import program_registry
        return program_registry.by_woo_product(
            product_id=product_id, product_name=product_name)
    except Exception as exc:
        logger.debug(f"registry product lookup failed: {exc}")
        return None


def determine_league_cached(product_name, current_seasons, league_cache, session=None,
                            _memo=None):
    """Resolve a Woo product to a League, memoised per product name.

    WARNING: this used to be a SECOND, independent implementation of
    determine_league, and it had drifted badly:

      * it was never made registry-aware, so it logged "Unknown division" and
        the caller `continue`d -- the bulk order sync silently skipped every
        order for any program added after Premier/Classic, permanently; and
      * `league_cache` holds DICTS (reference_cache.get_leagues returns
        {'id','name',...}) while this function did `league.season` and
        `league.name` attribute access -- an AttributeError on the very first
        iteration, so the "optimised" path was already dead.

    It now delegates to the single parser. `_memo` keeps the per-run cost down:
    one order sync sees the same handful of product names thousands of times.
    """
    if _memo is None:
        _memo = {}
    key = (product_name or '').upper().strip()
    if key in _memo:
        return _memo[key]
    league = determine_league(product_name, current_seasons, session=session)
    _memo[key] = league
    return league


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