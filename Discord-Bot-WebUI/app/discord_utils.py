import os
import aiohttp
from aiohttp import ClientSession
import asyncio
from datetime import datetime, timedelta
from web_config import Config
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON
import logging
import time
from typing import Union, List, Dict, Any
from app.utils.discord_request_handler import optimized_discord_request
from app.decorators import db_operation, query_operation, with_appcontext
from app.models import Team, Player, db
from app import create_app

logger = logging.getLogger(__name__)

# Permission constants
VIEW_CHANNEL = 1024
SEND_MESSAGES = 2048
READ_MESSAGE_HISTORY = 65536
TEAM_ROLE_PERMISSIONS = VIEW_CHANNEL + SEND_MESSAGES + READ_MESSAGE_HISTORY  # 68608

LEAGUE_PREMIER = "Premier"
LEAGUE_CLASSIC = "Classic"
LEAGUE_ECS_FC = "ECS FC"

# Rate limit constants
MAX_RETRIES = 5
GLOBAL_RATE_LIMIT = 50  # Adjust according to Discord's global rate limit per second

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
    
    def __call__(self):
        """Make the class callable for use as a decorator"""
        def decorator(func):
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
        return decorator

# Create a global rate limiter instance
rate_limiter = RateLimiter(max_calls=GLOBAL_RATE_LIMIT, period=1)

# Cache for categories and roles to minimize API calls
category_cache = {}
global_role_cache = {}

async def make_discord_request(method, url, session, **kwargs):
    """Wrapper around optimized discord request handler."""
    return await optimized_discord_request(method, url, session, **kwargs)

async def get_or_create_category(guild_id, category_name, session):
    """Gets the category by name or creates it if it doesn't exist, using caching to minimize API calls."""
    # Check cache first
    if category_name in category_cache:
        logger.info(f"Category '{category_name}' found in cache with ID {category_cache[category_name]}")
        return category_cache[category_name]

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"

    # Fetch the list of channels only once
    if not category_cache.get('channels'):
        channels = await make_discord_request('GET', url, session)
        category_cache['channels'] = channels
    else:
        channels = category_cache['channels']

    for channel in channels:
        if channel['type'] == 4 and channel['name'].lower() == category_name.lower():
            category_id = channel['id']
            category_cache[category_name] = category_id
            logger.info(f"Category '{category_name}' already exists with ID {category_id}")
            return category_id

    # Create the category
    category_id = await create_category_with_retry(guild_id, category_name, session)
    if category_id:
        category_cache[category_name] = category_id
    return category_id

async def create_category_with_retry(guild_id, category_name, session):
    """Creates a new category with proper permissions."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"

    # Get the ID of the WG: ECS FC ADMIN role
    wg_ecs_fc_admin_role_id = await get_or_create_global_role("WG: ECS FC ADMIN", session)

    # Deny @everyone access, allow admin role
    permission_overwrites = [
        {
            "id": str(guild_id),  # Deny @everyone
            "type": 0,            # Role
            "deny": str(VIEW_CHANNEL),  # Deny VIEW_CHANNEL
            "allow": "0"
        },
        {
            "id": str(wg_ecs_fc_admin_role_id),
            "type": 0,            # Role
            "allow": str(VIEW_CHANNEL),  # Allow VIEW_CHANNEL
            "deny": "0"
        }
    ]

    payload = {
        "name": category_name,
        "type": 4,
        "permission_overwrites": permission_overwrites
    }

    response = await make_discord_request('POST', url, session, json=payload)
    if response:
        category_id = response['id']
        logger.info(f"Created category: {category_name} with ID {category_id}")
        return category_id
    else:
        logger.error(f"Failed to create category {category_name}")
        return None

async def get_or_create_global_role(role_name, session):
    logger.debug(f"Attempting to get or create global role '{role_name}'")
    if role_name in global_role_cache:
        logger.debug(f"Role '{role_name}' found in cache with ID {global_role_cache[role_name]}")
        return global_role_cache[role_name]

    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"

    # Fetch the list of existing roles once
    if 'roles' not in global_role_cache:
        logger.debug("Fetching roles from the bot's REST API")
        try:
            roles = await make_discord_request('GET', url, session)
            if roles is None:
                logger.error("Failed to fetch roles - No response received")
                return None
            global_role_cache['roles'] = roles
        except Exception as e:
            logger.exception(f"Exception occurred while fetching roles: {e}")
            return None
    else:
        roles = global_role_cache['roles']
        logger.debug(f"Using cached roles")

    # Check if the role already exists
    for role in roles:
        logger.debug(f"Checking role: '{role['name']}' against '{role_name}'")
        if role['name'] == role_name:
            role_id = role['id']
            global_role_cache[role_name] = role_id
            logger.info(f"Global role '{role_name}' already exists with ID {role_id}")
            return role_id

    # Create the role
    role_id = await create_discord_role(guild_id, role_name, session)
    if role_id:
        global_role_cache[role_name] = role_id
    return role_id

async def create_discord_role(guild_id, role_name, session):
    """Creates a Discord role and returns its ID."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    payload = {"name": role_name}

    response = await make_discord_request('POST', url, session, json=payload)
    if response and 'id' in response:
        role_id = response['id']
        logger.info(f"Created role '{role_name}' with ID {role_id}")
        return role_id
    else:
        logger.error(f"Failed to create role '{role_name}'")
        return None

@db_operation
async def create_discord_channel(team_name, division, team_id):
    """Creates a new channel in Discord under the specified division category for a given team name."""
    guild_id = int(os.getenv('SERVER_ID'))
    category_name = f"ECS FC PL {division.capitalize()}"

    async with aiohttp.ClientSession() as session:
        category_id = await get_or_create_category(guild_id, category_name, session)

        if category_id:
            # Create roles first and ensure they are registered
            await create_discord_roles(team_name, team_id)

            # Wait until roles are registered in the database
            team = await wait_for_role_registration(team_id)
            if not team:
                logger.error(f"Failed to retrieve role IDs for team {team_name}.")
                return

            # Get or create WG: ECS FC ADMIN role
            wg_ecs_fc_admin_role_id = await get_or_create_global_role("WG: ECS FC ADMIN", session)

            # Deny @everyone access, allow team roles and admin
            permission_overwrites = [
                {"id": str(guild_id), "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"},
                {"id": str(team.discord_player_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
                {"id": str(team.discord_coach_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
                {"id": str(wg_ecs_fc_admin_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"}
            ]

            # Create the team channel with permission_overwrites
            payload = {"name": team_name, "parent_id": category_id, "type": 0, "permission_overwrites": permission_overwrites}
            url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"

            response = await make_discord_request('POST', url, session, json=payload)
            if response:
                discord_channel_id = response['id']
                logger.info(f"Created Discord channel: {team_name} under category {category_name} with ID {discord_channel_id}")

                # Update the team with the discord_channel_id
                team.discord_channel_id = discord_channel_id
                # No need to call db.session.commit(); handled by decorator
            else:
                logger.error(f"Failed to create channel for team {team_name}")
        else:
            logger.error(f"Failed to get or create category {category_name}")

@db_operation
async def create_discord_roles(team_name, team_id):
    """Creates two Discord roles (Coach and Player) for a team and stores their IDs."""
    guild_id = int(os.getenv('SERVER_ID'))
    coach_role_name = f"ECS-FC-PL-{team_name}-Coach"
    player_role_name = f"ECS-FC-PL-{team_name}-Player"

    async with aiohttp.ClientSession() as session:
        # Create Coach role
        coach_role_id = await create_discord_role(guild_id, coach_role_name, session)

        # Create Player role
        player_role_id = await create_discord_role(guild_id, player_role_name, session)

        # Update the team with the role IDs
        team = Team.query.get(team_id)
        team.discord_coach_role_id = coach_role_id
        team.discord_player_role_id = player_role_id
        logger.info(f"Created roles for team {team_name}: Coach Role ID {coach_role_id}, Player Role ID {player_role_id}")
        # No need to call db.session.commit(); handled by decorator

async def wait_for_role_registration(team_id, max_attempts=20, delay=0.1):
    """Waits for the role IDs (coach and player) to be registered in the database for a given team."""
    for attempt in range(max_attempts):
        team = Team.query.get(team_id)
        if team and team.discord_coach_role_id and team.discord_player_role_id:
            logger.debug(f"Roles registered for team ID {team_id}")
            return team
        await asyncio.sleep(delay)
    logger.error(f"Role IDs for team {team_id} not found after {max_attempts} attempts.")
    return None

async def assign_role_to_player(player, role_name, session):
    """Assigns a Discord role to a player."""
    if not player.discord_id:
        logger.warning(f"Player {player.name} does not have a linked Discord account.")
        return

    guild_id = int(Config.SERVER_ID)
    
    try:
        # Get or create the role
        role_id = await get_or_create_global_role(role_name, session)
        if not role_id:
            raise Exception(f"Could not get or create role {role_name}")

        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
        
        try:
            await make_discord_request('PUT', url, session)
            logger.info(f"Assigned role {role_name} to player {player.discord_id}.")
        except Exception as e:
            if '404' in str(e):
                # Role doesn't exist - recreate it
                logger.warning(f"Role {role_name} not found, attempting to recreate...")
                # Clear cache for this role
                if role_name in global_role_cache:
                    del global_role_cache[role_name]
                # Try to create role again
                role_id = await get_or_create_global_role(role_name, session, force_create=True)
                if role_id:
                    # Try assigning again
                    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
                    await make_discord_request('PUT', url, session)
                    logger.info(f"Successfully recreated and assigned role {role_name} to player {player.discord_id}.")
                else:
                    raise Exception(f"Failed to recreate role {role_name}")
            else:
                raise

    except Exception as e:
        logger.error(f"Failed to assign role {role_name} to player {player.name}: {e}")
        raise

async def assign_global_role(role_name, player, session):
    """Assigns a global role to a player for general access to global league channels."""
    if not player.discord_id:
        logger.warning(f"Player {player.name} does not have a linked Discord account.")
        return

    guild_id = int(Config.SERVER_ID)
    # Get the role ID for the global role
    role_id = await get_or_create_global_role(role_name, session)

    if not role_id:
        logger.error(f"Failed to get or create global role {role_name}.")
        return

    # Assign the role to the player
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
    try:
        await make_discord_request('PUT', url, session)
        logger.info(f"Assigned global role {role_name} to player {player.discord_id}.")
    except Exception as e:
        logger.error(f"Failed to assign global role to player {player.name}: {e}")

async def remove_role_from_player(player):
    """Removes the player's role in Discord when they are removed from the team."""
    if not player.discord_id:
        logger.warning(f"Player {player.name} does not have a linked Discord account.")
        return

    team = Team.query.get(player.team_id)
    if not team:
        logger.error(f"Team with ID {player.team_id} not found.")
        return

    # Determine the correct role ID to remove
    role_id = team.discord_player_role_id
    if player.is_coach:
        role_id = team.discord_coach_role_id

    if not role_id:
        logger.error(f"Role ID not found for team {team.name}.")
        return

    guild_id = int(Config.SERVER_ID)
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
    async with aiohttp.ClientSession() as session:
        try:
            await make_discord_request('DELETE', url, session)
            logger.info(f"Removed role ID {role_id} from user {player.discord_id}.")
        except Exception as e:
            logger.error(f"Failed to remove role from player {player.name}: {e}")

@db_operation
async def rename_discord_roles(team, new_team_name):
    """Renames the Discord roles associated with a team."""
    guild_id = int(Config.SERVER_ID)
    async with aiohttp.ClientSession() as session:
        # Rename Coach role
        if team.discord_coach_role_id:
            await rename_discord_role(guild_id, team.discord_coach_role_id, f"ECS-FC-PL-{new_team_name}-Coach", session)

        # Rename Player role
        if team.discord_player_role_id:
            await rename_discord_role(guild_id, team.discord_player_role_id, f"ECS-FC-PL-{new_team_name}-Player", session)

async def rename_discord_role(guild_id, role_id, new_role_name, session):
    """Renames a Discord role."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
    payload = {"name": new_role_name}
    logger.debug(f"Attempting to rename role ID {role_id} to {new_role_name}")

    try:
        await make_discord_request('PATCH', url, session, json=payload)
        logger.info(f"Successfully renamed Discord role ID {role_id} to {new_role_name}")
    except Exception as e:
        logger.error(f"Failed to rename role ID {role_id}: {e}")

@db_operation
async def rename_discord_channel(team, new_team_name):
    """Renames an existing channel in Discord for the specified team."""
    url = f"{Config.BOT_API_URL}/channels/{team.discord_channel_id}"
    payload = {"name": new_team_name}
    logger.debug(f"Attempting to rename channel ID {team.discord_channel_id} to {new_team_name}")

    async with aiohttp.ClientSession() as session:
        try:
            await make_discord_request('PATCH', url, session, json=payload)
            logger.info(f"Renamed Discord channel ID {team.discord_channel_id} from {team.name} to {new_team_name}")
        except Exception as e:
            logger.error(f"Failed to rename channel {team.discord_channel_id}: {e}")

@db_operation
async def delete_discord_roles(team):
    """Deletes the Discord roles associated with a team."""
    guild_id = int(Config.SERVER_ID)
    async with aiohttp.ClientSession() as session:
        # Delete Coach role
        if team.discord_coach_role_id:
            await delete_discord_role(guild_id, team.discord_coach_role_id, session)

        # Delete Player role
        if team.discord_player_role_id:
            await delete_discord_role(guild_id, team.discord_player_role_id, session)

async def delete_discord_role(guild_id, role_id, session):
    """Deletes a Discord role."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
    try:
        await make_discord_request('DELETE', url, session)
        logger.info(f"Deleted Discord role ID {role_id}")
    except Exception as e:
        logger.error(f"Failed to delete role ID {role_id}: {e}")

@db_operation
async def delete_discord_channel(team):
    """Deletes an existing channel in Discord for the specified team."""
    url = f"{Config.BOT_API_URL}/channels/{team.discord_channel_id}"
    async with aiohttp.ClientSession() as session:
        try:
            await make_discord_request('DELETE', url, session)
            logger.info(f"Deleted Discord channel ID {team.discord_channel_id}: {team.name}")
        except Exception as e:
            logger.error(f"Failed to delete channel ID {team.discord_channel_id}: {e}")

async def process_role_assignments(players):
    results = []
    async with aiohttp.ClientSession() as session:
        for player in players:
            player_result = await process_single_player(player, session)
            results.append(player_result)
            logger.info(f"Processed player {player.name}: {player_result}")
    return results

async def process_single_player(player, session):
    player_result = {
        'name': player.name,
        'discord_id': player.discord_id,
        'team': player.team.name if player.team else 'No Team',
        'league': player.team.league.name if player.team and player.team.league else 'No League',
        'assigned_roles': [],
        'errors': []
    }

    if not player.discord_id:
        player_result['errors'].append("No linked Discord account")
        return player_result

    if not player.team:
        player_result['errors'].append("No team assigned")
        return player_result

    team = player.team
    guild_id = int(os.getenv('SERVER_ID'))

    # Assign team-specific role
    role_id = team.discord_player_role_id if not player.is_coach else team.discord_coach_role_id
    if not role_id:
        player_result['errors'].append(f"No {'coach' if player.is_coach else 'player'} role found for team {team.name}")
    else:
        role_name = f"{'Coach' if player.is_coach else 'Player'} - {team.name}"
        await assign_role(player, role_id, role_name, guild_id, session, player_result)

    # Assign global league role
    league_name = team.league.name.strip().lower()
    global_role_name = get_global_role_name(league_name)
    if global_role_name:
        global_role_id = await get_or_create_global_role(global_role_name, session)
        if global_role_id:
            await assign_role(player, global_role_id, global_role_name, guild_id, session, player_result)
        else:
            player_result['errors'].append(f"Failed to get or create global role {global_role_name}")
    else:
        player_result['errors'].append(f"Unknown league '{league_name}'")

    return player_result

async def assign_role(player, role_id, role_name, guild_id, session, player_result):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
    try:
        await make_discord_request('PUT', url, session)
        player_result['assigned_roles'].append(role_name)
        logger.info(f"Assigned role '{role_name}' (ID: {role_id}) to player {player.name}")
    except Exception as e:
        error_msg = f"Failed to assign role '{role_name}': {str(e)}"
        player_result['errors'].append(error_msg)
        logger.error(error_msg)

def get_global_role_name(league_name):
    if league_name == "classic":
        return "ECS-FC-PL-CLASSIC"
    elif league_name == "premier":
        return "ECS-FC-PL-PREMIER"
    elif league_name == "ecs fc":
        return "ECS-FC-LEAGUE"
    else:
        return None

async def get_player_role_data(players):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_player_data(player, session) for player in players]
        return await asyncio.gather(*tasks)

async def fetch_player_data(player, session):
    try:
        current_roles, status = await get_discord_roles(player.discord_id, session)
        expected_roles = await get_expected_roles(discord_id, session)
        
        return {
            'id': player.id,
            'name': player.name,
            'discord_id': player.discord_id,
            'team': player.team.name if player.team else 'No Team',
            'league': player.team.league.name if player.team and player.team.league else 'No League',
            'current_roles': current_roles,
            'expected_roles': expected_roles,
            'status': status
        }
    except Exception as e:
        logger.error(f"Error fetching data for player {player.name}: {str(e)}")
        return {
            'id': player.id,
            'name': player.name,
            'discord_id': player.discord_id,
            'team': player.team.name if player.team else 'No Team',
            'league': player.team.league.name if player.team and player.team.league else 'No League',
            'current_roles': [],
            'expected_roles': get_expected_roles(player, session),
            'status': 'error'
        }

@db_operation
def mark_player_for_update(player_id):
    try:
        Player.query.filter_by(id=player_id).update({Player.discord_needs_update: True})
        # No need to call db.session.commit(); handled by decorator
    except Exception as e:
        logger.error(f"Error marking player {player_id} for update: {str(e)}")

@db_operation
def mark_team_for_update(team_id):
    try:
        Player.query.filter_by(team_id=team_id).update({Player.discord_needs_update: True})
        # No need to call db.session.commit(); handled by decorator
    except Exception as e:
        logger.error(f"Error marking team {team_id} for update: {str(e)}")

@db_operation
def mark_league_for_update(league_id):
    try:
        Player.query.join(Team).filter(Team.league_id == league_id).update({Player.discord_needs_update: True})
        # No need to call db.session.commit(); handled by decorator
    except Exception as e:
        logger.error(f"Error marking league {league_id} for update: {str(e)}")

async def update_player_roles(player, session, force_update=False):
    if not player.discord_id:
        return False

    current_roles, status = await get_discord_roles(player.discord_id, session, force_check=force_update)
    expected_roles = get_expected_roles(player, session)

    roles_to_add = set(expected_roles) - set(current_roles)
    guild_id = int(os.getenv('SERVER_ID'))

    try:
        for role_name in roles_to_add:
            role_id = await get_role_id(guild_id, role_name, session)
            if role_id:
                await add_role_to_member(guild_id, player.discord_id, role_id, session)

        # Fetch roles again to confirm changes
        updated_roles, _ = await get_discord_roles(player.discord_id, session, force_check=True)
        player.discord_roles = updated_roles
        player.discord_last_verified = datetime.utcnow()
        player.discord_needs_update = False
        # No need to call db.session.commit(); handled by decorator
        return True
    except Exception as e:
        logger.error(f"Error updating roles for player {player.name}: {str(e)}")
        return False

async def add_role_to_member(guild_id, user_id, role_id, session):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    try:
        await make_discord_request('PUT', url, session)
    except Exception as e:
        logger.error(f"Error adding role {role_id} to user {user_id}: {str(e)}")

async def remove_role_from_member(guild_id, user_id, role_id, session):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    try:
        await make_discord_request('DELETE', url, session)
    except Exception as e:
        logger.error(f"Error removing role {role_id} from user {user_id}: {str(e)}")

async def process_role_updates(force_update=False):
    if force_update:
        players_to_update = Player.query.filter(Player.discord_id.isnot(None)).all()
    else:
        players_to_update = Player.query.filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
        ).all()

    async with aiohttp.ClientSession() as session:
        tasks = [update_player_roles(player, session, force_update) for player in players_to_update]
        results = await asyncio.gather(*tasks)

    return all(results)

async def get_role_id(guild_id, role_name, session):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    try:
        response = await make_discord_request('GET', url, session)
        for role in response:
            if role['name'] == role_name:
                return role['id']
    except Exception as e:
        logger.error(f"Error fetching role ID for {role_name}: {str(e)}")
    return None

async def get_discord_roles(user_id, session, force_check=False):
    player = Player.query.filter_by(discord_id=user_id).first()
    if player and player.discord_roles and player.discord_last_verified and not force_check:
        if datetime.utcnow() - player.discord_last_verified < timedelta(days=90):
            return player.discord_roles, "cached"

    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles"

    try:
        response = await make_discord_request('GET', url, session)
        if response and 'roles' in response:
            roles = [role['name'] for role in response['roles']]
            if player:
                player.discord_roles = roles
                player.discord_last_verified = datetime.utcnow()
                player.discord_needs_update = False
                # No need to call db.session.commit(); handled by decorator
            return roles, "active"
        else:
            logger.warning(f"No roles found for user {user_id}")
            return [], "no_roles"
    except Exception as e:
        logger.error(f"Error fetching roles for user {user_id}: {str(e)}")
        return [], "error"

async def get_expected_roles(player_or_id: Union[Player, str], session=None) -> list:
    """
    Get expected roles for a player. Can accept either a Player object or discord_id.
    
    Args:
        player_or_id: Either a Player object or discord_id string
        session: Optional aiohttp session for API calls if needed
    """
    # If we got a discord_id instead of a Player object
    if isinstance(player_or_id, str):
        if not session:
            raise ValueError("Session required when passing discord_id")
        player = await fetch_player_data(player_or_id, session)
    else:
        player = player_or_id

    roles = []
    if player and player.team:
        # Add team-specific role
        role_suffix = 'Coach' if player.is_coach else 'Player' 
        roles.append(f"ECS-FC-PL-{player.team.name}-{role_suffix}")
        
        # Add league role
        if player.team.league:
            league_map = {
                'Premier': 'ECS-FC-PL-PREMIER',
                'Classic': 'ECS-FC-PL-CLASSIC',
                'ECS FC': 'ECS-FC-LEAGUE'
            }
            league_role = league_map.get(player.team.league.name)
            if league_role:
                roles.append(league_role)

    # Add referee role if applicable
    if player and player.is_ref:
        roles.append('Referee')
    
    logger.debug(f"Expected roles for player {player.id if player else 'Unknown'}: {roles}")
    return roles

@db_operation
def mark_player_for_update(player_id):
    Player.query.filter_by(id=player_id).update({Player.discord_needs_update: True})
    # No need to call db.session.commit(); handled by decorator
    logger.info(f"Marked player {player_id} for Discord update.")

@db_operation
def mark_team_for_update(team_id):
    Player.query.filter_by(team_id=team_id).update({Player.discord_needs_update: True})
    # No need to call db.session.commit(); handled by decorator
    logger.info(f"Marked team {team_id} for Discord update.")

@db_operation
def mark_league_for_update(league_id):
    Player.query.join(Team).filter(Team.league_id == league_id).update({Player.discord_needs_update: True})
    # No need to call db.session.commit(); handled by decorator
    logger.info(f"Marked league {league_id} for Discord update.")

@db_operation
async def update_player_roles(player, session, force_update=False):
    if not player.discord_id:
        return False

    current_roles, status = await get_discord_roles(player.discord_id, session, force_check=force_update)
    expected_roles = get_expected_roles(player, session)

    roles_to_add = set(expected_roles) - set(current_roles)
    guild_id = int(os.getenv('SERVER_ID'))

    try:
        for role_name in roles_to_add:
            role_id = await get_role_id(guild_id, role_name, session)
            if role_id:
                await add_role_to_member(guild_id, player.discord_id, role_id, session)

        # Fetch roles again to confirm changes
        updated_roles, _ = await get_discord_roles(player.discord_id, session, force_check=True)
        player.discord_roles = updated_roles
        player.discord_last_verified = datetime.utcnow()
        player.discord_needs_update = False
        # No need to call db.session.commit(); handled by decorator
        return True
    except Exception as e:
        logger.error(f"Error updating roles for player {player.name}: {str(e)}")
        return False

async def add_role_to_member(guild_id, user_id, role_id, session):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    try:
        await make_discord_request('PUT', url, session)
    except Exception as e:
        logger.error(f"Error adding role {role_id} to user {user_id}: {str(e)}")

async def remove_role_from_member(guild_id, user_id, role_id, session):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    try:
        await make_discord_request('DELETE', url, session)
    except Exception as e:
        logger.error(f"Error removing role {role_id} from user {user_id}: {str(e)}")

@query_operation
async def process_role_updates(force_update=False):
    if force_update:
        players_to_update = Player.query.filter(Player.discord_id.isnot(None)).all()
    else:
        players_to_update = Player.query.filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < datetime.utcnow() - timedelta(days=90))
        ).all()

    async with aiohttp.ClientSession() as session:
        tasks = [update_player_roles(player, session, force_update) for player in players_to_update]
        results = await asyncio.gather(*tasks)
    
    return all(results)

async def get_role_id(guild_id, role_name, session):
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    try:
        response = await make_discord_request('GET', url, session)
        for role in response:
            if role['name'] == role_name:
                return role['id']
    except Exception as e:
        logger.error(f"Error fetching role ID for {role_name}: {str(e)}")
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

def validate_roles(fetched_roles: List[str], expected_roles: List[str]) -> bool:
    """
    Validate that the fetched roles contain all expected roles.
    Extra roles beyond the expected ones are allowed.
    """
    expected_set = set(expected_roles)
    fetched_set = set(fetched_roles)
    return expected_set.issubset(fetched_set)

async def process_single_player_update(player):
    """Process role updates for a single player."""
    try:
        async with aiohttp.ClientSession() as session:
            # Get current roles from Discord
            current_roles = await fetch_user_roles(player.discord_id, session)
            expected_roles = get_expected_roles(player, session)
            
            # Track successful and failed role assignments
            results = {
                'success': [],
                'failed': []
            }
            
            # Attempt to assign each role
            for role_name in expected_roles:
                try:
                    await assign_role_to_player(player, role_name, session)
                    results['success'].append(role_name)
                except Exception as e:
                    logger.warning(f"Failed to assign role {role_name} to player {player.name}: {str(e)}")
                    results['failed'].append({
                        'role': role_name,
                        'error': str(e)
                    })

            # Update player's role information
            player.discord_roles = current_roles
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            
            # Return result with both successes and failures
            return {
                'success': True,
                'player_data': {
                    'id': player.id,
                    'current_roles': current_roles,
                    'expected_roles': expected_roles,
                    'results': results
                }
            }

    except Exception as e:
        logger.error(f"Error processing player update for {player.name}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

async def process_mass_update(players):
    async with aiohttp.ClientSession() as session:
        tasks = [process_single_player_update(player) for player in players]
        results = await asyncio.gather(*tasks)
        return all(results)

@query_operation
async def get_discord_roles(user_id, session, force_check=False):
    player = Player.query.filter_by(discord_id=user_id).first()
    if player and player.discord_roles and player.discord_last_verified and not force_check:
        if datetime.utcnow() - player.discord_last_verified < timedelta(days=90):
            return player.discord_roles, "cached"

    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles"
    
    try:
        response = await make_discord_request('GET', url, session)
        if response and 'roles' in response:
            roles = [role['name'] for role in response['roles']]
            if player:
                player.discord_roles = roles
                player.discord_last_verified = datetime.utcnow()
                player.discord_needs_update = False
                # No need to call db.session.commit(); handled by decorator
            return roles, "active"
        else:
            logger.warning(f"No roles found for user {user_id}")
            return [], "no_roles"
    except Exception as e:
        logger.error(f"Error fetching roles for user {user_id}: {str(e)}")
        return [], "error"

async def get_role_names(guild_id, role_ids, session):
    """
    Fetches the names of roles given their IDs.
    
    :param guild_id: The ID of the Discord server
    :param role_ids: A list of role IDs
    :param session: An aiohttp ClientSession
    :return: A list of role names
    """
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"

    try:
        response = await make_discord_request('GET', url, session)
        if response:
            role_map = {role['id']: role['name'] for role in response}
            return [role_map.get(role_id, "Unknown Role") for role_id in role_ids]
        else:
            logger.warning(f"No roles found for guild {guild_id}")
            return []
    except Exception as e:
        logger.error(f"Error fetching role names for guild {guild_id}: {str(e)}")
        return []

@db_operation
async def create_match_thread(match):
    match_channel_id = Config.MATCH_CHANNEL_ID
    
    thread_name = f"Match Thread: Seattle Sounders FC vs {match.opponent} - {match.date_time.strftime('%m/%d/%Y %I:%M %p PST')}"
    
    payload = {
        "name": thread_name,
        "type": 11,  # public thread
        "auto_archive_duration": 4320,  # 72 hours
        "message": {
            "content": "Match thread created! Discuss the game here and make your predictions.",
            "embed_data": {
                "title": f"Match Thread: Seattle Sounders FC vs {match.opponent}",
                "description": f"**Let's go Sounders!**",
                "color": 0x5B9A49,  # Sounders green color
                "fields": [
                    {"name": "Date and Time", "value": match.date_time.strftime("%m/%d/%Y %I:%M %p PST"), "inline": False},
                    {"name": "Venue", "value": match.venue, "inline": False},
                    {"name": "Competition", "value": match.competition, "inline": True},
                    {"name": "Broadcast", "value": "AppleTV", "inline": True},
                    {"name": "Home/Away", "value": "Home" if match.is_home_game else "Away", "inline": True}
                ],
                "thumbnail_url": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/9726.png",
                "footer_text": "Use /predict to participate in match predictions!"
            }
        }
    }
    
    # Add links if available
    if match.summary_link:
        payload["message"]["embed_data"]["fields"].append(
            {"name": "Match Summary", "value": f"[Click here]({match.summary_link})", "inline": True}
        )
    if match.stats_link:
        payload["message"]["embed_data"]["fields"].append(
            {"name": "Match Statistics", "value": f"[Click here]({match.stats_link})", "inline": True}
        )
    if match.commentary_link:
        payload["message"]["embed_data"]["fields"].append(
            {"name": "Live Commentary", "value": f"[Click here]({match.commentary_link})", "inline": True}
        )
    
    async with aiohttp.ClientSession() as session:
        url = f"{Config.BOT_API_URL}/channels/{match_channel_id}/threads"
        
        try:
            response = await make_discord_request('POST', url, session, json=payload)
            if response and 'id' in response:
                thread_id = response['id']
                match.discord_thread_id = thread_id
                # No need to call db.session.commit(); handled by decorator
                logger.info(f"Successfully created thread: {thread_id} for match against {match.opponent}")
                return thread_id
            else:
                logger.error("Failed to create thread: No response or 'id' in response")
                return None
        except Exception as e:
            logger.error(f"Error creating thread: {str(e)}")
            return None