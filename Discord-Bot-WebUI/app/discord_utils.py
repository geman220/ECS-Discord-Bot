import os
import aiohttp
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from functools import wraps
from web_config import Config
from app.utils.discord_request_handler import optimized_discord_request
from app.decorators import handle_db_operation, query_operation
from app.models import Team, Player, MLSMatch

logger = logging.getLogger(__name__)

# Permission constants
VIEW_CHANNEL = 1024
SEND_MESSAGES = 2048
READ_MESSAGE_HISTORY = 65536
TEAM_ROLE_PERMISSIONS = VIEW_CHANNEL + SEND_MESSAGES + READ_MESSAGE_HISTORY  # 68608

# Rate limit constants
GLOBAL_RATE_LIMIT = 50  # Adjust according to Discord's global rate limit per second

# Global caches
category_cache: Dict[str, str] = {}
role_name_cache: Dict[str, str] = {}

# Rate limiter class
class RateLimiter:
    def __init__(self, max_calls, period):
        self._max_calls = max_calls
        self._period = period
        self._calls = 0
        self._reset_time = time.time()
        self._lock = asyncio.Lock() if hasattr(asyncio, 'Lock') else None
    
    def _should_reset(self, current_time):
        """Check if we should reset the counter"""
        return current_time >= self._reset_time + self._period
    
    def _reset_counter(self, current_time):
        """Reset the counter and time"""
        self._reset_time = current_time
        self._calls = 0
    
    def acquire_sync(self):
        """Synchronous acquire method"""
        current_time = time.time()
        
        if self._should_reset(current_time):
            self._reset_counter(current_time)
            
        if self._calls >= self._max_calls:
            wait_time = self._reset_time + self._period - current_time
            logger.warning(f"Rate limiter sleeping for {wait_time} seconds")
            time.sleep(wait_time)
            self._reset_counter(time.time())
            
        self._calls += 1
    
    async def acquire_async(self):
        """Asynchronous acquire method"""
        if not self._lock:
            self._lock = asyncio.Lock()
            
        async with self._lock:
            current_time = time.time()
            
            if self._should_reset(current_time):
                self._reset_counter(current_time)
                
            if self._calls >= self._max_calls:
                wait_time = self._reset_time + self._period - current_time
                logger.warning(f"Rate limiter sleeping for {wait_time} seconds")
                await asyncio.sleep(wait_time)
                self._reset_counter(time.time())
                
            self._calls += 1
    
    def limit(self):
        """Create a rate limiting decorator with explicit naming"""
        def rate_limit_decorator(func):
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                self.acquire_sync()
                return func(*args, **kwargs)
            
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                await self.acquire_async()
                return await func(*args, **kwargs)
            
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper
        return rate_limit_decorator

# Create a global rate limiter instance
rate_limiter = RateLimiter(max_calls=GLOBAL_RATE_LIMIT, period=1)

# Cache for categories and roles to minimize API calls
category_cache = {}
global_role_cache = {}

async def make_discord_request(
    method: str, url: str, session: aiohttp.ClientSession, retries: int = 3, delay: float = 0.5, **kwargs
) -> Any:
    for attempt in range(retries):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 404:
                    logger.warning(f"Received 404 when accessing {url}: Not found")
                    return None
                elif response.status >= 400:
                    response_text = await response.text()
                    logger.error(f"Error {response.status} for {url}: {response_text}")
                    response.raise_for_status()
                else:
                    return await response.json()
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} - Error making {method} request to {url}: {e}")
            await asyncio.sleep(delay)
    logger.error(f"Failed to complete {method} request to {url} after {retries} attempts.")
    return None

async def get_role_id(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
    """Gets the role ID for a given role name, using cache to minimize API calls."""
    role_id = role_name_cache.get(role_name)
    if role_id:
        return role_id

    # Fetch roles from Discord
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response:
        for role in response:
            role_name_cache[role['name']] = role['id']
        return role_name_cache.get(role_name)
    return None

async def create_role(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
    """Creates a new role in Discord and returns its ID."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    payload = {"name": role_name}
    response = await make_discord_request('POST', url, session, json=payload)
    if response and 'id' in response:
        role_id = response['id']
        role_cache[role_name] = role_id
        logger.info(f"Created role '{role_name}' with ID {role_id}")
        return role_id
    logger.error(f"Failed to create role '{role_name}'")
    return None

async def get_or_create_role(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
    """Retrieves a role ID by name or creates the role if it doesn't exist."""
    # Check cache first
    role_id = role_name_cache.get(role_name)
    if role_id:
        return role_id

    # Fetch roles from Discord
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response:
        for role in response:
            role_name_cache[role['name']] = role['id']
            if role['name'] == role_name:
                return role['id']

    # Create role if not found
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

async def assign_role_to_member(
    guild_id: int, user_id: str, role_id: str, session: aiohttp.ClientSession
) -> None:
    """Assigns a role to a member in the guild."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    await make_discord_request('PUT', url, session)

async def remove_role_from_member(
    guild_id: int, user_id: str, role_id: str, session: aiohttp.ClientSession
) -> None:
    """Removes a role from a member in the guild."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    await make_discord_request('DELETE', url, session)

async def get_member_roles(user_id: str, session: aiohttp.ClientSession) -> Optional[List[str]]:
    """Fetches role names from Discord for a specific user."""
    guild_id = int(os.getenv('SERVER_ID') or Config.SERVER_ID)
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response is None:
        logger.warning(f"User {user_id} not found in server.")
        return None  # User not in Discord
    if 'roles' in response:
        # `response['roles']` is now a list of role names (strings)
        role_names = response['roles']
        return role_names
    logger.error(f"No roles found for user {user_id}")
    return []

async def get_role_names(guild_id: int, role_ids: List[str], session: aiohttp.ClientSession) -> List[str]:
    """Fetches the names of roles given their IDs, utilizing cache."""
    missing_role_ids = [role_id for role_id in role_ids if role_id not in role_name_cache]

    if missing_role_ids:
        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
        response = await make_discord_request('GET', url, session)
        if response:
            for role in response:
                role_name_cache[role['id']] = role['name']

    role_names = [role_name_cache.get(role_id, "Unknown Role") for role_id in role_ids]
    return role_names

async def get_or_create_category(
    guild_id: int, category_name: str, session: aiohttp.ClientSession
) -> Union[str, None]:
    """Gets the category by name or creates it if it doesn't exist."""
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

async def create_category(guild_id: int, category_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
    """Creates a new category with proper permissions."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
    payload = {
        "name": category_name,
        "type": 4,  # Channel type 4 is category
    }
    response = await make_discord_request('POST', url, session, json=payload)
    if response and 'id' in response:
        category_id = response['id']
        category_cache[category_name] = category_id
        logger.info(f"Created category '{category_name}' with ID {category_id}")
        return category_id
    logger.error(f"Failed to create category '{category_name}'")
    return None

# Database Operations

@handle_db_operation()
async def create_discord_roles(team_name: str, team_id: int) -> None:
    """Creates Discord roles for a team and updates the database."""
    guild_id = int(os.getenv('SERVER_ID'))
    coach_role_name = f"ECS-FC-PL-{team_name}-Coach"
    player_role_name = f"ECS-FC-PL-{team_name}-Player"

    async with aiohttp.ClientSession() as session:
        coach_role_id = await get_or_create_role(guild_id, coach_role_name, session)
        player_role_id = await get_or_create_role(guild_id, player_role_name, session)

        # Update the team with the role IDs
        team = Team.query.get(team_id)
        team.discord_coach_role_id = coach_role_id
        team.discord_player_role_id = player_role_id
        logger.info(
            f"Created roles for team {team_name}: Coach Role ID {coach_role_id}, Player Role ID {player_role_id}"
        )

@handle_db_operation()
async def create_discord_channel(team_name: str, division: str, team_id: int) -> None:
    """Creates a new channel in Discord under the specified division category for a team."""
    guild_id = int(os.getenv('SERVER_ID'))
    category_name = f"ECS FC PL {division.capitalize()}"

    async with aiohttp.ClientSession() as session:
        category_id = await get_or_create_category(guild_id, category_name, session)
        if not category_id:
            logger.error(f"Failed to get or create category '{category_name}'")
            return

        # Ensure roles are created and registered
        await create_discord_roles(team_name, team_id)
        team = Team.query.get(team_id)
        if not team.discord_coach_role_id or not team.discord_player_role_id:
            logger.error(f"Role IDs not found for team '{team_name}'")
            return

        wg_admin_role_id = await get_or_create_role(guild_id, "WG: ECS FC ADMIN", session)

        permission_overwrites = [
            {"id": str(guild_id), "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"},
            {"id": str(team.discord_player_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
            {"id": str(team.discord_coach_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
            {"id": str(wg_admin_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
        ]

        payload = {
            "name": team_name,
            "parent_id": category_id,
            "type": 0,  # Text channel
            "permission_overwrites": permission_overwrites,
        }
        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
        response = await make_discord_request('POST', url, session, json=payload)
        if response and 'id' in response:
            team.discord_channel_id = response['id']
            logger.info(f"Created Discord channel '{team_name}' with ID {team.discord_channel_id}")
        else:
            logger.error(f"Failed to create channel for team '{team_name}'")

@handle_db_operation()
async def assign_roles_to_player(player: Player) -> None:
    """Assigns appropriate roles to a player."""
    if not player.discord_id or not player.team:
        logger.warning(f"Player '{player.name}' has no Discord ID or team assigned.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as session:
        # Assign team-specific role
        role_name_suffix = 'Coach' if player.is_coach else 'Player'
        team_role_name = f"ECS-FC-PL-{player.team.name}-{role_name_suffix}"
        team_role_id = await get_or_create_role(guild_id, team_role_name, session)
        if team_role_id:
            await assign_role_to_member(guild_id, player.discord_id, team_role_id, session)
            logger.info(f"Assigned role '{team_role_name}' to player '{player.name}'")
        else:
            logger.error(f"Failed to assign team role '{team_role_name}' to player '{player.name}'")

        # Assign league role
        league_role_name = get_league_role_name(player.team.league.name)
        if league_role_name:
            league_role_id = await get_or_create_role(guild_id, league_role_name, session)
            if league_role_id:
                await assign_role_to_member(guild_id, player.discord_id, league_role_id, session)
                logger.info(f"Assigned league role '{league_role_name}' to player '{player.name}'")
            else:
                logger.error(f"Failed to assign league role '{league_role_name}' to player '{player.name}'")
        else:
            logger.error(f"Unknown league '{player.team.league.name}' for player '{player.name}'")

def get_league_role_name(league_name: str) -> Union[str, None]:
    """Maps league names to role names."""
    league_map = {
        'Classic': 'ECS-FC-PL-CLASSIC',
        'Premier': 'ECS-FC-PL-PREMIER',
        'ECS FC': 'ECS-FC-LEAGUE',
    }
    return league_map.get(league_name.strip())

@handle_db_operation()
async def remove_player_roles(player: Player) -> None:
    """Removes roles from a player when they leave a team."""
    if not player.discord_id or not player.team:
        logger.warning(f"Player '{player.name}' has no Discord ID or team assigned.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as session:
        # Remove team-specific role
        role_name_suffix = 'Coach' if player.is_coach else 'Player'
        team_role_name = f"ECS-FC-PL-{player.team.name}-{role_name_suffix}"
        team_role_id = await get_role_id(guild_id, team_role_name, session)
        if team_role_id:
            await remove_role_from_member(guild_id, player.discord_id, team_role_id, session)
            logger.info(f"Removed role '{team_role_name}' from player '{player.name}'")
        else:
            logger.error(f"Team role '{team_role_name}' not found for player '{player.name}'")

@handle_db_operation()
async def rename_team_roles(team: Team, new_team_name: str) -> None:
    """Renames the Discord roles associated with a team."""
    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as session:
        # Rename Coach role
        if team.discord_coach_role_id:
            new_coach_role_name = f"ECS-FC-PL-{new_team_name}-Coach"
            await rename_role(guild_id, team.discord_coach_role_id, new_coach_role_name, session)
        # Rename Player role
        if team.discord_player_role_id:
            new_player_role_name = f"ECS-FC-PL-{new_team_name}-Player"
            await rename_role(guild_id, team.discord_player_role_id, new_player_role_name, session)

async def rename_role(guild_id: int, role_id: str, new_name: str, session: aiohttp.ClientSession) -> None:
    """Renames a role in Discord."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
    payload = {"name": new_name}
    response = await make_discord_request('PATCH', url, session, json=payload)
    if response:
        logger.info(f"Renamed role ID {role_id} to '{new_name}'")
    else:
        logger.error(f"Failed to rename role ID {role_id} to '{new_name}'")

@handle_db_operation()
async def delete_team_roles(team: Team) -> None:
    """Deletes the Discord roles associated with a team."""
    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as session:
        # Delete Coach role
        if team.discord_coach_role_id:
            await delete_role(guild_id, team.discord_coach_role_id, session)
        # Delete Player role
        if team.discord_player_role_id:
            await delete_role(guild_id, team.discord_player_role_id, session)

async def delete_role(guild_id: int, role_id: str, session: aiohttp.ClientSession) -> None:
    """Deletes a role from Discord."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
    response = await make_discord_request('DELETE', url, session)
    if response:
        logger.info(f"Deleted role ID {role_id}")
    else:
        logger.error(f"Failed to delete role ID {role_id}")

@handle_db_operation()
async def delete_team_channel(team: Team) -> None:
    """Deletes the Discord channel associated with a team."""
    if not team.discord_channel_id:
        logger.error(f"Team '{team.name}' does not have a Discord channel ID.")
        return

    url = f"{Config.BOT_API_URL}/channels/{team.discord_channel_id}"
    async with aiohttp.ClientSession() as session:
        response = await make_discord_request('DELETE', url, session)
        if response:
            logger.info(f"Deleted channel ID {team.discord_channel_id} for team '{team.name}'")
        else:
            logger.error(f"Failed to delete channel ID {team.discord_channel_id} for team '{team.name}'")

@handle_db_operation()
async def update_player_roles(player: Player, force_update: bool = False) -> None:
    """Updates the roles of a player in Discord."""
    if not player.discord_id:
        logger.warning(f"Player '{player.name}' does not have a Discord ID.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as session:
        current_roles_ids = await get_member_roles(player.discord_id, session)
        current_roles = await get_role_names(guild_id, current_roles_ids, session)

        expected_roles = await get_expected_roles(player)
        roles_to_add = set(expected_roles) - set(current_roles)
        roles_to_remove = set(current_roles) - set(expected_roles)

        # Add missing roles
        for role_name in roles_to_add:
            role_id = await get_or_create_role(guild_id, role_name, session)
            if role_id:
                await assign_role_to_member(guild_id, player.discord_id, role_id, session)
                logger.info(f"Added role '{role_name}' to player '{player.name}'")
            else:
                logger.error(f"Failed to add role '{role_name}' to player '{player.name}'")

        # Remove extra roles
        for role_name in roles_to_remove:
            role_id = await get_role_id(guild_id, role_name, session)
            if role_id:
                await remove_role_from_member(guild_id, player.discord_id, role_id, session)
                logger.info(f"Removed role '{role_name}' from player '{player.name}'")
            else:
                logger.error(f"Failed to remove role '{role_name}' from player '{player.name}'")

        # Update player's role information
        player.discord_roles = expected_roles
        player.discord_last_verified = datetime.utcnow()
        player.discord_needs_update = False

async def get_expected_roles(player: Player) -> List[str]:
    """Determines the expected role names for a player."""
    roles = []
    if player.team:
        role_suffix = 'Coach' if player.is_coach else 'Player'
        role_name = f"ECS-FC-PL-{player.team.name}-{role_suffix}"
        roles.append(role_name)
    # Add league role
    if player.team and player.team.league:
        league_role_name = get_league_role_name(player.team.league.name)
        if league_role_name:
            roles.append(league_role_name)
    # Add other roles as needed
    if player.is_ref:
        roles.append('Referee')
    return roles  # Return list of role names

@query_operation
async def process_role_updates(force_update: bool = False) -> None:
    """Processes role updates for all players who need it."""
    if force_update:
        players_to_update = Player.query.filter(Player.discord_id.isnot(None)).all()
    else:
        threshold_date = datetime.utcnow() - timedelta(days=90)
        players_to_update = Player.query.filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < threshold_date)
        ).all()

    for player in players_to_update:
        await update_player_roles(player, force_update=force_update)

# Helper Functions to Mark Players/Teams/Leagues for Update

@handle_db_operation()
def mark_player_for_update(player_id: int) -> None:
    Player.query.filter_by(id=player_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked player ID {player_id} for Discord update.")

@handle_db_operation()
def mark_team_for_update(team_id: int) -> None:
    Player.query.filter_by(team_id=team_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked team ID {team_id} for Discord update.")

@handle_db_operation()
def mark_league_for_update(league_id: int) -> None:
    Player.query.join(Team).filter(Team.league_id == league_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked league ID {league_id} for Discord update.")

@handle_db_operation()
async def process_single_player_update(player: Player) -> None:
    """Process role updates for a single player."""
    if not player.discord_id:
        logger.warning(f"Player '{player.name}' does not have a Discord ID.")
        return

    await update_player_roles(player, force_update=True)

@handle_db_operation()
async def create_match_thread(match: MLSMatch) -> Union[str, None]:
    """Creates a Discord thread for a match."""
    if not match:
        logger.error("No match provided for thread creation")
        return None

    guild_id = int(os.getenv('SERVER_ID'))
    channel_id = match.home_team.discord_channel_id

    if not channel_id:
        logger.error(f"No Discord channel found for match {match.match_id}")
        return None

    thread_name = f"{match.home_team.name} vs {match.opponent} - {match.date_time.strftime('%Y-%m-%d')}"
    
    url = f"{Config.BOT_API_URL}/channels/{channel_id}/threads"
    payload = {
        "name": thread_name,
        "type": 11,  # Public thread
        "auto_archive_duration": 1440  # Archive after 24 hours of inactivity
    }

    async with aiohttp.ClientSession() as session:
        response = await make_discord_request('POST', url, session, json=payload)
        if response and 'id' in response:
            thread_id = response['id']
            logger.info(f"Created thread '{thread_name}' with ID {thread_id}")
            return thread_id
        else:
            logger.error(f"Failed to create thread for match {match.match_id}")
            return None

async def fetch_user_roles(discord_id, session, retries=3, delay=0.5):
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{discord_id}/roles"
    
    for attempt in range(retries):
        try:
            response = await make_discord_request('GET', url, session)
            if response and 'roles' in response:
                roles = [role['name'] for role in response['roles']]
                
                # Fetch expected roles dynamically
                expected_roles = await get_expected_roles(discord_id, session)
                
                # Validate against dynamically fetched expected roles
                if validate_roles(roles, expected_roles):
                    logger.debug(f"Roles for user {discord_id} validated successfully: {roles}")
                    return roles
                else:
                    logger.warning(f"Roles mismatch for user {discord_id}: {roles} vs. {expected_roles}")

            await asyncio.sleep(delay)
        
        except Exception as e:
            logger.error(f"Error fetching roles for user {discord_id} on attempt {attempt + 1}: {str(e)}")
    
    logger.error(f"Failed to fetch and validate roles for user {discord_id} after {retries} attempts")
    return []
