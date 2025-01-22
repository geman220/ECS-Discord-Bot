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
    update_player_roles,
    rename_team_roles,
    create_discord_channel,
    delete_team_channel,
    delete_team_roles,
    get_expected_roles,
    process_role_updates,
    fetch_user_roles,
    process_single_player_update,
    remove_role_from_member,
    get_or_create_role,
    normalize_name,
    get_role_id,
    get_role_names
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
    try:
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return {'success': False, 'message': 'Player not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                update_player_roles(session, player, force_update=False)
            )
            
            # Update player info
            player.discord_roles = result.get('current_roles', [])
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            player.last_sync_attempt = datetime.utcnow()
            player.sync_status = 'success' if result.get('success') else 'mismatch'

            # Socket notification after DB updates
            socketio.emit('role_update', result)
            return result
        finally:
            loop.close()

    except SQLAlchemyError as e:
        logger.error(f"Database error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

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
    queue='discord'
)
def process_discord_role_updates(self, session, discord_ids: List[str]) -> Dict[str, Any]:
    """Process Discord role updates for multiple players."""
    try:
        # Get players needing updates
        players = session.query(Player).filter(
            Player.discord_id.in_(discord_ids)
        ).options(
            joinedload(Player.team),
            joinedload(Player.team).joinedload(Team.league)
        ).all()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                _process_role_updates_batch(session, players)
            )
        finally:
            loop.close()

        # Update player statuses
        for player in players:
            result = next((r for r in results if r.get('player_id') == player.id), None)
            if result:
                player.discord_last_verified = datetime.utcnow()
                player.discord_needs_update = False
                player.last_sync_attempt = datetime.utcnow()
                player.sync_status = 'success' if result.get('success') else 'error'
                if not result.get('success'):
                    player.sync_error = result.get('error')

        return {
            'success': True,
            'processed_count': len([r for r in results if r.get('success')]),
            'error_count': len([r for r in results if not r.get('success')]),
            'results': results
        }

    except Exception as e:
        logger.error(f"Error processing role updates: {str(e)}", exc_info=True)
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

@celery_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
def fetch_role_status(self, session) -> Dict[str, Any]:
    try:
        players = session.query(Player).filter(
            Player.discord_id.isnot(None)
        ).options(
            joinedload(Player.team),
            joinedload(Player.team).joinedload(Team.league)
        ).all()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                _fetch_roles_batch(session, players)
            )

            # Update player statuses in bulk
            for status in results['status_updates']:
                player = session.query(Player).get(status['id'])
                if player:
                    player.discord_role_sync_status = status['status']
                    player.last_role_check = datetime.utcnow()
                    if 'current_roles' in status:
                        player.discord_roles = status['current_roles']
                    if 'error' in status:
                        player.sync_error = status['error']

            socketio.emit('role_status_update', {
                'results': results['role_results'],
                'timestamp': datetime.utcnow().isoformat()
            })

            return {
                'success': True,
                'results': results['role_results'],
                'fetched_at': datetime.utcnow().isoformat()
            }
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error in fetch_role_status: {str(e)}")
        raise self.retry(exc=e, countdown=30)

def process_role_results(session, players: List[Player], role_results: List[Dict]) -> Dict[str, Any]:
    """Process role results from Discord API."""
    status_updates = []
    role_results = []

    for player, result in zip(players, role_results):
        try:
            if isinstance(result, dict) and 'error' in result:
                status_updates.append({
                    'id': player.id,
                    'status': 'error',
                    'error': result['error']
                })
                role_results.append(create_error_result(player))
                continue

            current_roles = result.get('roles', [])
            if player:
                expected_roles = []  # Get synchronously since we're in a sync function
                roles_match = set(current_roles) == set(expected_roles)
                status_updates.append({
                    'id': player.id,
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': current_roles
                })
                role_results.append({
                    'id': player.id,
                    'name': player.name,
                    'team': player.team.name if player.team else None,
                    'league': player.team.league.name if player.team and player.team.league else None,
                    'current_roles': current_roles,
                    'expected_roles': expected_roles,
                    'status_html': get_status_html(roles_match),
                    'last_verified': datetime.utcnow().isoformat()
                })

        except Exception as e:
            logger.error(f"Error processing player {player.id}: {str(e)}")
            status_updates.append({
                'id': player.id,
                'status': 'error',
                'error': str(e)
            })
            role_results.append(create_error_result(player))

    return {
        'status_updates': status_updates,
        'role_results': role_results
    }

async def _fetch_roles_batch(session, players: List[Player]) -> Dict[str, Any]:
    guild_id = Config.SERVER_ID
    status_updates = []
    role_results = []

    async with aiohttp.ClientSession() as aio_session:
        for player in players:
            try:
                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                expected_roles = await get_expected_roles(session, player)

                roles_match = set(current_roles) == set(expected_roles)
                status_html = get_status_html(roles_match)

                status_updates.append({
                    'id': player.id,
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': current_roles
                })

                role_results.append({
                    'id': player.id,
                    'name': player.name,
                    'team': player.team.name if player.team else None,
                    'league': player.team.league.name if player.team and player.team.league else None,
                    'current_roles': current_roles,
                    'expected_roles': expected_roles,
                    'status_html': status_html,
                    'last_verified': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error fetching roles for player {player.id}: {str(e)}")
                status_updates.append({
                    'id': player.id,
                    'status': 'error',
                    'error': str(e)
                })
                role_results.append(create_error_result({
                    'id': player.id,
                    'name': player.name,
                    'team': player.team.name if player.team else None,
                    'league': player.team.league.name if player.team and player.team.league else None
                }))

    return {
        'status_updates': status_updates,
        'role_results': role_results
    }

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
        return {'success': False, 'message': 'No Discord ID associated with player', 'error_type': 'no_discord_id'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            guild_id = int(Config.SERVER_ID)
            
            # First get all roles using the endpoint that works
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles"
            member_roles = await make_discord_request('GET', url, aio_session)
            
            if not member_roles:
                return {'success': True, 'message': f"No roles found for {player.name}"}

            # Find team-specific player roles
            roles_to_remove = []
            for role in member_roles.get('roles', []):
                if isinstance(role, str) and 'ECS-FC-PL-' in role and role.endswith('-PLAYER'):
                    roles_to_remove.append(role)

            # Remove team roles
            for role in roles_to_remove:
                await remove_role_from_member(guild_id, player.discord_id, role, aio_session)
                logger.info(f"Removed role '{role}' from player '{player.name}'")

            return {
                'success': True,
                'message': f"Team roles removed successfully from {player.name}",
                'removed_roles': roles_to_remove
            }

    except Exception as e:
        logger.error(f"Error removing roles: {str(e)}", exc_info=True)
        return {'success': False, 'message': f"Error removing roles: {str(e)}", 'error': str(e)}

@celery_task(name='app.tasks.tasks_discord.create_team_discord_resources_task', queue='discord')
def create_team_discord_resources_task(self, session, team_id: int):
    """Create Discord resources for a new team."""
    try:
        team = session.query(Team).options(
            joinedload(Team.league)
        ).get(team_id)
        
        if not team:
            logger.error(f"Team {team_id} not found")
            return {'success': False, 'message': 'Team not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Execute Discord channel creation
            channel_result = loop.run_until_complete(
                create_discord_channel(session, team.name, team.league.name, team.id)
            )
            
            # Set channel ID if successful
            if channel_result and channel_result.get('channel_id'):
                team.discord_channel_id = channel_result['channel_id']
            
            return {'success': True, 'message': 'Discord resources created'}
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error creating Discord resources: {str(e)}")
        raise self.retry(exc=e, countdown=30)

async def delete_channel(channel_id: str) -> bool:
    url = f"{Config.BOT_API_URL}/guilds/{Config.SERVER_ID}/channels/{channel_id}"
    async with aiohttp.ClientSession() as client:
        async with client.delete(url) as response:
            success = response.status == 200
            if success:
                logger.info(f"Deleted channel ID {channel_id}")
            return success

async def delete_role(role_id: str) -> bool:
    url = f"{Config.BOT_API_URL}/guilds/{Config.SERVER_ID}/roles/{role_id}"
    async with aiohttp.ClientSession() as client:
        async with client.delete(url) as response:
            success = response.status == 200
            if success:
                logger.info(f"Deleted role ID {role_id}")
            return success

@celery_task(name='app.tasks.tasks_discord.cleanup_team_discord_resources_task', queue='discord')
def cleanup_team_discord_resources_task(self, session, team_id: int):
    try:
        team = session.query(Team).with_for_update().get(team_id)
        if not team:
            return {'success': False, 'message': 'Team not found'}
        
        channel_id = team.discord_channel_id
        role_id = team.discord_player_role_id
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if channel_id:
                if loop.run_until_complete(delete_channel(channel_id)):
                    team.discord_channel_id = None
                    session.flush()
            
            if role_id:
                if loop.run_until_complete(delete_role(role_id)):
                    team.discord_player_role_id = None
                    session.flush()
            
            session.commit()
            return {'success': True, 'message': 'Discord resources cleaned up'}
        finally:
            loop.close()
            
    except Exception as e:
        session.rollback()
        logger.error(f"Error cleaning up Discord resources: {str(e)}")
        raise self.retry(exc=e, countdown=30)

@celery_task(name='app.tasks.tasks_discord.update_team_discord_resources_task', queue='discord')
def update_team_discord_resources_task(self, session, team_id: int, new_team_name: str):
    try:
        # Create session explicitly
        team = session.query(Team).options(joinedload(Team.league)).get(team_id)
        if not team:
            return {'success': False, 'message': 'Team not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(rename_team_roles(session, team, new_team_name))
            session.commit()  # Commit changes
            return {'success': True, 'message': 'Discord resources updated'}
        finally:
            loop.close()
    except Exception as e:
        session.rollback()  # Rollback on error
        raise self.retry(exc=e, countdown=30)

async def _process_role_updates_batch(session, players: List[Player]) -> List[Dict[str, Any]]:
    """Process role updates for a batch of players."""
    results = []
    for player in players:
        try:
            # Process each player's role update
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