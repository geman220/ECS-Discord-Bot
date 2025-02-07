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
        '<span class="badge bg-success">Synced</span>'
        if roles_match
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
            joinedload(Player.teams),
            joinedload(Player.teams).joinedload(Team.league)
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
    retry_backoff=True,
    rate_limit='50/s'  # Example: rate limit to 50 Discord calls/sec
)
def assign_roles_to_player_task(
    self,
    session,
    player_id: int,
    team_id: Optional[int] = None,
    only_add: bool = True 
) -> Dict[str, Any]:
    """
    Assign or update Discord roles for a player.
    - `only_add=True` => do NOT remove any roles they currently have.
    - `only_add=False` => remove roles that are not in the expected set.
    """
    logger.info(f"==> Starting assign_roles_to_player_task for player_id={player_id}, team_id={team_id}, only_add={only_add}")
    try:
        # Ensure DB connection
        session.connection()

        player = session.query(Player).get(player_id)
        if not player:
            logger.warning(f"Player {player_id} not found in DB.")
            return {'success': False, 'message': 'Player not found'}

        logger.info(f"Found player {player_id}, discord_id={player.discord_id}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            logger.debug("About to call _assign_roles_async(...)")
            result = loop.run_until_complete(_assign_roles_async(session, player.id, team_id, only_add))

            # Update DB with sync status
            with session.begin_nested():
                player.discord_roles_updated = datetime.utcnow()
                if result.get('success'):
                    player.discord_role_sync_status = 'completed'
                else:
                    player.discord_role_sync_status = 'failed'
                    player.sync_error = result.get('error')
                player.last_sync_attempt = datetime.utcnow()

            return {
                'success': True,
                'message': 'Roles assigned successfully',
                'player_id': player_id,
                'timestamp': datetime.utcnow().isoformat(),
                **result
            }
        finally:
            loop.stop()
            loop.close()
            asyncio.set_event_loop(None)

    except Exception as e:
        logger.error(f"Error assigning roles to player {player_id}: {e}", exc_info=True)
        # Use different retry delays based on exception type:
        countdown = 60 if isinstance(e, SQLAlchemyError) else 15
        raise self.retry(exc=e, countdown=countdown)

async def _assign_roles_async(
    session,
    player_id: int,
    team_id: Optional[int],
    only_add: bool
) -> Dict[str, Any]:
    """
    Internal async helper to do the actual Discord calls.
    """
    logger.info(f"==> Entering _assign_roles_async for player_id={player_id}, team_id={team_id}, only_add={only_add}")
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.warning("No Discord ID or missing player.")
        return {'success': False, 'message': 'No Discord ID'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            # If a specific team_id was provided, assign that team's role(s) only
            if team_id:
                team = session.query(Team).get(team_id)
                role_name = f"ECS-FC-PL-{team.name}-PLAYER"
                logger.debug(f"Assigning team role '{role_name}' to player {player_id}")

                # Get the role IDs from Discord
                role_id = await get_role_id(Config.SERVER_ID, role_name, aio_session)
                league_role_name = f"ECS-FC-PL-{team.league.name}"
                league_role_id = await get_role_id(Config.SERVER_ID, league_role_name, aio_session)

                # Only add these roles; do not remove any others
                if role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/guilds/{Config.SERVER_ID}/members/{player.discord_id}/roles/{role_id}",
                        session=aio_session
                    )
                if league_role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/guilds/{Config.SERVER_ID}/members/{player.discord_id}/roles/{league_role_id}",
                        session=aio_session
                    )
                return {'success': True}

            # Otherwise, run the normal “process_single_player_update” which can handle
            # whether to remove roles or only add them:
            logger.debug(f"No team_id specified, calling process_single_player_update(only_add={only_add})")
            return await process_single_player_update(session, player, only_add=only_add)

    except Exception as e:
        logger.error(f"Exception assigning roles: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}

@celery_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
def fetch_role_status(self, session) -> Dict[str, Any]:
    try:
        players = session.query(Player).filter(
            Player.discord_id.isnot(None)
        ).options(
            joinedload(Player.teams),
            joinedload(Player.teams).joinedload(Team.league)
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
    """
    Process role results from Discord API.
    NOTE: This function references `player.team` but we now
    handle multiple teams with a string of names.
    """
    status_updates = []
    updated_role_results = []

    for player, result in zip(players, role_results):
        try:
            if isinstance(result, dict) and 'error' in result:
                status_updates.append({
                    'id': player.id,
                    'status': 'error',
                    'error': result['error']
                })
                updated_role_results.append(create_error_result({
                    'id': player.id,
                    'name': player.name,
                    # Provide fallback strings
                    'team': "No Team",
                    'league': "No League",
                }))
                continue

            current_roles = result.get('roles', [])
            if player:
                # If you want multiple teams as a single string:
                teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
                leagues_str = ", ".join(sorted({
                    t.league.name for t in player.teams if t.league
                })) if player.teams else "No League"

                expected_roles = []  # Or call get_expected_roles(session, player) if needed
                roles_match = set(current_roles) == set(expected_roles)

                status_updates.append({
                    'id': player.id,
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': current_roles
                })

                updated_role_results.append({
                    'id': player.id,
                    'name': player.name,
                    'team': teams_str,
                    'league': leagues_str,
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
            updated_role_results.append(create_error_result({
                'id': player.id,
                'name': player.name,
                'team': "No Team",
                'league': "No League",
            }))

    return {
        'status_updates': status_updates,
        'role_results': updated_role_results
    }

async def _fetch_roles_batch(session, players: List[Player]) -> Dict[str, Any]:
    guild_id = Config.SERVER_ID
    status_updates = []
    role_results = []

    async with aiohttp.ClientSession() as aio_session:
        for player in players:
            try:
                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                
                # Filter to only consider managed roles for comparison
                managed_prefixes = ["ECS-FC-PL-", "Referee"]
                managed_current = {r for r in current_roles if any(r.startswith(p) for p in managed_prefixes)}
                
                # Build expected roles
                expected_roles = set()
                for team in player.teams:
                    if team.league and team.league.name:
                        league_name = team.league.name.strip().upper()
                        if league_name == 'PREMIER':
                            expected_roles.add("ECS-FC-PL-PREMIER")
                            if player.is_coach:
                                expected_roles.add("ECS-FC-PL-PREMIER-COACH")
                        elif league_name == 'CLASSIC':
                            expected_roles.add("ECS-FC-PL-CLASSIC")
                            if player.is_coach:
                                expected_roles.add("ECS-FC-PL-CLASSIC-COACH")
                    expected_roles.add(f"ECS-FC-PL-{team.name}-PLAYER")
                
                if player.is_ref:
                    expected_roles.add("Referee")

                roles_match = managed_current == expected_roles
                status_html = get_status_html(roles_match)

                teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
                leagues_str = ", ".join(sorted({t.league.name for t in player.teams if t.league})) if player.teams else "No League"

                status_updates.append({
                    'id': player.id,
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': list(current_roles)  # Convert set back to list
                })

                role_results.append({
                    'id': player.id,
                    'name': player.name,
                    'team': teams_str,
                    'league': leagues_str,
                    'current_roles': list(current_roles),
                    'expected_roles': list(expected_roles),
                    'status_html': status_html,
                    'last_verified': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error fetching roles for player {player.id}: {str(e)}")
                status_updates.append({'id': player.id, 'status': 'error', 'error': str(e)})
                role_results.append(create_error_result({
                    'id': player.id, 
                    'name': player.name,
                    'team': "No Team",
                    'league': "No League"
                }))

    return {
        'status_updates': status_updates,
        'role_results': role_results
    }

async def _fetch_role_status_async(session, player_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    guild_id = Config.SERVER_ID
    results = []
    status_updates = []

    async with aiohttp.ClientSession() as aio_session:
        for p_info in player_data:
            try:
                player = session.query(Player).get(p_info['id'])
                if not player:
                    continue

                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                
                # Filter managed roles
                managed_prefixes = ["ECS-FC-PL-", "Referee"]
                managed_current = {r for r in current_roles if any(r.startswith(p) for p in managed_prefixes)}
                
                # Build expected roles
                expected_roles = set()
                for team in player.teams:
                    if team.league and team.league.name:
                        league_name = team.league.name.strip().upper()
                        if league_name == 'PREMIER':
                            expected_roles.add("ECS-FC-PL-PREMIER")
                            if player.is_coach:
                                expected_roles.add("ECS-FC-PL-PREMIER-COACH")
                        elif league_name == 'CLASSIC':
                            expected_roles.add("ECS-FC-PL-CLASSIC")
                            if player.is_coach:
                                expected_roles.add("ECS-FC-PL-CLASSIC-COACH")
                    expected_roles.add(f"ECS-FC-PL-{team.name}-PLAYER")
                
                if player.is_ref:
                    expected_roles.add("Referee")

                roles_match = managed_current == expected_roles
                status_html = get_status_html(roles_match)

                teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
                leagues_str = ", ".join(sorted({t.league.name for t in player.teams if t.league})) if player.teams else "No League"

                status_updates.append({
                    'id': p_info['id'],
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': list(current_roles)
                })

                results.append({
                    'id': p_info['id'],
                    'name': p_info['name'],
                    'team': teams_str,
                    'league': leagues_str,
                    'current_roles': list(current_roles),
                    'expected_roles': list(expected_roles),
                    'status_html': status_html,
                    'last_verified': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error processing player {p_info['id']}: {str(e)}")
                results.append(create_error_result(p_info))

    # Update player statuses
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
def remove_player_roles_task(self, session, player_id: int, team_id: int) -> Dict[str, Any]:
    try:
        player = session.query(Player).options(
            joinedload(Player.teams),
            joinedload(Player.teams).joinedload(Team.league)
        ).get(player_id)
        if not player:
            return {'success': False, 'message': 'Player not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_remove_player_roles_async(session, player.id, team_id))
        finally:
            loop.close()

        # Now we can use result to update the player record
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

async def _remove_player_roles_async(session, player_id: int, team_id: Optional[int] = None) -> Dict[str, Any]:
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.error(f"No Discord ID for player {player_id}") 
        return {'success': False, 'message': 'No Discord ID'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            if team_id:
                team = session.query(Team).get(team_id)
                role_name = f"ECS-FC-PL-{team.name}-PLAYER"
                guild_id = int(Config.SERVER_ID)

                # Get all roles first
                url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles"
                member_roles = await make_discord_request('GET', url, aio_session)
                
                if member_roles:
                    # Remove this specific team's role
                    role_id = await get_role_id(guild_id, role_name, aio_session)
                    if role_id:
                        await remove_role_from_member(guild_id, player.discord_id, role_id, aio_session)
                        return {'success': True}

            return {'success': False, 'message': 'No team specified'}

    except Exception as e:
        logger.error(f"Error removing roles: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}

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