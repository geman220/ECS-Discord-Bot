import os
import aiohttp
import asyncio
from web_config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_category_with_retry(guild_id, category_name, session):
    """Creates a new category with retries in case of rate limits."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
    payload = {
        "name": category_name,
        "type": 4
    }

    while True:
        async with session.post(url, json=payload) as response:
            if response.status in [200, 201]:
                category = await response.json()
                print(f"Created category: {category_name} with ID {category['id']}")
                return category['id']
            elif response.status == 429:
                retry_after = response.headers.get('Retry-After', 1)
                print(f"Rate limited. Retrying after {retry_after} seconds.")
                await asyncio.sleep(float(retry_after))
            else:
                print(f"Failed to create category: {response.status}, {await response.text()}")
                return None

async def get_or_create_category(guild_id, category_name, session):
    """Gets the category by name or creates it if it doesn't exist."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"

    async with session.get(url) as response:
        if response.status == 200:
            channels = await response.json()
            for channel in channels:
                if channel['type'] == 4 and channel['name'].lower() == category_name.lower():
                    print(f"Category '{category_name}' already exists with ID {channel['id']}.")
                    return channel['id']

    return await create_category_with_retry(guild_id, category_name, session)

async def create_discord_channel(team_name, division, team_id):
    """Creates a new channel in Discord under the specified division category for a given team name using the bot's REST API."""
    from app.models import Team
    from app import db
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels"
    
    category_name = f"ECS FC PL {division.capitalize()}"
    
    async with aiohttp.ClientSession() as session:
        category_id = await get_or_create_category(guild_id, category_name, session)
        
        if category_id:
            # Create roles first
            await create_discord_roles(team_name, team_id)
            
            # Wait until roles are registered in the database
            team = None
            for _ in range(20):  # Retry up to 20 times with a short delay
                team = Team.query.get(team_id)
                if team and team.discord_coach_role_id and team.discord_player_role_id:
                    break
                await asyncio.sleep(0.1)
            
            if not team or not team.discord_coach_role_id or not team.discord_player_role_id:
                print(f"Failed to retrieve role IDs for team {team_name} from the database.")
                return
            
            # Create the channel with default permissions
            payload = {
                "name": team_name,
                "parent_id": category_id,
                "type": 0,
                "permission_overwrites": [
                    {
                        "id": guild_id,  # @everyone role
                        "type": 0,  # Role
                        "deny": "1024"  # Deny VIEW_CHANNEL
                    },
                ]
            }
            async with session.post(url, json=payload) as response:
                if response.status in [200, 201]:
                    channel = await response.json()
                    discord_channel_id = channel['id']
                    print(f"Created Discord channel: {team_name} under category {category_name} with ID {discord_channel_id}")
                    
                    # Update the team with the discord_channel_id
                    team.discord_channel_id = discord_channel_id
                    db.session.commit()

                    # Wait until the channel is properly registered in Discord
                    for _ in range(20):  # Retry up to 20 times with a short delay
                        try:
                            # Attempt to fetch the channel details
                            channel_check = await session.get(f"{url}/{discord_channel_id}")
                            if channel_check.status in [200, 201]:
                                break
                        except Exception as e:
                            print(f"Error fetching channel: {e}")
                        await asyncio.sleep(0.1)

                    # Update channel permissions to add Coach and Player roles
                    await update_channel_permissions(discord_channel_id, [
                        {
                            "id": team.discord_coach_role_id,
                            "type": 0,  # Role
                            "allow": "208373533760"  # Allow VIEW_CHANNEL
                        },
                        {
                            "id": team.discord_player_role_id,
                            "type": 0,  # Role
                            "allow": "208373533760"  # Allow VIEW_CHANNEL
                        }
                    ])
                else:
                    print(f"Failed to create channel: {response.status}, {await response.text()}")
        else:
            print(f"Could not find or create category: {category_name}. Channel creation aborted.")

async def update_channel_permissions(channel_id, permissions):
    """Updates channel permissions using the bot's REST API."""
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels/{channel_id}/permissions"
    
    async with aiohttp.ClientSession() as session:
        for permission in permissions:
            # Ensure both allow and deny are present in the payload
            payload = {
                "id": permission['id'],
                "type": permission['type'],
                "allow": permission.get("allow", "0"),  # Default to "0" if not set
                "deny": permission.get("deny", "0")    # Default to "0" if not set
            }
            permission_url = f"{url}/{payload['id']}"
            async with session.put(permission_url, json=payload) as response:
                if response.status in [200, 201]:
                    print(f"Updated permissions for role ID {payload['id']} on channel ID {channel_id}")
                else:
                    print(f"Failed to update permissions for role ID {payload['id']} on channel ID {channel_id}: {response.status}, {await response.text()}")

async def assign_roles_to_channel(channel_id, coach_role_id, player_role_id, session):
    """Assigns the Coach and Player roles to the channel with appropriate permissions and denies access to @everyone."""
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/channels/{channel_id}/permissions"

    permissions_payloads = [
        {
            "id": coach_role_id,
            "type": 0,  # Role
            "allow": "1049600",  # VIEW_CHANNEL, SEND_MESSAGES, etc.
            "deny": "0"  # No permissions denied
        },
        {
            "id": player_role_id,
            "type": 0,  # Role
            "allow": "1049600",  # VIEW_CHANNEL, SEND_MESSAGES, etc.
            "deny": "0"  # No permissions denied
        },
        {
            "id": guild_id,  # @everyone role
            "type": 0,  # Role
            "allow": "0",  # No permissions allowed
            "deny": "1024"  # Deny VIEW_CHANNEL
        }
    ]

    for payload in permissions_payloads:
        async with session.put(f"{url}/{payload['id']}", json=payload) as response:
            if response.status in [200, 201]:
                print(f"Assigned role ID {payload['id']} to channel ID {channel_id}")
            else:
                print(f"Failed to assign role: {response.status}, {await response.text()}")

async def rename_discord_channel(team, new_team_name):
    """Renames an existing channel in Discord for the specified team using the bot's REST API."""
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels/{team.discord_channel_id}"

    async with aiohttp.ClientSession() as session:
        payload = {
            "new_name": new_team_name  # Update the key to 'new_name' as expected by the API
        }
        async with session.patch(url, json=payload) as response:
            response_text = await response.text()
            if response.status in [200, 201]:
                logger.info(f"Renamed Discord channel ID {team.discord_channel_id} from {team.name} to {new_team_name}")
            else:
                logger.error(f"Failed to rename channel {team.discord_channel_id}: {response.status}, {response_text}")
                raise Exception(f"Failed to rename channel: {response.status}, {response_text}")

async def delete_discord_channel(team):
    """Deletes an existing channel in Discord for the specified team using the bot's REST API."""
    guild_id = int(os.getenv('SERVER_ID'))
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/channels/{team.discord_channel_id}"

    async with aiohttp.ClientSession() as session:
        async with session.delete(url) as response:
            if response.status == 200:
                print(f"Deleted Discord channel ID {team.discord_channel_id}: {team.name}")
            else:
                print(f"Failed to delete channel: {response.status}, {await response.text()}")

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
        team.discord_coach_role_id = coach_role_id
        team.discord_player_role_id = player_role_id
        db.session.commit()

async def create_discord_role(guild_id, role_name, session):
    """Creates a Discord role and returns its ID."""
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/roles"
    payload = {"name": role_name}
    
    async with session.post(url, json=payload) as response:
        if response.status in [200, 201]:
            role = await response.json()
            return role['id']
        else:
            print(f"Failed to create role: {response.status}, {await response.text()}")
            return None

async def rename_discord_roles(team, new_team_name):
    """Renames the Discord roles associated with a team."""
    guild_id = int(os.getenv('SERVER_ID'))
    
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
    payload = {"new_name": new_role_name}  # Update to match the expected field name
    
    logger.debug(f"Attempting to rename role ID {role_id} to {new_role_name}")
    logger.debug(f"Sending PUT request to URL: {url} with payload: {payload}")
    
    async with session.put(url, json=payload) as response:
        response_text = await response.text()
        if response.status in [200, 201]:
            logger.info(f"Successfully renamed Discord role ID {role_id} to {new_role_name}")
        else:
            logger.error(f"Failed to rename role ID {role_id}: {response.status}, {response_text}")
            raise Exception(f"Failed to rename role: {response.status}, {response_text}")

async def delete_discord_roles(team):
    """Deletes the Discord roles associated with a team."""
    guild_id = int(os.getenv('SERVER_ID'))
    
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
    
    async with session.delete(url) as response:
        if response.status == 200:
            print(f"Deleted Discord role ID {role_id}")
        else:
            print(f"Failed to delete role: {response.status}, {await response.text()}")

async def assign_role_to_player(player):
    """Sends a request to the bot API to assign a Discord role to a player."""
    from app.models import Team
    if not player.discord_id:
        print(f"Player {player.name} does not have a linked Discord account.")
        return

    team = Team.query.get(player.team_id)
    if not team:
        print(f"Team with ID {player.team_id} not found.")
        return

    role_id = team.discord_player_role_id
    if player.is_coach:
        role_id = team.discord_coach_role_id

    if not role_id:
        print(f"Role ID not found for the team {team.name} in the database.")
        return

    url = f"{Config.BOT_API_URL}/guilds/{os.getenv('SERVER_ID')}/members/{player.discord_id}/roles/{role_id}"
    
    async with aiohttp.ClientSession() as session:
        async with session.put(url) as response:
            if response.status == 200:
                print(f"Assigned role ID {role_id} to user {player.discord_id} for team {team.name}.")
            else:
                print(f"Failed to assign role: {response.status}, {await response.text()}")

async def remove_role_from_player(player):
    """Removes the player's role in Discord when they are removed from the team."""
    if not player.discord_id:
        print(f"Player {player.name} does not have a linked Discord account.")
        return

    guild_id = int(os.getenv('SERVER_ID'))
    from app.models import Team

    # Fetch the player's team
    team = Team.query.get(player.team_id)
    if not team:
        print(f"Team with ID {player.team_id} not found.")
        return

    # Determine the correct role ID to remove
    role_id = team.discord_player_role_id
    if player.is_coach:
        role_id = team.discord_coach_role_id

    if not role_id:
        print(f"Role ID not found for team {team.name}.")
        return

    # Remove the role from the user via bot API
    url = f"{Config.BOT_API_URL}/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}"
    
    async with aiohttp.ClientSession() as session:
        async with session.delete(url) as response:
            if response.status in [200, 204]:
                print(f"Removed role ID {role_id} from user {player.discord_id}.")
            else:
                print(f"Failed to remove role: {response.status}, {await response.text()}")