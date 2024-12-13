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
from app.models import Team, Player, MLSMatch, Match
from sqlalchemy.orm import Session
from app.utils.discord_request_handler import make_discord_request

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

class RateLimiter:
    def __init__(self, max_calls, period):
        self._max_calls = max_calls
        self._period = period
        self._calls = 0
        self._reset_time = time.time()
        self._lock = asyncio.Lock() if hasattr(asyncio, 'Lock') else None
    
    def _should_reset(self, current_time):
        return current_time >= self._reset_time + self._period
    
    def _reset_counter(self, current_time):
        self._reset_time = current_time
        self._calls = 0
    
    def acquire_sync(self):
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

rate_limiter = RateLimiter(max_calls=GLOBAL_RATE_LIMIT, period=1)

# Use role_name_cache and category_cache as defined

async def get_role_id(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
    role_id = role_name_cache.get(role_name)
    if role_id:
        return role_id

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response:
        for role in response:
            role_name_cache[role['name']] = role['id']
        return role_name_cache.get(role_name)
    return None

async def create_role(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
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

async def get_or_create_role(guild_id: int, role_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
    role_id = role_name_cache.get(role_name)
    if role_id:
        return role_id

    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response:
        for role in response:
            role_name_cache[role['name']] = role['id']
            if role['name'] == role_name:
                return role['id']

    return await create_role(guild_id, role_name, session)

async def assign_role_to_member(guild_id: int, user_id: str, role_id: str, session: aiohttp.ClientSession) -> None:
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    await make_discord_request('PUT', url, session)

async def remove_role_from_member(guild_id: int, user_id: str, role_id: str, session: aiohttp.ClientSession) -> None:
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    await make_discord_request('DELETE', url, session)

async def get_member_roles(user_id: str, session: aiohttp.ClientSession) -> Optional[List[str]]:
    guild_id = int(os.getenv('SERVER_ID') or Config.SERVER_ID)
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{user_id}/roles"
    response = await make_discord_request('GET', url, session)
    if response is None:
        logger.warning(f"User {user_id} not found in server.")
        return None
    if 'roles' in response:
        role_names = response['roles']
        return role_names
    logger.error(f"No roles found for user {user_id}")
    return []

async def get_role_names(guild_id: int, role_ids: List[str], session: aiohttp.ClientSession) -> List[str]:
    missing_role_ids = [r for r in role_ids if r not in role_name_cache]

    if missing_role_ids:
        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
        response = await make_discord_request('GET', url, session)
        if response:
            for role in response:
                role_name_cache[role['id']] = role['name']

    role_names = [role_name_cache.get(role_id, "Unknown Role") for role_id in role_ids]
    return role_names

async def get_or_create_category(guild_id: int, category_name: str, session: aiohttp.ClientSession) -> Union[str, None]:
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
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
    payload = {
        "name": category_name,
        "type": 4,
    }
    response = await make_discord_request('POST', url, session, json=payload)
    if response and 'id' in response:
        category_id = response['id']
        category_cache[category_name] = category_id
        logger.info(f"Created category '{category_name}' with ID {category_id}")
        return category_id
    logger.error(f"Failed to create category '{category_name}'")
    return None

async def create_discord_roles(session: Session, team_name: str, team_id: int) -> None:
    guild_id = int(os.getenv('SERVER_ID'))
    coach_role_name = f"ECS-FC-PL-{team_name}-Coach"
    player_role_name = f"ECS-FC-PL-{team_name}-Player"

    async with aiohttp.ClientSession() as http_session:
        coach_role_id = await get_or_create_role(guild_id, coach_role_name, http_session)
        player_role_id = await get_or_create_role(guild_id, player_role_name, http_session)

        team = session.query(Team).get(team_id)
        team.discord_coach_role_id = coach_role_id
        team.discord_player_role_id = player_role_id
        logger.info(
            f"Created roles for team {team_name}: Coach Role ID {coach_role_id}, Player Role ID {player_role_id}"
        )

async def create_discord_channel(session: Session, team_name: str, division: str, team_id: int) -> None:
    guild_id = int(os.getenv('SERVER_ID'))
    category_name = f"ECS FC PL {division.capitalize()}"

    async with aiohttp.ClientSession() as http_session:
        category_id = await get_or_create_category(guild_id, category_name, http_session)
        if not category_id:
            logger.error(f"Failed to get or create category '{category_name}'")
            return

        await create_discord_roles(session, team_name, team_id)
        team = session.query(Team).get(team_id)
        if not team.discord_coach_role_id or not team.discord_player_role_id:
            logger.error(f"Role IDs not found for team '{team_name}'")
            return

        wg_admin_role_id = await get_or_create_role(guild_id, "WG: ECS FC ADMIN", http_session)

        permission_overwrites = [
            {"id": str(guild_id), "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"},
            {"id": str(team.discord_player_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
            {"id": str(team.discord_coach_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
            {"id": str(wg_admin_role_id), "type": 0, "allow": str(TEAM_ROLE_PERMISSIONS), "deny": "0"},
        ]

        payload = {
            "name": team_name,
            "parent_id": category_id,
            "type": 0,
            "permission_overwrites": permission_overwrites,
        }
        url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
        response = await make_discord_request('POST', url, http_session, json=payload)
        if response and 'id' in response:
            team.discord_channel_id = response['id']
            logger.info(f"Created Discord channel '{team_name}' with ID {team.discord_channel_id}")
        else:
            logger.error(f"Failed to create channel for team '{team_name}'")

async def assign_roles_to_player(session: Session, player: Player) -> None:
    if not player.discord_id or not player.team:
        logger.warning(f"Player '{player.name}' has no Discord ID or team assigned.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        role_name_suffix = 'Coach' if player.is_coach else 'Player'
        team_role_name = f"ECS-FC-PL-{player.team.name}-{role_name_suffix}"
        team_role_id = await get_or_create_role(guild_id, team_role_name, http_session)
        if team_role_id:
            await assign_role_to_member(guild_id, player.discord_id, team_role_id, http_session)
            logger.info(f"Assigned role '{team_role_name}' to player '{player.name}'")
        else:
            logger.error(f"Failed to assign team role '{team_role_name}' to player '{player.name}'")

        league_role_name = get_league_role_name(player.team.league.name)
        if league_role_name:
            league_role_id = await get_or_create_role(guild_id, league_role_name, http_session)
            if league_role_id:
                await assign_role_to_member(guild_id, player.discord_id, league_role_id, http_session)
                logger.info(f"Assigned league role '{league_role_name}' to player '{player.name}'")
            else:
                logger.error(f"Failed to assign league role '{league_role_name}' to player '{player.name}'")
        else:
            logger.error(f"Unknown league '{player.team.league.name}' for player '{player.name}'")

def get_league_role_name(league_name: str) -> Union[str, None]:
    league_map = {
        'Classic': 'ECS-FC-PL-CLASSIC',
        'Premier': 'ECS-FC-PL-PREMIER',
        'ECS FC': 'ECS-FC-LEAGUE',
    }
    return league_map.get(league_name.strip())

async def remove_player_roles(session: Session, player: Player) -> None:
    if not player.discord_id or not player.team:
        logger.warning(f"Player '{player.name}' has no Discord ID or team assigned.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        role_name_suffix = 'Coach' if player.is_coach else 'Player'
        team_role_name = f"ECS-FC-PL-{player.team.name}-{role_name_suffix}"
        team_role_id = await get_role_id(guild_id, team_role_name, http_session)
        if team_role_id:
            await remove_role_from_member(guild_id, player.discord_id, team_role_id, http_session)
            logger.info(f"Removed role '{team_role_name}' from player '{player.name}'")
        else:
            logger.error(f"Team role '{team_role_name}' not found for player '{player.name}'")

async def rename_team_roles(session: Session, team: Team, new_team_name: str) -> None:
    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        if team.discord_coach_role_id:
            new_coach_role_name = f"ECS-FC-PL-{new_team_name}-Coach"
            await rename_role(guild_id, team.discord_coach_role_id, new_coach_role_name, http_session)

        if team.discord_player_role_id:
            new_player_role_name = f"ECS-FC-PL-{new_team_name}-Player"
            await rename_role(guild_id, team.discord_player_role_id, new_player_role_name, http_session)

async def rename_role(guild_id: int, role_id: str, new_name: str, session: aiohttp.ClientSession) -> None:
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
    payload = {"name": new_name}
    response = await make_discord_request('PATCH', url, session, json=payload)
    if response:
        logger.info(f"Renamed role ID {role_id} to '{new_name}'")
    else:
        logger.error(f"Failed to rename role ID {role_id} to '{new_name}'")

async def delete_team_roles(session: Session, team: Team) -> None:
    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        if team.discord_coach_role_id:
            await delete_role(guild_id, team.discord_coach_role_id, http_session)
        if team.discord_player_role_id:
            await delete_role(guild_id, team.discord_player_role_id, http_session)

async def delete_role(guild_id: int, role_id: str, session: aiohttp.ClientSession) -> None:
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles/{role_id}"
    response = await make_discord_request('DELETE', url, session)
    if response:
        logger.info(f"Deleted role ID {role_id}")
    else:
        logger.error(f"Failed to delete role ID {role_id}")

async def delete_team_channel(session: Session, team: Team) -> None:
    if not team.discord_channel_id:
        logger.error(f"Team '{team.name}' does not have a Discord channel ID.")
        return

    url = f"{Config.BOT_API_URL}/channels/{team.discord_channel_id}"
    async with aiohttp.ClientSession() as http_session:
        response = await make_discord_request('DELETE', url, http_session)
        if response:
            logger.info(f"Deleted channel ID {team.discord_channel_id} for team '{team.name}'")
        else:
            logger.error(f"Failed to delete channel ID {team.discord_channel_id} for team '{team.name}'")

async def update_player_roles(session: Session, player: Player, force_update: bool = False) -> None:
    if not player.discord_id:
        logger.warning(f"Player '{player.name}' does not have a Discord ID.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    async with aiohttp.ClientSession() as http_session:
        current_roles_ids = await get_member_roles(player.discord_id, http_session)
        if current_roles_ids is None:
            logger.warning(f"User {player.discord_id} not found in Discord guild.")
            return

        current_roles = await get_role_names(guild_id, current_roles_ids, http_session)
        expected_roles = await get_expected_roles(session, player)
        roles_to_add = set(expected_roles) - set(current_roles)
        roles_to_remove = set(current_roles) - set(expected_roles)

        for role_name in roles_to_add:
            role_id = await get_or_create_role(guild_id, role_name, http_session)
            if role_id:
                await assign_role_to_member(guild_id, player.discord_id, role_id, http_session)
                logger.info(f"Added role '{role_name}' to player '{player.name}'")
            else:
                logger.error(f"Failed to add role '{role_name}' to player '{player.name}'")

        for role_name in roles_to_remove:
            role_id = await get_role_id(guild_id, role_name, http_session)
            if role_id:
                await remove_role_from_member(guild_id, player.discord_id, role_id, http_session)
                logger.info(f"Removed role '{role_name}' from player '{player.name}'")
            else:
                logger.error(f"Failed to remove role '{role_name}' from player '{player.name}'")

        player.discord_roles = expected_roles
        player.discord_last_verified = datetime.utcnow()
        player.discord_needs_update = False

async def get_expected_roles(session: Session, player: Player) -> List[str]:
    roles = []
    if player.team:
        role_suffix = 'Coach' if player.is_coach else 'Player'
        role_name = f"ECS-FC-PL-{player.team.name}-{role_suffix}"
        roles.append(role_name)
    if player.team and player.team.league:
        league_role_name = get_league_role_name(player.team.league.name)
        if league_role_name:
            roles.append(league_role_name)
    if player.is_ref:
        roles.append('Referee')
    return roles

async def process_role_updates(session: Session, force_update: bool = False) -> None:
    if force_update:
        players_to_update = session.query(Player).filter(Player.discord_id.isnot(None)).all()
    else:
        threshold_date = datetime.utcnow() - timedelta(days=90)
        players_to_update = session.query(Player).filter(
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified == None) |
            (Player.discord_last_verified < threshold_date)
        ).all()

    for player in players_to_update:
        await update_player_roles(session, player, force_update=force_update)

def mark_player_for_update(session: Session, player_id: int) -> None:
    session.query(Player).filter_by(id=player_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked player ID {player_id} for Discord update.")

def mark_team_for_update(session: Session, team_id: int) -> None:
    session.query(Player).filter_by(team_id=team_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked team ID {team_id} for Discord update.")

def mark_league_for_update(session: Session, league_id: int) -> None:
    session.query(Player).join(Team).filter(Team.league_id == league_id).update({Player.discord_needs_update: True})
    logger.info(f"Marked league ID {league_id} for Discord update.")

async def process_single_player_update(session: Session, player: Player) -> dict:
    try:
        if not player.discord_id:
            logger.warning(f"Player '{player.name}' does not have a Discord ID.")
            return {'success': False, 'message': 'No Discord ID associated with player', 'error': 'no_discord_id'}

        await update_player_roles(session, player, force_update=True)
        return {'success': True, 'message': 'Roles updated successfully'}
    except Exception as e:
        logger.error(f"Error in process_single_player_update for player {player.id}: {str(e)}", exc_info=True)
        return {'success': False, 'message': 'An exception occurred', 'error': str(e)}

async def create_match_thread(session: Session, match: MLSMatch) -> Union[str, None]:
    if not match:
        logger.error("No match provided for thread creation")
        return None

    # Load the channel ID from environment
    guild_id = int(os.getenv('SERVER_ID'))
    mls_channel_id = os.getenv('MATCH_CHANNEL_ID')
    if not mls_channel_id:
        logger.error("No MATCH_CHANNEL_ID provided in environment.")
        return None

    # Determine team names based on is_home_game
    local_team_name = "Seattle Sounders FC"
    if match.is_home_game:
        home_team_name = local_team_name
        away_team_name = match.opponent
    else:
        home_team_name = match.opponent
        away_team_name = local_team_name

    # Construct the thread name
    thread_name = f"{home_team_name} vs {away_team_name} - {match.date_time.strftime('%Y-%m-%d')}"

    # Restore the richer embed formatting from previous code
    # We'll include date/time, venue, competition, broadcast, home/away, and links if available
    embed_data = {
        "title": f"Match Thread: {home_team_name} vs {away_team_name}",
        "description": "**Let's go Sounders!**",
        "color": 0x5B9A49,  # Sounders greenish color
        "fields": [
            {
                "name": "Date and Time",
                "value": match.date_time.strftime("%m/%d/%Y %I:%M %p PST"),
                "inline": False
            },
            {
                "name": "Venue",
                "value": match.venue if match.venue else "TBD",
                "inline": False
            },
            {
                "name": "Competition",
                "value": match.competition if match.competition else "Unknown",
                "inline": True
            },
            {
                "name": "Broadcast",
                "value": "AppleTV",
                "inline": True
            },
            {
                "name": "Home/Away",
                "value": "Home" if match.is_home_game else "Away",
                "inline": True
            }
        ],
        "thumbnail_url": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/9726.png",
        "footer_text": "Use /predict to participate in match predictions!"
    }

    # If we have summary, stats, or commentary links, add them as additional fields
    if match.summary_link:
        embed_data["fields"].append({"name": "Match Summary", "value": f"[Click here]({match.summary_link})", "inline": True})
    if match.stats_link:
        embed_data["fields"].append({"name": "Match Statistics", "value": f"[Click here]({match.stats_link})", "inline": True})
    if match.commentary_link:
        embed_data["fields"].append({"name": "Live Commentary", "value": f"[Click here]({match.commentary_link})", "inline": True})

    payload = {
        "name": thread_name,
        "type": 11,
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

async def fetch_user_roles(session: Session, discord_id, http_session: aiohttp.ClientSession, retries=3, delay=0.5):
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{discord_id}/roles"
    
    for attempt in range(retries):
        try:
            response = await make_discord_request('GET', url, http_session)
            if response and 'roles' in response:
                # Check if roles is a dict (role_id -> role_name) or a list of dicts
                if isinstance(response['roles'], dict):
                    # roles is a dict {role_id: role_name, ...}
                    roles = list(response['roles'].values())
                elif isinstance(response['roles'], list) and all(isinstance(r, dict) for r in response['roles']):
                    # roles is a list of dicts like [{'name': 'RoleName', ...}, ...]
                    roles = [r['name'] for r in response['roles']]
                else:
                    logger.error(f"Unexpected roles format in response for user {discord_id}: {response['roles']}")
                    roles = []

                expected_roles = await get_expected_roles_for_user(session, discord_id, http_session)
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

async def get_expected_roles_for_user(session: Session, discord_id: str, http_session: aiohttp.ClientSession) -> List[str]:
    # You need to determine the player from discord_id and then call get_expected_roles(session, player)
    player = session.query(Player).filter(Player.discord_id == discord_id).first()
    if not player:
        logger.warning(f"No player found with discord_id {discord_id}")
        return []
    return await get_expected_roles(session, player)

def validate_roles(actual: List[str], expected: List[str]) -> bool:
    # Implement your validation logic for roles
    return set(actual) == set(expected)
