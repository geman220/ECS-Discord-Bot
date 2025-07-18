# app/tasks/player_sync.py

from celery import shared_task
from sqlalchemy import text
from app.utils.pgbouncer_utils import set_session_timeout

from app.players_helpers import extract_player_info, match_player_weighted
from app.order_helpers import extract_jersey_size_from_product_name, determine_league
from app.utils.sync_data_manager import save_sync_data
from app.core import celery
from app.core.session_manager import managed_session
from app.models import Season, Player
from app.woocommerce import fetch_orders_from_woocommerce

import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True)
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

                    # Check if the player already exists in the system using weighted matching
                    existing_player = match_player_weighted(player_info, session)
                    if existing_player:
                        existing_players.add(existing_player.id)
                        player_league_updates.append({
                            'player_id': existing_player.id,
                            'league_id': league.id,
                            'order_id': order['order_id'],
                            'quantity': order['quantity']
                        })
                    else:
                        new_players.append({
                            'info': player_info,
                            'league_id': league.id,
                            'order_id': order['order_id'],
                            'quantity': order['quantity']
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

                # Prepare sync data and save it for later confirmation
                sync_data = {
                    'new_players': new_players,
                    'player_league_updates': player_league_updates,
                    'potential_inactive': potential_inactive
                }
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
                    'potential_inactive': len(potential_inactive)
                }

        except Exception as e:
            logger.error(f"Error in sync_players_with_woocommerce: {e}", exc_info=True)
            raise e