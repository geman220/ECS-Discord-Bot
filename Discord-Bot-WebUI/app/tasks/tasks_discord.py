from app import db
from app.models import Player, Team, League
from app.extensions import db, socketio
from app.decorators import celery_task, async_task
from app.discord_utils import (
    get_expected_roles, 
    process_role_updates, 
    fetch_user_roles,
    process_single_player_update
)
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
import aiohttp
import asyncio
import logging
from web_config import Config
from app.utils.discord_request_handler import discord_client, optimized_discord_request

logger = logging.getLogger(__name__)

async def batch_process_discord_requests(tasks: List[Tuple[str, str, dict]], batch_size: int = 10) -> List[Dict]:
    """
    Process Discord API requests in batches using the optimized request handler.
    
    Args:
        tasks: List of tuples containing (method, url, params)
        batch_size: Number of concurrent requests to process
    """
    results = []
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_tasks = []
            
            for method, url, params in batch:
                batch_tasks.append(
                    optimized_discord_request(method, url, session, **params)
                )
            
            # Process batch with gather
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    results.append({'error': str(result)})
                else:
                    results.append(result)
                    
    return results

@async_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
async def fetch_role_status(self):
    """Fetch Discord role status for all players with optimized batch processing."""
    players = Player.query.filter(Player.discord_id.isnot(None))\
        .options(
            db.joinedload(Player.team),
            db.joinedload(Player.team).joinedload(Team.league)
        ).all()
    
    guild_id = Config.SERVER_ID
    tasks = []
    player_map = {}
    
    for player in players:
        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles"
        tasks.append(('GET', url, {}))
        player_map[player.discord_id] = player
    
    # Process all requests in optimized batches
    results = []
    role_results = await batch_process_discord_requests(tasks)
    
    async with aiohttp.ClientSession() as session:
        for player, role_result in zip(players, role_results):
            try:
                if role_result and not isinstance(role_result.get('error'), str):
                    current_roles = [role['name'] for role in role_result.get('roles', [])]
                    # Make sure to await the coroutine
                    expected_roles = await get_expected_roles(player, session)
                    
                    roles_match = set(current_roles) == set(expected_roles)
                    status_html = (
                        '<span class="badge bg-success">Synced</span>' if roles_match
                        else '<span class="badge bg-warning">Out of Sync</span>'
                    )
                    
                    player.discord_roles = current_roles
                    player.discord_last_verified = datetime.utcnow()
                    
                    results.append({
                        'id': player.id,
                        'name': player.name,
                        'discord_id': player.discord_id,
                        'team': player.team.name if player.team else 'No Team',
                        'league': player.team.league.name if player.team and player.team.league else 'No League',
                        'current_roles': current_roles,
                        'expected_roles': expected_roles,
                        'status_html': status_html,
                        'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    })
                else:
                    results.append({
                        'id': player.id,
                        'name': player.name,
                        'discord_id': player.discord_id,
                        'team': player.team.name if player.team else 'No Team',
                        'league': player.team.league.name if player.team and player.team.league else 'No League',
                        'current_roles': [],
                        'expected_roles': [],
                        'status_html': '<span class="badge bg-secondary">Not in Discord</span>',
                        'last_verified': 'Never'
                    })
            except Exception as e:
                logger.error(f"Error processing player {player.id}: {str(e)}")
                results.append({
                    'id': player.id,
                    'name': player.name,
                    'discord_id': player.discord_id,
                    'team': player.team.name if player.team else 'No Team',
                    'league': player.team.league.name if player.team and player.team.league else 'No League',
                    'current_roles': [],
                    'expected_roles': [],
                    'status_html': '<span class="badge bg-danger">Error</span>',
                    'last_verified': 'Never'
                })

    db.session.commit()
    socketio.emit('role_status_update', {'results': results})
    return results

@async_task(name='app.tasks.tasks_discord.update_player_discord_roles', queue='discord')
async def update_player_discord_roles(self, player_id: int):
    """Update Discord roles for a single player."""
    try:
        player = Player.query.get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return False

        async with aiohttp.ClientSession() as session:
            # Use optimized request handler for role operations
            current_roles = await fetch_user_roles(player.discord_id, session)
            expected_roles = get_expected_roles(player, session)
            
            # Process updates using optimized client
            await process_single_player_update(player)
            
            # Get final role state
            final_roles = await fetch_user_roles(player.discord_id, session)
            
            # Update database
            player.discord_roles = final_roles
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            
            roles_match = set(final_roles) == set(expected_roles)
            status_html = (
                '<span class="badge bg-success">Synced</span>' if roles_match
                else '<span class="badge bg-warning">Out of Sync</span>'
            )

            result = {
                'success': True,
                'player_data': {
                    'id': player.id,
                    'current_roles': final_roles,
                    'expected_roles': expected_roles,
                    'status_html': status_html,
                    'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                }
            }

            socketio.emit('role_update', result['player_data'])
            return result

    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise

@celery_task(name='app.tasks.tasks_discord.process_discord_role_updates', queue='discord')
def process_discord_role_updates(self):
    """Process Discord role updates for all marked players."""
    try:
        players = Player.query.filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
        ).all()

        if not players:
            logger.info("No players need Discord role updates")
            return True

        logger.info(f"Processing Discord role updates for {len(players)} players")
        process_role_updates(players)
        return True

    except Exception as e:
        logger.error(f"Error processing Discord role updates: {str(e)}")
        raise