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
    logger.debug(f"Looking up role ID for name: {role_name}")

    # Check cache for an exact or normalized match
    if role_name in role_name_cache:
        logger.debug(f"Cache hit for role {role_name}: {role_name_cache[role_name]}")
        return role_name_cache[role_name]
    target_normalized = normalize_name(role_name)
    for cached_name, rid in role_name_cache.items():
        if normalize_name(cached_name) == target_normalized:
            logger.debug(f"Normalized cache hit for {role_name}: {rid}")
            return rid

    # Fetch roles from Discord API and refresh cache
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response:
        role_name_cache.clear()
        role_name_cache.update({role['name']: role['id'] for role in response})
        logger.debug(f"Updated role cache with {len(response)} roles")
        if role_name in role_name_cache:
            return role_name_cache[role_name]
        for discord_role in response:
            if normalize_name(discord_role['name']) == target_normalized:
                logger.debug(f"Found normalized match: {discord_role['name']} -> {discord_role['id']}")
                return discord_role['id']
    logger.error(f"Role not found: {role_name}")
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
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
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
    existing_id = await get_role_id(guild_id, role_name, session)
    if existing_id:
        return existing_id
    normalized_name = normalize_name(role_name)
    return await create_role(guild_id, normalized_name, session)


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

        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
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

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
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

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
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
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles"
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
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
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

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
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
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
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
                {"id": str(team.discord_player_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
                {"id": str(wg_admin_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
                {"id": str(pl_leadership_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
            ]
            payload = {
                "name": team_name,
                "parent_id": category_id,
                "type": 0,  # text channel
                "permission_overwrites": permission_overwrites,
            }
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
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
            new_player_role_name = f"ECS-FC-PL-{new_team_name}-Player"
            tasks.append(rename_role(guild_id, team.discord_player_role_id, new_player_role_name, http_session))
        if team.discord_channel_id:
            url = f"{Config.BOT_API_URL}/channels/{team.discord_channel_id}"
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

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id_str}"
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
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels/{team.discord_channel_id}"
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

            to_add = [r for r in expected_roles if normalize_name(r) not in current_normalized]
            to_remove = [r for r in current_roles
                         if normalize_name(r) in managed_normalized and normalize_name(r) not in expected_normalized]

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

    Returns:
        List[str]: Combined list of static and team-specific roles.
    """
    static_roles = [
        "ECS-FC-PL-PREMIER",
        "ECS-FC-PL-CLASSIC",
        "ECS-FC-PL-PREMIER-COACH",
        "ECS-FC-PL-CLASSIC-COACH",
        "Referee"
    ]
    teams = session.query(Team).all()
    team_roles = [f"ECS-FC-PL-{team.name}-PLAYER" for team in teams]
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

    # Determine leagues associated with the player
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

    # Append league-based roles, normalizing the constructed role names
    for league_name in leagues_for_user:
        if league_name == "PREMIER":
            roles.append(normalize_name("ECS-FC-PL-PREMIER"))
            if player.is_coach:
                roles.append(normalize_name("ECS-FC-PL-PREMIER-COACH"))
        elif league_name == "CLASSIC":
            roles.append(normalize_name("ECS-FC-PL-CLASSIC"))
            if player.is_coach:
                roles.append(normalize_name("ECS-FC-PL-CLASSIC-COACH"))

    # Append team-based roles using normalized role names
    for t in player.teams:
        roles.append(normalize_name(f"ECS-FC-PL-{t.name}-PLAYER"))

    if player.is_ref:
        roles.append(normalize_name("Referee"))
    
    return roles


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

    Args:
        session (Session): The database session.
        match (MLSMatch): The MLS match instance.

    Returns:
        Optional[str]: The ID of the created thread if successful; otherwise, None.
    """
    if not match:
        logger.error("No match provided for thread creation")
        return None

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

    thread_name = f"{home_team_name} vs {away_team_name} - {match.date_time.strftime('%Y-%m-%d')}"
    embed_data = {
        "title": f"Match Thread: {home_team_name} vs {away_team_name}",
        "description": "**Let's go Sounders!**",
        "color": 0x5B9A49,
        "fields": [
            {"name": "Date and Time", "value": match.date_time.strftime("%m/%d/%Y %I:%M %p PST"), "inline": False},
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

    async with aiohttp.ClientSession() as http_session:
        response = await make_discord_request('POST', f"{Config.BOT_API_URL}/channels/{mls_channel_id}/threads", http_session, json=payload)
        if response and 'id' in response:
            thread_id = response['id']
            logger.info(f"Created thread '{thread_name}' with ID {thread_id}")
            return thread_id
        else:
            logger.error(f"Failed to create thread for MLS match {match.match_id}")
            return None


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
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{discord_id}/roles"
    
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