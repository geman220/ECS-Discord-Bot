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

from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError

# Import optimized utilities
from app.utils.cache_manager import reference_cache, clear_player_cache
from app.utils.query_optimizer import (
    QueryOptimizer, 
    memory_efficient_session, 
    efficient_player_discord_batch,
    stream_players_with_discord_ids,
    BatchConfig
)
import traceback

from app.core import socketio
from app.decorators import celery_task
from app.models import Player, Team, User, PlayerTeamSeason, Season
from app.utils.task_session_manager import task_session
from app.discord_utils import (
    update_player_roles,
    rename_team_roles,
    create_discord_channel,
    get_expected_roles,
    fetch_user_roles,
    process_single_player_update,
    remove_role_from_member,
    get_role_id,
    get_member_roles,
    normalize_name
)
from web_config import Config
from app.utils.discord_request_handler import make_discord_request

logger = logging.getLogger(__name__)


def get_current_season_teams(session, player):
    """
    Get current season teams for a player using PlayerTeamSeason records.
    Falls back to direct team relationships if no current season records exist.
    
    Args:
        session: Database session
        player: Player object
        
    Returns:
        List of current season team dictionaries with id, name, and league_name
    """
    try:
        # First, try to get current season
        current_season = session.query(Season).filter_by(is_current=True).first()
        
        if current_season:
            # Query teams through PlayerTeamSeason for current season only
            current_season_teams = session.query(Team).join(
                PlayerTeamSeason, Team.id == PlayerTeamSeason.team_id
            ).filter(
                PlayerTeamSeason.player_id == player.id,
                PlayerTeamSeason.season_id == current_season.id
            ).all()
            
            if current_season_teams:
                return [{'id': team.id, 'name': team.name, 'league_name': team.league.name if team.league else None} 
                        for team in current_season_teams]
        
        # Fallback: Filter teams by leagues from current seasons
        # This handles cases where PlayerTeamSeason records haven't been created yet
        current_seasons = session.query(Season).filter_by(is_current=True).all()
        if current_seasons:
            current_season_league_ids = [league.id for season in current_seasons for league in season.leagues]
            current_teams = [team for team in player.teams 
                            if team.league_id in current_season_league_ids]
            
            if current_teams:
                return [{'id': team.id, 'name': team.name, 'league_name': team.league.name if team.league else None} 
                        for team in current_teams]
        
        # Final fallback: return empty list to avoid assigning old roles
        logger.warning(f"No current season teams found for player {player.id}, returning empty list to avoid old roles")
        return []
        
    except Exception as e:
        logger.error(f"Error getting current season teams for player {player.id}: {e}")
        return []


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


def _extract_player_role_data(session, player_id: int):
    """Extract player data for Discord role update."""
    try:
        player = session.query(Player).options(joinedload(Player.user)).get(player_id)
        if not player:
            raise ValueError(f"Player {player_id} not found")
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_player_role_data: {e}")
        raise
    
    # Get all required data from database while session is available
    try:
        # Extract the basic player data and calculate roles in async phase
        # Use helper function to get only current season teams
        teams = get_current_season_teams(session, player)
        
        # Get Flask user roles for division role assignment
        user_roles = []
        try:
            if player.user:
                # Safely load roles with a separate query to avoid joinedload issues
                user_with_roles = session.query(User).options(joinedload(User.roles)).filter_by(id=player.user.id).first()
                if user_with_roles and user_with_roles.roles:
                    user_roles = [role.name for role in user_with_roles.roles]
        except SQLAlchemyError as e:
            logger.warning(f"Could not load user roles for player {player.id}: {e}")
            user_roles = []
        
        # Get league information for division role assignment
        league_names = []
        if player.league and player.league.name:
            league_names.append(player.league.name)
        if player.primary_league and player.primary_league.name:
            league_names.append(player.primary_league.name)
        for league in player.other_leagues:
            if league.name:
                league_names.append(league.name)
        
        return {
            'player_id': player_id,
            'discord_id': player.discord_id,
            'name': player.name,
            'is_active': player.is_current_player,
            'is_coach': player.is_coach,
            'current_roles': player.discord_roles or [],
            'teams': teams,
            'user_roles': user_roles,
            'league_names': list(set(league_names)),  # Remove duplicates
            'force_update': False
        }
    except Exception as e:
        logger.error(f"Error extracting player data: {e}")
        raise


async def _execute_player_role_update_async(data):
    """Execute Discord role update without database session."""
    # Calculate expected roles based on team data
    expected_roles = []
    
    # Add team roles based on teams
    for team in data.get('teams', []):
        if team.get('league_name') in ['Premier', 'Classic']:
            # Add player role
            expected_roles.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Player")
    
    # Add league division roles based on Flask user roles AND database league fields
    user_roles = data.get('user_roles', [])
    league_names = data.get('league_names', [])
    
    # Priority 1: Flask user roles (most authoritative)
    if 'pl-premier' in user_roles:
        if 'ECS-FC-PL-PREMIER' not in expected_roles:
            expected_roles.append('ECS-FC-PL-PREMIER')
    if 'pl-classic' in user_roles:
        if 'ECS-FC-PL-CLASSIC' not in expected_roles:
            expected_roles.append('ECS-FC-PL-CLASSIC')
    
    # Priority 2: Database league associations (fallback)
    for league_name in league_names:
        if league_name.lower() == 'premier' and 'ECS-FC-PL-PREMIER' not in expected_roles:
            expected_roles.append('ECS-FC-PL-PREMIER')
        elif league_name.lower() == 'classic' and 'ECS-FC-PL-CLASSIC' not in expected_roles:
            expected_roles.append('ECS-FC-PL-CLASSIC')
    
    # Add substitute roles based on Flask user roles
    if 'Premier Sub' in user_roles:
        if 'ECS-FC-PL-PREMIER-SUB' not in expected_roles:
            expected_roles.append('ECS-FC-PL-PREMIER-SUB')
    if 'Classic Sub' in user_roles:
        if 'ECS-FC-PL-CLASSIC-SUB' not in expected_roles:
            expected_roles.append('ECS-FC-PL-CLASSIC-SUB')
    if 'ECS FC Sub' in user_roles:
        if 'ECS-FC-LEAGUE-SUB' not in expected_roles:
            expected_roles.append('ECS-FC-LEAGUE-SUB')
    
    # Add coach roles based on leagues (not teams) if player is coach
    if data.get('is_coach'):
        # Priority 1: Flask user roles for coach assignments
        if 'pl-premier' in user_roles:
            if 'ECS-FC-PL-PREMIER-COACH' not in expected_roles:
                expected_roles.append('ECS-FC-PL-PREMIER-COACH')
        if 'pl-classic' in user_roles:
            if 'ECS-FC-PL-CLASSIC-COACH' not in expected_roles:
                expected_roles.append('ECS-FC-PL-CLASSIC-COACH')
        
        # Priority 2: Database league associations for coach assignments
        for league_name in league_names:
            if league_name.lower() == 'premier' and 'ECS-FC-PL-PREMIER-COACH' not in expected_roles:
                expected_roles.append('ECS-FC-PL-PREMIER-COACH')
            elif league_name.lower() == 'classic' and 'ECS-FC-PL-CLASSIC-COACH' not in expected_roles:
                expected_roles.append('ECS-FC-PL-CLASSIC-COACH')
    
    # Get app managed roles (these are roles our app can modify)
    app_managed_roles = [
        'ECS-FC-PL-PREMIER',
        'ECS-FC-PL-CLASSIC',
        'ECS-FC-PL-PREMIER-COACH',
        'ECS-FC-PL-CLASSIC-COACH',
        'ECS-FC-PL-PREMIER-SUB',
        'ECS-FC-PL-CLASSIC-SUB',
        'ECS-FC-LEAGUE-SUB'
    ]
    
    # Add team-specific player roles to managed roles
    for team in data.get('teams', []):
        app_managed_roles.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Player")
    
    # Prepare data for async-only function
    player_data = {
        'id': data['player_id'],
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': data.get('current_roles', []),
        'expected_roles': expected_roles,
        'app_managed_roles': app_managed_roles
    }
    
    # Perform the async Discord operations
    from app.discord_utils import update_player_roles_async_only
    result = await update_player_roles_async_only(player_data, force_update=data.get('force_update', False))
    
    # Return result with data needed for database update
    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'current_roles': result.get('current_roles', []),
        'roles_added': result.get('roles_added', []),
        'roles_removed': result.get('roles_removed', []),
        'player_id': data['player_id'],
        'sync_status': 'success' if result.get('success') else 'mismatch'
    }


def _update_player_after_role_sync(session, result):
    """Update player record after async role sync completes."""
    if not result.get('success'):
        return result
    
    player = session.query(Player).get(result['player_id'])
    if player:
        player.discord_roles = result.get('current_roles', [])
        player.discord_last_verified = datetime.utcnow()
        player.discord_needs_update = False
        player.last_sync_attempt = datetime.utcnow()
        player.sync_status = result.get('sync_status', 'success')
    
    return result


@celery_task(
    name='app.tasks.tasks_discord.update_player_discord_roles',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
async def update_player_discord_roles(self, session, player_id: int) -> Dict[str, Any]:
    """
    Update Discord roles for a single player using two-phase pattern.
    
    Phase 1: Extract player data from database
    Phase 2: Update Discord roles via API (async, no DB session)
    Phase 3: Update player record with results
    
    Args:
        session: Database session (used only in phase 1).
        player_id: ID of the player to update.
        
    Returns:
        A dictionary with the update result.
    """
    try:
        # This task will be handled by the decorator's two-phase pattern
        # but also needs a final database update, so we handle that specially
        pass
    except SQLAlchemyError as e:
        logger.error(f"Database error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


# This task needs special handling since it requires a final DB update
# We'll mark it with a special flag and handle it in the decorator
update_player_discord_roles._extract_data = _extract_player_role_data
update_player_discord_roles._execute_async = _execute_player_role_update_async
update_player_discord_roles._two_phase = True
update_player_discord_roles._requires_final_db_update = True
update_player_discord_roles._final_db_update = _update_player_after_role_sync


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


def _extract_batch_role_update_data(session, discord_ids: List[str]):
    """Extract player data for batch Discord role updates using optimized batch processing."""
    try:
        # Use optimized batch processing from query optimizer
        players_data = efficient_player_discord_batch(session, discord_ids)
        
        logger.info(f"Extracted batch role update data for {len(players_data)} players from {len(discord_ids)} Discord IDs using optimized processing")
        return {'players': players_data}
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_batch_role_update_data: {e}", exc_info=True)
        raise


async def _execute_batch_role_update_async(data):
    """Execute batch Discord role updates without database session."""
    players_data = data['players']
    results = []
    
    # Process each player
    for player_data in players_data:
        try:
            # Use the same logic as single player update
            result = await _execute_player_role_update_async(player_data)
            results.append({
                'id': player_data['id'],
                'discord_id': player_data['discord_id'],
                'status': 'synced' if result.get('success') else 'error',
                'success': result.get('success', False),
                'error': result.get('message', '') if not result.get('success') else None,
                'current_roles': result.get('current_roles', []),
                'roles_added': result.get('roles_added', []),
                'roles_removed': result.get('roles_removed', [])
            })
        except Exception as e:
            logger.error(f"Error processing player {player_data.get('name', 'unknown')}: {e}")
            results.append({
                'id': player_data['id'],
                'discord_id': player_data['discord_id'],
                'status': 'error',
                'success': False,
                'error': str(e)
            })
    
    return {
        'success': True,
        'results': results,
        'processed_count': len([r for r in results if r.get('status') == 'synced']),
        'error_count': len([r for r in results if r.get('status') != 'synced'])
    }


def _update_players_after_batch_role_sync(session, result):
    """Update player records after batch role sync completes."""
    if not result.get('success'):
        return result
    
    # Update each player's sync info based on the results
    for player_result in result.get('results', []):
        player = session.query(Player).get(player_result['id'])
        if player:
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            player.last_sync_attempt = datetime.utcnow()
            player.sync_status = 'success' if player_result.get('status') == 'synced' else 'error'
            if not player_result.get('success'):
                player.sync_error = player_result.get('error')
            if player_result.get('current_roles'):
                player.discord_roles = player_result['current_roles']
    
    return result


@celery_task(
    name='app.tasks.tasks_discord.process_discord_role_updates',
    queue='discord'
)
async def process_discord_role_updates(self, session, discord_ids: List[str]) -> Dict[str, Any]:
    """
    Process Discord role updates for multiple players using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        discord_ids: List of Discord IDs to process.
        
    Returns:
        A summary dictionary with counts and details of the processed results.
    """
    pass


# Attach phase methods
process_discord_role_updates._extract_data = _extract_batch_role_update_data
process_discord_role_updates._execute_async = _execute_batch_role_update_async
process_discord_role_updates._two_phase = True
process_discord_role_updates._requires_final_db_update = True
process_discord_role_updates._final_db_update = _update_players_after_batch_role_sync


def _extract_assign_roles_data(session, player_id: int, team_id: Optional[int] = None, only_add: bool = True):
    """Extract player data for role assignment."""
    player = session.query(Player).get(player_id)
    if not player:
        raise ValueError(f"Player {player_id} not found")
    
    # Get team info if specific team provided
    target_team = None
    if team_id:
        target_team = session.query(Team).get(team_id)
        if target_team:
            target_team = {
                'id': target_team.id,
                'name': target_team.name,
                'league_name': target_team.league.name if target_team.league else None
            }
    
    # Get all player teams (current season only)
    teams = get_current_season_teams(session, player)
    
    # Get Flask user roles for division role assignment
    user_roles = []
    if player.user and player.user.roles:
        user_roles = [role.name for role in player.user.roles]
    
    return {
        'player_id': player_id,
        'discord_id': player.discord_id,
        'name': player.name,
        'is_active': player.is_current_player,
        'is_coach': player.is_coach,
        'current_roles': player.discord_roles or [],
        'teams': teams,
        'user_roles': user_roles,
        'target_team': target_team,
        'only_add': only_add
    }


async def _execute_assign_roles_async(data):
    """Execute role assignment without database session."""
    # Use the same role calculation logic but only for target team if specified
    target_team = data.get('target_team')
    teams_to_process = [target_team] if target_team else data.get('teams', [])
    
    expected_roles = []
    
    # Add team roles
    for team in teams_to_process:
        if team and team.get('league_name') in ['Premier', 'Classic']:
            expected_roles.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Player")
    
    # Add league division roles if processing all teams (based on Flask user roles)
    if not target_team:
        user_roles = data.get('user_roles', [])
        if 'pl-premier' in user_roles:
            if 'ECS-FC-PL-PREMIER' not in expected_roles:
                expected_roles.append('ECS-FC-PL-PREMIER')
        if 'pl-classic' in user_roles:
            if 'ECS-FC-PL-CLASSIC' not in expected_roles:
                expected_roles.append('ECS-FC-PL-CLASSIC')
        
        # Add substitute roles based on Flask user roles
        if 'Premier Sub' in user_roles:
            if 'ECS-FC-PL-PREMIER-SUB' not in expected_roles:
                expected_roles.append('ECS-FC-PL-PREMIER-SUB')
        if 'Classic Sub' in user_roles:
            if 'ECS-FC-PL-CLASSIC-SUB' not in expected_roles:
                expected_roles.append('ECS-FC-PL-CLASSIC-SUB')
        if 'ECS FC Sub' in user_roles:
            if 'ECS-FC-LEAGUE-SUB' not in expected_roles:
                expected_roles.append('ECS-FC-LEAGUE-SUB')
        
        # Add coach roles based on leagues if player is coach
        if data.get('is_coach'):
            if 'pl-premier' in user_roles:
                if 'ECS-FC-PL-PREMIER-COACH' not in expected_roles:
                    expected_roles.append('ECS-FC-PL-PREMIER-COACH')
            if 'pl-classic' in user_roles:
                if 'ECS-FC-PL-CLASSIC-COACH' not in expected_roles:
                    expected_roles.append('ECS-FC-PL-CLASSIC-COACH')
    
    # Prepare data for async-only function
    player_data = {
        'id': data['player_id'],
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': data.get('current_roles', []),
        'expected_roles': expected_roles,
        'app_managed_roles': [
            'ECS-FC-PL-PREMIER',
            'ECS-FC-PL-CLASSIC',
            'ECS-FC-PL-PREMIER-COACH',
            'ECS-FC-PL-CLASSIC-COACH',
            'ECS-FC-PL-PREMIER-SUB',
            'ECS-FC-PL-CLASSIC-SUB',
            'ECS-FC-LEAGUE-SUB'
        ] + [f"ECS-FC-PL-{normalize_name(team['name'])}-Player" for team in data.get('teams', [])]
    }
    
    # Execute role assignment
    from app.discord_utils import update_player_roles_async_only
    only_add_value = data.get('only_add', True)
    force_update_value = not only_add_value
    logger.info(f"Task parameters: only_add={only_add_value}, force_update={force_update_value}")
    result = await update_player_roles_async_only(player_data, force_update=force_update_value)
    
    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'current_roles': result.get('current_roles', []),
        'roles_added': result.get('roles_added', []),
        'roles_removed': result.get('roles_removed', []),
        'player_id': data['player_id'],
        'timestamp': datetime.utcnow().isoformat()
    }


def _update_player_after_assign_roles(session, result):
    """Update player record after role assignment."""
    if not result.get('success'):
        return result
    
    player = session.query(Player).get(result['player_id'])
    if player:
        player.discord_roles_updated = datetime.utcnow()
        if result.get('success'):
            player.discord_role_sync_status = 'completed'
        else:
            player.discord_role_sync_status = 'failed'
            player.sync_error = result.get('message')
        player.last_sync_attempt = datetime.utcnow()
        if result.get('current_roles'):
            player.discord_roles = result['current_roles']
    
    return result


@celery_task(
    name='app.tasks.tasks_discord.assign_roles_to_player_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True,
    rate_limit='50/s'
)
async def assign_roles_to_player_task(self, session, player_id: int, team_id: Optional[int] = None, only_add: bool = True) -> Dict[str, Any]:
    """
    Assign or update Discord roles for a player using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        player_id: ID of the player.
        team_id: Optional team ID to scope role assignment.
        only_add: If True, only add roles; if False, remove roles not in the expected set.
        
    Returns:
        A dictionary with success status and details of the role assignment.
    """
    pass


# Attach phase methods
assign_roles_to_player_task._extract_data = _extract_assign_roles_data
assign_roles_to_player_task._execute_async = _execute_assign_roles_async
assign_roles_to_player_task._requires_final_db_update = True
assign_roles_to_player_task._final_db_update = _update_player_after_assign_roles
assign_roles_to_player_task._two_phase = True


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
                role_name = f"ECS-FC-PL-{normalize_name(team.name)}-Player"
                league_role_name = f"ECS-FC-PL-{team.league.name}"
                guild_id = Config.SERVER_ID

                # Retrieve role IDs and assign roles via the Discord API.
                role_id = await get_role_id(guild_id, role_name, aio_session)
                league_role_id = await get_role_id(guild_id, league_role_name, aio_session)

                if role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}",
                        session=aio_session
                    )
                if league_role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles/{league_role_id}",
                        session=aio_session
                    )
                return {'success': True}

            # Process role update for the player without team-specific roles.
            logger.debug(f"No team_id specified, calling process_single_player_update(only_add={only_add})")
            return await process_single_player_update(session, player, only_add=only_add)

    except Exception as e:
        logger.error(f"Exception assigning roles: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}


def _extract_fetch_role_status_data(session):
    """Extract player data for role status fetching using optimized streaming."""
    try:
        # Use memory-efficient streaming from query optimizer
        all_players_data = []
        
        with memory_efficient_session(session, BatchConfig(batch_size=100)) as efficient_session:
            for batch_data in stream_players_with_discord_ids(efficient_session, batch_size=100):
                all_players_data.extend(batch_data)
        
        logger.info(f"Successfully processed {len(all_players_data)} players using optimized streaming")
        return {'players': all_players_data}
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_fetch_role_status_data: {e}", exc_info=True)
        raise


async def _execute_fetch_role_status_async(data):
    """Execute role status fetching without database session."""
    players_data = data['players']
    results = []
    status_updates = []
    
    # Fetch roles for each player (simplified version of _fetch_roles_batch)
    async with aiohttp.ClientSession() as session:
        for player_data in players_data:
            try:
                # Get current roles from Discord
                roles = await get_member_roles(player_data['discord_id'], session)
                
                # Create result data
                teams_str = ", ".join(t['name'] for t in player_data['teams']) if player_data['teams'] else "No Team"
                leagues_str = ", ".join(sorted({t['league_name'] for t in player_data['teams'] if t['league_name']})) if player_data['teams'] else "No League"
                
                results.append({
                    'id': player_data['id'],
                    'name': player_data['name'],
                    'team': teams_str,
                    'league': leagues_str,
                    'current_roles': roles or [],
                    'expected_roles': [],  # Simplified for now
                    'status_html': '<span class="badge badge-success">Synced</span>',
                    'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    'roles_match': True
                })
                
                status_updates.append({
                    'id': player_data['id'],
                    'status': 'synced',
                    'current_roles': roles or []
                })
                
            except Exception as e:
                logger.error(f"Error fetching roles for player {player_data['name']}: {e}")
                results.append({
                    'id': player_data['id'],
                    'name': player_data['name'],
                    'team': "Error",
                    'league': "Error",
                    'error': str(e)
                })
                status_updates.append({
                    'id': player_data['id'],
                    'status': 'error',
                    'error': str(e)
                })
    
    return {
        'success': True,
        'role_results': results,
        'status_updates': status_updates,
        'fetched_at': datetime.utcnow().isoformat()
    }


def _update_players_after_fetch_role_status(session, result):
    """Update player records after role status fetch."""
    if not result.get('success'):
        return result
    
    # Update players with the latest role sync status
    for status in result.get('status_updates', []):
        player = session.query(Player).get(status['id'])
        if player:
            player.discord_role_sync_status = status['status']
            player.last_role_check = datetime.utcnow()
            if 'current_roles' in status:
                player.discord_roles = status['current_roles']
            if 'error' in status:
                player.sync_error = status['error']
    
    # Emit updated role status to clients
    try:
        from app import socketio
        socketio.emit('role_status_update', {
            'results': result['role_results'],
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.warning(f"Failed to emit socket event: {e}")
    
    return {
        'success': True,
        'results': result['role_results'],
        'fetched_at': result['fetched_at']
    }


@celery_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
async def fetch_role_status(self, session) -> Dict[str, Any]:
    """
    Fetch and update role status for players with a Discord ID using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        
    Returns:
        A dictionary with success status, results, and timestamp.
    """
    pass


# Attach phase methods
fetch_role_status._extract_data = _extract_fetch_role_status_data
fetch_role_status._execute_async = _execute_fetch_role_status_async
fetch_role_status._two_phase = True
fetch_role_status._requires_final_db_update = True
fetch_role_status._final_db_update = _update_players_after_fetch_role_status


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
                    expected_roles.add(f"ECS-FC-PL-{normalize_name(team.name)}-Player")
                
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
                    expected_roles.add(f"ECS-FC-PL-{normalize_name(team.name)}-Player")
                
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


def _extract_remove_roles_data(session, player_id: int, team_id: int):
    """Extract player data for role removal."""
    try:
        # OPTIMIZED: Load minimal player data, avoid nested joinedloads
        player = session.query(Player).options(
            selectinload(Player.user).selectinload(User.roles)
        ).get(player_id)
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_remove_roles_data: {e}")
        raise
    if not player:
        raise ValueError(f"Player {player_id} not found")
    
    # Get team info with minimal data
    target_team = session.query(Team).options(
        joinedload(Team.league)
    ).get(team_id)
    if not target_team:
        raise ValueError(f"Team {team_id} not found")
    
    # Get Flask user roles for division role assignment
    user_roles = []
    try:
        if player.user and player.user.roles:
            user_roles = [role.name for role in player.user.roles]
    except Exception as e:
        logger.warning(f"Could not load user roles for player {player.id}: {e}")
        user_roles = []
    
    return {
        'player_id': player_id,
        'team_id': team_id,
        'discord_id': player.discord_id,
        'name': player.name,
        'current_roles': player.discord_roles or [],
        'user_roles': user_roles,
        'target_team': {
            'id': target_team.id,
            'name': target_team.name,
            'league_name': target_team.league.name if target_team.league else None
        }
    }


async def _execute_remove_roles_async(data):
    """Execute role removal without database session."""
    target_team = data['target_team']
    
    # Calculate roles to remove for this specific team
    roles_to_remove = []
    if target_team and target_team.get('league_name') in ['Premier', 'Classic']:
        roles_to_remove.extend([
            f"ECS-FC-PL-{normalize_name(target_team['name'])}-Player",
            f"ECS-FC-PL-{normalize_name(target_team['name'])}-Coach"
        ])
    
    # Prepare data for role removal
    player_data = {
        'id': data['player_id'],
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': data.get('current_roles', []),
        'expected_roles': [],  # Empty - we want to remove roles
        'app_managed_roles': roles_to_remove  # Only these specific roles
    }
    
    # Execute role removal using existing function
    from app.discord_utils import update_player_roles_async_only
    result = await update_player_roles_async_only(player_data, force_update=True)
    
    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'roles_removed': result.get('roles_removed', []),
        'player_id': data['player_id'],
        'team_id': data['team_id'],
        'processed_at': datetime.utcnow().isoformat()
    }


def _update_player_after_role_removal(session, result):
    """Update player record after role removal."""
    if not result.get('success'):
        return result
    
    player = session.query(Player).get(result['player_id'])
    if player:
        if result.get('success'):
            # Don't clear all roles, just update with current state
            player.discord_last_verified = datetime.utcnow()
            player.last_role_removal = datetime.utcnow()
            player.role_removal_status = 'completed'
        else:
            player.role_removal_status = 'failed'
            player.last_role_removal = datetime.utcnow()
            if result.get('message'):
                player.role_removal_error = result['message']
    
    return {
        'success': True,
        'message': 'Roles removed successfully',
        'player_id': result['player_id'],
        'team_id': result['team_id'],
        'processed_at': result['processed_at'],
        'roles_removed': result.get('roles_removed', [])
    }


@celery_task(
    name='app.tasks.tasks_discord.remove_player_roles_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
async def remove_player_roles_task(self, session, player_id: int, team_id: int) -> Dict[str, Any]:
    """
    Remove Discord roles for a player using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        player_id: ID of the player.
        team_id: ID of the team.
        
    Returns:
        A dictionary with the result and updated player info.
    """
    pass


# Attach phase methods
remove_player_roles_task._extract_data = _extract_remove_roles_data
remove_player_roles_task._execute_async = _execute_remove_roles_async
remove_player_roles_task._two_phase = True
remove_player_roles_task._requires_final_db_update = True
remove_player_roles_task._final_db_update = _update_player_after_role_removal


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
                role_name = f"ECS-FC-PL-{normalize_name(team.name)}-Player"
                guild_id = int(Config.SERVER_ID)

                url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles"
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


def _extract_create_team_data(session, team_id: int):
    """Extract team data for Discord resource creation."""
    # Force a fresh read from the database to avoid stale data
    session.expire_all()
    
    team = session.query(Team).options(
        joinedload(Team.league)
    ).get(team_id)
    
    if not team:
        # Try one more time with a fresh query in case of timing issues
        session.rollback()  # Clear any potential issues
        team = session.query(Team).filter(Team.id == team_id).first()
        
        if not team:
            logger.error(f"Team {team_id} not found after retry - skipping Discord resource creation")
            # Log more debug info
            team_count = session.query(Team).count()
            logger.debug(f"Total teams in database: {team_count}")
            recent_teams = session.query(Team).order_by(Team.id.desc()).limit(10).all()
            logger.debug(f"Recent team IDs: {[t.id for t in recent_teams]}")
            return None
    
    logger.info(f"Found team {team_id}: {team.name} in league {team.league.name if team.league else 'No League'}")
    
    return {
        'team_id': team_id,
        'team_name': team.name,
        'league_name': team.league.name if team.league else None
    }


async def _execute_create_team_discord_async(data):
    """Execute Discord resource creation without database session."""
    # Create Discord channel using async-only approach
    from app.discord_utils import create_discord_channel_async_only
    
    channel_result = await create_discord_channel_async_only(
        data['team_name'], 
        data['league_name'], 
        data['team_id']
    )
    
    return {
        'success': channel_result.get('success', False),
        'message': channel_result.get('message', 'Discord resources created'),
        'channel_id': channel_result.get('channel_id'),
        'player_role_id': channel_result.get('player_role_id'),
        'team_id': data['team_id']
    }


def _update_team_after_discord_creation(session, result):
    """Update team record after Discord resource creation."""
    if not result.get('success'):
        return result
    
    team = session.query(Team).get(result['team_id'])
    if team:
        if result.get('channel_id'):
            team.discord_channel_id = result['channel_id']
        if result.get('player_role_id'):
            team.discord_player_role_id = result['player_role_id']
    
    return {'success': True, 'message': 'Discord resources created'}


@celery_task(name='app.tasks.tasks_discord.create_team_discord_resources_task', queue='discord')
async def create_team_discord_resources_task(self, session, team_id: int):
    """
    Create Discord resources for a new team using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        team_id: ID of the team.
        
    Returns:
        A dictionary indicating success or failure.
    """
    pass


# Attach phase methods - using both approaches for reliability
create_team_discord_resources_task._extract_data = _extract_create_team_data
create_team_discord_resources_task._execute_async = _execute_create_team_discord_async
create_team_discord_resources_task._requires_final_db_update = True
create_team_discord_resources_task._final_db_update = _update_team_after_discord_creation

# Also set the _two_phase attribute as a fallback
create_team_discord_resources_task._two_phase = True


async def delete_channel(channel_id: str) -> bool:
    """
    Async helper to delete a Discord channel.
    
    Args:
        channel_id: ID of the channel to delete.
        
    Returns:
        True if deletion was successful, False otherwise.
    """
    url = f"{Config.BOT_API_URL}/api/server/guilds/{Config.SERVER_ID}/channels/{channel_id}"
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
    url = f"{Config.BOT_API_URL}/api/server/guilds/{Config.SERVER_ID}/roles/{role_id}"
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
        
        # Use synchronous Discord client
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()
        
        if channel_id:
            result = discord_client.delete_channel(channel_id)
            if result.get('success', False):
                team.discord_channel_id = None
                session.flush()
        
        if role_id:
            result = discord_client.delete_role(role_id)
            if result.get('success', False):
                team.discord_player_role_id = None
                session.flush()
        
        # Commit happens automatically in @celery_task decorator
        return {'success': True, 'message': 'Discord resources cleaned up'}
            
    except Exception as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Error cleaning up Discord resources: {str(e)}")
        raise self.retry(exc=e, countdown=30)


def _extract_update_team_data(session, team_id: int, new_team_name: str):
    """Extract team data for Discord resource update."""
    team = session.query(Team).options(joinedload(Team.league)).get(team_id)
    if not team:
        raise ValueError(f"Team {team_id} not found")
    
    return {
        'team_id': team_id,
        'old_team_name': team.name,
        'new_team_name': new_team_name,
        'league_name': team.league.name if team.league else None,
        'discord_coach_role_id': team.discord_coach_role_id,
        'discord_player_role_id': team.discord_player_role_id,
        'discord_channel_id': team.discord_channel_id
    }


async def _execute_update_team_discord_async(data):
    """Execute Discord resource update without database session."""
    import os
    import aiohttp
    from app.utils.discord_request_handler import make_discord_request
    
    # Use async-only version of rename team roles
    from app.discord_utils import rename_team_roles_async_only
    
    # Rename roles
    role_result = await rename_team_roles_async_only(
        data['old_team_name'],
        data['new_team_name'],
        data['discord_coach_role_id'],
        data['discord_player_role_id']
    )
    
    # Rename channel if it exists
    channel_success = True
    channel_message = ""
    if data.get('discord_channel_id'):
        try:
            bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
            url = f"{bot_api_url}/api/server/channels/{data['discord_channel_id']}"
            
            async with aiohttp.ClientSession() as session:
                response = await make_discord_request('PATCH', url, session, json={'new_name': data['new_team_name']})
                if response:
                    logger.info(f"Renamed channel to: {data['new_team_name']}")
                    channel_message = f"Channel renamed to: {data['new_team_name']}"
                else:
                    logger.error(f"Failed to rename channel")
                    channel_success = False
                    channel_message = f"Failed to rename channel"
        except Exception as e:
            logger.error(f"Error renaming channel: {e}")
            channel_success = False
            channel_message = f"Error renaming channel: {e}"
    else:
        channel_message = "No channel to rename"
    
    # Combine results
    overall_success = role_result.get('success', False) and channel_success
    combined_message = f"{role_result.get('message', '')}. {channel_message}"
    
    return {
        'success': overall_success,
        'message': combined_message,
        'team_id': data['team_id']
    }


@celery_task(name='app.tasks.tasks_discord.update_team_discord_resources_task', queue='discord')
async def update_team_discord_resources_task(self, session, team_id: int, new_team_name: str):
    """
    Update Discord resources when a team's name changes using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        team_id: ID of the team.
        new_team_name: The new team name.
        
    Returns:
        A dictionary indicating success or failure.
    """
    pass


# Attach phase methods
update_team_discord_resources_task._extract_data = _extract_update_team_data
update_team_discord_resources_task._execute_async = _execute_update_team_discord_async
update_team_discord_resources_task._two_phase = True


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