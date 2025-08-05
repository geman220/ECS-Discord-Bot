# app/discord_utils.py

"""
Discord Utilities Module

This module contains helper classes and functions for interacting with the Discord API,
including rate limiting, role and channel management, and higher-level logic such as creating
match threads and synchronizing player roles.
"""

import os
import aiohttp
import asyncio
import logging
import time
import re
from functools import wraps
from typing import Optional, List, Dict, Any, Union
from zoneinfo import ZoneInfo

from web_config import Config

from app.models import Team, Player, MLSMatch, League, player_teams
from sqlalchemy.orm import Session
from sqlalchemy import update
from app.utils.discord_request_handler import make_discord_request

logger = logging.getLogger(__name__)

# Permission constants (Discord permission bits)
VIEW_CHANNEL = 1024
SEND_MESSAGES = 2048
READ_MESSAGE_HISTORY = 65536
SEND_MESSAGES_IN_THREADS = 274877906944
CREATE_PUBLIC_THREADS = 34359738368
MANAGE_MESSAGES = 8192
USE_APPLICATION_COMMANDS = 2147483648

# Permission sets for different roles
TEAM_PLAYER_PERMISSIONS = (
    VIEW_CHANNEL + 
    SEND_MESSAGES + 
    READ_MESSAGE_HISTORY + 
    SEND_MESSAGES_IN_THREADS + 
    CREATE_PUBLIC_THREADS + 
    USE_APPLICATION_COMMANDS
)  # 277077967872

LEADERSHIP_PERMISSIONS = (
    VIEW_CHANNEL + 
    SEND_MESSAGES + 
    READ_MESSAGE_HISTORY + 
    SEND_MESSAGES_IN_THREADS + 
    CREATE_PUBLIC_THREADS + 
    MANAGE_MESSAGES + 
    USE_APPLICATION_COMMANDS
)  # 277077976064

# Legacy permission constant (for backward compatibility)
TEAM_ROLE_PERMISSIONS = VIEW_CHANNEL + SEND_MESSAGES + READ_MESSAGE_HISTORY  # 68608

# Rate limit constants
GLOBAL_RATE_LIMIT = 50  # Adjust according to Discord's global rate limit per second

# Global caches for categories and roles
category_cache: Dict[str, str] = {}
role_name_cache: Dict[str, str] = {}

class RateLimiter:
    """
    A simple rate limiter to control the number of API calls per period.

    Supports both synchronous and asynchronous usage.
    """
    def __init__(self, max_calls: int, period: float):
        self._max_calls = max_calls
        self._period = period
        self._calls = 0
        self._reset_time = time.time()
        self._lock = asyncio.Lock() if hasattr(asyncio, 'Lock') else None

    def _should_reset(self, current_time: float) -> bool:
        return current_time >= self._reset_time + self._period

    def _reset_counter(self, current_time: float) -> None:
        self._reset_time = current_time
        self._calls = 0

    def acquire_sync(self) -> None:
        current_time = time.time()
        if self._should_reset(current_time):
            self._reset_counter(current_time)
        if self._calls >= self._max_calls:
            wait_time = self._reset_time + self._period - current_time
            logger.warning(f"Rate limiter sleeping for {wait_time:.2f} seconds")
            time.sleep(wait_time)
            self._reset_counter(time.time())
        self._calls += 1

    async def acquire_async(self) -> None:
        if not self._lock:
            self._lock = asyncio.Lock()
        async with self._lock:
            current_time = time.time()
            if self._should_reset(current_time):
                self._reset_counter(current_time)
            if self._calls >= self._max_calls:
                wait_time = self._reset_time + self._period - current_time
                logger.warning(f"Rate limiter sleeping for {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
                self._reset_counter(time.time())
            self._calls += 1

    def limit(self):
        """
        Decorator that applies rate limiting to a function (sync or async).
        """
        def rate_limit_decorator(func):
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                self.acquire_sync()
                return func(*args, **kwargs)
            
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                await self.acquire_async()
                return await func(*args, **kwargs)
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return rate_limit_decorator


rate_limiter = RateLimiter(max_calls=GLOBAL_RATE_LIMIT, period=1)


def normalize_name(name: str) -> str:
    """
    Normalize a name to match Discord's role naming conventions.

    Args:
        name (str): The input name.

    Returns:
        str: Normalized name.
    """
    return name.strip().upper().replace(' ', '-').replace('_', '-')


# ---------------------------
# Role Management Functions
# ---------------------------

async def get_role_id(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Optional[str]:
    """
    Retrieve the ID of a role by its name, using cache and refreshing if necessary.

    Args:
        guild_id (int): The Discord guild ID.
        role_name (str): The role name to look up.
        session (aiohttp.ClientSession): The HTTP session for making Discord API calls.

    Returns:
        Optional[str]: The role ID if found, else None.
    """
    logger.info(f"Looking up role ID for name: '{role_name}'")

    # Check cache for an exact or normalized match
    if role_name in role_name_cache:
        logger.info(f"Exact cache hit for role '{role_name}': {role_name_cache[role_name]}")
        return role_name_cache[role_name]
    
    target_normalized = normalize_name(role_name)
    logger.info(f"Role '{role_name}' normalized to: '{target_normalized}'")
    
    # Check if any cached roles match when normalized
    for cached_name, rid in role_name_cache.items():
        cached_normalized = normalize_name(cached_name)
        if cached_normalized == target_normalized:
            logger.info(f"Normalized cache hit: '{role_name}' -> '{cached_name}' (both normalize to '{target_normalized}'): {rid}")
            return rid
    
    logger.info(f"No cached role matches '{role_name}' (normalized: '{target_normalized}')")
    logger.debug(f"Available cached roles: {list(role_name_cache.keys())}")

    # Fetch roles from Discord API and refresh cache
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response:
        role_name_cache.clear()
        role_name_cache.update({role['name']: role['id'] for role in response})
        logger.info(f"Updated role cache with {len(response)} roles from Discord API")
        
        # Log coach-related roles for debugging
        coach_roles = [role['name'] for role in response if 'COACH' in role['name'].upper()]
        if coach_roles:
            logger.info(f"Found existing coach roles on Discord: {coach_roles}")
        
        # Check for exact match first
        if role_name in role_name_cache:
            logger.info(f"Exact match found after cache refresh: '{role_name}' -> {role_name_cache[role_name]}")
            return role_name_cache[role_name]
            
        # Check for normalized match
        for discord_role in response:
            discord_normalized = normalize_name(discord_role['name'])
            if discord_normalized == target_normalized:
                logger.info(f"Normalized match found: '{role_name}' ('{target_normalized}') matches Discord role '{discord_role['name']}' ('{discord_normalized}') -> {discord_role['id']}")
                return discord_role['id']
                
        # Log what we're looking for vs what exists for coach roles
        if 'COACH' in target_normalized:
            logger.warning(f"Coach role '{role_name}' (normalized: '{target_normalized}') not found in Discord. Existing coach roles: {coach_roles}")
    else:
        logger.error(f"Failed to fetch roles from Discord API")
        
    logger.error(f"Role not found: '{role_name}' (normalized: '{target_normalized}')")
    return None


async def create_role(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Optional[str]:
    """
    Create a new role in the specified guild.

    Args:
        guild_id (int): The Discord guild ID.
        role_name (str): The desired role name.
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        Optional[str]: The created role's ID if successful, else None.
    """
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/roles"
    payload = {"name": role_name}
    response = await make_discord_request('POST', url, session, json=payload)
    if response and 'id' in response:
        role_id = response['id']
        role_name_cache[role_name] = role_id
        logger.info(f"Created role '{role_name}' with ID {role_id}")
        return role_id
    logger.error(f"Failed to create role '{role_name}'")
    return None


async def get_or_create_role(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Optional[str]:
    """
    Retrieve an existing role ID by name or create a new role if not found.

    Args:
        guild_id (int): The Discord guild ID.
        role_name (str): The role name.
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        Optional[str]: The role ID.
    """
    logger.info(f"get_or_create_role called for: '{role_name}' in guild {guild_id}")
    
    existing_id = await get_role_id(guild_id, role_name, session)
    if existing_id:
        logger.info(f"Found existing role '{role_name}': {existing_id}")
        return existing_id
        
    normalized_name = normalize_name(role_name)
    logger.info(f"Role '{role_name}' not found, creating new role with normalized name: '{normalized_name}'")
    
    created_id = await create_role(guild_id, normalized_name, session)
    if created_id:
        logger.info(f"Successfully created new role '{normalized_name}': {created_id}")
    else:
        logger.error(f"Failed to create role '{normalized_name}'")
    
    return created_id


async def assign_role_to_member(guild_id: int, user_id: str, role_id: Union[str, int],
                                session: aiohttp.ClientSession) -> None:
    """
    Assign a role to a Discord member.

    Args:
        guild_id (int): The Discord guild ID.
        user_id (str): The Discord user ID.
        role_id (Union[str, int]): The role ID (or name to be resolved).
        session (aiohttp.ClientSession): The HTTP session.
    """
    role_id = str(role_id)
    logger.debug(f"Assigning role {role_id} to user {user_id}")
    try:
        if not role_id.isdigit():
            resolved_id = await get_role_id(guild_id, role_id, session)
            if not resolved_id:
                logger.error(f"Could not find role ID for role name '{role_id}'")
                return
            role_id = resolved_id

        url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
        result = await make_discord_request('PUT', url, session)
        if result:
            logger.info(f"Successfully assigned role {role_id} to user {user_id}")
        else:
            logger.error(f"Failed to assign role {role_id} to user {user_id}")
    except Exception as e:
        logger.error(f"Error assigning role {role_id} to user {user_id}: {str(e)}")
        raise


@rate_limiter.limit()
async def remove_role_from_member(guild_id: int, user_id: str, role_id: Union[str, int],
                                  session: aiohttp.ClientSession) -> None:
    """
    Remove a role from a Discord member.

    Args:
        guild_id (int): The Discord guild ID.
        user_id (str): The Discord user ID.
        role_id (Union[str, int]): The role ID (or name to resolve).
        session (aiohttp.ClientSession): The HTTP session.
    """
    role_id = str(role_id)
    if not role_id.isdigit():
        resolved_id = await get_role_id(guild_id, role_id, session)
        if not resolved_id:
            logger.error(f"Could not find role ID for role name '{role_id}'")
            return
        role_id = resolved_id

    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    await make_discord_request('DELETE', url, session)
    logger.info(f"Removed role '{role_id}' from user '{user_id}'")


async def delete_role(guild_id: int, role_id: Union[str, int], session: aiohttp.ClientSession) -> None:
    """
    Delete a role from a guild.

    Args:
        guild_id (int): The Discord guild ID.
        role_id (Union[str, int]): The role ID (or name to resolve).
        session (aiohttp.ClientSession): The HTTP session.
    """
    role_id = str(role_id)
    if not role_id.isdigit():
        resolved_id = await get_role_id(guild_id, role_id, session)
        if not resolved_id:
            logger.error(f"Could not find role ID for role name '{role_id}'")
            return
        role_id = resolved_id

    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/roles/{role_id}"
    response = await make_discord_request('DELETE', url, session)
    if response:
        logger.info(f"Deleted role ID {role_id}")
        role_name = next((name for name, rid in role_name_cache.items() if rid == role_id), None)
        if role_name:
            del role_name_cache[role_name]
    else:
        logger.error(f"Failed to delete role ID {role_id}")


# ---------------------------
# Channel / Category Helpers
# ---------------------------

async def get_member_roles(user_id: str, session: aiohttp.ClientSession) -> Optional[List[str]]:
    """
    Retrieve a list of role names for a Discord member.

    Args:
        user_id (str): The Discord user ID.
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        Optional[List[str]]: List of role names, or None if failed.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response is None:
        return None
    if 'roles' in response:
        role_ids = []
        if isinstance(response['roles'], list):
            if all(isinstance(r, dict) for r in response['roles']):
                role_ids = [str(r.get('id')) for r in response['roles']]
            else:
                role_ids = [str(r) for r in response['roles']]
        elif isinstance(response['roles'], dict):
            role_ids = list(response['roles'].keys())
        return await get_role_names(guild_id, role_ids, session)
    return []


async def get_role_names(guild_id: int, role_ids: List[str], session: aiohttp.ClientSession) -> List[str]:
    """
    Convert a list of role IDs to role names using cache or by querying the Discord API.

    Args:
        guild_id (int): The Discord guild ID.
        role_ids (List[str]): List of role IDs.
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        List[str]: List of role names.
    """
    try:
        missing_role_ids = [r for r in role_ids if r not in role_name_cache.values()]
        if missing_role_ids:
            url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/roles"
            response = await make_discord_request('GET', url, session)
            if response:
                for role in response:
                    role_name_cache[role['name']] = role['id']
        id_to_name = {v: k for k, v in role_name_cache.items()}
        return [id_to_name.get(rid, rid) for rid in role_ids]
    except Exception as e:
        logger.error(f"Error getting role names: {e}")
        return role_ids


async def get_or_create_category(guild_id: int, category_name: str, session: aiohttp.ClientSession) -> Optional[str]:
    """
    Retrieve an existing category ID by name or create a new category.

    Args:
        guild_id (int): The Discord guild ID.
        category_name (str): The category name.
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        Optional[str]: The category ID.
    """
    if category_name in category_cache:
        return category_cache[category_name]

    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/channels"
    channels = await make_discord_request('GET', url, session)
    if channels:
        for channel in channels:
            if channel['type'] == 4 and channel['name'].lower() == category_name.lower():
                category_id = channel['id']
                category_cache[category_name] = category_id
                return category_id
    return await create_category(guild_id, category_name, session)


async def create_category(guild_id: int, category_name: str, session: aiohttp.ClientSession) -> Optional[str]:
    """
    Create a new category in the specified guild.

    Args:
        guild_id (int): The Discord guild ID.
        category_name (str): The desired category name.
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        Optional[str]: The newly created category ID.
    """
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/channels"
    payload = {"name": category_name, "type": 4}
    response = await make_discord_request('POST', url, session, json=payload)
    if response and 'id' in response:
        category_id = response['id']
        category_cache[category_name] = category_id
        logger.info(f"Created category '{category_name}' with ID {category_id}")
        return category_id
    logger.error(f"Failed to create category '{category_name}'")
    return None


# ---------------------------
# Higher-Level Logic
# ---------------------------

async def create_discord_roles(session: Session, team_name: str, team_id: int) -> Dict[str, Any]:
    """
    Create or retrieve a 'Player' role for the team and store its ID in the database.

    Args:
        session (Session): The database session.
        team_name (str): The team's name.
        team_id (int): The team's ID.

    Returns:
        Dict[str, Any]: Result with success status and role ID or error message.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    player_role_name = f"ECS-FC-PL-{team_name}-Player"
    try:
        async with aiohttp.ClientSession() as http_session:
            player_role_id = await get_or_create_role(guild_id, player_role_name, http_session)
            if not player_role_id:
                return {'success': False, 'error': 'Failed to create role'}
            team = session.query(Team).get(team_id)
            team.discord_player_role_id = player_role_id
            session.commit()
            logger.info(f"Created or retrieved role for team {team_name}: Player Role ID {player_role_id}")
            return {'success': True, 'role_id': player_role_id}
    except Exception as e:
        logger.error(f"Error creating role: {str(e)}")
        return {'success': False, 'error': str(e)}


async def create_discord_channel_async_only(team_name: str, division: str, team_id: int) -> Dict[str, Any]:
    """
    Create a dedicated Discord channel for a team without database session.
    
    Args:
        team_name: The team's name
        division: Division identifier  
        team_id: The team's ID
        
    Returns:
        Dict with success status and channel_id if successful
    """
    try:
        guild_id = int(os.getenv('SERVER_ID'))
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        category_name = f"ECS FC PL {division.capitalize()}"
        
        async with aiohttp.ClientSession() as session:
            # First, get or create the category
            category_id = await get_or_create_category(guild_id, category_name, session)
            if not category_id:
                return {'success': False, 'message': f"Failed to get/create category '{category_name}'"}
            
            # Create or get the required Discord roles
            player_role_name = f"ECS-FC-PL-{team_name}-Player"
            player_role_id = await get_or_create_role(guild_id, player_role_name, session)
            if not player_role_id:
                return {'success': False, 'message': f"Failed to create player role '{player_role_name}'"}
                
            # Get admin and leadership roles
            wg_admin_role_id = await get_or_create_role(guild_id, "WG: ECS FC ADMIN", session)
            pl_leadership_role_id = await get_or_create_role(guild_id, "WG: ECS FC PL Leadership", session)
            
            # Set up permission overwrites
            permission_overwrites = [
                {"id": str(guild_id), "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"},
                {"id": str(player_role_id), "type": 0, "allow": str(TEAM_PLAYER_PERMISSIONS), "deny": "0"},
            ]
            
            # Add admin permissions if roles exist
            if wg_admin_role_id:
                permission_overwrites.append({"id": str(wg_admin_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"})
            if pl_leadership_role_id:
                permission_overwrites.append({"id": str(pl_leadership_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"})
            
            # Create channel with proper setup
            channel_data = {
                'name': team_name,
                'type': 0,  # Text channel
                'topic': f"Team channel for {team_name} ({division})",
                'parent_id': category_id,
                'permission_overwrites': permission_overwrites
            }
            
            url = f"{bot_api_url}/api/server/guilds/{guild_id}/channels"
            response = await make_discord_request('POST', url, session, json=channel_data)
            
            if response and 'id' in response:
                channel_id = response['id']
                logger.info(f"Created Discord channel '{team_name}' with ID {channel_id} in category '{category_name}'")
                return {
                    'success': True,
                    'channel_id': channel_id,
                    'player_role_id': player_role_id,
                    'message': f'Channel created for {team_name} in {category_name}'
                }
            else:
                logger.error(f"Failed to create Discord channel for {team_name}")
                return {
                    'success': False,
                    'message': 'Failed to create channel'
                }
                    
    except Exception as e:
        logger.error(f"Error creating Discord channel for {team_name}: {e}")
        return {
            'success': False,
            'message': str(e)
        }


async def rename_team_roles_async_only(old_team_name: str, new_team_name: str, coach_role_id: str, player_role_id: str) -> Dict[str, Any]:
    """
    Rename team roles without database session.
    
    Args:
        old_team_name: Current team name
        new_team_name: New team name
        coach_role_id: Discord coach role ID
        player_role_id: Discord player role ID
        
    Returns:
        Dict with success status
    """
    try:
        guild_id = int(os.getenv('SERVER_ID'))
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        
        async with aiohttp.ClientSession() as session:
            success_count = 0
            total_roles = 0
            
            # Rename coach role
            if coach_role_id:
                total_roles += 1
                new_coach_name = f"ECS-FC-PL-{normalize_name(new_team_name)}-Coach"
                url = f"{bot_api_url}/api/server/guilds/{guild_id}/roles/{coach_role_id}"
                async with session.patch(url, json={'new_name': new_coach_name}) as response:
                    if response.status == 200:
                        success_count += 1
                        logger.info(f"Renamed coach role to: {new_coach_name}")
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to rename coach role: {error_text}")
            
            # Rename player role
            if player_role_id:
                total_roles += 1
                new_player_name = f"ECS-FC-PL-{normalize_name(new_team_name)}-Player"
                url = f"{bot_api_url}/api/server/guilds/{guild_id}/roles/{player_role_id}"
                async with session.patch(url, json={'new_name': new_player_name}) as response:
                    if response.status == 200:
                        success_count += 1
                        logger.info(f"Renamed player role to: {new_player_name}")
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to rename player role: {error_text}")
            
            return {
                'success': success_count == total_roles,
                'message': f'Renamed {success_count}/{total_roles} roles for team {new_team_name}'
            }
            
    except Exception as e:
        logger.error(f"Error renaming team roles: {e}")
        return {
            'success': False,
            'message': str(e)
        }


async def create_match_thread_async_only(match_data: Dict[str, Any]) -> Optional[str]:
    """
    Create a Discord thread for an MLS match without database session.
    
    Args:
        match_data: Dictionary containing match information
        
    Returns:
        Thread ID if successful, None otherwise
    """
    try:
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        
        # Create thread payload
        thread_data = {
            'match_id': match_data['id'],
            'home_team': match_data['home_team'],
            'away_team': match_data['away_team'],
            'date': match_data.get('date'),
            'time': match_data.get('time'),
            'venue': match_data.get('venue'),
            'competition': match_data.get('competition'),
            'summary_link': match_data.get('summary_link'),
            'stats_link': match_data.get('stats_link'),
            'commentary_link': match_data.get('commentary_link')
        }
        
        async with aiohttp.ClientSession() as session:
            url = f"{bot_api_url}/api/create_match_thread"
            async with session.post(url, json=thread_data, timeout=30) as response:
                if response.status == 200:
                    result = await response.json()
                    thread_id = result.get('thread_id')
                    logger.info(f"Created Discord thread for match {match_data['id']}: {thread_id}")
                    return thread_id
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create Discord thread: {error_text}")
                    return None
                    
    except Exception as e:
        logger.error(f"Error creating Discord thread for match {match_data.get('id', 'unknown')}: {e}")
        return None


async def create_discord_channel(session: Session, team_name: str, division: str, team_id: int) -> Dict[str, Any]:
    """
    Create a dedicated Discord channel for a team under a specific category.

    Args:
        session (Session): The database session.
        team_name (str): The team's name.
        division (str): Division identifier.
        team_id (int): The team's ID.

    Returns:
        Dict[str, Any]: Result with success status and channel ID or error message.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    category_name = f"ECS FC PL {division.capitalize()}"
    try:
        async with aiohttp.ClientSession() as http_session:
            category_id = await get_or_create_category(guild_id, category_name, http_session)
            if not category_id:
                return {'success': False, 'error': f"Failed to get/create category '{category_name}'"}
            
            role_result = await create_discord_roles(session, team_name, team_id)
            if not role_result.get('success'):
                return role_result
            
            team = session.query(Team).get(team_id)
            if not team.discord_player_role_id:
                return {'success': False, 'error': 'Player role ID not found'}
            
            wg_admin_role_id = await get_or_create_role(guild_id, "WG: ECS FC ADMIN", http_session)
            pl_leadership_role_id = await get_or_create_role(guild_id, "WG: ECS FC PL Leadership", http_session)
            
            permission_overwrites = [
                {"id": str(guild_id), "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"},
                {"id": str(team.discord_player_role_id), "type": 0, "allow": str(TEAM_PLAYER_PERMISSIONS), "deny": "0"},
                {"id": str(wg_admin_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"},
                {"id": str(pl_leadership_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"},
            ]
            payload = {
                "name": team_name,
                "parent_id": category_id,
                "type": 0,  # text channel
                "permission_overwrites": permission_overwrites,
            }
            url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/channels"
            response = await make_discord_request('POST', url, http_session, json=payload)
            if response and 'id' in response:
                team.discord_channel_id = response['id']
                session.commit()
                logger.info(f"Created Discord channel '{team_name}' with ID {team.discord_channel_id}")
                return {'success': True, 'channel_id': team.discord_channel_id}
            else:
                return {'success': False, 'error': 'Failed to create channel'}
    except Exception as e:
        logger.error(f"Error creating channel: {str(e)}")
        return {'success': False, 'error': str(e)}


async def assign_roles_to_player(guild_id: int, player: Player) -> None:
    """
    Assign the expected Discord roles to a player based on team and league membership.

    Args:
        guild_id (int): The Discord guild ID.
        player (Player): The player instance.
    """
    if not player.discord_id or not player.teams:
        logger.warning(f"Player '{player.name}' has no Discord ID or no team assigned.")
        return

    async with aiohttp.ClientSession() as http_session:
        expected_roles = await get_expected_roles(session=None, player=player)
        for role_name in expected_roles:
            role_id = await get_or_create_role(guild_id, role_name, http_session)
            if role_id:
                await assign_role_to_member(guild_id, player.discord_id, role_id, http_session)
                logger.info(f"Assigned role '{role_name}' (ID: {role_id}) to player '{player.name}'")
            else:
                logger.error(f"Failed to get/create role '{role_name}' for player '{player.name}'")


def get_league_role_name(league_name: str) -> Optional[str]:
    """
    Normalize and map a league name to a standardized role name.

    Args:
        league_name (str): The league name.

    Returns:
        Optional[str]: The standardized role name if found, else None.
    """
    normalized = normalize_name(league_name)
    logger.debug(f"Raw league name: {league_name} → Normalized: {normalized}")
    league_map = {
        'PREMIER': 'ECS-FC-PL-PREMIER',
        'CLASSIC': 'ECS-FC-PL-CLASSIC',
        'ECS-FC': 'ECS-FC-LEAGUE'
    }
    role = league_map.get(normalized)
    logger.debug(f"Mapped role: {role}")
    return role


async def remove_player_roles(session: Session, player: Player) -> None:
    """
    Remove roles from a player across all teams.

    Args:
        session (Session): The database session.
        player (Player): The player instance.
    """
    if not player.discord_id or not player.teams:
        logger.warning(f"Player '{player.name}' has no Discord ID or teams assigned.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    role_name_suffix = 'Coach' if player.is_coach else 'Player'
    
    async with aiohttp.ClientSession() as http_session:
        for t in player.teams:
            team_role_name = f"ECS-FC-PL-{t.name}-{role_name_suffix}"
            team_role_id = await get_role_id(guild_id, team_role_name, http_session)
            if team_role_id:
                await remove_role_from_member(guild_id, player.discord_id, team_role_id, http_session)
                logger.info(f"Removed role '{team_role_name}' from player '{player.name}'")
            else:
                logger.error(f"Team role '{team_role_name}' not found for player '{player.name}'")


async def rename_team_roles(session: Session, team: Team, new_team_name: str) -> None:
    """
    Rename the team's associated roles and channels to reflect a new team name.

    Args:
        session (Session): The database session.
        team (Team): The team instance.
        new_team_name (str): The new team name.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        tasks = []
        if team.discord_player_role_id:
            new_player_role_name = f"ECS-FC-PL-{normalize_name(new_team_name)}-Player"
            tasks.append(rename_role(guild_id, team.discord_player_role_id, new_player_role_name, http_session))
        if team.discord_channel_id:
            url = f"{Config.BOT_API_URL}/api/server/channels/{team.discord_channel_id}"
            tasks.append(make_discord_request('PATCH', url, http_session, json={"new_name": new_team_name}))
        await asyncio.gather(*tasks)


async def rename_role(guild_id: int, role_id: Union[str, int], new_name: str, session: aiohttp.ClientSession) -> None:
    """
    Rename a Discord role.

    Args:
        guild_id (int): The Discord guild ID.
        role_id (Union[str, int]): The role ID or role name to be resolved.
        new_name (str): The new role name.
        session (aiohttp.ClientSession): The HTTP session.
    """
    role_id_str = str(role_id)
    if not role_id_str.isdigit():
        resolved_id = await get_role_id(guild_id, role_id_str, session)
        if not resolved_id:
            logger.error(f"Could not find role ID for role name '{role_id_str}'")
            return
        role_id_str = resolved_id

    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/roles/{role_id_str}"
    payload = {"new_name": new_name}
    response = await make_discord_request('PATCH', url, session, json=payload)
    if response:
        logger.info(f"Renamed role ID {role_id_str} to '{new_name}'")
        old_name = next((n for n, rid in role_name_cache.items() if rid == role_id_str), None)
        if old_name:
            del role_name_cache[old_name]
        role_name_cache[new_name] = role_id_str
    else:
        logger.error(f"Failed to rename role ID {role_id_str} to '{new_name}'")


async def delete_team_roles(session: Session, team: Team) -> None:
    """
    Delete the Discord roles associated with a team.

    Args:
        session (Session): The database session.
        team (Team): The team instance.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        if team.discord_player_role_id:
            await delete_role(guild_id, team.discord_player_role_id, http_session)
            team.discord_player_role_id = None
            session.commit()


async def delete_team_channel(session: Session, team: Team) -> Dict[str, Any]:
    """
    Delete a team's Discord channel.

    Args:
        session (Session): The database session.
        team (Team): The team instance.

    Returns:
        Dict[str, Any]: Result of the deletion.
    """
    if not team.discord_channel_id:
        return {'success': False, 'error': 'No channel ID'}

    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/channels/{team.discord_channel_id}"
    async with aiohttp.ClientSession() as http_session:
        response = await make_discord_request('DELETE', url, http_session)
        if response:
            logger.info(f"Deleted channel ID {team.discord_channel_id}")
            team.discord_channel_id = None
            session.commit()
            return {'success': True, 'channel_id': team.discord_channel_id, 'error': None}
        else:
            return {'success': False, 'error': 'Failed to delete channel'}


# ---------------------------
# Player Role Updating & Sync
# ---------------------------

async def update_player_roles_async_only(player_data: Dict[str, Any], force_update: bool = False) -> Dict[str, Any]:
    """
    Update a player's Discord roles without database session (async-only version).
    
    Args:
        player_data: Dictionary containing player information
        force_update: If True, remove roles not in the expected set
        
    Returns:
        Dict[str, Any]: Result indicating success, and lists of roles added/removed
    """
    if not player_data.get('discord_id'):
        return {'success': False, 'error': 'No Discord ID'}
    
    guild_id = int(os.getenv('SERVER_ID'))
    try:
        async with aiohttp.ClientSession() as http_session:
            # Use the provided player data instead of database queries
            current_roles = player_data.get('current_roles', [])
            expected_roles = player_data.get('expected_roles', [])
            app_managed_roles = player_data.get('app_managed_roles', [])
            
            current_normalized = {normalize_name(r) for r in current_roles or []}
            expected_normalized = {normalize_name(r) for r in expected_roles}
            managed_normalized = {normalize_name(r) for r in app_managed_roles}
            
            # Identify coach roles in current Discord roles
            coach_roles = [r for r in current_roles if "COACH" in r.upper()]
            
            # Log role information for debugging
            logger.info(f"Player {player_data['name']} Discord role update:")
            logger.info(f"Current roles: {current_roles}")
            logger.info(f"Expected roles: {expected_roles}")
            logger.info(f"Coach roles found: {coach_roles}")
            
            to_add = [r for r in expected_roles if normalize_name(r) not in current_normalized]
            
            # Handle role removal based on force_update and coach status
            if force_update:
                to_remove = []
                logger.info(f"Force update enabled - checking roles for removal")
                logger.info(f"Managed roles: {app_managed_roles}")
                logger.info(f"Expected normalized: {expected_normalized}")
                logger.info(f"Managed normalized: {managed_normalized}")
                
                for role in current_roles:
                    normalized_role = normalize_name(role)
                    logger.info(f"Checking role: {role} (normalized: {normalized_role})")
                    
                    # Remove if it's in the managed list and not expected
                    if normalized_role in managed_normalized and normalized_role not in expected_normalized:
                        logger.info(f"Marking {role} for removal (in managed list)")
                        to_remove.append(role)
                    # Also remove any ECS-FC-PL team/coach roles that aren't expected
                    elif (role.startswith('ECS-FC-PL-') and 
                          ('-PLAYER' in role.upper() or '-COACH' in role.upper()) and 
                          normalized_role not in expected_normalized):
                        logger.info(f"Marking {role} for removal (ECS-FC-PL pattern)")
                        to_remove.append(role)
                    else:
                        logger.info(f"Not removing {role}: startswith={role.startswith('ECS-FC-PL-')}, has_player={'-PLAYER' in role.upper()}, has_coach={'-COACH' in role.upper()}, not_expected={normalized_role not in expected_normalized}")
                        
                logger.info(f"Total roles marked for removal: {to_remove}")
            else:
                to_remove = []
                logger.info(f"Force update disabled - no roles will be removed")
            
            # Execute role changes via Discord API
            roles_added = []
            roles_removed = []
            
            # Add roles
            for role_name in to_add:
                try:
                    # Get or create the role
                    role_id = await get_or_create_role(guild_id, role_name, http_session)
                    if role_id:
                        # Assign role to user
                        await assign_role_to_member(guild_id, player_data['discord_id'], role_id, http_session)
                        roles_added.append(role_name)
                        logger.info(f"Added role {role_name} to player {player_data['name']}")
                except Exception as e:
                    logger.error(f"Failed to add role {role_name}: {e}")
            
            # Remove roles
            for role_name in to_remove:
                try:
                    # Get role ID
                    role_id = await get_role_id(guild_id, role_name, http_session)
                    if role_id:
                        # Remove role from user
                        await remove_role_from_member(guild_id, player_data['discord_id'], role_id, http_session)
                        roles_removed.append(role_name)
                        logger.info(f"Removed role {role_name} from player {player_data['name']}")
                except Exception as e:
                    logger.error(f"Failed to remove role {role_name}: {e}")
            
            # Get final roles after changes
            final_roles = await get_member_roles(player_data['discord_id'], http_session)
            
            return {
                'success': True,
                'current_roles': final_roles,
                'roles_added': roles_added,
                'roles_removed': roles_removed,
                'player_id': player_data.get('id'),
                'discord_id': player_data['discord_id']
            }
            
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_data.get('name', 'unknown')}: {e}")
        return {
            'success': False,
            'error': str(e),
            'player_id': player_data.get('id'),
            'discord_id': player_data.get('discord_id')
        }


async def update_player_roles(session: Session, player: Player, force_update: bool = False) -> Dict[str, Any]:
    """
    Update a player's Discord roles.

    Args:
        session (Session): The database session.
        player (Player): The player instance.
        force_update (bool): If True, remove roles not in the expected set.

    Returns:
        Dict[str, Any]: Result indicating success, and lists of roles added/removed.
    """
    if not player.discord_id:
        return {'success': False, 'error': 'No Discord ID'}

    guild_id = int(os.getenv('SERVER_ID'))
    try:
        async with aiohttp.ClientSession() as http_session:
            current_roles = await fetch_user_roles(session, player.discord_id, http_session)
            app_managed = await get_app_managed_roles(session)
            current_normalized = {normalize_name(r) for r in current_roles or []}
            expected_roles = await get_expected_roles(session, player)
            expected_normalized = {normalize_name(r) for r in expected_roles}
            managed_normalized = {normalize_name(r) for r in app_managed}
            
            # Identify coach roles in current Discord roles
            coach_roles = [r for r in current_roles if "COACH" in r.upper()]
            coach_role_names = {normalize_name(r) for r in coach_roles}
            
            # Log role information for debugging
            logger.info(f"Player {player.id} ({player.name}) Discord role update:")
            logger.info(f"Current roles: {current_roles}")
            logger.info(f"Expected roles: {expected_roles}")
            logger.info(f"Coach roles found: {coach_roles}")
            logger.info(f"Player is_coach flag: {player.is_coach}")
            
            # Log Discord coach role status for debugging
            has_discord_coach_role = bool(coach_roles)
            logger.info(f"Player {player.id} Discord coach role status: {has_discord_coach_role}, Database is_coach: {player.is_coach}")
            
            # Trust the database is_coach flag rather than synchronizing with Discord
            # This allows profile page updates to properly remove coach roles

            to_add = [r for r in expected_roles if normalize_name(r) not in current_normalized]
            
            # Just remove the duplicate to_add line since we already have it above
            # We want to keep the one that follows our database is_coach update
            
            # When force_update is true or if player.is_coach is false, allow coach roles to be removed
            # Otherwise, preserve them
            if force_update:
                to_remove = [r for r in current_roles
                         if normalize_name(r) in managed_normalized and normalize_name(r) not in expected_normalized]
            else:
                to_remove = [r for r in current_roles
                         if normalize_name(r) in managed_normalized 
                         and normalize_name(r) not in expected_normalized 
                         and (not "COACH" in r.upper() or not player.is_coach)]
                
            logger.info(f"Roles to add: {to_add}")
            logger.info(f"Roles to remove: {to_remove}")

            for role_name in to_add:
                role_id = await get_or_create_role(guild_id, role_name, http_session)
                if role_id:
                    await assign_role_to_member(guild_id, player.discord_id, role_id, http_session)

            for role_name in to_remove:
                role_id = await get_role_id(guild_id, role_name, http_session)
                if role_id:
                    await remove_role_from_member(guild_id, player.discord_id, role_id, http_session)

            return {'success': True, 'added': to_add, 'removed': to_remove}

    except Exception as e:
        logger.error(f"Role update failed for {player.name}: {str(e)}")
        return {'success': False, 'error': str(e)}


async def get_app_managed_roles(session: Session) -> List[str]:
    """
    Get a list of roles that are managed by the application.
    Only includes current season teams to avoid managing old team roles.

    Returns:
        List[str]: Combined list of static and current season team-specific roles.
    """
    static_roles = [
        "ECS-FC-PL-PREMIER",
        "ECS-FC-PL-CLASSIC",
        "ECS-FC-PL-PREMIER-COACH",
        "ECS-FC-PL-CLASSIC-COACH",
        "ECS-FC-PL-UNVERIFIED",  # New unverified role
        "ECS-FC-LEAGUE",  # ECS FC league role
        "ECS-FC-PL-PREMIER-SUB",  # Premier substitute role
        "ECS-FC-PL-CLASSIC-SUB",  # Classic substitute role
        "ECS-FC-LEAGUE-SUB",  # ECS FC substitute role
        "Referee"
    ]
    
    # Only include current season teams to avoid managing old team roles
    from app.models import Season, PlayerTeamSeason
    
    current_season = session.query(Season).filter_by(is_current=True).first()
    if current_season:
        # Get teams that are active in the current season
        current_teams = session.query(Team).join(
            PlayerTeamSeason, Team.id == PlayerTeamSeason.team_id
        ).filter(
            PlayerTeamSeason.season_id == current_season.id
        ).distinct().all()
        team_roles = [f"ECS-FC-PL-{normalize_name(team.name)}-Player" for team in current_teams]
    else:
        # Fallback: if no current season, don't include any team roles
        team_roles = []
        
    return static_roles + team_roles


async def get_expected_roles(session: Session, player: Player) -> List[str]:
    """
    Build the complete set of roles the player should have.

    Factors include league membership, team membership, coach/ref status,
    and preserving non-managed roles from Discord.

    Returns:
        List[str]: List of expected role names.
    """
    roles = []
    app_role_prefixes = ["ECS-FC-PL-", "Referee"]

    async with aiohttp.ClientSession() as aio_session:
        current_roles = await fetch_user_roles(session, player.discord_id, aio_session)

    # Preserve any roles that are not managed by our app
    for role in current_roles:
        if not any(role.startswith(prefix) for prefix in app_role_prefixes):
            roles.append(role)

    # Get the player's Flask application roles
    user_roles = []
    if player.user and player.user.roles:
        user_roles = [role.name for role in player.user.roles]
        logger.info(f"Player {player.id} has Flask roles: {user_roles}")
    else:
        logger.info(f"Player {player.id} has no Flask user or roles")

    # Check user approval status for the new approval system
    approval_status = getattr(player.user, 'approval_status', 'pending') if player.user else 'pending'
    approval_league = getattr(player.user, 'approval_league', None) if player.user else None
    
    logger.info(f"Player {player.id} has approval_status='{approval_status}', approval_league='{approval_league}'")

    # Handle unverified users (pending approval)
    if approval_status == 'pending' and 'pl-unverified' in user_roles:
        roles.append(normalize_name("ECS-FC-PL-UNVERIFIED"))
        logger.info(f"Player {player.id} assigned ECS-FC-PL-UNVERIFIED role (pending approval)")
        # Return early for unverified users - they only get the unverified role
        return roles

    # Handle denied users (remove all roles)
    if approval_status == 'denied':
        logger.info(f"Player {player.id} is denied - no league roles assigned")
        # Return early for denied users - they only get preserved non-managed roles
        return roles

    # Handle approved users by directly mapping Flask roles to Discord roles
    if approval_status == 'approved':
        # Direct mapping of Flask roles to Discord roles (can have multiple)
        # Base league roles
        if 'pl-classic' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-CLASSIC"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-CLASSIC based on Flask role 'pl-classic'")
        
        if 'pl-premier' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-PREMIER"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-PREMIER based on Flask role 'pl-premier'")
        
        if 'pl-ecs-fc' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-ECS-FC"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-ECS-FC based on Flask role 'pl-ecs-fc'")
        
        # Substitute roles
        if 'Classic Sub' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-CLASSIC-SUB"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-CLASSIC-SUB based on Flask role 'Classic Sub'")
        
        if 'Premier Sub' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-PREMIER-SUB"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-PREMIER-SUB based on Flask role 'Premier Sub'")
        
        if 'ECS FC Sub' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-ECS-FC-SUB"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-ECS-FC-SUB based on Flask role 'ECS FC Sub'")

    # Check if the player has the "Pub League Coach" role in the Flask app
    has_coach_role_in_flask = "Pub League Coach" in user_roles
    
    # Use database is_coach flag as the authoritative source for Discord role assignment
    should_have_coach_status = player.is_coach
    
    # Log determination for debugging
    logger.info(f"Player {player.id} has database is_coach={player.is_coach}, Flask 'Pub League Coach'={has_coach_role_in_flask}")
    logger.info(f"Final determination - should have coach status: {should_have_coach_status}")

    # Add coach roles if approved and has coach status
    if approval_status == 'approved' and should_have_coach_status:
        # Add coach roles based on the user's Flask league roles
        if 'pl-classic' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-CLASSIC-COACH"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-CLASSIC-COACH based on Flask role 'pl-classic' and coach status")
        
        if 'pl-premier' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-PREMIER-COACH"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-PREMIER-COACH based on Flask role 'pl-premier' and coach status")
        
        if 'pl-ecs-fc' in user_roles:
            roles.append(normalize_name("ECS-FC-PL-ECS-FC-COACH"))
            logger.info(f"Player {player.id} assigned ECS-FC-PL-ECS-FC-COACH based on Flask role 'pl-ecs-fc' and coach status")

    # Determine leagues associated with the player (fallback for backward compatibility)
    leagues_for_user = set()
    if player.league_id:
        league_obj = session.query(League).filter_by(id=player.league_id).first()
        if league_obj and league_obj.name:
            leagues_for_user.add(league_obj.name.strip().upper())
    if player.primary_league_id:
        league_obj = session.query(League).filter_by(id=player.primary_league_id).first()
        if league_obj and league_obj.name:
            leagues_for_user.add(league_obj.name.strip().upper())
    for t in player.teams:
        if t.league and t.league.name:
            leagues_for_user.add(t.league.name.strip().upper())

    # For non-approved users, no league roles are assigned - they only get team-based roles
    if approval_status != 'approved':
        logger.info(f"Player {player.id} is not approved, only team-based roles will be assigned")

    # Append team-based roles using normalized role names
    for t in player.teams:
        roles.append(normalize_name(f"ECS-FC-PL-{t.name}-PLAYER"))

    if player.is_ref:
        roles.append(normalize_name("Referee"))
    
    # Remove duplicates while preserving order
    unique_roles = []
    seen = set()
    for role in roles:
        if role not in seen:
            seen.add(role)
            unique_roles.append(role)
    
    logger.info(f"Player {player.id} final expected roles: {unique_roles}")
    return unique_roles


async def process_role_updates(session: Session, force_update: bool = False) -> None:
    """
    Bulk process role updates for players.
    
    If force_update is False, only update players needing verification.
    """
    from datetime import datetime, timedelta
    if force_update:
        players_to_update = session.query(Player).filter(Player.discord_id.isnot(None)).all()
    else:
        threshold_date = datetime.utcnow() - timedelta(days=90)
        players_to_update = session.query(Player).filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < threshold_date)
        ).all()

    for p in players_to_update:
        await update_player_roles(session, p, force_update=force_update)


def mark_player_for_update(session: Session, player_id: int) -> None:
    """
    Mark a player for Discord role update.
    """
    session.query(Player).filter_by(id=player_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked player ID {player_id} for Discord update.")


def mark_team_for_update(session: Session, team_id: int) -> None:
    """
    Mark all players in a team for Discord update.
    """
    stmt = (
        update(Player)
        .where(
            Player.id.in_(
                session.query(player_teams.c.player_id)
                .filter(player_teams.c.team_id == team_id)
            )
        )
        .values(discord_needs_update=True)
    )
    session.execute(stmt)
    logger.info(f"Marked all players for team ID {team_id} for Discord update.")


def mark_league_for_update(session: Session, league_id: int) -> None:
    """
    Mark players in teams belonging to a league for Discord update.
    """
    stmt = (
        update(Player)
        .where(
            Player.id.in_(
                session.query(player_teams.c.player_id)
                .join(Team, Team.id == player_teams.c.team_id)
                .filter(Team.league_id == league_id)
            )
        )
        .values(discord_needs_update=True)
    )
    session.execute(stmt)
    logger.info(f"Marked league ID {league_id} for Discord update.")


async def process_single_player_update(session: Session, player: Player, only_add: bool = False) -> dict:
    """
    Update a single player's roles on Discord.

    Args:
        session (Session): The database session.
        player (Player): The player instance.
        only_add (bool): If True, only add missing roles (do not remove).

    Returns:
        dict: Result of the update process.
    """
    from app.tasks.tasks_discord import update_player_roles
    try:
        if not player.discord_id:
            logger.warning(f"Player '{player.name}' does not have a Discord ID.")
            return {'success': False, 'message': 'No Discord ID associated with player', 'error': 'no_discord_id'}

        # Log important information for debugging
        logger.info(f"Processing Discord role update for player {player.id} ({player.name}), only_add={only_add}")
        logger.info(f"Player is_coach: {player.is_coach}")
        
        force = not only_add
        result = await update_player_roles(session, player, force_update=force)
        if result.get('success'):
            return {'success': True, 'message': 'Roles updated successfully'}
        else:
            return {'success': False, 'message': 'Role update failed', 'error': result.get('error')}
    except Exception as e:
        logger.error(f"Error in process_single_player_update for player {player.id}: {str(e)}", exc_info=True)
        return {'success': False, 'message': 'An exception occurred', 'error': str(e)}


# -------------------------------------------
# Example: Creating a Match Thread
# -------------------------------------------

async def create_match_thread(session: Session, match: MLSMatch) -> Optional[str]:
    """
    Create a Discord thread for an MLS match.

    Constructs an embed payload with match details and triggers a POST request
    to the Discord API to create a thread under a specified channel.
    
    Includes duplicate prevention by:
    1. Checking if the match already has a thread ID in the database
    2. Checking existing threads in the Discord channel with a similar name
    3. Using database locking to prevent race conditions

    Args:
        session (Session): The database session.
        match (MLSMatch): The MLS match instance.

    Returns:
        Optional[str]: The ID of the created thread if successful; otherwise, None.
    """
    if not match:
        logger.error("No match provided for thread creation")
        return None
        
    # Check if match already has a thread - this prevents duplicate creation
    if match.discord_thread_id and match.thread_created:
        logger.info(f"Match {match.match_id} already has thread ID {match.discord_thread_id}")
        return match.discord_thread_id

    # Try to acquire a database lock on this match to prevent race conditions
    # Use 'WITH FOR UPDATE SKIP LOCKED' to avoid deadlocks
    locked_match = session.query(MLSMatch).filter(
        MLSMatch.id == match.id
    ).with_for_update(skip_locked=True).first()
    
    if not locked_match:
        logger.warning(f"Could not acquire lock on match {match.match_id}, another process may be creating a thread")
        return None
        
    # Double-check after lock acquisition
    if locked_match.discord_thread_id and locked_match.thread_created:
        logger.info(f"After lock: match {match.match_id} already has thread ID {locked_match.discord_thread_id}")
        return locked_match.discord_thread_id

    guild_id = int(os.getenv('SERVER_ID'))
    mls_channel_id = os.getenv('MATCH_CHANNEL_ID')
    if not mls_channel_id:
        logger.error("No MATCH_CHANNEL_ID provided in environment.")
        return None

    local_team_name = "Seattle Sounders FC"
    if match.is_home_game:
        home_team_name = local_team_name
        away_team_name = match.opponent
    else:
        home_team_name = match.opponent
        away_team_name = local_team_name

    # Convert match.date_time to PST for display
    logger.info(f"DEBUG: Original match.date_time: {match.date_time}")
    if match.date_time.tzinfo is None:
        utc_time = match.date_time.replace(tzinfo=ZoneInfo("UTC"))
    else:
        utc_time = match.date_time.astimezone(ZoneInfo("UTC"))
    logger.info(f"DEBUG: UTC time: {utc_time}")
    pst_time = utc_time.astimezone(ZoneInfo("America/Los_Angeles"))
    logger.info(f"DEBUG: PST time: {pst_time}")
    logger.info(f"DEBUG: Formatted time: {pst_time.strftime('%m/%d/%Y %I:%M %p %Z')}")

    thread_name = f"{home_team_name} vs {away_team_name} - {pst_time.strftime('%Y-%m-%d')}"
    
    # Check if a thread with a similar name already exists to prevent duplicates
    async with aiohttp.ClientSession() as http_session:
        # Fetch existing threads in the channel
        existing_threads_url = f"{Config.BOT_API_URL}/api/server/channels/{mls_channel_id}/threads/active"
        existing_threads = await make_discord_request('GET', existing_threads_url, http_session)
        
        if existing_threads and isinstance(existing_threads, list):
            for thread in existing_threads:
                if 'name' in thread and thread['name'] == thread_name:
                    logger.warning(f"Thread with name '{thread_name}' already exists, id: {thread['id']}")
                    
                    # Update the match with the existing thread ID
                    match.discord_thread_id = thread['id']
                    match.thread_created = True
                    session.commit()
                    
                    return thread['id']
                    
        # No duplicate found, proceed with thread creation
        embed_data = {
            "title": f"Match Thread: {home_team_name} vs {away_team_name}",
            "description": "**Let's go Sounders!**",
            "color": 0x5B9A49,
            "fields": [
                {"name": "Date and Time", "value": pst_time.strftime("%m/%d/%Y %I:%M %p %Z"), "inline": False},
                {"name": "Venue", "value": match.venue if match.venue else "TBD", "inline": False},
                {"name": "Competition", "value": match.competition if match.competition else "Unknown", "inline": True},
                {"name": "Broadcast", "value": "AppleTV", "inline": True},
                {"name": "Home/Away", "value": "Home" if match.is_home_game else "Away", "inline": True}
            ],
            "thumbnail_url": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/9726.png",
            "footer_text": "Use /predict to participate in match predictions!"
        }
        if match.summary_link:
            embed_data["fields"].append({"name": "Match Summary", "value": f"[Click here]({match.summary_link})", "inline": True})
        if match.stats_link:
            embed_data["fields"].append({"name": "Match Statistics", "value": f"[Click here]({match.stats_link})", "inline": True})
        if match.commentary_link:
            embed_data["fields"].append({"name": "Live Commentary", "value": f"[Click here]({match.commentary_link})", "inline": True})

        payload = {
            "name": thread_name,
            "type": 11,  # GUILD_PUBLIC_THREAD
            "auto_archive_duration": 1440,
            "message": {
                "content": "Match thread created! Discuss the game here and make your predictions.",
                "embed_data": embed_data
            }
        }

        response = await make_discord_request('POST', f"{Config.BOT_API_URL}/api/server/channels/{mls_channel_id}/threads", http_session, json=payload)
        if response and 'id' in response:
            thread_id = response['id']
            logger.info(f"Created thread '{thread_name}' with ID {thread_id}")
            
            # Save the thread ID to prevent future duplicates
            match.discord_thread_id = thread_id
            match.thread_created = True
            session.commit()
            
            return thread_id
        else:
            logger.error(f"Failed to create thread for MLS match {match.match_id}")
            return None


async def invite_user_to_server(user_id: str) -> Dict[str, Any]:
    """
    Invite a user to the Discord server.
    
    Args:
        user_id (str): The Discord user ID to invite.
        
    Returns:
        Dict[str, Any]: A dictionary with the invitation result.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    try:
        async with aiohttp.ClientSession() as session:
            # Check if user is already in the server first
            url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}"
            member_check = await make_discord_request('GET', url, session)
            
            if member_check:
                # User is already in the server
                logger.info(f"User {user_id} is already in the server {guild_id}")
                return {'success': True, 'message': 'User is already in the server'}
            
            # For development environment, we can skip actual invitation
            # and let users join manually if needed
            if os.getenv('FLASK_ENV') == 'development' or os.getenv('ENVIRONMENT') == 'development':
                logger.info(f"Skipping Discord invite in development environment for user {user_id}")
                return {
                    'success': True,
                    'message': 'Development mode - invite skipped'
                }
            
            # Generate a server invite for the user
            url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/invites"
            payload = {
                "target_user_id": user_id,
                "max_uses": 1,
                "max_age": 86400,  # 24 hours
                "temporary": False
            }
            
            response = await make_discord_request('POST', url, session, json=payload)
            if response and 'code' in response:
                logger.info(f"Successfully created invite for user {user_id} to server {guild_id}")
                return {
                    'success': True, 
                    'invite_code': response['code'],
                    'message': 'Invitation sent successfully'
                }
            else:
                # Return generic Discord invite link as fallback
                invite_link = "https://discord.gg/weareecs"
                logger.warning(f"Failed to create direct invite for user {user_id}, providing generic invite link")
                return {
                    'success': True,
                    'invite_link': invite_link,
                    'message': 'Using generic invite link as fallback'
                }
    except Exception as e:
        logger.error(f"Error inviting user {user_id} to server {guild_id}: {str(e)}")
        # Still return a partial success with the public invite link
        return {
            'success': True,  # Mark as success to continue registration
            'invite_link': "https://discord.gg/weareecs",
            'message': f'Error creating invite: {str(e)}. Using public invite as fallback.'
        }


async def check_user_in_server(user_id: str, session: aiohttp.ClientSession) -> bool:
    """
    Check if a user is already in the Discord server.
    
    Args:
        user_id (str): The Discord user ID.
        session (aiohttp.ClientSession): The HTTP session.
        
    Returns:
        bool: True if the user is in the server, False otherwise.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}"
    
    try:
        response = await make_discord_request('GET', url, session)
        return response is not None
    except Exception as e:
        logger.error(f"Error checking if user {user_id} is in server {guild_id}: {str(e)}")
        return False


async def fetch_user_roles(session: Session, discord_id: str, http_session: aiohttp.ClientSession, retries: int = 3, delay: float = 0.5) -> List[str]:
    """
    Fetch the roles of a Discord member with retry logic.

    Args:
        session (Session): The database session.
        discord_id (str): The Discord user ID.
        http_session (aiohttp.ClientSession): The HTTP session.
        retries (int): Number of retries.
        delay (float): Delay between retries in seconds.

    Returns:
        List[str]: A list of role names.
    """
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{discord_id}/roles"
    
    for attempt in range(retries):
        try:
            response = await make_discord_request('GET', url, http_session)
            if isinstance(response, list):
                return response
            elif response and 'roles' in response:
                if isinstance(response['roles'], dict):
                    return list(response['roles'].values())
                elif isinstance(response['roles'], list):
                    if all(isinstance(r, dict) for r in response['roles']):
                        return [r['name'] for r in response['roles']]
                    return response['roles']
            logger.warning(f"Unexpected response format for user {discord_id}: {response}")
            await asyncio.sleep(delay)
        except Exception as e:
            logger.error(f"Error fetching roles for user {discord_id} on attempt {attempt + 1}: {str(e)}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
            else:
                return []
    return []