"""
Discord Cleanup Tasks for Season Rollover

This module provides targeted cleanup of Discord resources during season rollover,
specifically for Pub League team channels and roles. It ensures only the correct
resources are deleted and preserves all other Discord elements.
"""

import logging
import aiohttp
import asyncio
import os
from app.models import Team, League, Season
from app.discord_utils import normalize_name

logger = logging.getLogger(__name__)


# Old function removed - functionality moved to two-phase pattern below


async def _delete_discord_channel_api(session: aiohttp.ClientSession, bot_api_url: str, guild_id: str, channel_id: str, team_name: str) -> bool:
    """
    Delete a specific Discord channel using the Discord bot API.
    
    Args:
        session: aiohttp ClientSession for making HTTP requests
        bot_api_url: Base URL of the Discord bot API
        guild_id: ID of the Discord guild
        channel_id: ID of the channel to delete
        team_name: Name of the team (for logging)
        
    Returns:
        bool: True if channel was deleted, False otherwise
    """
    max_retries = 3
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            url = f"{bot_api_url}/api/server/guilds/{guild_id}/channels/{channel_id}"
            logger.info(f"Attempting to delete Discord channel for team {team_name} via API: {url} (attempt {attempt + 1})")
            
            async with session.delete(url) as response:
                if response.status == 200:
                    logger.info(f"Successfully deleted Discord channel for team: {team_name}")
                    return True
                elif response.status == 404:
                    logger.warning(f"Discord channel not found for team: {team_name} (ID: {channel_id})")
                    return False
                elif response.status == 429:  # Rate limited
                    logger.warning(f"Rate limited when deleting channel for team: {team_name}, retrying in {retry_delay * (2 ** attempt)} seconds")
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete Discord channel for team {team_name}. Status: {response.status}, Error: {error_text}")
                    return False
                
        except Exception as e:
            logger.error(f"Error deleting Discord channel for team {team_name}: {e}")
            if attempt == max_retries - 1:
                return False
            await asyncio.sleep(retry_delay * (2 ** attempt))
    
    return False


async def _delete_discord_role_api(session: aiohttp.ClientSession, bot_api_url: str, guild_id: str, role_id: str, role_name: str) -> bool:
    """
    Delete a specific Discord role using the Discord bot API.
    
    Args:
        session: aiohttp ClientSession for making HTTP requests
        bot_api_url: Base URL of the Discord bot API
        guild_id: ID of the Discord guild
        role_id: ID of the role to delete
        role_name: Name of the role (for logging)
        
    Returns:
        bool: True if role was deleted, False otherwise
    """
    max_retries = 3
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            url = f"{bot_api_url}/api/server/guilds/{guild_id}/roles/{role_id}"
            logger.info(f"Attempting to delete Discord role {role_name} via API: {url} (attempt {attempt + 1})")
            
            async with session.delete(url) as response:
                if response.status == 200:
                    logger.info(f"Successfully deleted Discord role: {role_name}")
                    return True
                elif response.status == 404:
                    logger.warning(f"Discord role not found: {role_name} (ID: {role_id})")
                    return False
                elif response.status == 429:  # Rate limited
                    logger.warning(f"Rate limited when deleting role {role_name}, retrying in {retry_delay * (2 ** attempt)} seconds")
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete Discord role {role_name}. Status: {response.status}, Error: {error_text}")
                    return False
                
        except Exception as e:
            logger.error(f"Error deleting Discord role {role_name}: {e}")
            if attempt == max_retries - 1:
                return False
            await asyncio.sleep(retry_delay * (2 ** attempt))
    
    return False


def validate_cleanup_target(season_id: int, league_name: str, team_name: str) -> bool:
    """
    Validate that a cleanup target is appropriate for deletion.
    
    This is a safety check to ensure we're only deleting the correct resources.
    
    Args:
        season_id: ID of the season being cleaned up
        league_name: Name of the league
        team_name: Name of the team
        
    Returns:
        bool: True if the target is safe to delete, False otherwise
    """
    # Only allow cleanup of Premier and Classic team resources
    if league_name not in ['Premier', 'Classic']:
        logger.warning(f"Attempted to clean up non-team league: {league_name}")
        return False
    
    # Don't allow cleanup of placeholder team names that might be system-wide
    prohibited_names = ['FUN WEEK', 'BYE', 'TST', 'ADMIN', 'GLOBAL', 'LEAGUE', 'SYSTEM']
    if any(prohibited in team_name.upper() for prohibited in prohibited_names):
        logger.warning(f"Attempted to clean up prohibited team name: {team_name}")
        return False
    
    return True


# Celery task wrapper
from app.decorators import celery_task

def _extract_season_cleanup_data(session, old_season_id: int):
    """Extract all data needed for season Discord cleanup."""
    team_cleanup_data = []
    
    # Get the old season
    old_season = session.query(Season).get(old_season_id)
    if not old_season:
        raise ValueError(f"Season {old_season_id} not found")
    
    # Only process Pub League seasons
    if old_season.league_type != 'Pub League':
        return {
            'skip': True,
            'message': f'Skipped non-Pub League season: {old_season.league_type}'
        }
    
    # Get all leagues for this season
    leagues = session.query(League).filter_by(season_id=old_season_id).all()
    
    # Collect all team data that needs cleanup
    for league in leagues:
        # Only process Premier and Classic leagues
        if league.name not in ['Premier', 'Classic']:
            logger.info(f"Skipping non-team league: {league.name}")
            continue
            
        logger.info(f"Processing {league.name} league for cleanup")
        
        # Get all teams in this league
        teams = session.query(Team).filter_by(league_id=league.id).all()
        
        for team in teams:
            team_cleanup_data.append({
                'name': team.name,
                'discord_channel_id': team.discord_channel_id,
                'discord_coach_role_id': team.discord_coach_role_id,
                'discord_player_role_id': team.discord_player_role_id,
                'league_name': league.name
            })
    
    return {
        'skip': False,
        'season_id': old_season_id,
        'teams': team_cleanup_data
    }


async def _execute_season_cleanup_async(data):
    """Execute Discord cleanup without database session."""
    if data.get('skip'):
        return {'success': True, 'message': data['message']}
    
    return await _cleanup_discord_resources_async(data['teams'], data['season_id'])


@celery_task(name='cleanup_pub_league_discord_resources')
async def cleanup_pub_league_discord_resources_celery_task(self, session, old_season_id: int):
    """Celery task wrapper for Discord cleanup using standardized pattern."""
    # This function now uses the two-phase pattern automatically via the decorator
    pass


# Attach the two-phase methods to the task function
cleanup_pub_league_discord_resources_celery_task._extract_data = _extract_season_cleanup_data
cleanup_pub_league_discord_resources_celery_task._execute_async = _execute_season_cleanup_async
cleanup_pub_league_discord_resources_celery_task._two_phase = True


async def _cleanup_discord_resources_async(team_cleanup_data: list, season_id: int) -> dict:
    """
    Perform the actual Discord cleanup without holding database sessions.
    
    Args:
        team_cleanup_data: List of team data dictionaries with Discord IDs
        season_id: Season ID for logging
        
    Returns:
        dict: Result with success status and message/error
    """
    try:
        logger.info(f"Starting Discord cleanup for season {season_id} with {len(team_cleanup_data)} teams")
        
        # Get Discord bot API configuration
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        guild_id = os.getenv('SERVER_ID')
        
        if not guild_id:
            logger.error("SERVER_ID environment variable not set")
            return {'success': False, 'error': 'SERVER_ID environment variable not set'}
        
        teams_cleaned = 0
        channels_deleted = 0
        roles_deleted = 0
        
        async with aiohttp.ClientSession() as session_http:
            for team_data in team_cleanup_data:
                try:
                    # Clean up team Discord channel
                    if team_data['discord_channel_id']:
                        channel_deleted = await _delete_discord_channel_api(
                            session_http, bot_api_url, guild_id, team_data['discord_channel_id'], team_data['name']
                        )
                        if channel_deleted:
                            channels_deleted += 1
                        # Add delay to avoid rate limits
                        await asyncio.sleep(0.5)
                    
                    # Clean up team coach role
                    if team_data['discord_coach_role_id']:
                        role_deleted = await _delete_discord_role_api(
                            session_http, bot_api_url, guild_id, team_data['discord_coach_role_id'], f"{team_data['name']} Coach"
                        )
                        if role_deleted:
                            roles_deleted += 1
                        # Add delay to avoid rate limits
                        await asyncio.sleep(0.5)
                    
                    # Clean up team player role
                    if team_data['discord_player_role_id']:
                        role_deleted = await _delete_discord_role_api(
                            session_http, bot_api_url, guild_id, team_data['discord_player_role_id'], f"ECS-FC-PL-{normalize_name(team_data['name'])}-Player"
                        )
                        if role_deleted:
                            roles_deleted += 1
                        # Add delay to avoid rate limits
                        await asyncio.sleep(0.5)
                    
                    teams_cleaned += 1
                    logger.info(f"Cleaned up Discord resources for team: {team_data['name']}")
                    
                    # Add delay between teams to avoid rate limits
                    await asyncio.sleep(1.0)
                    
                except Exception as e:
                    logger.error(f"Error cleaning up team {team_data['name']}: {e}")
                    continue
        
        logger.info(f"Discord cleanup completed: {teams_cleaned} teams, {channels_deleted} channels, {roles_deleted} roles")
        return {'success': True, 'message': f'Discord cleanup completed for season {season_id}: {teams_cleaned} teams, {channels_deleted} channels, {roles_deleted} roles'}
        
    except Exception as e:
        logger.error(f"Error in Discord cleanup: {e}")
        return {'success': False, 'error': str(e)}


# Old function removed - functionality moved to two-phase pattern below


def _extract_league_cleanup_data(session, league_id: int):
    """Extract all data needed for league Discord cleanup."""
    # Get the league
    league = session.query(League).get(league_id)
    if not league:
        raise ValueError(f"League {league_id} not found")
    
    # Only process Premier and Classic leagues (team-based leagues)
    if league.name not in ['Premier', 'Classic']:
        return {
            'skip': True,
            'message': f'Skipped non-team league: {league.name}'
        }
    
    # Get all teams in this league
    teams = session.query(Team).filter_by(league_id=league_id).all()
    
    # Collect all team data that needs cleanup
    team_cleanup_data = []
    for team in teams:
        team_cleanup_data.append({
            'name': team.name,
            'discord_channel_id': team.discord_channel_id,
            'discord_coach_role_id': team.discord_coach_role_id,
            'discord_player_role_id': team.discord_player_role_id
        })
    
    return {
        'skip': False,
        'league_id': league_id,
        'league_name': league.name,
        'teams': team_cleanup_data
    }


async def _execute_league_cleanup_async(data):
    """Execute league Discord cleanup without database session."""
    if data.get('skip'):
        return {'success': True, 'message': data['message']}
    
    return await _cleanup_league_discord_resources_async(
        data['teams'], data['league_id'], data['league_name']
    )


@celery_task(name='cleanup_league_discord_resources')
async def cleanup_league_discord_resources_task(self, session, league_id: int):
    """Celery task wrapper for league Discord cleanup using standardized pattern."""
    # This function now uses the two-phase pattern automatically via the decorator
    pass


# Attach the two-phase methods to the task function
cleanup_league_discord_resources_task._extract_data = _extract_league_cleanup_data
cleanup_league_discord_resources_task._execute_async = _execute_league_cleanup_async
cleanup_league_discord_resources_task._two_phase = True


async def _cleanup_league_discord_resources_async(team_cleanup_data: list, league_id: int, league_name: str) -> dict:
    """
    Perform the actual Discord cleanup for a league without holding database sessions.
    
    Args:
        team_cleanup_data: List of team data dictionaries with Discord IDs
        league_id: League ID for logging
        league_name: League name for logging
        
    Returns:
        dict: Result with success status and message/error
    """
    try:
        logger.info(f"Starting Discord cleanup for league {league_name} ({league_id}) with {len(team_cleanup_data)} teams")
        
        # Get Discord bot API configuration
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        guild_id = os.getenv('SERVER_ID')
        
        if not guild_id:
            logger.error("SERVER_ID environment variable not set")
            return {'success': False, 'error': 'SERVER_ID environment variable not set'}
        
        teams_cleaned = 0
        channels_deleted = 0
        roles_deleted = 0
        
        async with aiohttp.ClientSession() as session_http:
            for team_data in team_cleanup_data:
                try:
                    # Clean up team Discord channel
                    if team_data['discord_channel_id']:
                        channel_deleted = await _delete_discord_channel_api(
                            session_http, bot_api_url, guild_id, team_data['discord_channel_id'], team_data['name']
                        )
                        if channel_deleted:
                            channels_deleted += 1
                    
                    # Clean up team coach role
                    if team_data['discord_coach_role_id']:
                        role_deleted = await _delete_discord_role_api(
                            session_http, bot_api_url, guild_id, team_data['discord_coach_role_id'], f"{team_data['name']} Coach"
                        )
                        if role_deleted:
                            roles_deleted += 1
                    
                    # Clean up team player role
                    if team_data['discord_player_role_id']:
                        role_deleted = await _delete_discord_role_api(
                            session_http, bot_api_url, guild_id, team_data['discord_player_role_id'], f"ECS-FC-PL-{normalize_name(team_data['name'])}-Player"
                        )
                        if role_deleted:
                            roles_deleted += 1
                    
                    teams_cleaned += 1
                    logger.info(f"Cleaned up Discord resources for team: {team_data['name']}")
                    
                except Exception as e:
                    logger.error(f"Error cleaning up team {team_data['name']}: {e}")
                    # Continue with other teams even if one fails
        
        logger.info(f"Discord cleanup completed for league {league_name}: {teams_cleaned} teams processed, {channels_deleted} channels deleted, {roles_deleted} roles deleted")
        return {'success': True, 'message': f'Discord cleanup completed for league {league_name}: {teams_cleaned} teams, {channels_deleted} channels, {roles_deleted} roles'}
        
    except Exception as e:
        logger.error(f"Error during Discord cleanup for league {league_id}: {e}")
        return {'success': False, 'error': str(e)}