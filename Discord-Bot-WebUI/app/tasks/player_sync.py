# app/tasks/player_sync.py

from celery import shared_task
from sqlalchemy import text
from app.utils.pgbouncer_utils import set_session_timeout

from app.players_helpers import extract_player_info, match_player_weighted, match_player_with_details, match_player_with_details_cached, is_username_style_name, standardize_name
from app.order_helpers import extract_jersey_size_from_product_name, determine_league, determine_league_cached
from app.utils.sync_data_manager import save_sync_data


def make_json_serializable(obj):
    """
    Recursively convert any object to JSON-serializable format.
    """
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, dict):
        return {str(k): make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [make_json_serializable(item) for item in obj]
    elif hasattr(obj, '__dict__'):
        # For objects with attributes, convert to dict
        return make_json_serializable(obj.__dict__)
    else:
        # For anything else, convert to string
        return str(obj)
from app.core import celery
from app.core.session_manager import managed_session
from app.models import Season, Player, League, User
from app.woocommerce import fetch_orders_from_woocommerce

import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, time_limit=600, soft_time_limit=540)  # 10 minute hard limit, 9 minute soft limit
def sync_players_with_woocommerce(self, user_id=None):
    """
    Synchronize player data from WooCommerce.

    This task performs the following steps:
      - Enters the Flask application context.
      - Opens a managed database session.
      - Fetches the current season(s) and specifically the current Pub League season.
      - Iterates through WooCommerce orders page by page:
          * Fetches orders for a given page.
          * Extracts player info from the billing data.
          * Determines the appropriate league and jersey size.
          * Matches the extracted info against existing players.
          * Collects data for new players and updates for existing players.
      - Identifies potentially inactive players based on active player records.
      - Saves a synchronization package in Redis for later confirmation.
      - Updates Celery task state throughout processing.

    Returns:
        A dictionary summarizing the sync results, including counts of new players,
        updated players, and potential inactive players.

    Raises:
        Exception: Propagates any encountered exceptions after logging.
    """
    with celery.flask_app.app_context():
        try:
            # Register task with TaskManager
            try:
                from app.utils.task_manager import TaskManager
                TaskManager.register_task(
                    task_id=self.request.id,
                    task_type='player_sync',
                    user_id=user_id or 0,
                    description='Sync players from WooCommerce'
                )
            except Exception as e:
                logger.warning(f"Failed to register task with TaskManager: {e}")
                
            # Helper function to update both Celery and TaskManager
            def update_task_status(stage, message, progress):
                self.update_state(state='PROGRESS', meta={
                    'stage': stage,
                    'message': message,
                    'progress': progress
                })
                try:
                    TaskManager.update_task_status(
                        task_id=self.request.id,
                        status='PROGRESS',
                        progress=progress,
                        stage=stage,
                        message=message
                    )
                except Exception as e:
                    logger.warning(f"Failed to update TaskManager status: {e}")
            # Phase 1: Fetch required data and close session
            current_season_data = None
            current_seasons_data = []
            
            with managed_session() as session:
                # Initial state update: fetching current season
                update_task_status('init', 'Fetching current season...', 5)

                # Query current seasons and the specific current Pub League season
                current_seasons = session.query(Season).filter_by(is_current=True).all()
                current_season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
                if not current_season:
                    raise Exception('No current Pub League season found.')

                # Extract needed data from database objects
                current_season_data = {
                    'name': current_season.name,
                    'id': current_season.id
                }
                current_seasons_data = [{'name': s.name, 'id': s.id} for s in current_seasons]

            # Phase 2: Fetch all orders from WooCommerce without holding database sessions
            update_task_status('woo', 'Fetching orders from WooCommerce...', 10)

            all_orders = []
            page = 1
            
            # Process orders page by page until no more orders are returned
            while True:
                update_task_status('woo', f'Fetching page {page}...', 10 + (page * 5))

                try:
                    orders_page = fetch_orders_from_woocommerce(
                        current_season_name=current_season_data['name'],
                        filter_current_season=True,
                        current_season_names=[s['name'] for s in current_seasons_data],
                        max_pages=1,
                        page=page,
                        per_page=100
                    )
                    if not orders_page:
                        logger.info(f"No orders found on page {page}, stopping.")
                        break

                    all_orders.extend(orders_page)
                    logger.info(f"Successfully fetched {len(orders_page)} orders from page {page}. Total: {len(all_orders)}")
                    
                    # Add a safety limit to prevent infinite loops
                    if page > 20:  # Reasonable limit
                        logger.warning(f"Reached page limit (20) to prevent infinite loops. Stopping at page {page}")
                        break
                    
                    page += 1
                except Exception as e:
                    logger.error(f"Error fetching page {page}: {e}")
                    break

            total_orders_fetched = len(all_orders)
            logger.info(f"WooCommerce fetch complete. Total orders fetched: {total_orders_fetched}")
            update_task_status('fetch_complete', f'Fetched {total_orders_fetched} orders from WooCommerce', 50)

            # Phase 3: Process orders against database
            update_task_status('process_start', 'Starting order processing...', 52)
            with managed_session() as session:
                # Initialize tracking variables
                new_players = []
                existing_players = set()
                player_league_updates = []
                flagged_multi_orders = []
                email_mismatch_players = []  # Track players with email mismatches
                buyer_order_map = {}  # Track multiple orders from same buyer
                
                # Reload current seasons for league determination
                current_seasons = session.query(Season).filter_by(is_current=True).all()
                logger.info(f"Found {len(current_seasons)} current seasons for processing")
                
                # Use Redis cache for leagues instead of loading all into memory
                from app.utils.cache_manager import reference_cache
                league_cache = {league['id']: league for league in reference_cache.get_leagues(session)}
                logger.info(f"Loaded {len(league_cache)} leagues from cache")
                
                # Create indexed lookup for players instead of loading all into memory
                # Build email and name indexes for efficient player matching
                update_task_status('cache', 'Building player lookup indexes...', 55)
                
                # Create efficient player lookup by email
                player_email_lookup = {}
                for player_id, email in session.query(Player.id, User.email).join(User).all():
                    if email and email.strip().lower():
                        player_email_lookup[email.strip().lower()] = player_id
                
                # Create efficient player lookup by name (for fuzzy matching)
                player_name_lookup = {}
                for player_id, name in session.query(Player.id, Player.name).filter(Player.name.isnot(None)).all():
                    if name and name.strip():
                        key = name.strip().lower().replace(' ', '').replace('-', '').replace('.', '')
                        if key:
                            player_name_lookup[key] = player_id
                
                logger.info(f"Built lookup indexes: {len(player_email_lookup)} emails, {len(player_name_lookup)} names")
                
                # Process all fetched orders
                update_task_status('process', f'Processing {total_orders_fetched} orders...', 60)
                
                for idx, order in enumerate(all_orders):
                    # Update progress every 50 orders to reduce overhead (was every 10)
                    if idx % 50 == 0 and total_orders_fetched > 0:
                        progress = 60 + (idx / total_orders_fetched * 30)  # 60-90% range
                        update_task_status('process', f'Processing order {idx + 1}/{total_orders_fetched}...', int(progress))
                    
                    # Extract player billing info and verify it is valid
                    player_info = extract_player_info(order['billing'])
                    if not player_info:
                        continue

                    # Determine league based on the product name and current seasons - using cache for performance
                    product_name = order['product_name']
                    league = determine_league_cached(product_name, current_seasons, league_cache)
                    if not league:
                        continue

                    # Determine jersey size and attach to player info
                    jersey_size = extract_jersey_size_from_product_name(product_name)
                    player_info['jersey_size'] = jersey_size

                    # Track multiple orders from same buyer
                    buyer_key = f"{player_info.get('email', '').lower()}_{player_info.get('name', '').lower()}"
                    if buyer_key not in buyer_order_map:
                        buyer_order_map[buyer_key] = []
                    buyer_order_map[buyer_key].append({
                        'order': {
                            'order_id': order['order_id'],
                            'product_name': order['product_name'],
                            'quantity': order['quantity']
                        },
                        'player_info': player_info,
                        'league_id': league.id,
                        'league_name': league.name,
                        'product_name': product_name,
                        'jersey_size': jersey_size
                    })

                    # Check if the player already exists using optimized lookup - no need to load full objects
                    existing_player_id = None
                    
                    # First try email lookup (most reliable)
                    if player_info.get('email'):
                        email_key = player_info['email'].strip().lower()
                        existing_player_id = player_email_lookup.get(email_key)
                    
                    # If no email match, try name-based lookup
                    if not existing_player_id and player_info.get('name'):
                        name_key = player_info['name'].strip().lower().replace(' ', '').replace('-', '').replace('.', '')
                        if name_key:
                            existing_player_id = player_name_lookup.get(name_key)
                    
                    # Load the actual player object only if we found a match
                    existing_player = None
                    if existing_player_id:
                        existing_player = session.query(Player).get(existing_player_id)
                    
                    if existing_player:
                        existing_players.add(existing_player.id)
                        
                        # Check if existing player has a username-style name that should be updated
                        should_update_name = False
                        name_update_reason = None
                        woo_name = standardize_name(player_info.get('name', ''))
                        
                        if is_username_style_name(existing_player.name) and woo_name:
                            should_update_name = True
                            old_name = existing_player.name
                            name_update_reason = f"Username-style name '{old_name}' updated to real name '{woo_name}'"
                            
                            # Update the player's name in the database
                            existing_player.name = woo_name
                            logger.info(f"Updated player {existing_player.id} name from '{old_name}' to '{woo_name}' (Order: {order['order_id']})")
                        
                        # Create update record with match details
                        update_record = {
                            'player_id': existing_player.id,
                            'league_id': league.id,
                            'order_id': order['order_id'],
                            'quantity': order['quantity'],
                            'buyer_info': player_info,
                            'match_type': match_result['match_type'],
                            'confidence': match_result['confidence'],
                            'flags': match_result['flags'],
                            'name_updated': should_update_name,
                            'name_update_reason': name_update_reason
                        }
                        player_league_updates.append(update_record)
                        
                        # Only flag email mismatches that weren't resolved by name+phone matching
                        if 'email_mismatch' in match_result['flags']:
                            email_mismatch_players.append({
                                'existing_player': {
                                    'id': existing_player.id,
                                    'name': existing_player.name,
                                    'discord_email': existing_player.user.email,
                                    'phone': existing_player.phone
                                },
                                'order_info': {
                                    'woo_email': player_info.get('email', ''),
                                    'woo_name': player_info.get('name', ''),
                                    'woo_phone': player_info.get('phone', ''),
                                    'order_id': order['order_id'],
                                    'product_name': product_name,
                                    'jersey_size': jersey_size
                                },
                                'match_details': {
                                    'match_type': match_result['match_type'],
                                    'confidence': match_result['confidence'],
                                    'flags': match_result['flags']
                                }
                            })
                    else:
                        # No match found - flag for manual review
                        new_player_entry = {
                            'info': player_info,
                            'league_id': league.id,
                            'league_name': league.name,
                            'jersey_size': jersey_size,
                            'order_id': order['order_id'],
                            'quantity': order['quantity'],
                            'requires_review': True,
                            'reason': f'Player not found in database - {match_result["match_type"]} - requires manual verification'
                        }
                        new_players.append(new_player_entry)
                
                
                # Update progress state after processing all orders
                self.update_state(state='PROGRESS', meta={
                    'stage': 'process',
                    'message': f'Processed {total_orders_fetched} orders',
                    'progress': 60
                })

                # Identify inactive players - ALL currently active players without current WooCommerce orders
                self.update_state(state='PROGRESS', meta={
                    'stage': 'inactive',
                    'message': 'Identifying players to mark inactive...',
                    'progress': 90
                })
                
                # Get ALL currently active players (not just current leagues)
                all_active_players = session.query(Player).filter(
                    Player.is_current_player == True
                ).all()
                
                # Build list of players to be marked inactive (active players with no current orders)
                players_to_inactivate = []
                for player in all_active_players:
                    if player.id not in existing_players:
                        # This player is active but has no current WooCommerce order
                        players_to_inactivate.append({
                            'player_id': player.id,
                            'player_name': player.name,
                            'username': player.user.username if player.user else 'No User',
                            'league_name': player.league.name if player.league else 'No League',
                            'reason': 'No current WooCommerce membership found'
                        })
                
                potential_inactive = [p['player_id'] for p in players_to_inactivate]

                # Detect and flag multi-person orders
                for buyer_key, orders in buyer_order_map.items():
                    if len(orders) > 1 or any(order['order']['quantity'] > 1 for order in orders):
                        flagged_multi_orders.append({
                            'buyer_key': buyer_key,
                            'buyer_info': orders[0]['player_info'],
                            'orders': orders,
                            'total_memberships': sum(order['order']['quantity'] for order in orders),
                            'reason': f'Buyer purchased {sum(order["order"]["quantity"] for order in orders)} memberships across {len(orders)} order(s)'
                        })

                # Prepare sync data and clean it thoroughly for JSON serialization
                sync_data = {
                    'new_players': new_players,
                    'player_league_updates': player_league_updates,
                    'potential_inactive': potential_inactive,
                    'players_to_inactivate': players_to_inactivate,  # Detailed info for review
                    'flagged_multi_orders': flagged_multi_orders,
                    'email_mismatch_players': email_mismatch_players
                }
                
                # Apply comprehensive cleaning to ensure everything is JSON serializable
                sync_data = make_json_serializable(sync_data)
                save_sync_data(self.request.id, sync_data)

                # Commit happens automatically in managed_session
                update_task_status('complete', 'Processing complete', 100)
                
                # Update TaskManager with success status
                try:
                    TaskManager.update_task_status(self.request.id, 'SUCCESS')
                except Exception as e:
                    logger.warning(f"Failed to update TaskManager success status: {e}")

                return {
                    'status': 'complete',
                    'new_players': len(new_players),
                    'existing_players': len(existing_players),
                    'potential_inactive': len(potential_inactive),
                    'flagged_multi_orders': len(flagged_multi_orders),
                    'flagged_orders_require_review': len(flagged_multi_orders) > 0
                }

        except Exception as e:
            logger.error(f"Error in sync_players_with_woocommerce: {e}", exc_info=True)
            
            # Update TaskManager with failure status
            try:
                TaskManager.update_task_status(
                    task_id=self.request.id,
                    status='FAILURE',
                    message=str(e)
                )
            except Exception as te:
                logger.warning(f"Failed to update TaskManager failure status: {te}")
                
            raise e