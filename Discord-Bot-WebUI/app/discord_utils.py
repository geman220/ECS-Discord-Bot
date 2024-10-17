import os
import aiohttp
from aiohttp import ClientSession
import asyncio
from datetime import datetime, timedelta
from web_config import Config
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
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
        self._lock = asyncio.Lock()
        self._reset_time = asyncio.get_event_loop().time()

    async def acquire(self):
        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            if current_time >= self._reset_time + self._period:
                self._reset_time = current_time
                self._calls = 0
            if self._calls >= self._max_calls:
                wait_time = self._reset_time + self._period - current_time
                logger.warning(f"Rate limiter sleeping for {wait_time} seconds")
                await asyncio.sleep(wait_time)
                self._reset_time = asyncio.get_event_loop().time()
                self._calls = 0
            self._calls += 1

# Instantiate the global rate limiter
rate_limiter = RateLimiter(max_calls=GLOBAL_RATE_LIMIT, period=1)

# Cache for categories and roles to minimize API calls
category_cache = {}
global_role_cache = {}

async def make_discord_request(method, url, session, **kwargs):
    backoff = 1
    for attempt in range(MAX_RETRIES):
        try:
            await rate_limiter.acquire()
            logger.debug(f"Making request {method} {url} with kwargs {kwargs}")
            async with session.request(method, url, timeout=30, **kwargs) as response:
                logger.debug(f"Received response with status {response.status} for {method} {url}")
                if response.status in [200, 201, 204]:
                    logger.debug(f"Request successful: {method} {url}")
                    if response.content_length and response.content_length > 0:
                        json_response = await response.json()
                        logger.debug(f"Response JSON: {json_response}")
                        return json_response
                    else:
                        return None
                elif response.status == 429:
                    retry_after = response.headers.get('Retry-After', 1)
                    backoff = float(retry_after)
                    logger.warning(f"Rate limited on {method} {url}. Retrying after {backoff} seconds.")
                    await asyncio.sleep(backoff)
                else:
                    error_text = await response.text()
                    logger.error(f"Failed request {method} {url}: {response.status}, {error_text}")
                    raise Exception(f"Discord API request failed: {response.status}, {error_text}")
        except Exception as e:
            logger.exception(f"Exception during {method} {url}: {e}")
            raise
    logger.error(f"Exceeded max retries for {method} {url}")
    raise Exception(f"Exceeded max retries for {method} {url}")

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

async def create_discord_channel(team_name, division, team_id):
    """Creates a new channel in Discord under the specified division category for a given team name."""
    from app.models import Team
    from app import db
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
                try:
                    team.discord_channel_id = discord_channel_id
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Error committing channel ID for team {team_name}: {str(e)}")
            else:
                logger.error(f"Failed to create channel for team {team_name}")
        else:
            logger.error(f"Failed to get or create category {category_name}")

async def create_discord_roles(team_name, team_id):
    """Creates two Discord roles (Coach and Player) for a team and stores their IDs."""
    from app.models import Team
    from app import db
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
        try:
            team.discord_coach_role_id = coach_role_id
            team.discord_player_role_id = player_role_id
            db.session.commit()
            logger.info(f"Created roles for team {team_name}: Coach Role ID {coach_role_id}, Player Role ID {player_role_id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing role IDs for team {team_name}: {str(e)}")

async def wait_for_role_registration(team_id, max_attempts=20, delay=0.1):
    """Waits for the role IDs (coach and player) to be registered in the database for a given team."""
    from app.models import Team
    team = None
    for attempt in range(max_attempts):
        team = Team.query.get(team_id)
        if team and team.discord_coach_role_id and team.discord_player_role_id:
            logger.debug(f"Roles registered for team ID {team_id}")
            return team
        await asyncio.sleep(delay)
    logger.error(f"Role IDs for team {team_id} not found after {max_attempts} attempts.")
    return None

async def assign_role_to_player(player):
    """Assigns both global and team-specific Discord roles to a player."""
    from app.models import Team
    if not player.discord_id:
        logger.warning(f"Player {player.name} does not have a linked Discord account.")
        return

    team = Team.query.get(player.team_id)
    if not team:
        logger.error(f"Team with ID {player.team_id} not found.")
        return

    guild_id = int(Config.SERVER_ID)
    async with aiohttp.ClientSession() as session:
        # Assign team role (coach or player)
        role_id = team.discord_player_role_id
        if player.is_coach:
            role_id = team.discord_coach_role_id

        if not role_id:
            logger.error(f"Role ID not found for the team {team.name} in the database.")
            return

        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
        try:
            await make_discord_request('PUT', url, session)
            logger.info(f"Assigned role ID {role_id} to user {player.discord_id} for team {team.name}.")
        except Exception as e:
            logger.error(f"Failed to assign role to player {player.name}: {e}")

        # Log the league name
        division_name = team.league.name.strip().lower()
        logger.debug(f"Player {player.name} is on team {team.name} in league '{division_name}' (repr: {repr(division_name)})")

        # Assign the global role based on the division
        if division_name == "classic":
            global_role_name = "ECS-FC-PL-CLASSIC"
        elif division_name == "premier":
            global_role_name = "ECS-FC-PL-PREMIER"
        elif division_name == "ecs fc":
            # Handle as needed
            global_role_name = "ECS-FC-LEAGUE"  # Adjust as necessary
        else:
            logger.warning(f"Unknown division '{division_name}' for team {team.name}")
            return
        logger.debug(f"Assigning global role '{global_role_name}' to player '{player.name}'")
        await assign_global_role(global_role_name, player, session)

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
    from app.models import Team
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
        expected_roles = get_expected_roles(player)
        
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
            'expected_roles': get_expected_roles(player),
            'status': 'error'
        }

def get_expected_roles(player):
    roles = []
    if player.team:
        roles.append(f"ECS-FC-PL-{player.team.name}-{'Coach' if player.is_coach else 'Player'}")
        if player.team.league:
            roles.append(f"ECS-FC-PL-{player.team.league.name.upper()}")
    if player.is_ref:
        roles.append("Referee")
    return roles

def mark_player_for_update(player_id):
    from app import db
    from app.models import Player
    try:
        Player.query.filter_by(id=player_id).update({Player.discord_needs_update: True})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking player {player_id} for update: {str(e)}")


def mark_team_for_update(team_id):
    from app import db
    from app.models import Player
    try:
        Player.query.filter_by(team_id=team_id).update({Player.discord_needs_update: True})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking team {team_id} for update: {str(e)}")


def mark_league_for_update(league_id):
    from app import db
    from app.models import Player, Team
    try:
        Player.query.join(Team).filter(Team.league_id == league_id).update({Player.discord_needs_update: True})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking league {league_id} for update: {str(e)}")

async def update_player_roles(player, session, force_update=False):
    from app import db
    if not player.discord_id:
        return False

    current_roles, status = await get_discord_roles(player.discord_id, session, force_check=force_update)
    expected_roles = get_expected_roles(player)

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
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating roles for player {player.name}: {str(e)}")
        return False

async def add_role_to_member(guild_id, user_id, role_id, session):
    url = f"{os.getenv('BOT_API_URL')}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    try:
        await make_discord_request('PUT', url, session)
    except Exception as e:
        logger.error(f"Error adding role {role_id} to user {user_id}: {str(e)}")

async def remove_role_from_member(guild_id, user_id, role_id, session):
    url = f"{os.getenv('BOT_API_URL')}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    try:
        await make_discord_request('DELETE', url, session)
    except Exception as e:
        logger.error(f"Error removing role {role_id} from user {user_id}: {str(e)}")

async def process_role_updates(force_update=False):
    from app.models import Player
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
    url = f"{os.getenv('BOT_API_URL')}/guilds/{guild_id}/roles"
    try:
        response = await make_discord_request('GET', url, session)
        for role in response:
            if role['name'] == role_name:
                return role['id']
    except Exception as e:
        logger.error(f"Error fetching role ID for {role_name}: {str(e)}")
    return None

async def fetch_user_roles(discord_id, session):
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{os.getenv('BOT_API_URL')}/guilds/{guild_id}/members/{discord_id}/roles"
    
    try:
        response = await make_discord_request('GET', url, session)
        if response and 'roles' in response:
            return [role['name'] for role in response['roles']]
        else:
            return []
    except Exception as e:
        print(f"Error fetching roles for user {discord_id}: {str(e)}")
        return []

async def process_single_player_update(player):
    async with aiohttp.ClientSession() as session:
        try:
            await assign_role_to_player(player)
            return True
        except Exception as e:
            print(f"Error updating roles for player {player.name}: {str(e)}")
            return False

async def process_mass_update(players):
    async with aiohttp.ClientSession() as session:
        tasks = [process_single_player_update(player) for player in players]
        results = await asyncio.gather(*tasks)
        return all(results)

async def get_discord_roles(user_id, session, force_check=False):
    from app import db
    from app.models import Player
    player = Player.query.filter_by(discord_id=user_id).first()
    if player and player.discord_roles and player.discord_last_verified and not force_check:
        if datetime.utcnow() - player.discord_last_verified < timedelta(days=90):
            return player.discord_roles, "cached"

    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{os.getenv('BOT_API_URL')}/guilds/{guild_id}/members/{user_id}/roles"
    
    try:
        response = await make_discord_request('GET', url, session)
        if response and 'roles' in response:
            roles = [role['name'] for role in response['roles']]
            if player:
                try:
                    player.discord_roles = roles
                    player.discord_last_verified = datetime.utcnow()
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Error committing Discord roles for player {player.name}: {str(e)}")
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
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    thread_data = await response.json()
                    thread_id = thread_data['id']
                    logger.info(f"Successfully created thread: {thread_id} for match against {match.opponent}")
                    return thread_id
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create thread. Status: {response.status}, Response: {error_text}")
                    return None
        except Exception as e:
            logger.error(f"Error creating thread: {str(e)}")
            return None