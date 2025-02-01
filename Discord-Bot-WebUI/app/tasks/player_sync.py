# app/tasks/player_sync.py

import logging
from celery import shared_task
from app.core import celery
from app.core.session_manager import managed_session
from app.models import Season, Player
from app.woocommerce import fetch_orders_from_woocommerce
from sqlalchemy import text
from app.players_helpers import (
    extract_player_info,
    match_player_weighted,
    create_user_for_player  # used later in confirmation
)
from app.order_helpers import (
    extract_jersey_size_from_product_name,
    determine_league
)
from app.player_management_helpers import (
    create_player_profile,
    record_order_history
)
from app.utils.sync_data_manager import save_sync_data

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def sync_players_with_woocommerce(self):
    """
    This task synchronizes player data from WooCommerce.
    It fetches orders page by page, processes them (identifying new players,
    updating existing ones, and flagging inactive players), and stores a sync
    package in Redis for later confirmation.
    """
    with celery.flask_app.app_context():
        try:
            # Use managed_session() instead of g.db_session or db.session directly.
            with managed_session() as session:
                # Stage 1: Fetch current season(s)
                self.update_state(state='PROGRESS', meta={
                    'stage': 'init',
                    'message': 'Fetching current season...',
                    'progress': 5
                })
                current_seasons = session.query(Season).filter_by(is_current=True).all()
                current_season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
                if not current_season:
                    raise Exception('No current Pub League season found.')

                # Prepare lists to store results
                new_players = []
                existing_players = set()
                player_league_updates = []
                total_orders_fetched = 0

                # Stage 2: Process orders page by page
                page = 1
                while True:
                    self.update_state(state='PROGRESS', meta={
                        'stage': 'woo',
                        'message': f'Fetching page {page}...',
                        'progress': 10
                    })
                    # Set a custom idle timeout for this transaction (affects only this transaction)
                    session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60000'"))
    
                    orders_page = fetch_orders_from_woocommerce(
                        current_season_name=current_season.name,
                        filter_current_season=True,
                        current_season_names=[s.name for s in current_seasons],
                        max_pages=1,  # Fetch one page at a time
                        page=page,
                        per_page=100
                    )
                    if not orders_page:
                        break

                    total_orders_fetched += len(orders_page)
                    for order in orders_page:
                        # Process each order (your existing logic)
                        player_info = extract_player_info(order['billing'])
                        if not player_info:
                            continue

                        product_name = order['product_name']
                        league = determine_league(product_name, current_seasons, session=session)
                        if not league:
                            continue

                        jersey_size = extract_jersey_size_from_product_name(product_name)
                        player_info['jersey_size'] = jersey_size

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
                    # Commit after processing each page
                    session.commit()
                    self.update_state(state='PROGRESS', meta={
                        'stage': 'process',
                        'message': f'Processed page {page}. Total orders so far: {total_orders_fetched}',
                        'progress': 10 + (page * 8)
                    })
                    page += 1

                # Stage 3: Identify inactive players
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

                # Save sync package to Redis for later confirmation
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
            # No need to call session.rollback() here because managed_session() handles it.
            logger.error(f"Error in sync_players_with_woocommerce: {e}", exc_info=True)
            raise e