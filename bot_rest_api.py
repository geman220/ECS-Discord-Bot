# discord bot_rest_api.py

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from shared_states import bot_ready, bot_state
import logging
import discord
import asyncio
import aiohttp
import os
import requests
from discord.ext import commands
from datetime import datetime

# FIX THIS AFTER TESTING
TEAM_ID = '9726'

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

class EmbedField(BaseModel):
    name: str
    value: str
    inline: bool = False

class EmbedData(BaseModel):
    title: str
    description: str
    color: int
    fields: List[EmbedField]
    thumbnail_url: Optional[str] = None
    footer_text: Optional[str] = None

class MessageContent(BaseModel):
    content: str
    embed_data: EmbedData

class ThreadRequest(BaseModel):
    name: str
    type: int = 11
    auto_archive_duration: int = 4320  # 72 hours in minutes
    message: MessageContent

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
        print(f"Received request: {request.dict()}")
        home_channel = bot.get_channel(request.home_channel_id)
        away_channel = bot.get_channel(request.away_channel_id)
        if not home_channel or not away_channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        match_datetime = datetime.strptime(f"{request.match_date} {request.match_time}", "%Y-%m-%d %H:%M:%S")
        formatted_date = match_datetime.strftime('%-m/%-d/%y')
        formatted_time = match_datetime.strftime('%-I:%M %p')
        
        home_message = await home_channel.send(
            f"\u26BD **{request.home_team_name}** - Are you available for the match on {formatted_date} at {formatted_time}? "
            "React with \U0001F44D for Yes, \U0001F44E for No, or \U0001F937 for Maybe."
        )
        away_message = await away_channel.send(
            f"\u26BD **{request.away_team_name}** - Are you available for the match on {formatted_date} at {formatted_time}? "
            "React with \U0001F44D for Yes, \U0001F44E for No, or \U0001F937 for Maybe."
        )
        
        for message in [home_message, away_message]:
            await message.add_reaction("\U0001F44D")  # Thumbs Up
            await message.add_reaction("\U0001F44E")  # Thumbs Down
            await message.add_reaction("\U0001F937")  # Shrug
            bot_state.add_managed_message_id(message.id)
        
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

@app.post("/channels/{channel_id}/threads")
async def create_thread(channel_id: int, request: dict, bot: commands.Bot = Depends(get_bot)):
    logger.info(f"Attempting to create thread '{request['name']}' in channel {channel_id}")
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Channel {channel_id} not found")
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
    if not isinstance(channel, discord.ForumChannel):
        logger.error(f"Channel {channel_id} is not a forum channel")
        raise HTTPException(status_code=400, detail=f"Channel {channel_id} is not a forum channel")
    
    try:
        # Create Discord Embed object
        embed = discord.Embed(
            title=request['message']['embed_data']['title'],
            description=request['message']['embed_data']['description'],
            color=request['message']['embed_data']['color']
        )
        for field in request['message']['embed_data']['fields']:
            embed.add_field(name=field['name'], value=field['value'], inline=field['inline'])
        if request['message']['embed_data'].get('thumbnail_url'):
            embed.set_thumbnail(url=request['message']['embed_data']['thumbnail_url'])
        if request['message']['embed_data'].get('footer_text'):
            embed.set_footer(text=request['message']['embed_data']['footer_text'])
        
        # Create the thread
        thread = await channel.create_thread(
            name=request['name'],
            content=request['message']['content'],
            embed=embed,
            auto_archive_duration=request['auto_archive_duration']
        )
        
        # Handle ThreadWithMessage object
        if hasattr(thread, 'thread'):
            thread = thread.thread
        
        logger.info(f"Created thread '{request['name']}' (ID: {thread.id}) in forum {channel_id}")
        return {"id": str(thread.id), "name": thread.name}
    except discord.errors.Forbidden as e:
        logger.error(f"Permission error creating thread in forum {channel_id}: {str(e)}")
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to create threads")
    except discord.errors.HTTPException as e:
        logger.error(f"Discord API error creating thread in forum {channel_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create thread: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error creating thread in forum {channel_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

# Add this new endpoint to send a message to a thread
@app.post("/channels/{thread_id}/messages")
async def send_message_to_thread(thread_id: int, content: str, bot: commands.Bot = Depends(get_bot)):
    thread = bot.get_channel(thread_id)
    if not thread or not isinstance(thread, discord.Thread):
        raise HTTPException(status_code=404, detail="Thread not found")

    try:
        message = await thread.send(content)
        logger.info(f"Sent message to thread {thread_id}")
        return {"message_id": message.id, "content": message.content}
    except discord.errors.Forbidden:
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to send messages to this thread")
    except discord.errors.HTTPException as e:
        logger.error(f"Failed to send message to thread: {e}")
        raise HTTPException(status_code=500, detail="Failed to send message to thread")

@app.post("/post_match_update")
async def post_match_update(update: dict, bot: commands.Bot = Depends(get_bot)):
    thread_id = update.get("thread_id")
    update_type = update.get("update_type")
    update_data = update.get("update_data", {})

    try:
        embed = create_match_embed(update_type, update_data)
        
        channel = bot.get_channel(int(thread_id))
        if channel:
            await channel.send(embed=embed)
            logger.info(f"Successfully sent {update_type} update to thread {thread_id}")
        else:
            logger.error(f"Channel {thread_id} not found")
            raise HTTPException(status_code=404, detail=f"Channel {thread_id} not found")

    except Exception as e:
        logger.error(f"Error in post_match_update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True}

def create_match_embed(update_type, update_data):
    focus_team_id = str(TEAM_ID)  # Our team ID

    if update_type == "score_update":
        return create_score_update_embed(update_data, focus_team_id)
    elif update_type in ["match_event", "hype_event"]:
        return create_match_event_embed(update_data, focus_team_id, is_hype=(update_type == "hype_event"))
    elif update_type == "halftime":
        return create_halftime_embed(update_data, focus_team_id)
    elif update_type == "fulltime":
        return create_fulltime_embed(update_data, focus_team_id)
    elif update_type == "pre_match_info":
        return create_pre_match_embed(update_data, focus_team_id)
    else:
        # Default embed for unknown update types
        logger.warning(f"Unknown update type: {update_type}")
        embed = discord.Embed(
            title="Match Update",
            description="An update has occurred."
        )
        return embed

def create_match_update_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    match_status = update_data.get('match_status', "Unknown")
    time = update_data.get('time', "N/A")
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")

    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()

    # Determine if the focus team is the home or away team
    if home_team_id == focus_team_id:
        # Our team is the home team
        embed.title = f"🏟️ Match Update: {home_team_name} vs {away_team_name}"
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))

        if int(home_score) > int(away_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value="We're leading! Let's keep up the momentum! 💪", inline=False)
        elif int(home_score) < int(away_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value="We're trailing. Time to rally! 🔥", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value="All tied up! Push for the lead! ⚽", inline=False)
    elif away_team_id == focus_team_id:
        # Our team is the away team
        embed.title = f"🏟️ Match Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))

        if int(away_score) > int(home_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value="We're ahead! Keep the pressure on! 💪", inline=False)
        elif int(away_score) < int(home_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value="We're behind. Let's fight back! 🔥", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value="It's a draw! Let's take the lead! ⚽", inline=False)
    else:
        # Neither team is our focus team
        embed.title = f"Match Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()
        embed.add_field(name="Status", value=match_status, inline=False)

    embed.add_field(name="Match Status", value=match_status, inline=True)
    embed.add_field(name="Time", value=time, inline=True)

    return embed

def create_match_event_embed(event_data, focus_team_id, is_hype=False):
    event_type = event_data.get('type', '')
    event_team = event_data.get('team', {})
    event_time = event_data.get('time', "N/A")
    athlete = event_data.get('player', {})
    home_team = event_data.get('home_team', {})
    away_team = event_data.get('away_team', {})
    home_score = event_data.get('home_score', "0")
    away_score = event_data.get('away_score', "0")

    event_team_id = str(event_team.get('id', ""))
    event_team_name = event_team.get('displayName', "Unknown Team")
    is_focus_team_event = event_team_id == focus_team_id

    # Prepare embed based on event type and favorability
    if event_type == "Goal":
        embed = create_goal_embed(event_team_name, athlete, is_focus_team_event, event_time, is_hype)
    elif event_type in ["Yellow Card", "Red Card"]:
        embed = create_card_embed(event_type, event_team_name, athlete, is_focus_team_event, event_time, is_hype)
    else:
        embed = discord.Embed(
            title=f"{event_type} - {event_team_name}",
            description=f"An event occurred for {event_team_name}."
        )
        embed.color = discord.Color.green() if is_hype else discord.Color.blue()
        embed.add_field(name="Time", value=event_time, inline=True)

    # Add current score to the embed
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    embed.add_field(name="Score", value=f"{home_team_name} {home_score} - {away_score} {away_team_name}", inline=False)

    # Add player image
    add_player_image(embed, athlete)

    return embed

def create_goal_embed(team_name, athlete, is_focus_team_event, event_time, is_hype):
    scorer_name = athlete.get('displayName', "Unknown Player")

    if is_focus_team_event:
        # Our team scored
        embed = discord.Embed(
            title=f"🎉 GOOOOOAAAALLLL! {team_name} scores!",
            description=f"**{scorer_name}** nets one for us at {event_time}! Keep it coming! ⚽🔥",
            color=discord.Color.green()
        )
    else:
        # Opponent team scored
        if is_hype:
            # Hype for opponent's misfortune (not applicable for goals)
            pass  # This case shouldn't happen based on your logic
        else:
            embed = discord.Embed(
                title=f"😡 Goal for {team_name}",
                description=f"{scorer_name} scores for the opposition at {event_time}. Let's strike back! 💪",
                color=discord.Color.red()
            )

    return embed

def create_card_embed(card_type, team_name, athlete, is_focus_team_event, event_time, is_hype):
    player_name = athlete.get('displayName', "Unknown Player")
    emoji = "🟨" if card_type == "Yellow Card" else "🟥"

    if is_hype:
        # Favorable event (opponent received a card)
        embed = discord.Embed(
            title=f"{emoji} {card_type} for {team_name}",
            description=f"{player_name} from {team_name} got a {card_type.lower()} at {event_time}! Advantage us! 😈",
            color=discord.Color.green()
        )
    else:
        # Unfavorable event (our team received a card)
        embed = discord.Embed(
            title=f"{emoji} {card_type} for {team_name}",
            description=f"Unfortunately, {player_name} received a {card_type.lower()} at {event_time}. Stay focused!",
            color=discord.Color.red() if card_type == "Red Card" else discord.Color.gold()
        )
    return embed

def create_substitution_embed(team_name, athlete, is_focus_team_event, event_time):
    player_in = athlete.get('in', {}).get('displayName', "Unknown Player")
    player_out = athlete.get('out', {}).get('displayName', "Unknown Player")

    if is_focus_team_event:
        embed = discord.Embed(
            title=f"🔄 Substitution for {team_name}",
            description=f"{player_in} comes on for {player_out} at {event_time}. Fresh legs! 🏃‍♂️",
            color=discord.Color.blue()
        )
    else:
        embed = discord.Embed(
            title=f"🔄 Substitution for {team_name}",
            description=f"{team_name} brings on {player_in} for {player_out} at {event_time}. Stay focused!",
            color=discord.Color.light_grey()
        )

    return embed

def add_player_image(embed, athlete):
    if isinstance(athlete, dict) and 'id' in athlete:
        player_id = athlete['id']
        player_image_url = f"https://a.espncdn.com/combiner/i?img=/i/headshots/soccer/players/full/{player_id}.png"
        embed.set_thumbnail(url=player_image_url)

def create_score_update_embed(update_data, focus_team_id):
    # Extract current and previous scores
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = int(update_data.get('home_score', "0"))
    away_score = int(update_data.get('away_score', "0"))
    previous_home_score = int(update_data.get('previous_home_score', home_score))
    previous_away_score = int(update_data.get('previous_away_score', away_score))
    time = update_data.get('time', "N/A")

    # Determine if a goal has been scored
    goal_scored = False
    if home_score > previous_home_score or away_score > previous_away_score:
        goal_scored = True
        # Prepare event data for the goal
        if home_score > previous_home_score:
            scoring_team = home_team
            scoring_team_id = str(home_team.get('id', ""))
            scoring_team_name = home_team.get('displayName', "Home Team")
        else:
            scoring_team = away_team
            scoring_team_id = str(away_team.get('id', ""))
            scoring_team_name = away_team.get('displayName', "Away Team")

        # Include player information if available
        goal_scorer = update_data.get('goal_scorer', {})
        event_data = {
            'type': 'Goal',
            'team': scoring_team,
            'player': goal_scorer,
            'time': time,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': str(home_score),
            'away_score': str(away_score)
        }
        return create_match_event_embed(event_data, focus_team_id)

    # If no goal, create a generic score update embed
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.add_field(name="Time", value=time, inline=True)

    if home_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.green() if home_score > away_score else discord.Color.red()
        embed.set_thumbnail(url=home_team.get('logo'))
        if home_score > away_score:
            embed.add_field(name="Status", value="We're in the lead! Keep pushing! 🔥", inline=False)
        elif home_score < away_score:
            embed.add_field(name="Status", value="We're behind, but it's not over! Let's rally! 💪", inline=False)
        else:
            embed.add_field(name="Status", value="It's all square! Time to take control! ⚖️", inline=False)
    elif away_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.color = discord.Color.green() if away_score > home_score else discord.Color.red()
        embed.set_thumbnail(url=away_team.get('logo'))
        if away_score > home_score:
            embed.add_field(name="Status", value="We're in the lead! Keep pushing! 🔥", inline=False)
        elif away_score < home_score:
            embed.add_field(name="Status", value="We're behind, but it's not over! Let's rally! 💪", inline=False)
        else:
            embed.add_field(name="Status", value="It's all square! Time to take control! ⚖️", inline=False)
    else:
        embed.title = f"Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()

    return embed

def create_halftime_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")

    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = "Half-Time"
    embed.color = discord.Color.orange()
    embed.set_footer(text="45 minutes played. Second half coming up!")

    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.add_field(name="Our Performance", value="Stay tuned for the second half!", inline=False)
        embed.set_thumbnail(url=home_team.get('logo'))
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.add_field(name="Our Performance", value="Stay tuned for the second half!", inline=False)
        embed.set_thumbnail(url=away_team.get('logo'))
    else:
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"

    return embed

def create_fulltime_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")

    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = "Full-Time"
    embed.set_footer(text="Match has ended.")

    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        if int(home_score) > int(away_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Result", value="Victory! 🎉", inline=False)
        elif int(home_score) < int(away_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value="Defeat. We'll come back stronger! 💪", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Result", value="Draw. A hard-fought point! ⚖️", inline=False)
        embed.set_thumbnail(url=home_team.get('logo'))
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        if int(away_score) > int(home_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Result", value="Victory! 🎉", inline=False)
        elif int(away_score) < int(home_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value="Defeat. We'll come back stronger! 💪", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Result", value="Draw. A hard-fought point! ⚖️", inline=False)
        embed.set_thumbnail(url=away_team.get('logo'))
    else:
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()

    return embed

def create_pre_match_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🚨 Pre-Match Hype: {home_team_name} vs {away_team_name} 🚨"
    embed.color = discord.Color.blue()

    embed.add_field(name="📅 Date", value=update_data.get('match_date_formatted', "N/A"), inline=False)
    embed.add_field(name="🏟️ Venue", value=update_data.get('venue', "N/A"), inline=False)
    embed.add_field(name="🏠 Home Form", value=update_data.get('home_form', "N/A"), inline=True)
    embed.add_field(name="🛫 Away Form", value=update_data.get('away_form', "N/A"), inline=True)

    odds_info = (
        f"Home Win: {update_data.get('home_odds', 'N/A')}\n"
        f"Draw: {update_data.get('draw_odds', 'N/A')}\n"
        f"Away Win: {update_data.get('away_odds', 'N/A')}"
    )
    embed.add_field(name="💰 Odds", value=odds_info, inline=False)

    if home_team_id == str(focus_team_id):
        embed.description = f"🔥 It's matchday! Get ready to witness {home_team_name} dominate on home turf! 🏟️"
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Team Spirit", value="Our boys are fired up and ready to give it their all! 💪", inline=False)
    elif away_team_id == str(focus_team_id):
        embed.description = f"🌟 It's time for {away_team_name} to shine on the road! Let's show them what we're made of! 💪"
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Away Day Magic", value="We're taking our A-game to their turf! Let's make our traveling fans proud! 🛫", inline=False)
    else:
        embed.description = "An exciting match is on the horizon! Who will come out on top?"

    return embed