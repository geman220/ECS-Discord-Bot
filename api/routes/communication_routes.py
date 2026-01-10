"""
FastAPI Communication Routes for Discord Bot Operations.
Handles direct messaging, thread messaging, and communication features.

Extracted from bot_rest_api.py to create a modular router.
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from discord.ext import commands
import discord
import logging
from typing import Optional
from datetime import datetime

from api.utils.discord_utils import get_bot
from api.models.schemas import (
    LeagueEventAnnouncementRequest,
    LeagueEventUpdateRequest,
    LeagueEventDeleteRequest
)
from config import BOT_CONFIG

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Event type configurations for embeds
LEAGUE_EVENT_COLORS = {
    'party': 0x9c27b0,      # Purple
    'meeting': 0xff9800,    # Orange
    'social': 0xe91e63,     # Pink
    'training': 0x4caf50,   # Green
    'tournament': 0xf44336, # Red
    'other': 0x607d8b       # Blue-grey
}

LEAGUE_EVENT_ICONS = {
    'party': '🎉',
    'meeting': '👥',
    'social': '❤️',
    'training': '⚽',
    'tournament': '🏆',
    'other': '📅'
}


@router.post("/send_discord_dm")
async def send_discord_dm(
    message: str = Body(..., embed=True, description="The message to send"),
    discord_id: str = Body(..., embed=True, description="The player's Discord ID"),
    bot: commands.Bot = Depends(get_bot)
):
    """Send a direct message to a Discord user."""
    # Fetch the Discord user by their discord_id
    try:
        user = await bot.fetch_user(int(discord_id))
    except Exception as e:
        raise HTTPException(status_code=404, detail="User not found or Discord ID invalid")
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Attempt to send a DM to the user
    try:
        dm_channel = await user.create_dm()
        dm_message = await dm_channel.send(message)
        return {"status": "sent", "message_id": dm_message.id}
    except discord.Forbidden as e:
        # Extract specific error details from Discord API
        error_code = getattr(e, 'code', None)
        error_text = str(e)
        
        # Provide specific error messages based on Discord error codes
        if error_code == 50007:
            detail = "Cannot send DM to this user - they have disabled DMs from server members"
        elif error_code == 50001:
            detail = "Cannot send DM to this user - missing access (user may have blocked the bot)"
        elif "Cannot send messages to this user" in error_text:
            detail = "Cannot send DM to this user - they have disabled DMs or blocked the bot"
        else:
            detail = f"Cannot send DM to this user - Discord error {error_code}: {error_text}"
            
        logger.warning(f"Failed to send DM to user {discord_id}: {detail}")
        raise HTTPException(status_code=403, detail=detail)
    except discord.HTTPException as e:
        # Handle other Discord HTTP errors
        error_detail = f"Discord API error {e.status}: {e.text}"
        logger.error(f"Discord HTTP error sending DM to {discord_id}: {error_detail}")
        raise HTTPException(status_code=e.status, detail=error_detail)
    except Exception as e:
        logger.error(f"Unexpected error sending DM to {discord_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send DM: {str(e)}")


def create_league_event_embed(request: LeagueEventAnnouncementRequest) -> discord.Embed:
    """Create a Discord embed for a league event announcement."""
    from zoneinfo import ZoneInfo

    event_type = request.event_type.lower()
    color = LEAGUE_EVENT_COLORS.get(event_type, LEAGUE_EVENT_COLORS['other'])
    icon = LEAGUE_EVENT_ICONS.get(event_type, LEAGUE_EVENT_ICONS['other'])

    # Format the event type for display
    type_display = event_type.replace('_', ' ').title()

    # Build title
    title = f"{icon} {request.title}"

    # Build embed
    embed = discord.Embed(
        title=title,
        description=request.description or "",
        color=color
    )

    # Pacific timezone for display
    pacific_tz = ZoneInfo('America/Los_Angeles')

    # Parse and format datetime - convert to Pacific time for display
    try:
        start_dt = datetime.fromisoformat(request.start_datetime.replace('Z', '+00:00'))
        # Convert to Pacific timezone for display
        start_dt_pacific = start_dt.astimezone(pacific_tz)

        if request.is_all_day:
            date_str = start_dt_pacific.strftime("%A, %B %d, %Y")
            embed.add_field(name="📅 Date", value=date_str, inline=True)
        else:
            date_str = start_dt_pacific.strftime("%A, %B %d, %Y")
            time_str = start_dt_pacific.strftime("%I:%M %p")
            embed.add_field(name="📅 Date", value=date_str, inline=True)
            embed.add_field(name="🕐 Time", value=time_str, inline=True)

        # Add end time if provided
        if request.end_datetime:
            end_dt = datetime.fromisoformat(request.end_datetime.replace('Z', '+00:00'))
            end_dt_pacific = end_dt.astimezone(pacific_tz)
            if not request.is_all_day:
                end_time_str = end_dt_pacific.strftime("%I:%M %p")
                embed.add_field(name="🏁 Until", value=end_time_str, inline=True)
    except ValueError as e:
        logger.warning(f"Failed to parse datetime for event {request.event_id}: {e}")
        embed.add_field(name="📅 Date", value=request.start_datetime, inline=True)

    # Add location if provided
    if request.location:
        embed.add_field(name="📍 Location", value=request.location, inline=False)

    # Add event type badge
    embed.add_field(name="🏷️ Event Type", value=type_display, inline=True)

    # Footer
    embed.set_footer(text="Pub League Event • React to show interest!")

    return embed


async def resolve_channel(
    bot: commands.Bot,
    channel_id: Optional[int] = None,
    channel_name: Optional[str] = None
) -> discord.TextChannel:
    """
    Resolve a channel by ID, name, or fall back to configured default.

    Priority:
    1. channel_id if provided
    2. channel_name lookup if provided
    3. Configured LEAGUE_ANNOUNCEMENTS_CHANNEL_ID
    4. Fall back to MATCH_CHANNEL_ID
    """
    guild_id = BOT_CONFIG.get('server_id')
    if not guild_id:
        raise HTTPException(status_code=500, detail="Server ID not configured")

    guild = bot.get_guild(int(guild_id))
    if not guild:
        try:
            guild = await bot.fetch_guild(int(guild_id))
        except Exception:
            raise HTTPException(status_code=500, detail="Could not access Discord server")

    # Try channel_id first
    if channel_id:
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                raise HTTPException(status_code=404, detail=f"Channel with ID {channel_id} not found")
        return channel

    # Try channel_name lookup
    if channel_name:
        channel_name_lower = channel_name.lower().strip()
        for channel in guild.text_channels:
            if channel.name.lower() == channel_name_lower:
                return channel
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found. Available channels: {', '.join([c.name for c in guild.text_channels[:10]])}..."
        )

    # Fall back to configured channel
    default_channel_id = BOT_CONFIG.get('league_announcements_channel_id')
    if not default_channel_id:
        default_channel_id = BOT_CONFIG.get('match_channel_id')

    if not default_channel_id:
        raise HTTPException(
            status_code=500,
            detail="No announcement channel configured. Set LEAGUE_ANNOUNCEMENTS_CHANNEL_ID in environment."
        )

    channel = bot.get_channel(int(default_channel_id))
    if not channel:
        try:
            channel = await bot.fetch_channel(int(default_channel_id))
        except Exception:
            raise HTTPException(status_code=500, detail="Configured announcement channel not accessible")

    return channel


@router.post("/api/league-event/announce")
async def post_league_event_announcement(
    request: LeagueEventAnnouncementRequest,
    bot: commands.Bot = Depends(get_bot)
):
    """
    Post a league event announcement to Discord.

    Supports channel resolution by:
    - Direct channel_id
    - Channel name lookup (channel_name)
    - Configured default (LEAGUE_ANNOUNCEMENTS_CHANNEL_ID)
    """
    try:
        # Resolve the channel
        channel = await resolve_channel(bot, request.channel_id, request.channel_name)

        # Create the embed
        embed = create_league_event_embed(request)

        # Post the announcement
        message = await channel.send(embed=embed)

        logger.info(f"Posted league event announcement for event {request.event_id} to channel {channel.name} ({channel.id})")

        return {
            "status": "success",
            "message_id": message.id,
            "channel_id": channel.id,
            "channel_name": channel.name
        }

    except HTTPException:
        raise
    except discord.Forbidden as e:
        logger.error(f"Permission denied posting to channel: {e}")
        raise HTTPException(status_code=403, detail="Bot lacks permission to post in that channel")
    except discord.HTTPException as e:
        logger.error(f"Discord API error: {e}")
        raise HTTPException(status_code=e.status, detail=f"Discord API error: {e.text}")
    except Exception as e:
        logger.error(f"Unexpected error posting league event announcement: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/league-event/announce/{event_id}")
async def update_league_event_announcement(
    event_id: int,
    request: LeagueEventUpdateRequest,
    bot: commands.Bot = Depends(get_bot)
):
    """Update an existing league event announcement."""
    try:
        channel = bot.get_channel(request.channel_id)
        if not channel:
            channel = await bot.fetch_channel(request.channel_id)

        message = await channel.fetch_message(request.message_id)

        # Create updated embed
        announcement_request = LeagueEventAnnouncementRequest(
            event_id=request.event_id,
            title=request.title,
            description=request.description,
            event_type=request.event_type,
            location=request.location,
            start_datetime=request.start_datetime,
            end_datetime=request.end_datetime,
            is_all_day=request.is_all_day
        )
        embed = create_league_event_embed(announcement_request)

        # Update the message
        await message.edit(embed=embed)

        logger.info(f"Updated league event announcement for event {event_id}")

        return {
            "status": "success",
            "message_id": message.id,
            "channel_id": channel.id
        }

    except discord.NotFound:
        raise HTTPException(status_code=404, detail="Message not found - it may have been deleted")
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Bot lacks permission to edit that message")
    except Exception as e:
        logger.error(f"Error updating league event announcement: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/league-event/announce")
async def delete_league_event_announcement(
    request: LeagueEventDeleteRequest,
    bot: commands.Bot = Depends(get_bot)
):
    """Delete a league event announcement from Discord."""
    try:
        channel = bot.get_channel(request.channel_id)
        if not channel:
            channel = await bot.fetch_channel(request.channel_id)

        message = await channel.fetch_message(request.message_id)
        await message.delete()

        logger.info(f"Deleted league event announcement (message {request.message_id})")

        return {"status": "success", "deleted": True}

    except discord.NotFound:
        # Already deleted, consider it a success
        return {"status": "success", "deleted": True, "note": "Message was already deleted"}
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Bot lacks permission to delete that message")
    except Exception as e:
        logger.error(f"Error deleting league event announcement: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/channels/by-name/{channel_name}")
async def get_channel_by_name(
    channel_name: str,
    bot: commands.Bot = Depends(get_bot)
):
    """
    Look up a channel by name and return its ID.
    Useful for configuring announcement channels by name instead of ID.
    """
    try:
        channel = await resolve_channel(bot, channel_name=channel_name)
        return {
            "channel_id": channel.id,
            "channel_name": channel.name,
            "channel_type": str(channel.type)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error looking up channel by name: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Event reminder configurations
EVENT_REMINDER_COLORS = {
    'party': 0x9c27b0,      # Purple
    'meeting': 0xff9800,    # Orange
    'social': 0xe91e63,     # Pink
    'plop': 0x4caf50,       # Green
    'tournament': 0xf44336, # Red
    'fundraiser': 0xff5722, # Deep Orange
    'other': 0x607d8b       # Blue-grey
}

EVENT_REMINDER_ICONS = {
    'party': '🎉',
    'meeting': '👥',
    'social': '❤️',
    'plop': '⚽',
    'tournament': '🏆',
    'fundraiser': '💰',
    'other': '📅'
}


@router.post("/api/event-reminder")
async def post_event_reminder(
    title: str = Body(..., embed=True),
    event_type: str = Body(..., embed=True),
    date_str: str = Body(..., embed=True),
    time_str: str = Body(..., embed=True),
    location: Optional[str] = Body(None, embed=True),
    description: Optional[str] = Body(None, embed=True),
    channel_name: str = Body('league-announcements', embed=True),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Post an event reminder to a Discord channel.

    Used for reminding members about upcoming events.
    """
    try:
        # Resolve the channel
        channel = await resolve_channel(bot, channel_name=channel_name)

        # Build the embed
        event_type_lower = event_type.lower()
        color = EVENT_REMINDER_COLORS.get(event_type_lower, EVENT_REMINDER_COLORS['other'])
        icon = EVENT_REMINDER_ICONS.get(event_type_lower, EVENT_REMINDER_ICONS['other'])

        embed = discord.Embed(
            title=f"{icon} Reminder: {title}",
            description=description or "",
            color=color
        )

        embed.add_field(name="📅 Date", value=date_str, inline=True)
        embed.add_field(name="🕐 Time", value=time_str, inline=True)

        if location:
            embed.add_field(name="📍 Location", value=location, inline=False)

        embed.set_footer(text="Don't miss it!")

        # Send the message
        message = await channel.send(embed=embed)

        logger.info(f"Posted event reminder for '{title}' to {channel.name}")

        return {
            "status": "success",
            "message_id": message.id,
            "channel_id": channel.id,
            "channel_name": channel.name
        }

    except HTTPException:
        raise
    except discord.Forbidden as e:
        logger.error(f"Permission denied posting event reminder: {e}")
        raise HTTPException(status_code=403, detail="Bot lacks permission to post in that channel")
    except Exception as e:
        logger.error(f"Error posting event reminder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/plop-reminder")
async def post_plop_reminder(
    date_str: str = Body(..., embed=True),
    time_str: str = Body(..., embed=True),
    location: str = Body(..., embed=True),
    end_time_str: Optional[str] = Body(None, embed=True),
    channel_name: str = Body('league-announcements', embed=True),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Post a PLOP reminder to Discord.

    Specifically formatted for PLOP events with emphasis on the location.
    """
    try:
        # Resolve the channel
        channel = await resolve_channel(bot, channel_name=channel_name)

        # Build the PLOP-specific embed
        embed = discord.Embed(
            title="⚽ PLOP This Weekend!",
            description="Get ready for Sunday's pickup game!",
            color=0x4caf50  # Green
        )

        embed.add_field(name="📅 When", value=date_str, inline=True)

        # Time field - show range if end time provided
        time_display = time_str
        if end_time_str:
            time_display = f"{time_str} - {end_time_str}"
        embed.add_field(name="🕐 Time", value=time_display, inline=True)

        # Location is the most important info - make it prominent
        embed.add_field(
            name="📍 Location",
            value=f"**{location}**",
            inline=False
        )

        embed.set_footer(text="See you there! 🏟️")

        # Send the message
        message = await channel.send(embed=embed)

        logger.info(f"Posted PLOP reminder for {date_str} at {location}")

        return {
            "status": "success",
            "message_id": message.id,
            "channel_id": channel.id,
            "channel_name": channel.name
        }

    except HTTPException:
        raise
    except discord.Forbidden as e:
        logger.error(f"Permission denied posting PLOP reminder: {e}")
        raise HTTPException(status_code=403, detail="Bot lacks permission to post in that channel")
    except Exception as e:
        logger.error(f"Error posting PLOP reminder: {e}")
        raise HTTPException(status_code=500, detail=str(e))