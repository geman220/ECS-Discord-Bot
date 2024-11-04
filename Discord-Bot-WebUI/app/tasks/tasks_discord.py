from app import db
from app.models import Player, Team, League
from app.extensions import db, socketio
from app.decorators import celery_task, async_task, session_context, db_operation, query_operation
from app.discord_utils import (
    get_expected_roles, 
    process_role_updates, 
    fetch_user_roles,
    process_single_player_update
)
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
import aiohttp
import asyncio
import logging
from web_config import Config
from app.utils.discord_request_handler import discord_client, optimized_discord_request

logger = logging.getLogger(__name__)

async def batch_process_discord_requests(tasks: List[Tuple[str, str, dict]], batch_size: int = 10) -> List[Dict]:
    """Process Discord API requests in batches using the optimized request handler."""
    results = []
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_tasks = []
            
            for method, url, params in batch:
                batch_tasks.append(
                    optimized_discord_request(method, url, session, **params)
                )
            
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            results.extend([
                {'error': str(result)} if isinstance(result, Exception) else result
                for result in batch_results
            ])
                    
    return results

@async_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
async def fetch_role_status(self) -> List[Dict[str, Any]]:
    """Fetch Discord role status for all players with optimized batch processing."""
    try:
        @query_operation
        def get_players_with_discord():
            return Player.query.filter(Player.discord_id.isnot(None))\
                .options(
                    db.joinedload(Player.team),
                    db.joinedload(Player.team).joinedload(Team.league)
                ).all()

        players = get_players_with_discord()
        guild_id = Config.SERVER_ID
        tasks = []
        results = []

        # Prepare API requests
        for player in players:
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles"
            tasks.append(('GET', url, {}))

        # Process all requests in optimized batches
        role_results = await batch_process_discord_requests(tasks)

        async with aiohttp.ClientSession() as session:
            for player, role_result in zip(players, role_results):
                try:
                    result = await process_player_role_status(player, role_result, session)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error processing player {player.id}: {str(e)}")
                    results.append(create_error_result(player))

        socketio.emit('role_status_update', {'results': results})
        return results

    except Exception as e:
        logger.error(f"Error in fetch_role_status: {str(e)}", exc_info=True)
        return []

async def process_player_role_status(player: Player, role_result: Dict, session: aiohttp.ClientSession) -> Dict[str, Any]:
    """Process role status for a single player."""
    if role_result and not isinstance(role_result.get('error'), str):
        current_roles = [role['name'] for role in role_result.get('roles', [])]
        expected_roles = await get_expected_roles(player, session)
        roles_match = set(current_roles) == set(expected_roles)
        status_html = get_status_html(roles_match)

        @db_operation
        def update_player_role_info(player_id: int, current_roles: List[str]) -> None:
            player = Player.query.get(player_id)
            if player:
                player.discord_roles = current_roles
                player.discord_last_verified = datetime.utcnow()

        update_player_role_info(player.id, current_roles)

        return create_result_dict(
            player, current_roles, expected_roles,
            status_html, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        )
    else:
        return create_not_in_discord_result(player)

@async_task(name='app.tasks.tasks_discord.update_player_discord_roles', queue='discord')
async def update_player_discord_roles(self, player_id: int) -> Dict[str, Any]:
    """Update Discord roles for a single player."""
    try:
        @query_operation
        def get_player() -> Optional[Player]:
            return Player.query.get(player_id)

        player = get_player()
        if not player:
            logger.error(f"Player {player_id} not found")
            return {'success': False, 'message': 'Player not found'}

        async with aiohttp.ClientSession() as session:
            current_roles = await fetch_user_roles(player.discord_id, session)
            expected_roles = await get_expected_roles(player, session)
            
            await process_single_player_update(player)
            final_roles = await fetch_user_roles(player.discord_id, session)

            @db_operation
            def update_player_status():
                player = Player.query.get(player_id)
                if player:
                    player.discord_roles = final_roles
                    player.discord_last_verified = datetime.utcnow()
                    player.discord_needs_update = False
                return player

            updated_player = update_player_status()
            
            roles_match = set(final_roles) == set(expected_roles)
            status_html = get_status_html(roles_match)

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
        return {'success': False, 'message': str(e)}

@celery_task(name='app.tasks.tasks_discord.process_discord_role_updates', queue='discord')
def process_discord_role_updates(self) -> bool:
    """Process Discord role updates for all marked players."""
    try:
        @query_operation
        def get_players_needing_updates() -> List[Player]:
            return Player.query.filter(
                (Player.discord_needs_update == True) |
                (Player.discord_last_verified == None) |
                (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
            ).all()

        players = get_players_needing_updates()

        if not players:
            logger.info("No players need Discord role updates")
            return True

        logger.info(f"Processing Discord role updates for {len(players)} players")
        process_role_updates(players)

        @db_operation
        def update_players_status(player_ids: List[int]) -> None:
            Player.query.filter(Player.id.in_(player_ids)).update({
                Player.discord_last_verified: datetime.utcnow(),
                Player.discord_needs_update: False
            }, synchronize_session=False)

        update_players_status([p.id for p in players])
        return True

    except Exception as e:
        logger.error(f"Error processing Discord role updates: {str(e)}")
        return False

# Helper functions
def get_status_html(roles_match: bool) -> str:
    """Generate status HTML based on role match status."""
    return (
        '<span class="badge bg-success">Synced</span>' if roles_match
        else '<span class="badge bg-warning">Out of Sync</span>'
    )

def create_result_dict(
    player: Player,
    current_roles: List[str],
    expected_roles: List[str],
    status_html: str,
    last_verified: str
) -> Dict[str, Any]:
    """Create a standardized result dictionary for a player."""
    return {
        'id': player.id,
        'name': player.name,
        'discord_id': player.discord_id,
        'team': player.team.name if player.team else 'No Team',
        'league': player.team.league.name if player.team and player.team.league else 'No League',
        'current_roles': current_roles,
        'expected_roles': expected_roles,
        'status_html': status_html,
        'last_verified': last_verified
    }

def create_not_in_discord_result(player: Player) -> Dict[str, Any]:
    """Create a result dictionary for a player not in Discord."""
    return create_result_dict(
        player=player,
        current_roles=[],
        expected_roles=[],
        status_html='<span class="badge bg-secondary">Not in Discord</span>',
        last_verified='Never'
    )

def create_error_result(player: Player) -> Dict[str, Any]:
    """Create a result dictionary for a player with an error."""
    return create_result_dict(
        player=player,
        current_roles=[],
        expected_roles=[],
        status_html='<span class="badge bg-danger">Error</span>',
        last_verified='Never'
    )