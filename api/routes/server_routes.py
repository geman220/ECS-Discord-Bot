"""
FastAPI router for Discord server management endpoints.
Handles channels, roles, permissions, and member role management.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from discord.ext import commands
from shared_states import get_bot_instance, bot_ready
import logging
import discord
import asyncio
import aiohttp
import os

from api.models.schemas import (
    ChannelRequest, RoleRequest, UpdateChannelRequest, 
    UpdateRoleRequest, PermissionRequest, PermissionOverwriteRequest
)
from api.utils.discord_utils import get_bot
from api.utils.api_client import get_session, direct_api_permission_update

# Set up logging
logger = logging.getLogger(__name__)

# Create the router
router = APIRouter(prefix="/api/server", tags=["server"])

# Session management is handled by api_client module

# Models and dependencies imported from other modules

# Functions imported from other modules

# Channel management endpoints
@router.get("/guilds/{guild_id}/channels")
async def get_channels(guild_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    
    channels = [{"id": channel.id, "name": channel.name, "type": channel.type.value} for channel in guild.channels]
    return channels

@router.post("/guilds/{guild_id}/channels")
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

@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: int, request: UpdateChannelRequest, bot: commands.Bot = Depends(get_bot)):
    try:
        # Fetch the channel directly from Discord API to avoid cache issues
        channel = await bot.fetch_channel(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Debugging: Log the new name received
        logger.debug(f"Received request to rename channel {channel_id} to: {request.new_name}")

        # Edit the channel name
        await channel.edit(name=request.new_name)  # Accessing the parsed new_name field
        return {"id": channel.id, "name": channel.name}
    except discord.errors.NotFound:
        raise HTTPException(status_code=404, detail="Channel not found")
    except Exception as e:
        logger.error(f"Failed to update channel: {e}")
        raise HTTPException(status_code=500, detail="Failed to update channel")

@router.delete("/guilds/{guild_id}/channels/{channel_id}")
async def delete_channel(guild_id: int, channel_id: int, bot: commands.Bot = Depends(get_bot)):
    logger.info(f"Received request to delete channel {channel_id} in guild {guild_id}")
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error(f"Guild not found for ID: {guild_id}")
        raise HTTPException(status_code=404, detail="Guild not found")

    try:
        channel = await bot.fetch_channel(channel_id)
        if not channel:
            logger.error(f"Channel not found for ID: {channel_id}")
            raise HTTPException(status_code=404, detail="Channel not found")
        await channel.delete()
        logger.info(f"Successfully deleted channel: {channel_id}")
        return {"status": "Channel deleted"}
    except Exception as e:
        logger.error(f"Error deleting channel: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete channel")

# Role management endpoints
@router.post("/guilds/{guild_id}/roles")
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

@router.get("/guilds/{guild_id}/roles")
async def get_roles(guild_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    roles = [{"id": role.id, "name": role.name} for role in guild.roles]
    return roles

@router.patch("/guilds/{guild_id}/roles/{role_id}")
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

@router.delete("/guilds/{guild_id}/roles/{role_id}")
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

# Permission management endpoints
@router.put("/guilds/{guild_id}/channels/{channel_id}/permissions/{role_id}")
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

# Member role management endpoints
@router.get("/guilds/{guild_id}/members/{user_id}/roles")
async def get_member_roles(guild_id: int, user_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error(f"Guild with ID {guild_id} not found.")
        raise HTTPException(status_code=404, detail="Guild not found")
    
    try:
        member = await guild.fetch_member(user_id)
        if not member:
            logger.error(f"Member with ID {user_id} not found in guild {guild_id}.")
            raise HTTPException(status_code=404, detail="Member not found")
        
        # Return a list of role names
        role_names = [role.name for role in member.roles]
        return {
            "user_id": str(member.id),
            "username": member.name,
            "roles": role_names  # Return role names directly
        }
    except discord.NotFound as e:
        logger.error(f"Member with ID {user_id} not found in guild {guild_id}: {e}")
        raise HTTPException(status_code=404, detail="Member not found")
    except discord.Forbidden as e:
        logger.error(f"Bot lacks permissions to fetch member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to access this member")
    except discord.HTTPException as e:
        logger.error(f"HTTPException while fetching member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=e.status, detail=f"Discord API error: {e.text}")
    except Exception as e:
        logger.exception(f"Unexpected error while fetching member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get member roles")

@router.put("/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
async def add_role_to_member(guild_id: int, user_id: int, role_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    member = await guild.fetch_member(user_id)
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

@router.delete("/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
async def remove_role_from_member(guild_id: int, user_id: int, role_id: int, bot: commands.Bot = Depends(get_bot)):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    member = await guild.fetch_member(user_id)
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

@router.get("/guilds/{guild_id}/members/{user_id}")
async def get_member(guild_id: int, user_id: int, bot: commands.Bot = Depends(get_bot)):
    """Get a member's basic information from the guild."""
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error(f"Guild with ID {guild_id} not found.")
        raise HTTPException(status_code=404, detail="Guild not found")
    
    try:
        member = await guild.fetch_member(user_id)
        return {
            "id": str(member.id),
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "username": member.name,
            "display_name": member.display_name,
            "discriminator": member.discriminator,
            "avatar": str(member.avatar.url) if member.avatar else None,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "premium_since": member.premium_since.isoformat() if member.premium_since else None,
            "pending": member.pending,
            "roles": [{"id": str(role.id), "name": role.name} for role in member.roles if role.name != "@everyone"]
        }
    except discord.NotFound:
        logger.info(f"Member {user_id} not found in guild {guild_id}")
        raise HTTPException(status_code=404, detail="Member not found")
    except discord.Forbidden as e:
        logger.error(f"Bot lacks permissions to fetch member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to access this member")
    except discord.HTTPException as e:
        logger.error(f"HTTPException while fetching member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=e.status, detail=f"Discord API error: {e.text}")
    except Exception as e:
        logger.exception(f"Unexpected error while fetching member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch member")

@router.get("/guilds/{guild_id}/members/{user_id}/status")
async def check_member_status(guild_id: int, user_id: int, bot: commands.Bot = Depends(get_bot)):
    """Check if a user is a member of the guild."""
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error(f"Guild with ID {guild_id} not found.")
        raise HTTPException(status_code=404, detail="Guild not found")
    
    try:
        member = await guild.fetch_member(user_id)
        return {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "in_server": True,
            "username": member.name,
            "display_name": member.display_name
        }
    except discord.NotFound:
        return {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "in_server": False,
            "username": None,
            "display_name": None
        }
    except discord.Forbidden as e:
        logger.error(f"Bot lacks permissions to fetch member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to access this member")
    except discord.HTTPException as e:
        logger.error(f"HTTPException while fetching member {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=e.status, detail=f"Discord API error: {e.text}")
    except Exception as e:
        logger.exception(f"Unexpected error while checking member status {user_id} in guild {guild_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to check member status")

@router.post("/guilds/{guild_id}/invites")
async def create_invite(guild_id: int, request: dict, bot: commands.Bot = Depends(get_bot)):
    """Create a server invite."""
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    try:
        # Get the default channel or a general channel to create invite from
        channel = None
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).create_instant_invite:
                channel = ch
                break
        
        if not channel:
            raise HTTPException(status_code=403, detail="No channel found where bot can create invites")

        invite = await channel.create_invite(
            max_uses=request.get("max_uses", 1),
            max_age=request.get("max_age", 86400),  # 24 hours default
            unique=True
        )
        
        return {
            "invite_url": invite.url,
            "invite_code": invite.code,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
            "max_uses": invite.max_uses
        }
    except Exception as e:
        logger.error(f"Failed to create invite: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create invite: {e}")


