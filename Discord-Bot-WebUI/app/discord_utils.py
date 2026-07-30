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
import json
from functools import wraps
from typing import Optional, List, Dict, Any, Union
from zoneinfo import ZoneInfo

from web_config import Config

from app.models import Team, Player, MLSMatch, League, player_teams
from sqlalchemy.orm import Session
from sqlalchemy import update
from app.utils.discord_request_handler import make_discord_request
from app.utils.sync_ai_client import get_sync_ai_client

logger = logging.getLogger(__name__)

# Permission constants (Discord permission bits)
VIEW_CHANNEL = 1024
SEND_MESSAGES = 2048
READ_MESSAGE_HISTORY = 65536
SEND_MESSAGES_IN_THREADS = 274877906944
CREATE_PUBLIC_THREADS = 34359738368
MANAGE_MESSAGES = 8192
USE_APPLICATION_COMMANDS = 2147483648
# Discord split pinning out of MANAGE_MESSAGES (in effect since early 2026):
# MANAGE_MESSAGES now only covers deleting other people's messages, and pinning
# requires this bit explicitly. Discord's one-time migration only patched
# overwrites that already existed, so anything we create must set it ourselves.
PIN_MESSAGES = 1 << 51  # 2251799813685248

# Permission sets for different roles
TEAM_PLAYER_PERMISSIONS = (
    VIEW_CHANNEL +
    SEND_MESSAGES +
    READ_MESSAGE_HISTORY +
    SEND_MESSAGES_IN_THREADS +
    CREATE_PUBLIC_THREADS +
    USE_APPLICATION_COMMANDS
)  # 311385197568

LEADERSHIP_PERMISSIONS = (
    VIEW_CHANNEL +
    SEND_MESSAGES +
    READ_MESSAGE_HISTORY +
    SEND_MESSAGES_IN_THREADS +
    CREATE_PUBLIC_THREADS +
    MANAGE_MESSAGES +
    PIN_MESSAGES +
    USE_APPLICATION_COMMANDS
)  # 2252111198891008 (was 311385205760 before PIN_MESSAGES)

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
                                session: aiohttp.ClientSession) -> bool:
    """
    Assign a role to a Discord member.

    Args:
        guild_id (int): The Discord guild ID.
        user_id (str): The Discord user ID.
        role_id (Union[str, int]): The role ID (or name to be resolved).
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        bool: True only if Discord confirmed the assignment. Callers MUST check
        this before recording the role as granted — see the note below.

    The bot's PUT endpoint returns {"status": "Role assigned"} (truthy JSON) on
    success, and make_discord_request returns None for 404 (member/role gone)
    and for 403 (bot lacks Manage Roles, or its role sits below the target in the
    hierarchy). So truthiness is a valid success signal here.

    This used to return None unconditionally, and callers appended to
    `roles_added` regardless — making that list a record of INTENT, not outcome.
    A member who had left the guild 404'd on every grant and the sync still
    reported success, which then cleared discord_needs_update and erased the only
    signal that would have made a later sweep retry.
    """
    role_id = str(role_id)
    logger.debug(f"Assigning role {role_id} to user {user_id}")
    try:
        if not role_id.isdigit():
            resolved_id = await get_role_id(guild_id, role_id, session)
            if not resolved_id:
                logger.error(f"Could not find role ID for role name '{role_id}'")
                return False
            role_id = resolved_id

        url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
        result = await make_discord_request('PUT', url, session)
        if result:
            logger.info(f"Successfully assigned role {role_id} to user {user_id}")
            return True
        logger.error(
            f"Failed to assign role {role_id} to user {user_id} "
            f"(404 member/role not found, or 403 bot permission/hierarchy)")
        return False
    except Exception as e:
        logger.error(f"Error assigning role {role_id} to user {user_id}: {str(e)}")
        raise


async def set_team_channel_player_visibility(guild_id: int, channel_id: Union[str, int],
                                             player_role_id: Union[str, int], visible: bool,
                                             session: aiohttp.ClientSession) -> bool:
    """
    Flip a team channel's player-role overwrite between hidden and visible.

    Used by the make_teams_public reveal toggle: hidden denies VIEW_CHANNEL,
    visible grants the standard TEAM_PLAYER_PERMISSIONS.

    Returns True on success.
    """
    try:
        if visible:
            payload = {"id": int(player_role_id), "type": 0, "allow": str(TEAM_PLAYER_PERMISSIONS), "deny": "0"}
        else:
            payload = {"id": int(player_role_id), "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)}
        url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/channels/{channel_id}/permissions/{player_role_id}"
        result = await make_discord_request('PUT', url, session, json=payload)
        if result:
            logger.info(f"Set channel {channel_id} player role {player_role_id} visible={visible}")
            return True
        logger.error(f"Failed to set visibility on channel {channel_id} for role {player_role_id}")
        return False
    except Exception as e:
        logger.error(f"Error setting channel {channel_id} visibility for role {player_role_id}: {e}")
        return False


@rate_limiter.limit()
async def remove_role_from_member(guild_id: int, user_id: str, role_id: Union[str, int],
                                  session: aiohttp.ClientSession) -> bool:
    """
    Remove a role from a Discord member.

    Args:
        guild_id (int): The Discord guild ID.
        user_id (str): The Discord user ID.
        role_id (Union[str, int]): The role ID (or name to resolve).
        session (aiohttp.ClientSession): The HTTP session.

    Returns:
        bool: True only if Discord confirmed the removal.

    This used to DISCARD the response entirely and log "Removed role"
    unconditionally, so the log and the caller's `roles_removed` list both
    asserted a removal that may never have happened. 404 (member left the guild)
    and 403 (bot below the target role in the hierarchy) both return None from
    make_discord_request and were reported as success.
    """
    role_id = str(role_id)
    if not role_id.isdigit():
        resolved_id = await get_role_id(guild_id, role_id, session)
        if not resolved_id:
            logger.error(f"Could not find role ID for role name '{role_id}'")
            return False
        role_id = resolved_id

    url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    result = await make_discord_request('DELETE', url, session)
    if result:
        logger.info(f"Removed role '{role_id}' from user '{user_id}'")
        return True
    logger.error(
        f"FAILED to remove role '{role_id}' from user '{user_id}' "
        f"(404 member/role not found, or 403 bot permission/hierarchy). "
        f"The role is still on the member.")
    return False


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

        # The bot returns role NAMES here, not IDs
        # (api/routes/server_routes.py: `role_names = [role.name for role in
        # member.roles]`). Passing names to get_role_names costs a wasted round
        # trip on EVERY call: it filters with `r not in role_name_cache.values()`
        # where the values are numeric IDs, so a name never matches, the
        # "missing" list is always non-empty, and it unconditionally fetches the
        # FULL guild role list -- then discards it, because `id_to_name.get(rid,
        # rid)` falls through to the name it already had.
        #
        # So get_member_roles was silently 2 HTTP requests, one of them a whole
        # guild role list. That is now on the per-player hot path (the live read
        # in update_player_roles_async_only), which would have made a 300-player
        # drain issue 600 needless guild-wide fetches per tick, unrate-limited.
        #
        # Only resolve when the values actually look like snowflakes.
        if role_ids and all(str(r).isdigit() for r in role_ids):
            return await get_role_names(guild_id, role_ids, session)
        return role_ids
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

async def create_discord_channel_async_only(team_name: str, league_name: str, team_id: int,
                                            teams_public: bool = True) -> Dict[str, Any]:
    """
    Create a dedicated Discord channel for a team without database session.

    Args:
        team_name: The team's name
        league_name: League name (e.g., "Pub League Premier", "Pub League Classic", "ECS FC")
        team_id: The team's ID
        teams_public: make_teams_public toggle state. When False, Pub League
            channels are created with the player role denied VIEW so drafted
            players can't see their team until the reveal
            (sync_team_channel_visibility_task flips this later).

    Returns:
        Dict with success status and channel_id if successful
    """
    try:
        guild_id = int(os.getenv('SERVER_ID'))
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')

        # Determine category and channel naming based on league type.
        #
        # NOTE: league type controls the CATEGORY, the CHANNEL name, the leadership
        # role and the pre-reveal hiding -- but NOT the per-team role prefix. Team
        # role names are always "ECS-FC-PL-<team>-Player/-Coach" because every
        # consumer of those names hardcodes that prefix: get_expected_roles(),
        # get_app_managed_roles(), rename_team_roles_async_only() and the reconcile
        # allowlist (app_role_prefixes). Creating ECS FC League roles under an
        # "ECS-FC-LEAGUE-" prefix produced roles that the channel granted permissions
        # to but that no player or coach was ever assigned -- so ECS FC League
        # members could not see their own channel.
        # Resolved from the program registry first, so a new program lands in the
        # category an admin configured for it. The old else-branch built
        # f"ECS FC PL {league_name.capitalize()}", which for a multi-word league
        # name produced e.g. "ECS FC PL Summer sprint league" -- close enough to
        # look right in code review, different enough that get_or_create_category
        # would create a SECOND category next to the intended one.
        _program = None
        try:
            from app.services import program_registry
            _program = program_registry.by_league_name(league_name)
        except Exception as _reg_err:
            logger.warning(f"program registry unavailable for category resolution: {_reg_err}")

        if _program is not None and _program.discord_category_name:
            is_ecs_fc_league = not _program.is_pub_league_like
            category_name = _program.discord_category_name
            # Only the ECS FC league prefixes its channels; every pub-league-like
            # program uses the bare team name.
            channel_name = f"ecs-fc-{team_name}" if is_ecs_fc_league else team_name
        elif league_name and 'ECS FC' in league_name and 'Pub League' not in league_name:
            # ECS FC league teams go under "ECS FC LEAGUE TEAMS"
            is_ecs_fc_league = True
            category_name = "ECS FC LEAGUE TEAMS"
            channel_name = f"ecs-fc-{team_name}"  # ECS FC teams get ecs-fc- prefix
        elif league_name and 'Premier' in league_name:
            # Pub League Premier
            is_ecs_fc_league = False
            category_name = "ECS FC PL Premier"
            channel_name = team_name  # Pub League uses team name as-is
        elif league_name and 'Classic' in league_name:
            # Pub League Classic
            is_ecs_fc_league = False
            category_name = "ECS FC PL Classic"
            channel_name = team_name  # Pub League uses team name as-is
        else:
            # Default fallback
            is_ecs_fc_league = False
            category_name = f"ECS FC PL {league_name.capitalize() if league_name else 'Teams'}"
            channel_name = team_name

        # Single source of truth for per-team role names -- must match the
        # calculators in get_expected_roles()/get_app_managed_roles().
        role_prefix = "ECS-FC-PL"

        async with aiohttp.ClientSession() as session:
            # First, get or create the category
            category_id = await get_or_create_category(guild_id, category_name, session)
            if not category_id:
                return {'success': False, 'message': f"Failed to get/create category '{category_name}'"}

            # Create or get the required Discord roles using the appropriate prefix
            player_role_name = f"{role_prefix}-{team_name}-Player"
            player_role_id = await get_or_create_role(guild_id, player_role_name, session)
            if not player_role_id:
                return {'success': False, 'message': f"Failed to create player role '{player_role_name}'"}

            # Per-team coach role. assign_roles_to_player()/rename_team_roles_async_only()
            # already expect a "{prefix}-{team}-Coach" role to exist; create it here so
            # coaches can actually receive their team role and team.discord_coach_role_id
            # is populated for later rename/cleanup.
            coach_role_name = f"{role_prefix}-{team_name}-Coach"
            coach_role_id = await get_or_create_role(guild_id, coach_role_name, session)
            if not coach_role_id:
                # Hard failure, matching the player role. Continuing here produced a
                # channel with no coach overwrite -- coaches silently lost pin and
                # moderation on their own channel with nothing surfaced to the admin.
                return {'success': False, 'message': f"Failed to create coach role '{coach_role_name}'"}

            # Get admin and leadership roles (same for both league types)
            wg_admin_role_id = await get_or_create_role(guild_id, "WG: ECS FC ADMIN", session)
            # Use appropriate leadership role based on league type
            if is_ecs_fc_league:
                leadership_role_id = await get_or_create_role(guild_id, "WG: ECS FC Leadership", session)
            else:
                leadership_role_id = await get_or_create_role(guild_id, "WG: ECS FC PL Leadership", session)

            # Set up permission overwrites
            # Pre-reveal (teams hidden), Pub League player roles are denied VIEW —
            # players hold their team role but can't see the channel yet. ECS FC
            # League has no draft reveal, so it is never hidden.
            hide_from_players = not teams_public and not is_ecs_fc_league
            if hide_from_players:
                player_overwrite = {"id": str(player_role_id), "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)}
            else:
                player_overwrite = {"id": str(player_role_id), "type": 0, "allow": str(TEAM_PLAYER_PERMISSIONS), "deny": "0"}

            permission_overwrites = [
                {"id": str(guild_id), "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"},
                player_overwrite,
            ]

            # Coaches get elevated (mod) permissions, but scoped to their own team channel.
            if coach_role_id:
                permission_overwrites.append(
                    {"id": str(coach_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"}
                )

            # Add admin permissions if roles exist
            if wg_admin_role_id:
                permission_overwrites.append({"id": str(wg_admin_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"})
            if leadership_role_id:
                permission_overwrites.append({"id": str(leadership_role_id), "type": 0, "allow": str(LEADERSHIP_PERMISSIONS), "deny": "0"})

            # Create channel with proper setup
            channel_data = {
                'name': channel_name,
                'type': 0,  # Text channel
                'topic': f"Team channel for {team_name} ({league_name})",
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
                    'coach_role_id': coach_role_id,
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
    Includes retry logic and enhanced error handling.
    
    Args:
        match_data: Dictionary containing match information
        
    Returns:
        Thread ID if successful, None otherwise
    """
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
            
            # Create thread payload with all available data
            thread_data = {
                'match_id': match_data.get('id') or match_data.get('match_id'),
                'home_team': match_data['home_team'],
                'away_team': match_data['away_team'],
                'date': match_data.get('date'),
                'time': match_data.get('time'),
                'venue': match_data.get('venue', 'TBD'),
                'competition': match_data.get('competition', 'MLS'),
                'is_home_game': match_data.get('is_home_game', False),
                'summary_link': match_data.get('summary_link'),
                'stats_link': match_data.get('stats_link'),
                'commentary_link': match_data.get('commentary_link'),
                'broadcast': match_data.get('broadcast')
            }
            
            logger.info(f"Attempt {attempt + 1}/{max_retries} to create thread for match {thread_data['match_id']}")
            
            # Create session with custom timeout and retry settings
            timeout = aiohttp.ClientTimeout(total=45, connect=10, sock_read=30)
            connector = aiohttp.TCPConnector(force_close=True)
            
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                url = f"{bot_api_url}/api/create_match_thread"
                
                async with session.post(url, json=thread_data) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            result = json.loads(response_text) if response_text else {}
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON response: {response_text}")
                            result = {}
                        
                        thread_id = result.get('thread_id')
                        if thread_id:
                            logger.info(f"Successfully created Discord thread {thread_id} for match {thread_data['match_id']}")
                            return thread_id
                        else:
                            logger.warning(f"API returned 200 but no thread_id in response: {result}")
                            
                    elif response.status == 409:
                        # Thread already exists
                        logger.info(f"Thread already exists for match {thread_data['match_id']}")
                        try:
                            result = json.loads(response_text) if response_text else {}
                            existing_thread_id = result.get('thread_id')
                            if existing_thread_id:
                                return existing_thread_id
                        except:
                            pass
                            
                    elif response.status in [500, 502, 503, 504]:
                        # Server error, retry
                        logger.warning(f"Server error {response.status} creating thread: {response_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))
                            continue
                            
                    else:
                        logger.error(f"Failed to create thread (status {response.status}): {response_text}")
                        
        except asyncio.TimeoutError:
            logger.error(f"Timeout creating thread for match {match_data.get('id', 'unknown')} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
                
        except aiohttp.ClientError as e:
            logger.error(f"Client error creating thread for match {match_data.get('id', 'unknown')}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
                
        except Exception as e:
            logger.error(f"Unexpected error creating thread for match {match_data.get('id', 'unknown')}: {e}", exc_info=True)
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
    
    logger.error(f"Failed to create thread after {max_retries} attempts for match {match_data.get('id', 'unknown')}")
    return None


async def assign_roles_to_player(guild_id: int, player: Player,
                                 db_session: Optional[Session] = None) -> None:
    """
    Assign the expected Discord roles to a player based on team and league membership.

    Args:
        guild_id (int): The Discord guild ID.
        db_session (Session): REQUIRED in practice — see the guard below.
        player (Player): The player instance.
    """
    if not player.discord_id or not player.teams:
        logger.warning(f"Player '{player.name}' has no Discord ID or no team assigned.")
        return

    # NO LIVE CALLERS -- the only reference is the tombstone at app/publeague.py:39.
    #
    # It used to call get_expected_roles(session=None, ...), which the old
    # self-contained calculator tolerated by degrading. Now that the function
    # delegates to _extract_player_role_data(session, ...), a None session is an
    # immediate AttributeError. Fail with something actionable instead of a
    # NoneType error three frames down, and accept a session so the function is
    # correct if anyone revives it.
    if db_session is None:
        raise ValueError(
            "assign_roles_to_player requires a DB session: the expected-role "
            "calculator reads the player's teams, leagues and Flask roles. "
            "Pass db_session=g.db_session. (This function has no live callers; "
            "prefer assign_roles_to_player_task.)")

    async with aiohttp.ClientSession() as http_session:
        expected_roles = await get_expected_roles(session=db_session, player=player)
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

# Protected-role allowlist (registration-lifecycle overhaul, Phase 4 safety net).
# A FULL RECONCILE (update_player_roles_async_only with force_update=True) may ONLY
# remove low-harm churn roles: substitute roles (…-SUB) and the pending/unverified role.
# It must NEVER strip a player/team/division/coach/referee role, regardless of what any
# desired-set calculator computes — a wrongly-omitted role in the expected set would
# otherwise cause the league-wide Pub League role wipes that calculator drift has caused
# (a huge manual cleanup). Genuine departures (leaving a team, losing a role) are handled
# by the TARGETED remove_player_roles_task / explicit removals, NOT by this reconcile.
_RECONCILE_REMOVABLE_EXACT = {'ECS-FC-PL-UNVERIFIED'}

# Max roles a SINGLE player may lose in one allowlist-disabled reconcile before
# it is treated as a calculator failure rather than an intended cleanup. A real
# rollover sheds a team role, a team coach role and maybe a division role.
_MASS_REVOKE_LIMIT = 6


def _is_reconcile_removable(role_name: str) -> bool:
    """True only for roles a full reconcile is allowed to strip (sub + unverified)."""
    up = (role_name or '').strip().upper()
    if up in _RECONCILE_REMOVABLE_EXACT:
        return True
    return up.endswith('-SUB')


async def update_player_roles_async_only(player_data: Dict[str, Any], force_update: bool = False,
                                         enforce_allowlist: bool = True,
                                         pattern_sweep: bool = True) -> Dict[str, Any]:
    """
    Update a player's Discord roles without database session (async-only version).

    Args:
        player_data: Dictionary containing player information
        force_update: If True, remove roles not in the expected set
        enforce_allowlist: If True (default), the protected-role allowlist guards the
            computed removal set so a DRIFT-driven reconcile can only strip sub/unverified
            roles (never team/division/coach/referee). Pass False ONLY from a TARGETED
            caller that supplies an explicit, intentional removal list (e.g.
            _execute_remove_roles_async) — there the removal set is exactly what the caller
            chose, so it must execute in full (draft-remove team roles, deny offboarding).
        pattern_sweep: If True (default), ALSO mark any ECS-FC-PL-*-Player/-Coach role that
            isn't expected, even when it's absent from app_managed_roles. That catch-all is
            what makes a full reconcile / full offboarding pick up STALE team roles from
            teams the player is no longer associated with at all.

            Pass False for a SCOPED removal (one team_id) or a SCOPED grant (one target
            team): there expected_roles deliberately describes only that slice of the
            player, so the catch-all would strip every OTHER team's role too — e.g.
            removing a player from their Premier team also revoked their ECS FC team role,
            despite the caller's explicit, team-scoped app_managed_roles list.

    Returns:
        Dict[str, Any]: Result indicating success, and lists of roles added/removed
    """
    if not player_data.get('discord_id'):
        return {'success': False, 'error': 'No Discord ID'}
    
    guild_id = int(os.getenv('SERVER_ID'))
    try:
        # Explicit timeout: aiohttp defaults to 300s total, so a HANGING (not down)
        # bot could otherwise pin this task for minutes × retries and back up the
        # discord queue during the draft. A down bot fails fast on connect regardless.
        _timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=10)
        async with aiohttp.ClientSession(timeout=_timeout) as http_session:
            # Use the provided player data instead of database queries
            expected_roles = player_data.get('expected_roles', [])
            app_managed_roles = player_data.get('app_managed_roles', [])

            # Read LIVE Discord roles rather than trusting `player.discord_roles`.
            #
            # `to_remove` below is built by ITERATING current_roles, so an empty
            # or stale cache made every removal a silent no-op that still
            # returned success. That neutered `remove_player_roles_task` — the
            # only path that can strip a team/division/coach role, since the
            # reconcile allowlist blocks those — so draft-remove, deny and
            # deactivate all reported success while removing nothing.
            #
            # It also skipped needed GRANTS: `to_add` excludes anything the cache
            # claims the member already holds.
            #
            # There is a mechanism that actively empties the cache:
            # `get_member_roles` returns None when the bot is down or the member
            # 404s, and the finalizer writes that straight onto
            # `player.discord_roles`. One transient outage was enough to make a
            # player's removals permanently no-op.
            #
            # `revoke_unexpected_roles_task` already did exactly this and
            # documented why; the fix was never applied here. Falling back to the
            # cache on failure matches that behaviour — and a fallback to an
            # EMPTY cache is the safe direction: it removes nothing.
            _cached_roles = player_data.get('current_roles', []) or []
            try:
                _live_roles = await get_member_roles(player_data['discord_id'],
                                                     http_session)
            except Exception as _live_err:
                logger.warning(
                    f"Live role fetch failed for {player_data.get('name')}, "
                    f"falling back to cached roles: {_live_err}")
                _live_roles = None
            if _live_roles is None:
                logger.warning(
                    f"Could not read live Discord roles for "
                    f"{player_data.get('name')} — using the cached list "
                    f"({len(_cached_roles)} roles). Removals may be incomplete.")
            current_roles = _live_roles if _live_roles else _cached_roles
            
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
                    # Also remove any ECS-FC-PL team/coach roles that aren't expected.
                    # Gated on pattern_sweep: a SCOPED caller (one team) computes
                    # expected_roles for that team only, so this catch-all would strip
                    # the player's other teams' roles as collateral.
                    elif (pattern_sweep and
                          role.startswith('ECS-FC-PL-') and
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

            # PROTECTED-ROLE ALLOWLIST (safety net): a DRIFT-driven reconcile may ONLY strip
            # low-harm churn roles (sub / unverified). Team/division/coach/referee roles are
            # NEVER removed here even if omitted from expected_roles — that prevents the
            # league-wide Pub League role wipes that calculator drift caused. Skipped when
            # enforce_allowlist=False (a targeted caller supplied an explicit removal list).
            if to_remove and enforce_allowlist:
                _protected = [r for r in to_remove if not _is_reconcile_removable(r)]
                if _protected:
                    logger.warning(
                        f"Protected-role allowlist BLOCKED removal of {_protected} for "
                        f"{player_data.get('name')} (only sub/unverified are reconcile-removable)"
                    )
                to_remove = [r for r in to_remove if _is_reconcile_removable(r)]
                logger.info(f"Roles to remove after protected-allowlist filter: {to_remove}")

            # Execute role changes via Discord API
            roles_added = []
            roles_removed = []
            # Roles Discord refused or never confirmed. Kept separate from
            # roles_added/roles_removed so those two mean "confirmed by Discord"
            # rather than "we tried". Surfaced in the result so the caller can
            # decline to mark the player synced.
            roles_failed = []

            # BLAST-RADIUS CIRCUIT BREAKER.
            #
            # Only bites when enforce_allowlist=False, i.e. the protected-role
            # guard is deliberately OFF. Today that is season rollover
            # (app/season_routes.py:442), which reconciles an ENTIRE LEAGUE in
            # one unattended task.
            #
            # That path was previously self-limiting by accident: to_remove is
            # built by iterating current_roles, which came from the frequently
            # empty `player.discord_roles` cache, so the mass revoke was largely
            # a no-op. Reading live Discord state fixed the cache bug and, as a
            # side effect, made this mass revoke genuinely effective for the
            # first time -- with the allowlist off and a freshly rewritten
            # expected-role calculator behind it. A single wrong answer there is
            # exactly the league-wide wipe the allowlist exists to prevent.
            #
            # A rollover legitimately strips a handful of roles per player (last
            # season's team + coach). Stripping many more means the expected set
            # came back wrong. Refuse and let a human look, rather than proceed
            # at league scale.
            if not enforce_allowlist and len(to_remove) > _MASS_REVOKE_LIMIT:
                logger.error(
                    f"ABORTING role removal for {player_data.get('name')} "
                    f"(player_id={player_data.get('id')}): {len(to_remove)} roles "
                    f"queued for removal with the protected-role allowlist "
                    f"DISABLED, over the safety limit of {_MASS_REVOKE_LIMIT}. "
                    f"This usually means the expected-role calculation returned "
                    f"too little. Roles: {to_remove}")
                roles_failed.extend(to_remove)
                to_remove = []

            # Add roles
            for role_name in to_add:
                try:
                    # Get or create the role
                    role_id = await get_or_create_role(guild_id, role_name, http_session)
                    if role_id:
                        # Record the role as added ONLY if Discord confirmed it.
                        # roles_added used to be appended unconditionally, so it
                        # reported intent rather than outcome and the caller
                        # stored that as fact.
                        if await assign_role_to_member(
                                guild_id, player_data['discord_id'], role_id, http_session):
                            roles_added.append(role_name)
                            logger.info(f"Added role {role_name} to player {player_data['name']}")
                        else:
                            roles_failed.append(role_name)
                            logger.error(
                                f"Could NOT add role {role_name} to player "
                                f"{player_data['name']}")
                    else:
                        roles_failed.append(role_name)
                        logger.error(
                            f"Could not resolve/create role {role_name} for player "
                            f"{player_data['name']}")
                except Exception as e:
                    logger.error(f"Failed to add role {role_name}: {e}")
            
            # Remove roles
            for role_name in to_remove:
                try:
                    # Get role ID
                    role_id = await get_role_id(guild_id, role_name, http_session)
                    if role_id:
                        # Same as the grant loop: only record what Discord
                        # actually confirmed. A failed removal that reports
                        # success is worse than a grant failure -- it leaves a
                        # denied or deactivated member holding league access
                        # while every dashboard says they were offboarded.
                        if await remove_role_from_member(
                                guild_id, player_data['discord_id'], role_id, http_session):
                            roles_removed.append(role_name)
                            logger.info(f"Removed role {role_name} from player {player_data['name']}")
                        else:
                            roles_failed.append(role_name)
                            logger.error(
                                f"Could NOT remove role {role_name} from player "
                                f"{player_data['name']} — they STILL HOLD IT")
                    else:
                        roles_failed.append(role_name)
                        logger.error(
                            f"Could not resolve role {role_name} to remove from player "
                            f"{player_data['name']} — they may still hold it")
                except Exception as e:
                    logger.error(f"Failed to remove role {role_name}: {e}")
            
            # Get final roles after changes
            final_roles = await get_member_roles(player_data['discord_id'], http_session)
            
            # success reflects whether every intended change actually landed.
            # It used to be a hardcoded True, so a member who had left the guild
            # (404 on every call) produced a clean success -- which then cleared
            # discord_needs_update and erased the only signal that would have
            # made a later sweep retry.
            return {
                'success': not roles_failed,
                'current_roles': final_roles,
                'roles_added': roles_added,
                'roles_removed': roles_removed,
                'roles_failed': roles_failed,
                'sync_status': 'success' if not roles_failed else 'partial',
                'message': ('' if not roles_failed else
                            f"{len(roles_failed)} role op(s) failed: "
                            f"{', '.join(roles_failed)}"),
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

            # Managed set from the CANONICAL per-player calculator, matching the
            # expected set computed just below.
            #
            # This used to call get_app_managed_roles(session), which returns a
            # GLOBAL list: every current-season team role in the guild, not this
            # player's. Pairing a global managed set with a per-player expected
            # set means every team role in the league is a removal candidate for
            # every player -- and the two lists also disagreed about ECS FC
            # (managed here, deliberately unmanaged in the canonical calculator)
            # and ECS-FC-PL-UNVERIFIED (managed only here). A role in one list
            # but not the other is exactly what makes a role flap: granted by one
            # path, revoked by the other, forever.
            from app.tasks.tasks_discord import (
                _extract_player_role_data, _app_managed_roles,
            )
            _payload = _extract_player_role_data(session, player.id)
            app_managed = _app_managed_roles(_payload)

            current_normalized = {normalize_name(r) for r in current_roles or []}
            # Reuse the payload and the live role list already gathered above
            # instead of making get_expected_roles redo both.
            expected_roles = await get_expected_roles(
                session, player, payload=_payload, current_roles=current_roles)
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

            # PROTECTED-ROLE ALLOWLIST for this single-player reconcile: protect team-player
            # / division / referee roles from drift-driven stripping (prevents the PL role
            # wipes calculator drift caused), but keep COACH roles removable so an intentional
            # coach demotion (is_coach=False on a profile edit — the non-force branch above
            # only lists a coach role for removal when the player is no longer a coach) still
            # removes the Discord coach role. Sub/unverified stay removable too.
            if to_remove:
                def _removable_here(r):
                    return _is_reconcile_removable(r) or 'COACH' in (r or '').upper()
                _protected = [r for r in to_remove if not _removable_here(r)]
                if _protected:
                    logger.warning(
                        f"Protected-role allowlist BLOCKED removal of {_protected} for {player.name}"
                    )
                to_remove = [r for r in to_remove if _removable_here(r)]

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


def _program_role_names(session=None):
    """Every program's Discord division / coach / sub role name.

    THE SECOND CALCULATOR. get_expected_roles + get_app_managed_roles are the
    single-player path (update_player_roles -> process_role_updates, profile
    edits); tasks_discord.py holds the batch path. They must agree, and they had
    silently diverged: this file was still hardcoded to premier/classic/ecs-fc
    while the batch calculator went registry-driven, so whether a newer
    program's member kept their division role depended entirely on which sync
    ran last.

    Returns (division, coach, sub) name lists plus a lane->names mapping.
    """
    divisions, coaches, subs = [], [], []
    by_flask_role = {}
    try:
        from app.services import program_registry
        for pr in program_registry.all_programs(session):
            d = pr.division_role_name
            c = pr.coach_role_name
            sb = pr.sub_role_name
            if d:
                divisions.append(d)
            if c:
                coaches.append(c)
            if sb:
                subs.append(sb)
            if pr.flask_league_role and d:
                by_flask_role[pr.flask_league_role] = d
            if pr.flask_coach_role and c:
                by_flask_role[pr.flask_coach_role] = c
            if pr.flask_sub_role and sb:
                by_flask_role[pr.flask_sub_role] = sb
    except Exception as _reg_err:
        logger.warning(f"program registry unavailable in discord_utils: {_reg_err}")

    if not divisions:
        # Legacy floor. NEVER return empty: an empty expected set combined with a
        # populated managed set is what strips every role off every player.
        divisions = ["ECS-FC-PL-PREMIER", "ECS-FC-PL-CLASSIC", "ECS-FC-LEAGUE"]
        coaches = ["ECS-FC-PL-PREMIER-COACH", "ECS-FC-PL-CLASSIC-COACH"]
        subs = ["ECS-FC-PL-PREMIER-SUB", "ECS-FC-PL-CLASSIC-SUB", "ECS-FC-LEAGUE-SUB"]
        by_flask_role = {
            'pl-premier': "ECS-FC-PL-PREMIER", 'pl-classic': "ECS-FC-PL-CLASSIC",
            'pl-ecs-fc': "ECS-FC-LEAGUE",
            'Premier Coach': "ECS-FC-PL-PREMIER-COACH",
            'Classic Coach': "ECS-FC-PL-CLASSIC-COACH",
            'Premier Sub': "ECS-FC-PL-PREMIER-SUB",
            'Classic Sub': "ECS-FC-PL-CLASSIC-SUB",
            'ECS FC Sub': "ECS-FC-LEAGUE-SUB",
        }
    return divisions, coaches, subs, by_flask_role


async def get_app_managed_roles(session: Session) -> List[str]:
    """
    Get a list of roles that are managed by the application.
    Only includes current season teams to avoid managing old team roles.

    Returns:
        List[str]: Combined list of static and current season team-specific roles.
    """
    _divisions, _coaches, _subs, _ = _program_role_names(session)
    static_roles = (list(_divisions) + list(_coaches) + list(_subs)
                    + ["ECS-FC-PL-UNVERIFIED", "Referee"])

    # Teams from EVERY current season, not `.first()`.
    #
    # WARNING: `filter_by(is_current=True).first()` was an unqualified pick across
    # ALL league types. With three programs there are three is_current rows, so
    # which season's teams landed in the managed list was arbitrary -- and a team
    # role that is granted but NOT managed can never be revoked, while the
    # reverse strips roles that should stay.
    from app.models import Season, PlayerTeamSeason
    current_season_ids = [
        r[0] for r in session.query(Season.id).filter_by(is_current=True).all()
    ]
    if current_season_ids:
        current_teams = session.query(Team).join(
            PlayerTeamSeason, Team.id == PlayerTeamSeason.team_id
        ).filter(
            PlayerTeamSeason.season_id.in_(current_season_ids)
        ).distinct().all()
        team_roles = []
        for team in current_teams:
            team_roles.append(f"ECS-FC-PL-{normalize_name(team.name)}-Player")
            # Also manage the per-team -Coach role so it can be REVOKED when someone
            # stops coaching (matches the batch calculator's app_managed_roles).
            team_roles.append(f"ECS-FC-PL-{normalize_name(team.name)}-Coach")
    else:
        # Fallback: if no current season, don't include any team roles
        team_roles = []
        
    return static_roles + team_roles


async def get_expected_roles(session: Session, player: Player,
                             payload: Optional[Dict[str, Any]] = None,
                             current_roles: Optional[List[str]] = None) -> List[str]:
    """
    Build the complete set of roles the player should have.

    payload / current_roles let a caller that has ALREADY built the role payload
    or fetched the member's live Discord roles hand them in. update_player_roles
    has both, and without this it rebuilt the payload (~8 queries) and opened a
    second aiohttp session to re-fetch the same roles -- doubling the cost of a
    function that runs once per player over the whole league.

    Thin wrapper over the CANONICAL calculator in app/tasks/tasks_discord.py.
    Its only unique job is preserving Discord roles this app does not manage;
    everything app-managed is delegated.

    This function used to reimplement the whole calculation, and the two copies
    drifted badly. The batch/Celery path used `_compute_expected_roles`; THIS one
    is what the Discord bot's `on_member_join` reads (via
    app/user_api.py::get_player_by_discord), and the bot GRANTS whatever it
    returns. So the two halves of the system disagreed about what a member should
    have, and each would undo the other. The concrete divergences were:

      - No third-program support from a league or team basis. A Summer Sprint
        player whose role came from league association or team membership got
        ECS-FC-PL-SUMMER from the batch calculator, while this one omitted it AND
        still counted it as managed -- so it revoked what the other granted.
      - Exact string matching on league names where the canonical calculator
        matches fuzzily, so any league-name drift flipped a division role.
      - Team roles taken from `player.teams` (EVERY season) instead of
        current-season teams, so last season's team roles were expected here and
        revoked there.
      - Fail-CLOSED on approval status (`== 'approved'`) against the canonical
        fail-OPEN, so a NULL/odd status silently produced zero roles.

    Returns:
        List[str]: List of expected role names.
    """
    # 1. Preserve roles this app does not manage (the genuinely unique part).
    roles = []
    app_role_prefixes = ["ECS-FC-PL-", "Referee"]
    try:
        if current_roles is None:
            async with aiohttp.ClientSession() as aio_session:
                current_roles = await fetch_user_roles(
                    session, player.discord_id, aio_session)
    except Exception as e:
        # Not fatal: failing to read current roles only means we cannot carry
        # over unmanaged ones. The managed set below is computed from the DB.
        logger.warning(
            f"Could not read current Discord roles for player {player.id} while "
            f"preserving unmanaged roles: {e}")
        current_roles = []
    for role in (current_roles or []):
        if not any(role.startswith(prefix) for prefix in app_role_prefixes):
            roles.append(role)

    # 2. Delegate the app-managed set to the canonical calculator.
    #
    # Imported inside the function: tasks_discord imports this module at module
    # scope, so a top-level import here would be circular. This mirrors the
    # existing function-level import in process_single_player_update.
    from app.tasks.tasks_discord import (
        _extract_player_role_data, _compute_expected_roles,
    )
    try:
        data = payload if payload is not None else _extract_player_role_data(
            session, player.id)
    except Exception as e:
        # MUST NOT degrade to "just the unmanaged roles". An empty managed set
        # paired with a populated managed-roles list is precisely what strips
        # every role off a player, and this result feeds both the reconcile and
        # the bot's join handler. Fail loudly instead.
        logger.error(
            f"Could not build role payload for player {player.id}; refusing to "
            f"return a partial expected set: {e}")
        raise
    roles.extend(_compute_expected_roles(data))

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
        # Fetch ESPN data and generate AI description
        try:
            match_context = {
                'home_team': home_team_name,
                'away_team': away_team_name,
                'match_date': pst_time.strftime("%m/%d/%Y %I:%M %p %Z"),
                'venue': match.venue if match.venue else "TBD",
                'competition': match.competition if match.competition else "MLS",
                'is_home_game': match.is_home_game,
                'opponent': match.opponent
            }

            # Fetch real ESPN data (records, standings, h2h) for the AI to rewrite
            try:
                from app.utils.sync_espn_client import get_sync_espn_client
                from app.utils.competition_mappings import resolve_league_code
                espn = get_sync_espn_client()
                espn_match_id = match.match_id
                comp_code = resolve_league_code(match.competition)

                competitors = espn.get_event_competitors(espn_match_id, comp_code)
                if competitors:
                    home_info = espn.get_team_info(competitors['home_team_id'], comp_code)
                    away_info = espn.get_team_info(competitors['away_team_id'], comp_code)
                    h2h = espn.get_head_to_head(espn_match_id, comp_code)

                    # Build ESPN info string for AI to transform
                    parts = []
                    if home_info:
                        record = f"{home_info['wins']}W-{home_info['ties']}D-{home_info['losses']}L"
                        standing = home_info.get('standing_summary', '')
                        standing_short = standing.replace(' in ', ' ').replace(' Conference', '') if standing else ''
                        parts.append(f"{home_team_name} ({record}{', ' + standing_short if standing_short else ''})")
                    if away_info:
                        record = f"{away_info['wins']}W-{away_info['ties']}D-{away_info['losses']}L"
                        standing = away_info.get('standing_summary', '')
                        standing_short = standing.replace(' in ', ' ').replace(' Conference', '') if standing else ''
                        parts.append(f"{away_team_name} ({record}{', ' + standing_short if standing_short else ''})")
                    if h2h:
                        parts.append(f"Last meeting: {h2h}")

                    if parts:
                        match_context['espn_info'] = ". ".join(parts)
                        logger.info(f"Fetched ESPN data for thread context: {match_context['espn_info'][:100]}...")
            except Exception as e:
                logger.warning(f"Could not fetch ESPN data for thread context: {e}")

            ai_client = get_sync_ai_client()
            ai_description = ai_client.generate_match_thread_context(match_context)

            # Use AI description if generated, otherwise show competition + venue
            if ai_description:
                description = ai_description
            else:
                comp = match.competition if match.competition else "MLS"
                venue_name = match.venue if match.venue else ""
                description = f"{comp} - {venue_name}" if venue_name else comp

            logger.info(f"Generated AI description for match thread: {description[:100]}...")
        except Exception as e:
            logger.warning(f"Failed to generate AI description, using fallback: {e}")
            description = f"**{home_team_name} vs {away_team_name}**"

        embed_data = {
            "title": f"Match Thread: {home_team_name} vs {away_team_name}",
            "description": description,
            "color": 0x5B9A49,
            "fields": [
                {"name": "Date and Time", "value": pst_time.strftime("%m/%d/%Y %I:%M %p %Z"), "inline": False},
                {"name": "Venue", "value": match.venue if match.venue else "TBD", "inline": False},
                {"name": "Competition", "value": match.competition if match.competition else "Unknown", "inline": True},
                {"name": "Broadcast", "value": match.broadcast or "AppleTV", "inline": True},
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
                "content": f"Match Thread: {home_team_name} vs {away_team_name} - Share your predictions and discuss the match!",
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