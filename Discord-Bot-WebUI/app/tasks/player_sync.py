# app/tasks/player_sync.py

from celery import shared_task
from sqlalchemy import text
from app.utils.pgbouncer_utils import set_session_timeout

from app.players_helpers import extract_player_info, match_player_weighted, match_player_with_details
from app.order_helpers import extract_jersey_size_from_product_name, determine_league
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
from app.models import Season, Player
from app.woocommerce import fetch_orders_from_woocommerce

import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, time_limit=600, soft_time_limit=540)  # 10 minute hard limit, 9 minute soft limit
def sync_players_with_woocommerce(self):
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
            # Phase 1: Fetch required data and close session
            current_season_data = None
            current_seasons_data = []
            
            with managed_session() as session:
                # Initial state update: fetching current season
                self.update_state(state='PROGRESS', meta={
                    'stage': 'init',
                    'message': 'Fetching current season...',
                    'progress': 5
                })

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
            self.update_state(state='PROGRESS', meta={
                'stage': 'woo',
                'message': 'Fetching orders from WooCommerce...',
                'progress': 10
            })

            all_orders = []
            page = 1
            
            # Process orders page by page until no more orders are returned
            while True:
                self.update_state(state='PROGRESS', meta={
                    'stage': 'woo',
                    'message': f'Fetching page {page}...',
                    'progress': 10 + (page * 5)  # Progressive progress
                })

                orders_page = fetch_orders_from_woocommerce(
                    current_season_name=current_season_data['name'],
                    filter_current_season=True,
                    current_season_names=[s['name'] for s in current_seasons_data],
                    max_pages=1,
                    page=page,
                    per_page=100
                )
                if not orders_page:
                    break

                all_orders.extend(orders_page)
                page += 1

            total_orders_fetched = len(all_orders)

            # Phase 3: Process orders against database
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
                
                # Process all fetched orders
                for order in all_orders:
                    # Extract player billing info and verify it is valid
                    player_info = extract_player_info(order['billing'])
                    if not player_info:
                        continue

                    # Determine league based on the product name and current seasons
                    product_name = order['product_name']
                    league = determine_league(product_name, current_seasons, session=session)
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

                    # Check if the player already exists using enhanced matching
                    match_result = match_player_with_details(player_info, session)
                    existing_player = match_result['player']
                    
                    if existing_player:
                        existing_players.add(existing_player.id)
                        
                        # Create update record with match details
                        update_record = {
                            'player_id': existing_player.id,
                            'league_id': league.id,
                            'order_id': order['order_id'],
                            'quantity': order['quantity'],
                            'buyer_info': player_info,
                            'match_type': match_result['match_type'],
                            'confidence': match_result['confidence'],
                            'flags': match_result['flags']
                        }
                        player_league_updates.append(update_record)
                        
                        # Flag potential email mismatches for admin review
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
                                    'product_name': product_name
                                },
                                'match_details': {
                                    'match_type': match_result['match_type'],
                                    'confidence': match_result['confidence'],
                                    'flags': match_result['flags']
                                }
                            })
                    else:
                        # No match found - flag for manual review
                        new_players.append({
                            'info': player_info,
                            'league_id': league.id,
                            'order_id': order['order_id'],
                            'quantity': order['quantity'],
                            'requires_review': True,
                            'reason': f'Player not found in database - {match_result["match_type"]} - requires manual verification'
                        })
                
                # Update progress state after processing all orders
                self.update_state(state='PROGRESS', meta={
                    'stage': 'process',
                    'message': f'Processed {total_orders_fetched} orders',
                    'progress': 60
                })

                # Identify inactive players by comparing active player IDs with those updated via orders
                self.update_state(state='PROGRESS', meta={
                    'stage': 'inactive',
                    'message': 'Identifying inactive players...',
                    'progress': 90
                })
                current_league_ids = [league.id for season in current_seasons for league in season.leagues]
                all_active_players = session.query(Player).filter(
                    Player.league_id.in_(current_league_ids),
                    Player.is_current_player == True
                ).all()
                active_player_ids = {p.id for p in all_active_players}
                potential_inactive = list(active_player_ids - existing_players)

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
                    'flagged_multi_orders': flagged_multi_orders,
                    'email_mismatch_players': email_mismatch_players
                }
                
                # Apply comprehensive cleaning to ensure everything is JSON serializable
                sync_data = make_json_serializable(sync_data)
                save_sync_data(self.request.id, sync_data)

                # Commit happens automatically in managed_session
                self.update_state(state='PROGRESS', meta={
                    'stage': 'complete',
                    'message': 'Processing complete',
                    'progress': 100
                })

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
            raise e