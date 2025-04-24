# app/tasks/tasks_discord.py

"""
Discord Tasks Module

This module defines several Celery tasks and async helpers that manage Discord-related
operations including updating player roles, processing role updates, creating and
cleaning up Discord resources, and fetching role status.

Tasks and helpers include:
  - update_player_discord_roles: Update a single player's Discord roles.
  - process_discord_role_updates: Batch process role updates for multiple players.
  - assign_roles_to_player_task: Assign or update roles for a specific player.
  - fetch_role_status: Retrieve and process the current role status of players.
  - remove_player_roles_task: Remove a player's Discord roles.
  - create_team_discord_resources_task: Create Discord resources for a team.
  - cleanup_team_discord_resources_task: Clean up Discord resources for a team.
  - update_team_discord_resources_task: Update Discord resources when team names change.
  
Helper async functions perform HTTP calls to the Discord bot API using aiohttp.
"""

import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.core import socketio
from app.decorators import celery_task
from app.models import Player, Team
from app.discord_utils import (
    update_player_roles,
    rename_team_roles,
    create_discord_channel,
    get_expected_roles,
    fetch_user_roles,
    process_single_player_update,
    remove_role_from_member,
    get_role_id
)
from web_config import Config
from app.utils.discord_request_handler import make_discord_request

logger = logging.getLogger(__name__)


def get_status_html(roles_match: bool) -> str:
    """
    Generate an HTML snippet indicating whether roles are in sync.
    
    Args:
        roles_match: True if current roles match expected roles.
        
    Returns:
        A span element as a string representing the status.
    """
    return (
        '<span class="badge bg-success">Synced</span>'
        if roles_match
        else '<span class="badge bg-warning">Out of Sync</span>'
    )


def create_error_result(player_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a standardized error result for a player.
    
    Args:
        player_info: Dictionary containing player's id, name, team, and league.
        
    Returns:
        A dictionary with error status and default values.
    """
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
    """
    Update Discord roles for a single player.
    
    This task fetches the player from the database, calls an async helper to update
    roles via Discord API, and updates the player's role data and timestamps. It also
    emits a socketio event with the update result.
    
    Args:
        session: Database session.
        player_id: ID of the player to update.
        
    Returns:
        A dictionary with the update result.
        
    Raises:
        Retries the task if an error occurs.
    """
    try:
        player = session.query(Player).get(player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return {'success': False, 'message': 'Player not found'}

        # Create a new event loop to run async updates.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                update_player_roles(session, player, force_update=False)
            )
            # Update player role fields and timestamps.
            player.discord_roles = result.get('current_roles', [])
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            player.last_sync_attempt = datetime.utcnow()
            player.sync_status = 'success' if result.get('success') else 'mismatch'

            # Emit socket event to notify clients.
            socketio.emit('role_update', result)
            return result
        finally:
            loop.close()
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

    except SQLAlchemyError as e:
        logger.error(f"Database error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


async def _update_player_discord_roles_async(session, player_id: int) -> Dict[str, Any]:
    """
    Async helper to update a player's Discord roles.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        
    Returns:
        A dictionary with success status and role details.
    """
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
    """
    Process Discord role updates for multiple players.
    
    This task queries players by their Discord IDs, then asynchronously processes role
    updates in batch. After processing, it updates each player's sync status and emits
    a socketio event with the role status results.
    
    Args:
        session: Database session.
        discord_ids: List of Discord IDs to process.
        
    Returns:
        A summary dictionary with counts and details of the processed results.
    """
    try:
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
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

        # Update each player's sync info based on the results.
        for player in players:
            result = next((r for r in results if r.get('id') == player.id), None)
            if result:
                player.discord_last_verified = datetime.utcnow()
                player.discord_needs_update = False
                player.last_sync_attempt = datetime.utcnow()
                player.sync_status = 'success' if result.get('status') == 'synced' else 'error'
                if not result.get('success'):
                    player.sync_error = result.get('error')

        return {
            'success': True,
            'processed_count': len([r for r in results if r.get('status') == 'synced']),
            'error_count': len([r for r in results if r.get('status') != 'synced']),
            'results': results
        }

    except Exception as e:
        logger.error(f"Error processing role updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


@celery_task(
    name='app.tasks.tasks_discord.assign_roles_to_player_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True,
    rate_limit='50/s'
)
def assign_roles_to_player_task(self, session, player_id: int, team_id: Optional[int] = None, only_add: bool = True) -> Dict[str, Any]:
    """
    Assign or update Discord roles for a player.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        team_id: Optional team ID to scope role assignment.
        only_add: If True, only add roles; if False, remove roles not in the expected set.
        
    Returns:
        A dictionary with success status and details of the role assignment.
    
    Raises:
        Retries the task on error.
    """
    logger.info(f"==> Starting assign_roles_to_player_task for player_id={player_id}, team_id={team_id}, only_add={only_add}")
    try:
        # Ensure a DB connection is available.
        session.connection()

        player = session.query(Player).get(player_id)
        if not player:
            logger.warning(f"Player {player_id} not found in DB.")
            return {'success': False, 'message': 'Player not found'}

        logger.info(f"Found player {player_id}, discord_id={player.discord_id}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.debug("Calling _assign_roles_async(...)")
            result = loop.run_until_complete(_assign_roles_async(session, player.id, team_id, only_add))
            # Use a nested transaction to update player sync status.
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
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

    except Exception as e:
        logger.error(f"Error assigning roles to player {player_id}: {e}", exc_info=True)
        countdown = 60 if isinstance(e, SQLAlchemyError) else 15
        raise self.retry(exc=e, countdown=countdown)


async def _assign_roles_async(session, player_id: int, team_id: Optional[int], only_add: bool) -> Dict[str, Any]:
    """
    Async helper to assign roles to a player via Discord API.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        team_id: Optional team ID to determine specific role.
        only_add: Whether to only add roles.
        
    Returns:
        A dictionary with success status.
    """
    logger.info(f"==> Entering _assign_roles_async for player_id={player_id}, team_id={team_id}, only_add={only_add}")
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.warning("No Discord ID or missing player.")
        return {'success': False, 'message': 'No Discord ID'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            if team_id:
                team = session.query(Team).get(team_id)
                role_name = f"ECS-FC-PL-{team.name}-PLAYER"
                league_role_name = f"ECS-FC-PL-{team.league.name}"
                guild_id = Config.SERVER_ID

                # Retrieve role IDs and assign roles via the Discord API.
                role_id = await get_role_id(guild_id, role_name, aio_session)
                league_role_id = await get_role_id(guild_id, league_role_name, aio_session)

                if role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}",
                        session=aio_session
                    )
                if league_role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{league_role_id}",
                        session=aio_session
                    )
                return {'success': True}

            # Process role update for the player without team-specific roles.
            logger.debug(f"No team_id specified, calling process_single_player_update(only_add={only_add})")
            return await process_single_player_update(session, player, only_add=only_add)

    except Exception as e:
        logger.error(f"Exception assigning roles: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}


@celery_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
def fetch_role_status(self, session) -> Dict[str, Any]:
    """
    Fetch and update role status for players with a Discord ID.
    
    This task retrieves players, fetches current roles via an async batch call,
    updates each player's sync status, and emits a socketio event with the results.
    
    Args:
        session: Database session.
        
    Returns:
        A dictionary with success status, results, and timestamp.
    
    Raises:
        Retries the task on error.
    """
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
            results = loop.run_until_complete(_fetch_roles_batch(session, players))
            # Update players with the latest role sync status.
            for status in results['status_updates']:
                player = session.query(Player).get(status['id'])
                if player:
                    player.discord_role_sync_status = status['status']
                    player.last_role_check = datetime.utcnow()
                    if 'current_roles' in status:
                        player.discord_roles = status['current_roles']
                    if 'error' in status:
                        player.sync_error = status['error']

            # Emit updated role status to clients.
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
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

    except Exception as e:
        logger.error(f"Error in fetch_role_status: {str(e)}")
        raise self.retry(exc=e, countdown=30)


def process_role_results(session, players: List[Player], role_results: List[Dict]) -> Dict[str, Any]:
    """
    Process role results from Discord API and update player records.
    
    Args:
        session: Database session.
        players: List of Player objects.
        role_results: List of dictionaries with role status data.
        
    Returns:
        A dictionary with status updates and formatted role result data.
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
                    'team': "No Team",
                    'league': "No League",
                }))
                continue

            current_roles = result.get('roles', [])
            teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
            leagues_str = ", ".join(sorted({t.league.name for t in player.teams if t.league})) if player.teams else "No League"

            # In this example, expected_roles is an empty list; adjust as needed.
            expected_roles = []
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
                'league': "No League"
            }))

    return {
        'status_updates': status_updates,
        'role_results': updated_role_results
    }


async def _fetch_roles_batch(session, players: List[Player]) -> Dict[str, Any]:
    """
    Async helper to fetch Discord roles for a batch of players.
    
    Args:
        session: Database session.
        players: List of Player objects.
        
    Returns:
        A dictionary containing status updates and detailed role results.
    """
    status_updates = []
    role_results = []

    async with aiohttp.ClientSession() as aio_session:
        for player in players:
            try:
                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                # Filter roles managed by our system.
                managed_prefixes = ["ECS-FC-PL-", "Referee"]
                managed_current = {r for r in current_roles if any(r.startswith(p) for p in managed_prefixes)}
                
                # Compute expected roles based on team and league data.
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
                    'current_roles': list(current_roles)
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
    """
    Async helper to fetch role status for given player data.
    
    Args:
        session: Database session.
        player_data: List of dictionaries containing player IDs and names.
        
    Returns:
        A list of role status dictionaries.
    """
    results = []
    status_updates = []

    async with aiohttp.ClientSession() as aio_session:
        for p_info in player_data:
            try:
                player = session.query(Player).get(p_info['id'])
                if not player:
                    continue

                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                managed_prefixes = ["ECS-FC-PL-", "Referee"]
                managed_current = {r for r in current_roles if any(r.startswith(p) for p in managed_prefixes)}

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

    # Update players' role sync info
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
    """
    Remove Discord roles for a player.
    
    This task retrieves the player with associated teams, then calls an async helper
    to remove roles via the Discord API. It updates player records accordingly.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        team_id: ID of the team.
        
    Returns:
        A dictionary with the result and updated player info.
        
    Raises:
        Retries the task on error.
    """
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
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

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
    """
    Async helper to remove a player's Discord roles.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        team_id: Optional team ID to specify which role to remove.
        
    Returns:
        A dictionary with success status.
    """
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

                url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles"
                member_roles = await make_discord_request('GET', url, aio_session)
                
                if member_roles:
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
    """
    Create Discord resources for a new team.
    
    This task retrieves the team and creates a Discord channel for the team via an async helper.
    
    Args:
        session: Database session.
        team_id: ID of the team.
        
    Returns:
        A dictionary indicating success or failure.
    """
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
            channel_result = loop.run_until_complete(
                create_discord_channel(session, team.name, team.league.name, team.id)
            )
            if channel_result and channel_result.get('channel_id'):
                team.discord_channel_id = channel_result['channel_id']
            
            return {'success': True, 'message': 'Discord resources created'}
        finally:
            loop.close()
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()

    except Exception as e:
        logger.error(f"Error creating Discord resources: {str(e)}")
        raise self.retry(exc=e, countdown=30)


async def delete_channel(channel_id: str) -> bool:
    """
    Async helper to delete a Discord channel.
    
    Args:
        channel_id: ID of the channel to delete.
        
    Returns:
        True if deletion was successful, False otherwise.
    """
    url = f"{Config.BOT_API_URL}/guilds/{Config.SERVER_ID}/channels/{channel_id}"
    async with aiohttp.ClientSession() as client:
        async with client.delete(url) as response:
            success = response.status == 200
            if success:
                logger.info(f"Deleted channel ID {channel_id}")
            return success


async def delete_role(role_id: str) -> bool:
    """
    Async helper to delete a Discord role.
    
    Args:
        role_id: ID of the role to delete.
        
    Returns:
        True if deletion was successful, False otherwise.
    """
    url = f"{Config.BOT_API_URL}/guilds/{Config.SERVER_ID}/roles/{role_id}"
    async with aiohttp.ClientSession() as client:
        async with client.delete(url) as response:
            success = response.status == 200
            if success:
                logger.info(f"Deleted role ID {role_id}")
            return success


@celery_task(name='app.tasks.tasks_discord.cleanup_team_discord_resources_task', queue='discord')
def cleanup_team_discord_resources_task(self, session, team_id: int):
    """
    Clean up Discord resources for a team.
    
    This task deletes the team's Discord channel and role if they exist, and updates the team record.
    
    Args:
        session: Database session.
        team_id: ID of the team.
        
    Returns:
        A dictionary indicating success or failure.
    
    Raises:
        Retries the task on error.
    """
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
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()
            
    except Exception as e:
        session.rollback()
        logger.error(f"Error cleaning up Discord resources: {str(e)}")
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_discord.update_team_discord_resources_task', queue='discord')
def update_team_discord_resources_task(self, session, team_id: int, new_team_name: str):
    """
    Update Discord resources when a team's name changes.
    
    This task renames team roles via an async helper and updates the database.
    
    Args:
        session: Database session.
        team_id: ID of the team.
        new_team_name: The new team name.
        
    Returns:
        A dictionary indicating success or failure.
    
    Raises:
        Retries the task on error.
    """
    try:
        team = session.query(Team).options(joinedload(Team.league)).get(team_id)
        if not team:
            return {'success': False, 'message': 'Team not found'}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(rename_team_roles(session, team, new_team_name))
            session.commit()
            return {'success': True, 'message': 'Discord resources updated'}
        finally:
            loop.close()
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()
            loop.close()
            # Ensure connections are properly cleaned up after asyncio operations
            from app.utils.db_connection_monitor import ensure_connections_cleanup
            ensure_connections_cleanup()
    except Exception as e:
        session.rollback()
        raise self.retry(exc=e, countdown=30)


async def _process_role_updates_batch(session, players: List[Player]) -> List[Dict[str, Any]]:
    """
    Async helper to process role updates for a batch of players.
    
    Args:
        session: Database session.
        players: List of Player objects.
        
    Returns:
        A list of dictionaries representing the update result for each player.
    """
    results = []
    for player in players:
        try:
            await update_player_roles(session, player, force_update=False)
            results.append({
                'player_id': player.id,
                'success': True,
                'status': 'synced'
            })
        except Exception as e:
            results.append({
                'player_id': player.id,
                'success': False,
                'status': 'error',
                'error': str(e)
            })
    return results