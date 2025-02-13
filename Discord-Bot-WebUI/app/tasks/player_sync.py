# app/tasks/player_sync.py

from celery import shared_task
from sqlalchemy import text

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

                # Initialize tracking variables
                new_players = []
                existing_players = set()
                player_league_updates = []
                total_orders_fetched = 0

                page = 1
                # Process orders page by page until no more orders are returned
                while True:
                    self.update_state(state='PROGRESS', meta={
                        'stage': 'woo',
                        'message': f'Fetching page {page}...',
                        'progress': 10
                    })

                    # Set a high idle timeout to prevent transaction timeouts during order processing
                    session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60000'"))
    
                    orders_page = fetch_orders_from_woocommerce(
                        current_season_name=current_season.name,
                        filter_current_season=True,
                        current_season_names=[s.name for s in current_seasons],
                        max_pages=1,
                        page=page,
                        per_page=100
                    )
                    if not orders_page:
                        break

                    total_orders_fetched += len(orders_page)
                    for order in orders_page:
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
                    session.commit()

                    # Update progress state after processing each page
                    self.update_state(state='PROGRESS', meta={
                        'stage': 'process',
                        'message': f'Processed page {page}. Total orders so far: {total_orders_fetched}',
                        'progress': 10 + (page * 8)
                    })
                    page += 1

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

                session.commit()
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