from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from shared_states import bot_ready
import logging
import discord
import asyncio
import aiohttp
import os
import requests
from discord.ext import commands
from datetime import datetime

# Direct API call to Discord
async def direct_api_permission_update(channel_id, role_id, allow, deny, bot_token):
    url = f"https://discord.com/api/v10/channels/{channel_id}/permissions/{role_id}"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "allow": str(allow),
        "deny": str(deny),
        "type": 0  # For role overwrite
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, json=payload) as response:
            if response.status in [200, 204]:
                logger.info(f"Permissions set successfully for role ID {role_id} on channel ID {channel_id}")
                return {"status": "Permissions updated"}
            else:
                logger.error(f"Failed to set permissions: {response.status} - {await response.text()}")
                raise HTTPException(status_code=response.status, detail=f"Failed to set permissions: {await response.text()}")

# Initialize FastAPI app
app = FastAPI()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global bot instance, initially None
bot_instance = None

# Setter function to update the bot instance
def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot

# Dependency to get the bot instance
async def get_bot():
    logger.info("Waiting for bot to be ready...")
    while not bot_ready.is_set():
        await asyncio.sleep(0.1)
    logger.info("Bot is ready. Proceeding to get the bot instance.")

    if bot_instance is None or bot_instance.user is None:
        logger.error("Bot is not initialized properly.")
        raise HTTPException(status_code=500, detail="Bot is not initialized properly.")
    return bot_instance

class PermissionOverwriteRequest(BaseModel):
    id: int  # Role or Member ID
    type: int  # 0 for role, 1 for member
    allow: Optional[str] = "0"
    deny: Optional[str] = "0"

class ChannelRequest(BaseModel):
    name: str
    type: int = Field(..., description="Channel type: 0 for text channel, 4 for category")
    parent_id: Optional[int] = Field(None, description="Parent category ID (only for text channels)")
    permission_overwrites: Optional[List[PermissionOverwriteRequest]] = None

class PermissionRequest(BaseModel):
    id: int
    type: int
    allow: str
    deny: str

class RoleRequest(BaseModel):
    name: str
    permissions: str = "0"  # String representation of permissions integer
    mentionable: bool = False

class UpdateChannelRequest(BaseModel):
    new_name: str

class UpdateRoleRequest(BaseModel):
    new_name: str

class AvailabilityRequest(BaseModel):
    home_channel_id: int
    away_channel_id: int
    match_id: int
    match_date: str
    match_time: str
    home_team_name: str
    away_team_name: str

@app.get("/guilds/{guild_id}/channels")
async def get_channels(guild_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    
    channels = [{"id": channel.id, "name": channel.name, "type": channel.type.value} for channel in guild.channels]
    return channels

# Create a new channel in a guild
@app.post("/guilds/{guild_id}/channels")
async def create_channel(guild_id: int, request: ChannelRequest, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    overwrites = {}

    if request.permission_overwrites:
        for overwrite_data in request.permission_overwrites:
            target_id = overwrite_data.id
            overwrite_type = overwrite_data.type
            allow = int(overwrite_data.allow)
            deny = int(overwrite_data.deny)

            # Get the role or member object
            if overwrite_type == 0:  # Role
                target = guild.get_role(target_id)
            elif overwrite_type == 1:  # Member
                target = guild.get_member(target_id)
            else:
                continue  # Invalid type, skip

            if not target:
                logger.warning(f"Target with ID {target_id} not found")
                continue

            # Create PermissionOverwrite object
            permissions = discord.PermissionOverwrite.from_pair(
                discord.Permissions(allow), discord.Permissions(deny)
            )
            overwrites[target] = permissions

    if request.type == 4:  # Category creation
        try:
            new_category = await guild.create_category(request.name, overwrites=overwrites)
            return {"id": new_category.id, "name": new_category.name}
        except Exception as e:
            logger.error(f"Failed to create category: {e}")
            raise HTTPException(status_code=500, detail="Failed to create category")
    else:  # Text channel creation
        try:
            parent_category = guild.get_channel(request.parent_id) if request.parent_id else None
            new_channel = await guild.create_text_channel(
                request.name, category=parent_category, overwrites=overwrites
            )
            return {"id": new_channel.id, "name": new_channel.name}
        except Exception as e:
            logger.error(f"Failed to create channel: {e}")
            raise HTTPException(status_code=500, detail="Failed to create channel")

# Rename a channel in a guild
@app.patch("/guilds/{guild_id}/channels/{channel_id}")
async def update_channel(guild_id: int, channel_id: int, request: UpdateChannelRequest, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    channel = guild.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    try:
        await channel.edit(name=request.new_name)
        return {"id": channel.id, "name": channel.name}
    except Exception as e:
        logger.error(f"Failed to update channel: {e}")
        raise HTTPException(status_code=500, detail="Failed to update channel")

# Delete a channel in a guild
@app.delete("/guilds/{guild_id}/channels/{channel_id}")
async def delete_channel(guild_id: int, channel_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    channel = guild.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    try:
        # Optionally, archive the channel before deleting if needed
        await channel.delete()
        return {"status": "Channel deleted"}
    except Exception as e:
        logger.error(f"Failed to delete channel: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete channel")

# Create a new role in a guild
@app.post("/guilds/{guild_id}/roles")
async def create_role(
    guild_id: int,
    request: RoleRequest,
    bot: commands.Bot = Depends(get_bot)
):
    logger.info(f"Received request to create role '{request.name}' in guild '{guild_id}'")
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error(f"Guild not found: {guild_id}")
        raise HTTPException(status_code=404, detail="Guild not found")

    try:
        permissions = discord.Permissions(int(request.permissions))
        logger.debug(f"Creating role with permissions: {permissions.value}")
        new_role = await guild.create_role(
            name=request.name,
            permissions=permissions,
            mentionable=request.mentionable
        )
        logger.info(f"Created role '{new_role.name}' with ID {new_role.id}")
        response_data = {"id": str(new_role.id), "name": new_role.name}
        logger.debug(f"Returning response: {response_data}")
        return response_data
    except discord.errors.HTTPException as e:
        logger.exception(f"HTTPException occurred: {e.status} {e.text}")
        raise HTTPException(status_code=e.status, detail=e.text)
    except Exception as e:
        logger.exception(f"Failed to create role '{request.name}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create role: {e}")

# Get roles from guild
@app.get("/guilds/{guild_id}/roles")
async def get_roles(guild_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    roles = [{"id": role.id, "name": role.name} for role in guild.roles]
    return roles

# Rename a role in a guild
@app.put("/guilds/{guild_id}/roles/{role_id}")
async def update_role(guild_id: int, role_id: int, request: UpdateRoleRequest, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    role = guild.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    try:
        await role.edit(name=request.new_name)
        return {"id": role.id, "name": role.name}
    except Exception as e:
        logger.error(f"Failed to update role: {e}")
        raise HTTPException(status_code=500, detail="Failed to update role")

# Delete a role in a guild
@app.delete("/guilds/{guild_id}/roles/{role_id}")
async def delete_role(guild_id: int, role_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    role = guild.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    try:
        await role.delete()
        return {"status": "Role deleted"}
    except Exception as e:
        logger.error(f"Failed to delete role: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete role")

# Use bot's internal API or direct API call based on preference
@app.put("/guilds/{guild_id}/channels/{channel_id}/permissions/{role_id}")
async def update_channel_permissions(guild_id: int, channel_id: int, role_id: int, request: PermissionRequest, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    channel = guild.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    try:
        # Log the intended permissions
        logger.info(f"Attempting to set permissions for role ID {role_id} on channel ID {channel_id} with allow={request.allow} and deny={request.deny}")

        # Option 1: Use the bot's API (preferred)
        allow_permissions = discord.Permissions(int(request.allow))
        deny_permissions = discord.Permissions(int(request.deny))
        overwrite = discord.PermissionOverwrite.from_pair(allow_permissions, deny_permissions)
        await channel.set_permissions(guild.get_role(role_id), overwrite=overwrite)
        logger.info(f"Permissions set successfully using bot's internal API")

        return {"status": "Permissions updated"}

    except Exception as bot_api_error:
        logger.error(f"Failed to update permissions via bot's API: {bot_api_error}")
        logger.info("Falling back to direct Discord API call...")

        # Option 2: Fallback to a direct Discord API call if bot's API fails
        bot_token = os.getenv("DISCORD_BOT_TOKEN")  # Make sure to set this in your environment
        return await direct_api_permission_update(channel_id, role_id, request.allow, request.deny, bot_token)

@app.get("/guilds/{guild_id}/members/{user_id}/roles")
async def get_member_roles(guild_id: int, user_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    
    try:
        member = await guild.fetch_member(user_id)
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        roles = [{"id": str(role.id), "name": role.name} for role in member.roles]
        return {
            "user_id": str(member.id),
            "username": member.name,
            "roles": roles
        }
    except discord.errors.NotFound:
        raise HTTPException(status_code=404, detail="Member not found")
    except discord.errors.Forbidden:
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to access this member")
    except Exception as e:
        logger.error(f"Failed to get member roles: {e}")
        raise HTTPException(status_code=500, detail="Failed to get member roles")

@app.put("/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
async def add_role_to_member(guild_id: int, user_id: int, role_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    member = guild.get_member(user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    role = guild.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    try:
        await member.add_roles(role)
        logger.info(f"Role {role.name} assigned to user {member.name}")
        return {"status": "Role assigned"}
    except Exception as e:
        logger.error(f"Failed to assign role: {e}")
        raise HTTPException(status_code=500, detail="Failed to assign role")

@app.delete("/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
async def remove_role_from_member(guild_id: int, user_id: int, role_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    member = guild.get_member(user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    role = guild.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    try:
        await member.remove_roles(role)
        logger.info(f"Role {role.name} removed from user {member.name}")
        return {"status": "Role removed"}
    except Exception as e:
        logger.error(f"Failed to remove role: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove role")

@app.post("/api/post_availability")
async def post_availability(request: AvailabilityRequest, bot: commands.Bot = Depends(get_bot)):
    try:
        print(f"Received request: {request.dict()}")  # Log the received request data

        # Use the channel IDs provided in the request
        home_channel = bot.get_channel(request.home_channel_id)
        away_channel = bot.get_channel(request.away_channel_id)

        if not home_channel or not away_channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        match_datetime = datetime.strptime(f"{request.match_date} {request.match_time}", "%Y-%m-%d %H:%M:%S")
        formatted_date = match_datetime.strftime('%-m/%-d/%y')
        formatted_time = match_datetime.strftime('%-I:%M %p')

        # Send the messages to both channels
        home_message = await home_channel.send(
            f"\u26BD **{request.home_team_name}** - Are you available for the match on {formatted_date} at {formatted_time}? "
            "React with \U0001F44D for Yes, \U0001F44E for No, or \U0001F937 for Maybe."
        )

        away_message = await away_channel.send(
            f"\u26BD **{request.away_team_name}** - Are you available for the match on {formatted_date} at {formatted_time}? "
            "React with \U0001F44D for Yes, \U0001F44E for No, or \U0001F937 for Maybe."
        )

        await home_message.add_reaction("\U0001F44D")  # Thumbs Up
        await home_message.add_reaction("\U0001F44E")  # Thumbs Down
        await home_message.add_reaction("\U0001F937")  # Shrug

        await away_message.add_reaction("\U0001F44D")
        await away_message.add_reaction("\U0001F44E")
        await away_message.add_reaction("\U0001F937")

        # Send the message IDs back to the Web UI
        store_message_ids_in_web_ui(request.match_id, home_message.id, away_message.id)

        return {"home_message_id": home_message.id, "away_message_id": away_message.id}

    except Exception as e:
        print(f"Error in posting availability: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

def store_message_ids_in_web_ui(match_id, home_message_id, away_message_id):
    api_url = "http://webui:5000/api/store_message_ids"  # Adjust to your Web UI endpoint
    payload = {
        'match_id': match_id,
        'home_message_id': home_message_id,
        'away_message_id': away_message_id
    }
    response = requests.post(api_url, json=payload)
    if response.status_code != 200:
        print(f"Failed to store message IDs in Web UI: {response.text}")
