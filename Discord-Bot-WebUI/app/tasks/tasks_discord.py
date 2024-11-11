# app/tasks/tasks_discord.py

import logging
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from app.decorators import async_task
from app.utils.db_utils import celery_transactional_task
from app.models import Player, Team, League
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.core import socketio
from app.db_management import db_manager
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
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_player_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_player_discord_roles') as session:
                    player = session.query(Player).get(player_id)
                    if player:
                        return {
                            'id': player.id,
                            'discord_id': player.discord_id,
                            'name': player.name
                        }
                    return None

        player_data = await asyncio.get_event_loop().run_in_executor(executor, get_player_sync)
        if not player_data:
            logger.error(f"Player {player_id} not found")
            return {'success': False, 'message': 'Player not found'}

        discord_id = player_data['discord_id']
        if not discord_id:
            logger.error(f"No Discord ID for player {player_id}")
            return {'success': False, 'message': 'No Discord ID associated with player'}

        try:
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
                    with db_manager.session_scope(transaction_name='update_player_discord_status') as session:
                        player = session.query(Player).get(player_id)
                        if player:
                            player.discord_roles = final_roles
                            player.discord_last_verified = datetime.utcnow()
                            player.discord_needs_update = False
                            player.last_sync_attempt = datetime.utcnow()
                            player.sync_status = 'success' if roles_match else 'mismatch'
                            session.flush()
                            return player
                        return None

            updated_player = await asyncio.get_event_loop().run_in_executor(executor, update_player_status_sync)
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
                    'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    'roles_match': roles_match
                }
            }

            socketio.emit('role_update', result['player_data'])
            logger.info(f"Successfully updated Discord roles for player {player_id}", extra={
                'roles_match': roles_match,
                'current_roles': final_roles,
                'expected_roles': expected_roles
            })
            
            return result

        except aiohttp.ClientError as e:
            logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
            
            def update_sync_error():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_sync_error') as session:
                        player = session.query(Player).get(player_id)
                        if player:
                            player.last_sync_attempt = datetime.utcnow()
                            player.sync_status = 'error'
                            player.sync_error = str(e)
                            session.flush()
            
            await asyncio.get_event_loop().run_in_executor(executor, update_sync_error)
            raise

    except SQLAlchemyError as e:
        logger.error(f"Database error in _update_player_discord_roles_async: {str(e)}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error in _update_player_discord_roles_async: {str(e)}", exc_info=True)
        raise
    finally:
        executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_discord.update_player_discord_roles',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def update_player_discord_roles(self, player_id: int) -> Dict[str, Any]:
    """Update Discord roles for a player."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_update_player_discord_roles_async(self, player_id))
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

@celery_transactional_task(
    name='app.tasks.tasks_discord.process_discord_role_updates',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def process_discord_role_updates(self) -> Dict[str, Any]:
    """Process Discord role updates for all marked players."""
    try:
        # Get players needing updates
        with db_manager.session_scope(transaction_name='get_players_for_updates') as session:
            players = session.query(Player).filter(
                (Player.discord_needs_update == True) |
                (Player.discord_last_verified.is_(None)) |
                (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
            ).options(
                joinedload(Player.team),
                joinedload(Player.team).joinedload(Team.league)
            ).all()

            player_data = [{
                'id': player.id,
                'discord_id': player.discord_id,
                'name': player.name,
                'last_verified': player.discord_last_verified
            } for player in players if player.discord_id]

        if not player_data:
            logger.info("No players need Discord role updates")
            return {
                'success': True,
                'message': 'No updates needed',
                'processed_count': 0
            }

        logger.info(f"Processing Discord role updates for {len(player_data)} players")

        # Process updates in batches
        batch_size = 50
        processed_count = 0
        error_count = 0
        results = []

        for i in range(0, len(player_data), batch_size):
            batch = player_data[i:i + batch_size]
            try:
                # Process batch of role updates
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    batch_results = loop.run_until_complete(
                        process_role_updates([p['discord_id'] for p in batch])
                    )
                    processed_count += len(batch_results.get('processed', []))
                    error_count += len(batch_results.get('errors', []))
                    results.extend(batch_results.get('results', []))
                finally:
                    loop.close()

                # Update database for processed players
                with db_manager.session_scope(transaction_name='update_processed_players') as session:
                    for player_info in batch:
                        player = session.query(Player).get(player_info['id'])
                        if player:
                            player.discord_last_verified = datetime.utcnow()
                            player.discord_needs_update = False
                            player.last_sync_attempt = datetime.utcnow()
                            
                            # Update sync status based on results
                            player_result = next(
                                (r for r in results if r.get('player_id') == player.id), 
                                None
                            )
                            if player_result:
                                player.sync_status = 'success' if player_result.get('success') else 'error'
                                if not player_result.get('success'):
                                    player.sync_error = player_result.get('error')
                    
                    session.flush()

                logger.info(f"Processed batch of {len(batch)} players successfully")

            except Exception as e:
                logger.error(f"Error processing batch: {str(e)}", exc_info=True)
                error_count += len(batch)

        final_results = {
            'success': True,
            'message': f'Processed {processed_count} players with {error_count} errors',
            'processed_count': processed_count,
            'error_count': error_count,
            'total_players': len(player_data),
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        }

        # Emit status update
        socketio.emit('role_updates_complete', final_results)
        logger.info("Role updates completed", extra=final_results)

        return final_results

    except SQLAlchemyError as e:
        logger.error(f"Database error in process_discord_role_updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in process_discord_role_updates: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_discord.assign_roles_to_player_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def assign_roles_to_player_task(self, player_id: int) -> Dict[str, Any]:
    """Assign Discord roles to a player."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_assign_roles_async(player_id))
            return {
                'success': True,
                'message': 'Roles assigned successfully',
                'player_id': player_id,
                'timestamp': datetime.utcnow().isoformat(),
                **result
            }
        finally:
            loop.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error assigning roles to player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error assigning roles to player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _assign_roles_async(player_id: int) -> Dict[str, Any]:
    """Async helper for assign_roles_to_player_task"""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_player_data_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_player_role_data') as session:
                    player = session.query(Player).options(
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

        player_data = await asyncio.get_event_loop().run_in_executor(executor, get_player_data_sync)
        if not player_data:
            logger.error(f"Player {player_id} not found")
            return {
                'success': False,
                'message': 'Player not found',
                'error_type': 'not_found'
            }

        if not player_data.get('discord_id'):
            logger.error(f"No Discord ID for player {player_id}")
            return {
                'success': False,
                'message': 'No Discord ID associated with player',
                'error_type': 'no_discord_id'
            }

        # Process the role update
        update_result = await process_single_player_update(player_data)

        def update_player_status_sync(success: bool, error: Optional[str] = None):
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='update_role_assignment_status') as session:
                    player = session.query(Player).get(player_id)
                    if player:
                        player.discord_roles_updated = datetime.utcnow()
                        player.discord_role_sync_status = 'completed' if success else 'failed'
                        player.last_sync_attempt = datetime.utcnow()
                        if error:
                            player.sync_error = error
                        session.flush()

        # Update status based on result
        await asyncio.get_event_loop().run_in_executor(
            executor, 
            update_player_status_sync, 
            update_result.get('success', False),
            update_result.get('error')
        )

        if update_result.get('success'):
            logger.info(f"Successfully assigned roles to player {player_id}")
        else:
            logger.error(f"Failed to assign roles to player {player_id}: {update_result.get('error')}")

        return update_result

    except Exception as e:
        logger.error(f"Error in _assign_roles_async for player {player_id}: {str(e)}", exc_info=True)
        
        def mark_sync_failed_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='mark_role_assignment_failed') as session:
                    player = session.query(Player).get(player_id)
                    if player:
                        player.discord_role_sync_status = 'failed'
                        player.discord_role_sync_error = str(e)
                        player.last_sync_attempt = datetime.utcnow()
                        session.flush()

        await asyncio.get_event_loop().run_in_executor(executor, mark_sync_failed_sync)
        raise
    finally:
        executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_discord.bulk_assign_roles_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def bulk_assign_roles_task(self, player_ids: List[int]) -> Dict[str, Any]:
    """Bulk assign Discord roles to multiple players."""
    try:
        # Validate input
        if not player_ids:
            return {
                'success': False,
                'message': 'No player IDs provided',
                'processed_at': datetime.utcnow().isoformat()
            }

        # Get player details first
        with db_manager.session_scope(transaction_name='get_bulk_players') as session:
            players = session.query(Player).filter(
                Player.id.in_(player_ids)
            ).options(
                joinedload(Player.team)
            ).all()

            valid_players = [
                {
                    'id': player.id,
                    'name': player.name,
                    'discord_id': player.discord_id,
                    'team_name': player.team.name if player.team else None
                }
                for player in players
                if player.discord_id  # Only include players with Discord IDs
            ]

        results = {
            'total_requested': len(player_ids),
            'total_valid': len(valid_players),
            'successful': 0,
            'failed': 0,
            'failed_ids': [],
            'queued_tasks': [],
            'skipped_players': []
        }

        # Process in batches to avoid overwhelming the system
        batch_size = 50
        for i in range(0, len(valid_players), batch_size):
            batch = valid_players[i:i + batch_size]
            
            for player in batch:
                try:
                    # Queue task with exponential backoff between retries
                    task = assign_roles_to_player_task.apply_async(
                        kwargs={'player_id': player['id']},
                        countdown=5 * (i // batch_size),  # Stagger start times
                        expires=3600,  # Tasks expire after 1 hour
                        retry_policy={
                            'max_retries': 3,
                            'interval_start': 60,
                            'interval_step': 60,
                            'interval_max': 300,
                        }
                    )
                    
                    results['successful'] += 1
                    results['queued_tasks'].append({
                        'player_id': player['id'],
                        'task_id': task.id,
                        'name': player['name'],
                        'team': player['team_name']
                    })
                    
                    logger.info(f"Queued role assignment for player {player['name']} (ID: {player['id']})")
                
                except Exception as e:
                    logger.error(f"Failed to queue role assignment for player {player['id']}: {str(e)}")
                    results['failed'] += 1
                    results['failed_ids'].append({
                        'id': player['id'],
                        'name': player['name'],
                        'error': str(e)
                    })

        # Update status in database
        with db_manager.session_scope(transaction_name='update_bulk_assignment_status') as session:
            for player_data in valid_players:
                player = session.query(Player).get(player_data['id'])
                if player:
                    player.role_update_queued = True
                    player.last_bulk_update_attempt = datetime.utcnow()
            session.flush()

        # Track skipped players
        skipped_ids = set(player_ids) - {p['id'] for p in valid_players}
        if skipped_ids:
            with db_manager.session_scope(transaction_name='get_skipped_players') as session:
                skipped_players = session.query(Player).filter(Player.id.in_(skipped_ids)).all()
                results['skipped_players'] = [
                    {
                        'id': player.id,
                        'name': player.name,
                        'reason': 'No Discord ID' if not player.discord_id else 'Unknown'
                    }
                    for player in skipped_players
                ]

        final_results = {
            'success': True,
            'message': f"Queued role assignments for {results['successful']} players",
            'results': results,
            'processed_at': datetime.utcnow().isoformat()
        }

        # Emit progress update
        socketio.emit('bulk_role_assignment_update', final_results)
        
        logger.info(
            f"Bulk role assignment processed", 
            extra={
                'total_requested': results['total_requested'],
                'successful': results['successful'],
                'failed': results['failed'],
                'skipped': len(results['skipped_players'])
            }
        )

        return final_results

    except SQLAlchemyError as e:
        logger.error(f"Database error in bulk_assign_roles_task: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error in bulk_assign_roles_task: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)

@celery_transactional_task(
    name='app.tasks.tasks_discord.remove_player_roles_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def remove_player_roles_task(self, player_id: int) -> Dict[str, Any]:
    """Remove Discord roles from a player."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_remove_player_roles_async(player_id))
            return {
                'success': True,
                'message': 'Roles removed successfully',
                'player_id': player_id,
                'processed_at': datetime.utcnow().isoformat(),
                **result
            }
        finally:
            loop.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error removing roles from player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error removing roles from player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _remove_player_roles_async(player_id: int) -> Dict[str, Any]:
    """Async helper for remove_player_roles_task"""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_player_roles_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_player_roles') as session:
                    player = session.query(Player).options(
                        joinedload(Player.team),
                        joinedload(Player.team).joinedload(Team.league)
                    ).get(player_id)
                    if not player:
                        return None
                    return {
                        'id': player.id,
                        'discord_id': player.discord_id,
                        'roles': player.discord_roles or [],
                        'name': player.name
                    }

        player_data = await asyncio.get_event_loop().run_in_executor(executor, get_player_roles_sync)
        if not player_data:
            logger.error(f"Player {player_id} not found")
            return {
                'success': False,
                'message': 'Player not found',
                'error_type': 'not_found'
            }

        if not player_data.get('discord_id'):
            logger.error(f"No Discord ID for player {player_id}")
            return {
                'success': False,
                'message': 'No Discord ID associated with player',
                'error_type': 'no_discord_id'
            }

        # Process role removal
        try:
            await process_role_updates([player_data])
            
            def update_player_status_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_role_removal_status') as session:
                        player = session.query(Player).get(player_id)
                        if player:
                            player.discord_roles = []
                            player.discord_last_verified = datetime.utcnow()
                            player.last_role_removal = datetime.utcnow()
                            player.role_removal_status = 'completed'
                            session.flush()

            await asyncio.get_event_loop().run_in_executor(executor, update_player_status_sync)
            
            logger.info(f"Successfully removed roles from player {player_data['name']} (ID: {player_id})")
            
            return {
                'success': True,
                'message': f"Roles removed successfully from {player_data['name']}",
                'removed_roles': player_data['roles']
            }

        except Exception as e:
            logger.error(f"Error removing roles from player {player_id}: {str(e)}")
            
            def update_error_status_sync():
                from app import create_app
                app = create_app()
                
                with app.app_context():
                    with db_manager.session_scope(transaction_name='update_role_removal_error') as session:
                        player = session.query(Player).get(player_id)
                        if player:
                            player.role_removal_status = 'failed'
                            player.last_role_removal = datetime.utcnow()
                            player.role_removal_error = str(e)
                            session.flush()

            await asyncio.get_event_loop().run_in_executor(executor, update_error_status_sync)
            raise

    except Exception as e:
        logger.error(f"Error in _remove_player_roles_async for player {player_id}: {str(e)}", exc_info=True)
        raise
    finally:
        executor.shutdown()

@celery_transactional_task(
    name='app.tasks.tasks_discord.fetch_role_status',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
def fetch_role_status(self) -> Dict[str, Any]:
    """Fetch and verify Discord role status for all players."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_fetch_role_status_async())
            return {
                'success': True,
                'message': 'Role status fetch completed',
                'results': result,
                'fetched_at': datetime.utcnow().isoformat()
            }
        finally:
            loop.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except aiohttp.ClientError as e:
        logger.error(f"Discord API error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        logger.error(f"Error in fetch_role_status: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=15)

async def _fetch_role_status_async() -> List[Dict[str, Any]]:
    """Async helper for fetch_role_status"""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        def get_players_with_discord_sync():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='get_players_role_status') as session:
                    players = session.query(Player).filter(Player.discord_id.isnot(None))\
                        .options(
                            joinedload(Player.team),
                            joinedload(Player.team).joinedload(Team.league)
                        ).all()
                    return [{
                        'id': player.id,
                        'discord_id': player.discord_id,
                        'name': player.name,
                        'team': player.team.name if player.team else None,
                        'league': player.team.league.name if player.team and player.team.league else None
                    } for player in players]

        player_data = await asyncio.get_event_loop().run_in_executor(executor, get_players_with_discord_sync)
        guild_id = Config.SERVER_ID
        tasks = []
        results = []

        # Prepare Discord API requests
        for player_info in player_data:
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player_info['discord_id']}/roles"
            tasks.append(('GET', url, {}))

        # Fetch role data from Discord
        try:
            role_results = await optimized_discord_request(tasks)
        except aiohttp.ClientError as e:
            logger.error("Discord API error fetching roles", exc_info=True)
            role_results = [{'error': str(e)}] * len(tasks)

        # Process results for each player
        status_updates = []
        for player_info, role_result in zip(player_data, role_results):
            try:
                if isinstance(role_result, dict) and 'error' in role_result:
                    logger.error(f"Error from Discord API for player {player_info['id']}: {role_result['error']}")
                    status_updates.append({
                        'id': player_info['id'],
                        'status': 'error',
                        'error': role_result['error']
                    })
                    results.append({
                        'error': role_result['error'],
                        'id': player_info['id'],
                        'name': player_info['name']
                    })
                    continue

                current_roles = role_result.get('roles', [])
                expected_roles = await get_expected_roles(player_info, None)
                roles_match = set(current_roles) == set(expected_roles)

                status_updates.append({
                    'id': player_info['id'],
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': current_roles,
                    'expected_roles': expected_roles
                })

                results.append({
                    'id': player_info['id'],
                    'name': player_info['name'],
                    'team': player_info['team'],
                    'league': player_info['league'],
                    'current_roles': current_roles,
                    'expected_roles': expected_roles,
                    'status_html': get_status_html(roles_match),
                    'last_verified': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error processing player {player_info['id']}: {str(e)}")
                status_updates.append({
                    'id': player_info['id'],
                    'status': 'error',
                    'error': str(e)
                })
                error_result = create_error_result({
                    'id': player_info['id'],
                    'name': player_info['name'],
                    'team': player_info['team'],
                    'league': player_info['league']
                })
                results.append(error_result)

        # Update database with status
        def update_status_batch():
            from app import create_app
            app = create_app()
            
            with app.app_context():
                with db_manager.session_scope(transaction_name='update_role_status_batch') as session:
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

        await asyncio.get_event_loop().run_in_executor(executor, update_status_batch)

        # Emit results via WebSocket
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

    except Exception as e:
        logger.error(f"Error in _fetch_role_status_async: {str(e)}", exc_info=True)
        raise
    finally:
        executor.shutdown()

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