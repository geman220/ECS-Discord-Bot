# app/tasks/tasks_discord.py

import logging
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from app.celery_utils import async_task_with_context
from app.decorators import celery_task, async_task, session_context, db_operation, query_operation
from app.models import Player, Team, League
from sqlalchemy.orm import joinedload
from app.extensions import db, socketio
from app.discord_utils import (
    get_expected_roles,
    process_role_updates,
    fetch_user_roles,
    process_single_player_update
)
from web_config import Config
from app.utils.discord_request_handler import optimized_discord_request
from flask import current_app

logger = logging.getLogger(__name__)

async def _update_player_discord_roles_async(task_self, player_id: int):
    """Async helper for update_player_discord_roles"""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_player_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).get(player_id)
                    if player:
                        return {
                            'id': player.id,
                            'discord_id': player.discord_id,
                            'name': player.name
                        }
                    return None

        player_data = await loop.run_in_executor(executor, get_player_sync)
        if not player_data:
            logger.error(f"Player {player_id} not found")
            return {'success': False, 'message': 'Player not found'}

        discord_id = player_data['discord_id']

        async with aiohttp.ClientSession() as aio_session:
            current_roles = await fetch_user_roles(discord_id, aio_session)
            expected_roles = await get_expected_roles(player_data, aio_session)
            await process_single_player_update(player_data)
            final_roles = await fetch_user_roles(discord_id, aio_session)

        roles_match = set(final_roles) == set(expected_roles)
        status_html = get_status_html(roles_match)

        def update_player_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).get(player_id)
                    if player:
                        player.discord_roles = final_roles
                        player.discord_last_verified = datetime.utcnow()
                        player.discord_needs_update = False
                        return player
                    return None

        updated_player = await loop.run_in_executor(executor, update_player_status_sync)
        if not updated_player:
            logger.error(f"Player {player_id} not found during status update")
            return {'success': False, 'message': 'Player not found during status update'}

        result = {
            'success': True,
            'player_data': {
                'id': updated_player.id,
                'current_roles': final_roles,
                'expected_roles': expected_roles,
                'status_html': status_html,
                'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
        }

        socketio.emit('role_update', result['player_data'])
        return result
    finally:
        executor.shutdown()

async def _fetch_role_status_async():
    """Async helper for fetch_role_status"""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_players_with_discord_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    players = db.session.query(Player).filter(Player.discord_id.isnot(None))\
                        .options(
                            joinedload(Player.team),
                            joinedload(Player.team).joinedload(Team.league)
                        ).all()
                    return [{
                        'id': player.id,
                        'discord_id': player.discord_id
                    } for player in players]

        player_data = await loop.run_in_executor(executor, get_players_with_discord_sync)
        guild_id = Config.SERVER_ID
        tasks = []
        results = []

        for player_info in player_data:
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player_info['discord_id']}/roles"
            tasks.append(('GET', url, {}))

        role_results = await batch_process_discord_requests(tasks)

        for player_info, role_result in zip(player_data, role_results):
            try:
                if isinstance(role_result, dict) and 'error' in role_result:
                    logger.error(f"Error from Discord API for player {player_info['id']}: {role_result['error']}")
                    results.append({
                        'error': role_result['error'],
                        'id': player_info['id']
                    })
                    continue

                result = await process_player_role_status(player_info['id'], role_result)
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing player {player_info['id']}: {str(e)}")
                def create_error_result_sync():
                    from app import create_app
                    app = create_app()
                    
                    with app.app_context():
                        with session_context():
                            player = db.session.query(Player).get(player_info['id'])
                            if player:
                                return create_error_result(player)
                            return {'error': 'Player not found', 'id': player_info['id']}

                error_result = await loop.run_in_executor(executor, create_error_result_sync)
                results.append(error_result)

        socketio.emit('role_status_update', {'results': results})
        return results
    finally:
        executor.shutdown()

@celery_task(
    name='app.tasks.tasks_discord.update_player_discord_roles',
    queue='discord',
    bind=True
)
def update_player_discord_roles(self, player_id: int):
    """Update Discord roles for a player."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_update_player_discord_roles_async(self, player_id))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

@celery_task(
    name='app.tasks.tasks_discord.process_discord_role_updates',
    queue='discord',
    bind=True
)
def process_discord_role_updates(self) -> bool:
    """Process Discord role updates for all marked players."""
    try:
        with session_context():
            @query_operation
            def get_players_needing_updates() -> List[Dict[str, Any]]:
                players = db.session.query(Player).filter(
                    (Player.discord_needs_update == True) |
                    (Player.discord_last_verified == None) |
                    (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
                ).all()

                return [{
                    'id': player.id,
                    'discord_id': player.discord_id
                } for player in players]

            player_data = get_players_needing_updates()

        if not player_data:
            logger.info("No players need Discord role updates")
            return True

        logger.info(f"Processing Discord role updates for {len(player_data)} players")

        # Process updates
        asyncio.run(process_role_updates([d['discord_id'] for d in player_data]))

        with session_context():
            batch_size = 100
            for i in range(0, len(player_data), batch_size):
                batch = player_data[i:i + batch_size]

                @db_operation
                def update_players_batch():
                    db.session.query(Player).filter(
                        Player.id.in_([p['id'] for p in batch])
                    ).update({
                        Player.discord_last_verified: datetime.utcnow(),
                        Player.discord_needs_update: False
                    }, synchronize_session=False)

                update_players_batch()
                db.session.flush()

        return True

    except Exception as e:
        logger.error(f"Error processing Discord role updates: {str(e)}", exc_info=True)
        return False

@celery_task(
    name='app.tasks.tasks_discord.assign_roles_to_player_task',
    queue='discord',
    bind=True,
    max_retries=3
)
def assign_roles_to_player_task(self, player_id: int) -> bool:
    """Assign Discord roles to a player."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_assign_roles_async(player_id))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error assigning roles to player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

@celery_task(
    name='app.tasks.tasks_discord.bulk_assign_roles_task',
    queue='discord',
    bind=True
)
def bulk_assign_roles_task(self, player_ids: List[int]) -> Dict[str, Any]:
    """Bulk assign Discord roles to multiple players."""
    try:
        results = {
            'total': len(player_ids),
            'successful': 0,
            'failed': 0,
            'failed_ids': []
        }

        for player_id in player_ids:
            try:
                assign_roles_to_player_task.delay(player_id)
                results['successful'] += 1
            except Exception as e:
                logger.error(f"Failed to queue role assignment for player {player_id}: {str(e)}")
                results['failed'] += 1
                results['failed_ids'].append(player_id)

        return {
            'success': True,
            'message': f"Queued role assignments for {results['successful']} players",
            'results': results
        }

    except Exception as e:
        logger.error(f"Error in bulk_assign_roles_task: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': str(e)
        }

@celery_task(
    name='app.tasks.tasks_discord.remove_player_roles_task',
    queue='discord',
    bind=True,
    max_retries=3
)
def remove_player_roles_task(self, player_id: int) -> bool:
    """Remove Discord roles from a player."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_remove_player_roles_async(player_id))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error removing roles from player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e)

# Helper functions
def get_status_html(roles_match: bool) -> str:
    """Generate status HTML based on role match status."""
    return (
        '<span class="badge bg-success">Synced</span>' if roles_match
        else '<span class="badge bg-warning">Out of Sync</span>'
    )

def create_error_result(player: Player) -> Dict[str, Any]:
    """Create a result dictionary for a player with an error."""
    return {
        'id': player.id,
        'name': player.name,
        'discord_id': player.discord_id,
        'team': player.team.name if player.team else 'No Team',
        'league': player.team.league.name if player.team and player.team.league else 'No League',
        'current_roles': [],
        'expected_roles': [],
        'status_html': '<span class="badge bg-danger">Error</span>',
        'last_verified': 'Never'
    }

async def _assign_roles_async(player_id: int) -> bool:
    """Async helper for assign_roles_to_player_task"""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_player_data_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).options(
                        joinedload(Player.team),
                        joinedload(Player.team).joinedload(Team.league)
                    ).get(player_id)
                    
                    if not player:
                        return None
                        
                    return {
                        'id': player.id,
                        'discord_id': player.discord_id,
                        'name': player.name,
                        'team': {
                            'name': player.team.name if player.team else None,
                            'division': player.team.division if player.team else None
                        },
                        'league': {
                            'name': player.team.league.name if player.team and player.team.league else None
                        }
                    }

        player_data = await loop.run_in_executor(executor, get_player_data_sync)
        if not player_data:
            logger.error(f"Player {player_id} not found")
            return False

        # Process the role update
        await process_single_player_update(player_data)

        def update_player_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).get(player_id)
                    if player:
                        player.discord_roles_updated = datetime.utcnow()
                        player.discord_role_sync_status = 'completed'

        await loop.run_in_executor(executor, update_player_status_sync)
        logger.info(f"Successfully assigned roles to player {player_id}")
        return True

    except Exception as e:
        logger.error(f"Error in _assign_roles_async for player {player_id}: {str(e)}", exc_info=True)
        
        def mark_sync_failed_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).get(player_id)
                    if player:
                        player.discord_role_sync_status = 'failed'
                        player.discord_role_sync_error = str(e)

        await loop.run_in_executor(executor, mark_sync_failed_sync)
        raise
    finally:
        executor.shutdown()

def get_player_data_sync(player_id) -> Optional[Dict[str, Any]]:
    """Synchronous function for database access."""
    from app import create_app
    app = create_app()
    
    with app.app_context():
        with session_context():
            player = db.session.query(Player).options(
                joinedload(Player.team),
                joinedload(Player.team).joinedload(Team.league)
            ).get(player_id)
            if not player:
                return None
            return {
                'id': player.id,
                'name': player.name,
                'discord_id': player.discord_id,
                'team_data': {
                    'id': player.team.id if player.team else None,
                    'name': player.team.name if player.team else None
                }
            }

async def _remove_player_roles_async(player_id):
    """Async helper for remove_player_roles_task"""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_player_roles_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).options(
                        joinedload(Player.team),
                        joinedload(Player.team).joinedload(Team.league)
                    ).get(player_id)
                    if not player:
                        return None
                    return {
                        'id': player.id,
                        'discord_id': player.discord_id,
                        'roles': player.discord_roles or []
                    }

        player_data = await loop.run_in_executor(executor, get_player_roles_sync)
        if not player_data:
            logger.error(f"Player {player_id} not found")
            return False

        # Process role removal
        await process_role_updates([player_data])

        def update_player_status_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    player = db.session.query(Player).get(player_id)
                    if player:
                        player.discord_roles = []
                        player.discord_last_verified = datetime.utcnow()

        await loop.run_in_executor(executor, update_player_status_sync)
        logger.info(f"Successfully removed roles from player {player_id}")
        return True

    except Exception as e:
        logger.error(f"Error removing roles from player {player_id}: {str(e)}")
        return False
    finally:
        executor.shutdown()

async def _fetch_role_status_async():
    """Async helper for fetch_role_status"""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_players_with_discord_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with session_context():
                    players = db.session.query(Player).filter(Player.discord_id.isnot(None))\
                        .options(
                            joinedload(Player.team),
                            joinedload(Player.team).joinedload(Team.league)
                        ).all()
                    return [{
                        'id': player.id,
                        'discord_id': player.discord_id
                    } for player in players]

        player_data = await loop.run_in_executor(executor, get_players_with_discord_sync)
        guild_id = Config.SERVER_ID
        tasks = []
        results = []

        for player_info in player_data:
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player_info['discord_id']}/roles"
            tasks.append(('GET', url, {}))

        role_results = await batch_process_discord_requests(tasks)

        for player_info, role_result in zip(player_data, role_results):
            try:
                if isinstance(role_result, dict) and 'error' in role_result:
                    logger.error(f"Error from Discord API for player {player_info['id']}: {role_result['error']}")
                    results.append({
                        'error': role_result['error'],
                        'id': player_info['id']
                    })
                    continue

                result = await process_player_role_status(player_info['id'], role_result)
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing player {player_info['id']}: {str(e)}")
                def create_error_result_sync():
                    from app import create_app
                    app = create_app()
                    
                    with app.app_context():
                        with session_context():
                            player = db.session.query(Player).get(player_info['id'])
                            if player:
                                return create_error_result(player)
                            return {'error': 'Player not found', 'id': player_info['id']}

                error_result = await loop.run_in_executor(executor, create_error_result_sync)
                results.append(error_result)

        socketio.emit('role_status_update', {'results': results})
        return results
    finally:
        executor.shutdown()

@celery_task(
    name='app.tasks.tasks_discord.fetch_role_status', 
    queue='discord',
    bind=True,
    max_retries=3
)
def fetch_role_status(self) -> List[Dict[str, Any]]:
    """Fetch and verify Discord role status for all players."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_fetch_role_status_async())
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e)