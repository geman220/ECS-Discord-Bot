import logging
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from flask import current_app
from app.core import socketio, celery
from app.decorators import celery_task
from app.models import Player, Team
from app.discord_utils import (
    get_expected_roles,
    process_role_updates,
    fetch_user_roles,
    process_single_player_update,
    remove_role_from_member,
    get_or_create_role
)
from web_config import Config
from app.utils.discord_request_handler import optimized_discord_request, make_discord_request

logger = logging.getLogger(__name__)


def get_status_html(roles_match: bool) -> str:
    """Generate status HTML based on role match status."""
    return (
        '<span class="badge bg-success">Synced</span>' if roles_match
        else '<span class="badge bg-warning">Out of Sync</span>'
    )

def create_error_result(player_info: Dict[str, Any]) -> Dict[str, Any]:
    """Create a result dictionary for a player with an error."""
    return {
        'id': player_info['id'],
        'name': player_info['name'],
        'team': player_info.get('team', 'No Team'),
        'league': player_info.get('league', 'No League'),
        'current_roles': [],
        'expected_roles': [],
        'status_html': '<span class="badge bg-danger">Error</span>',
        'last_verified': 'Never',
        'error': True
    }

@celery_task(
    name='app.tasks.tasks_discord.update_player_discord_roles',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def update_player_discord_roles(self, session, player_id: int) -> Dict[str, Any]:
    """Update Discord roles for a player."""
    try:
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return {'success': False, 'message': 'Player not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_update_player_discord_roles_async(session, player.id))
            player.discord_roles = result['player_data']['current_roles']
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            player.last_sync_attempt = datetime.utcnow()
            player.sync_status = 'success' if result['player_data']['roles_match'] else 'mismatch'
            session.flush()

            socketio.emit('role_update', result['player_data'])
            return result
        finally:
            loop.close()

    except SQLAlchemyError as e:
        logger.error(f"Database error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _update_player_discord_roles_async(session, player_id: int) -> Dict[str, Any]:
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.error(f"No Discord ID or player not found for player_id {player_id}")
        return {'success': False, 'message': 'No Discord ID associated with player'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
            expected_roles = await get_expected_roles(session, player)
            await process_single_player_update(session, player)
            final_roles = await fetch_user_roles(session, player.discord_id, aio_session)

        roles_match = set(final_roles) == set(expected_roles)
        status_html = get_status_html(roles_match)

        result = {
            'success': True,
            'player_data': {
                'id': player.id,
                'current_roles': final_roles,
                'expected_roles': expected_roles,
                'status_html': status_html,
                'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'roles_match': roles_match
            }
        }

        logger.info(f"Successfully updated Discord roles for player {player.id}", extra={
            'roles_match': roles_match,
            'current_roles': final_roles,
            'expected_roles': expected_roles
        })
        return result

    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        return {'success': False, 'message': 'Discord API error', 'error': str(e)}

@celery_task(
    name='app.tasks.tasks_discord.process_discord_role_updates',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def process_discord_role_updates(self, session) -> Dict[str, Any]:
    """Process Discord role updates for all marked players."""
    try:
        players = session.query(Player).filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified.is_(None)) |
            (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
        ).options(
            joinedload(Player.team),
            joinedload(Player.team).joinedload(Team.league)
        ).all()

        player_data = [{
            'id': p.id,
            'discord_id': p.discord_id,
            'name': p.name
        } for p in players if p.discord_id]

        if not player_data:
            logger.info("No players need Discord role updates")
            return {
                'success': True,
                'message': 'No updates needed',
                'processed_count': 0
            }

        logger.info(f"Processing Discord role updates for {len(player_data)} players")

        discord_ids = [p['discord_id'] for p in player_data]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(_mass_process_role_updates(session, discord_ids))
        finally:
            loop.close()

        processed_count = len([r for r in results if r.get('success')])
        error_count = len([r for r in results if not r.get('success')])

        for p_info in player_data:
            player = session.query(Player).get(p_info['id'])
            if player:
                player.discord_last_verified = datetime.utcnow()
                player.discord_needs_update = False
                player.last_sync_attempt = datetime.utcnow()
                res = next((r for r in results if r.get('player_id') == p_info['id']), None)
                if res and res.get('success'):
                    player.sync_status = 'success'
                else:
                    player.sync_status = 'error'
                    if res and res.get('error'):
                        player.sync_error = res['error']

        session.flush()

        final_results = {
            'success': True,
            'message': f'Processed {processed_count} players with {error_count} errors',
            'processed_count': processed_count,
            'error_count': error_count,
            'total_players': len(player_data),
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        }

        socketio.emit('role_updates_complete', final_results)
        logger.info("Role updates completed", extra=final_results)

        return final_results

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_discord_role_updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in process_discord_role_updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

async def _mass_process_role_updates(session, discord_ids: List[str]) -> List[Dict[str, Any]]:
    results = []
    for discord_id in discord_ids:
        player = session.query(Player).filter_by(discord_id=discord_id).first()
        if not player:
            results.append({
                'player_id': None,
                'success': False,
                'error': 'Player not found for discord_id'
            })
            continue
        try:
            await update_player_roles(session, player, force_update=False)
            results.append({
                'player_id': player.id,
                'success': True
            })
        except Exception as e:
            results.append({
                'player_id': player.id,
                'success': False,
                'error': str(e)
            })
    return results

@celery_task(
    name='app.tasks.tasks_discord.assign_roles_to_player_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def assign_roles_to_player_task(self, session, player_id: int) -> Dict[str, Any]:
    """Assign Discord roles to a player."""
    try:
        player = session.query(Player).options(
            joinedload(Player.team),
            joinedload(Player.team).joinedload(Team.league)
        ).get(player_id)
        if not player:
            return {'success': False, 'message': 'Player not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_assign_roles_async(session, player.id))
        finally:
            loop.close()

        player.discord_roles_updated = datetime.utcnow()
        player.discord_role_sync_status = 'completed' if result.get('success') else 'failed'
        player.last_sync_attempt = datetime.utcnow()
        if not result.get('success'):
            player.sync_error = result.get('error')
        session.flush()

        return {
            'success': True,
            'message': 'Roles assigned successfully',
            'player_id': player_id,
            'timestamp': datetime.utcnow().isoformat(),
            **result
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error assigning roles to player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error assigning roles to player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _assign_roles_async(session, player_id: int) -> Dict[str, Any]:
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.error(f"No Discord ID for player {player_id}")
        return {
            'success': False,
            'message': 'No Discord ID associated with player',
            'error_type': 'no_discord_id'
        }

    try:
        result = await process_single_player_update(session, player)
    except Exception as e:
        logger.error(f"Exception in process_single_player_update for player {player_id}: {e}", exc_info=True)
        return {'success': False, 'message': 'Exception occurred', 'error': str(e)}

    if not result or not isinstance(result, dict):
        logger.error(f"process_single_player_update returned a non-dict or None for player {player_id}.")
        return {'success': False, 'message': 'Invalid return from process_single_player_update'}

    if result.get('success'):
        logger.info(f"Successfully assigned roles to player {player_id}")
    else:
        logger.error(f"Failed to assign roles to player {player_id}: {result.get('error', 'Unknown error')}")

    return result

@celery_task(
    name='app.tasks.tasks_discord.fetch_role_status',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def fetch_role_status(self, session) -> Dict[str, Any]:
    """Fetch and verify Discord role status for all players."""
    try:
        players = session.query(Player).filter(Player.discord_id.isnot(None))\
            .options(joinedload(Player.team), joinedload(Player.team).joinedload(Team.league)).all()

        player_data = [{
            'id': p.id,
            'discord_id': p.discord_id,
            'name': p.name,
            'team': p.team.name if p.team else None,
            'league': p.team.league.name if p.team and p.team.league else None
        } for p in players]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(_fetch_role_status_async(session, player_data))
        finally:
            loop.close()

        return {
            'success': True,
            'message': 'Role status fetch completed',
            'results': results,
            'fetched_at': datetime.utcnow().isoformat()
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _fetch_role_status_async(session, player_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    guild_id = Config.SERVER_ID
    tasks = []
    for p in player_data:
        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{p['discord_id']}/roles"
        tasks.append(('GET', url, {}))

    try:
        role_results = await optimized_discord_request(tasks)
    except aiohttp.ClientError as e:
        logger.error("Discord API error fetching roles", exc_info=True)
        role_results = [{'error': str(e)} for _ in tasks]

    results = []
    status_updates = []
    for p_info, role_result in zip(player_data, role_results):
        try:
            player = session.query(Player).get(p_info['id'])
            if isinstance(role_result, dict) and 'error' in role_result:
                logger.error(f"Error from Discord API for player {p_info['id']}: {role_result['error']}")
                status_updates.append({
                    'id': p_info['id'],
                    'status': 'error',
                    'error': role_result['error']
                })
                results.append(create_error_result(p_info))
                continue

            current_roles = role_result.get('roles', [])
            if player:
                expected_roles = await get_expected_roles(session, player)
            else:
                expected_roles = []

            roles_match = set(current_roles) == set(expected_roles)
            status_html = get_status_html(roles_match)
            status_updates.append({
                'id': p_info['id'],
                'status': 'synced' if roles_match else 'mismatch',
                'current_roles': current_roles
            })

            results.append({
                'id': p_info['id'],
                'name': p_info['name'],
                'team': p_info['team'],
                'league': p_info['league'],
                'current_roles': current_roles,
                'expected_roles': expected_roles,
                'status_html': status_html,
                'last_verified': datetime.utcnow().isoformat()
            })

        except Exception as e:
            logger.error(f"Error processing player {p_info['id']}: {str(e)}")
            status_updates.append({
                'id': p_info['id'],
                'status': 'error',
                'error': str(e)
            })
            results.append(create_error_result(p_info))

    for update in status_updates:
        player = session.query(Player).get(update['id'])
        if player:
            player.discord_role_sync_status = update['status']
            player.last_role_check = datetime.utcnow()
            if 'current_roles' in update:
                player.discord_roles = update['current_roles']
            if 'error' in update:
                player.sync_error = update['error']
    session.flush()

    socketio.emit('role_status_update', {
        'results': results,
        'timestamp': datetime.utcnow().isoformat()
    })

    status_counts = {
        'total': len(results),
        'synced': sum(1 for r in status_updates if r['status'] == 'synced'),
        'mismatch': sum(1 for r in status_updates if r['status'] == 'mismatch'),
        'error': sum(1 for r in status_updates if r['status'] == 'error')
    }

    logger.info("Role status check completed", extra={
        'stats': status_counts,
        'timestamp': datetime.utcnow().isoformat()
    })

    return results

@celery_task(
    name='app.tasks.tasks_discord.remove_player_roles_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def remove_player_roles_task(self, session, player_id: int) -> Dict[str, Any]:
    """Remove Discord roles from a player."""
    try:
        player = session.query(Player).options(
            joinedload(Player.team),
            joinedload(Player.team).joinedload(Team.league)
        ).get(player_id)
        if not player:
            return {'success': False, 'message': 'Player not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_remove_player_roles_async(session, player.id))
        finally:
            loop.close()

        if result.get('success'):
            player.discord_roles = []
            player.discord_last_verified = datetime.utcnow()
            player.last_role_removal = datetime.utcnow()
            player.role_removal_status = 'completed'
        else:
            player.role_removal_status = 'failed'
            player.last_role_removal = datetime.utcnow()
            if 'error' in result:
                player.role_removal_error = result['error']
        session.flush()

        return {
            'success': True,
            'message': 'Roles removed successfully',
            'player_id': player_id,
            'processed_at': datetime.utcnow().isoformat(),
            **result
        }

    except SQLAlchemyError as e:
        logger.error(f"Database error removing roles from player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error removing roles from player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _remove_player_roles_async(session, player_id: int) -> Dict[str, Any]:
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.error(f"No Discord ID or player not found for player_id {player_id}")
        return {
            'success': False,
            'message': 'No Discord ID associated with player',
            'error_type': 'no_discord_id'
        }

    async with aiohttp.ClientSession() as aio_session:
        current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
        expected_roles = []  # removing all roles
        roles_to_remove = set(current_roles) - set(expected_roles)
        guild_id = int(Config.SERVER_ID)

        for role_name in roles_to_remove:
            role_id = await get_or_create_role(guild_id, role_name, aio_session)
            if not role_id:
                logger.warning(f"No valid role ID found for role '{role_name}'. Skipping removal.")
                continue
            await remove_role_from_member(guild_id, player.discord_id, role_id, aio_session)

    logger.info(f"Successfully removed all roles from player {player.name} (ID: {player_id})")
    return {
        'success': True,
        'message': f"Roles removed successfully from {player.name}",
        'removed_roles': current_roles
    }