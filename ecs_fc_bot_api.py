"""
ECS FC Discord Bot API Router

This module provides REST API endpoints specifically for ECS FC Discord bot integration.
It handles RSVP message posting, embed updates, and direct message batches for ECS FC matches.
This router is designed to be included in the main bot API.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from shared_states import get_bot_instance, bot_ready
import logging
import discord
import asyncio
import aiohttp
from datetime import datetime
from discord.ext import commands

# Set up logging
logger = logging.getLogger(__name__)

# Initialize FastAPI router
router = APIRouter(prefix="/api/ecs_fc", tags=["ECS FC"])

# Pydantic models for request/response validation
class RSVPMessageRequest(BaseModel):
    match_id: int
    team_id: int
    team_name: str
    opponent_name: str
    match_date: str  # YYYY-MM-DD format
    match_time: str  # HH:MM format
    location: str
    is_home_match: bool
    rsvp_deadline: Optional[str] = None  # ISO format
    notes: Optional[str] = None
    field_name: Optional[str] = None
    response_counts: Dict[str, int] = Field(default_factory=lambda: {"yes": 0, "no": 0, "maybe": 0, "no_response": 0})

class RSVPMessageResponse(BaseModel):
    success: bool
    message_id: Optional[str] = None
    channel_id: Optional[str] = None
    error: Optional[str] = None

class DMBatchRequest(BaseModel):
    dm_list: List[Dict[str, str]]  # List of {"discord_id": str, "message": str}

class DMBatchResponse(BaseModel):
    success: bool
    sent_count: int
    failed_count: int
    details: List[Dict[str, str]]

class UpdateEmbedResponse(BaseModel):
    success: bool
    updated_message_id: Optional[str] = None
    error: Optional[str] = None

# Dependency to get the bot instance
async def get_bot():
    logger.info("get_bot function called. Waiting for bot to be ready...")
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for bot to be ready")
        raise HTTPException(status_code=503, detail="Bot is not ready")

    bot = get_bot_instance()
    if bot is None:
        logger.error("Bot instance is None in REST API")
        raise HTTPException(status_code=503, detail="Bot is not initialized properly")

    if not bot.is_ready():
        logger.error("Bot is not in the ready state")
        raise HTTPException(status_code=503, detail="Bot is not in the ready state")

    logger.info(f"Returning bot instance. Bot ID: {bot.user.id if bot.user else 'Unknown'}")
    return bot

async def get_team_channel_id(team_id: int) -> Optional[str]:
    """Get the Discord channel ID for an ECS FC team."""
    try:
        # Use the ECS FC API endpoint to get team channel mapping
        api_url = f"http://webui:5000/api/ecs-fc/team_channel/{team_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data', {}).get('channel_id')
                else:
                    logger.error(f"Failed to get channel ID for team {team_id}: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error getting team channel ID for team {team_id}: {str(e)}")
        return None

async def fetch_ecs_fc_rsvp_data(match_id: int) -> Dict[str, int]:
    """Fetch current RSVP data for an ECS FC match."""
    try:
        api_url = f"http://webui:5000/api/ecs-fc/matches/{match_id}/rsvp-summary"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data', {}).get('response_counts', {"yes": 0, "no": 0, "maybe": 0, "no_response": 0})
                else:
                    logger.warning(f"Failed to fetch RSVP data for match {match_id}: {response.status}")
                    return {"yes": 0, "no": 0, "maybe": 0, "no_response": 0}
    except Exception as e:
        logger.error(f"Error fetching RSVP data for match {match_id}: {str(e)}")
        return {"yes": 0, "no": 0, "maybe": 0, "no_response": 0}

def create_ecs_fc_embed(request: RSVPMessageRequest, response_counts: Dict[str, int]) -> discord.Embed:
    """Create a Discord embed for ECS FC RSVP messages."""
    embed = discord.Embed()
    embed.title = f"⚽ {request.team_name} vs {request.opponent_name}"
    embed.color = discord.Color.blue()
    
    # Parse match date and time
    try:
        match_datetime = datetime.strptime(f"{request.match_date} {request.match_time}", "%Y-%m-%d %H:%M")
        formatted_date = match_datetime.strftime('%A, %B %d, %Y')
        formatted_time = match_datetime.strftime('%I:%M %p')
    except ValueError:
        formatted_date = request.match_date
        formatted_time = request.match_time
    
    # Add match details
    embed.add_field(name="📅 Date", value=formatted_date, inline=True)
    embed.add_field(name="🕐 Time", value=formatted_time, inline=True)
    embed.add_field(name="📍 Location", value=request.location, inline=True)
    
    # Add match type
    match_type = "🏠 Home Match" if request.is_home_match else "🛫 Away Match"
    embed.add_field(name="Match Type", value=match_type, inline=True)
    
    # Add field name if provided
    if request.field_name:
        embed.add_field(name="🥅 Field", value=request.field_name, inline=True)
    
    # Add empty field for formatting
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    # Add current responses
    embed.add_field(
        name="📊 Current Responses",
        value=f"✅ Yes: {response_counts['yes']}\n"
              f"❌ No: {response_counts['no']}\n"
              f"❓ Maybe: {response_counts['maybe']}\n"
              f"⏳ No Response: {response_counts['no_response']}",
        inline=False
    )
    
    # Add RSVP deadline if provided
    if request.rsvp_deadline:
        try:
            deadline_dt = datetime.fromisoformat(request.rsvp_deadline.replace('Z', '+00:00'))
            deadline_str = deadline_dt.strftime('%B %d at %I:%M %p')
            embed.add_field(name="⏰ RSVP Deadline", value=deadline_str, inline=False)
        except ValueError:
            embed.add_field(name="⏰ RSVP Deadline", value=request.rsvp_deadline, inline=False)
    
    # Add notes if provided
    if request.notes:
        embed.add_field(name="📝 Notes", value=request.notes, inline=False)
    
    # Add footer with instructions
    embed.set_footer(text=f"React with ✅ for Yes, ❌ for No, or ❓ for Maybe\nMatch ID: {request.match_id} | React to RSVP!")
    
    return embed

@router.post("/post_rsvp_message", response_model=RSVPMessageResponse)
async def post_rsvp_message(request: RSVPMessageRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Send an RSVP message to an ECS FC team's Discord channel.
    
    This endpoint creates and posts an embed with match details and RSVP buttons
    to the team's Discord channel.
    """
    logger.info(f"Received request to post ECS FC RSVP message for match_id={request.match_id}, team={request.team_name}")
    
    try:
        # Get the team's Discord channel ID
        channel_id = await get_team_channel_id(request.team_id)
        if not channel_id:
            logger.error(f"Channel not found for ECS FC team {request.team_id}")
            raise HTTPException(status_code=404, detail=f"Channel not found for team {request.team_id}")
        
        # Get the Discord channel
        channel = bot.get_channel(int(channel_id))
        if not channel:
            logger.error(f"Discord channel not found for ID: {channel_id}")
            raise HTTPException(status_code=404, detail=f"Discord channel not found for ID: {channel_id}")
        
        # Create the embed with current response counts
        embed = create_ecs_fc_embed(request, request.response_counts)
        
        # Send the message
        message_content = f"⚽ **{request.team_name}** - Are you available for the match against **{request.opponent_name}**? React to RSVP!"
        message = await channel.send(content=message_content, embed=embed)
        
        # Add reaction buttons
        await message.add_reaction("✅")  # Yes
        await message.add_reaction("❌")  # No
        await message.add_reaction("❓")  # Maybe
        
        logger.info(f"Successfully posted ECS FC RSVP message: {message.id} in channel {channel_id}")
        
        # Store the message ID in the scheduled_message table for future updates
        await store_rsvp_message_id(request.match_id, message.id, channel_id)
        
        return RSVPMessageResponse(
            success=True,
            message_id=str(message.id),
            channel_id=channel_id
        )
        
    except discord.Forbidden:
        logger.error(f"Bot doesn't have permission to send messages to channel {channel_id}")
        raise HTTPException(status_code=403, detail="Bot doesn't have permission to send messages to this channel")
    except discord.HTTPException as e:
        logger.error(f"Discord API error: {e}")
        raise HTTPException(status_code=500, detail=f"Discord API error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error posting ECS FC RSVP message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

async def store_rsvp_message_id(match_id: int, message_id: str, channel_id: str):
    """Store the RSVP message ID in the database for future updates."""
    try:
        api_url = "http://webui:5000/api/ecs-fc/store_rsvp_message"
        data = {
            "match_id": match_id,
            "message_id": message_id,
            "channel_id": channel_id
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=data) as response:
                if response.status != 200:
                    logger.warning(f"Failed to store RSVP message ID: {response.status}")
    except Exception as e:
        logger.error(f"Error storing RSVP message ID: {str(e)}")

@router.post("/update_rsvp_embed/{match_id}", response_model=UpdateEmbedResponse)
async def update_rsvp_embed(match_id: int, bot: commands.Bot = Depends(get_bot)):
    """
    Update an existing ECS FC RSVP message with current response counts.
    
    This endpoint finds the original RSVP message and updates the embed
    with the latest response counts from the database.
    """
    logger.info(f"Received request to update ECS FC RSVP embed for match_id={match_id}")
    
    try:
        # Get the stored message information
        message_info = await get_stored_rsvp_message(match_id)
        if not message_info:
            logger.error(f"No stored RSVP message found for match {match_id}")
            raise HTTPException(status_code=404, detail=f"No RSVP message found for match {match_id}")
        
        message_id = message_info.get('message_id')
        channel_id = message_info.get('channel_id')
        
        # Get the Discord channel and message
        channel = bot.get_channel(int(channel_id))
        if not channel:
            logger.error(f"Discord channel not found for ID: {channel_id}")
            raise HTTPException(status_code=404, detail=f"Discord channel not found")
        
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            logger.error(f"Discord message not found for ID: {message_id}")
            raise HTTPException(status_code=404, detail=f"Discord message not found")
        
        # Get current RSVP data
        response_counts = await fetch_ecs_fc_rsvp_data(match_id)
        
        # Get match details for the embed
        match_details = await get_ecs_fc_match_details(match_id)
        if not match_details:
            logger.error(f"Match details not found for match {match_id}")
            raise HTTPException(status_code=404, detail=f"Match details not found")
        
        # Create the request object for the embed
        request = RSVPMessageRequest(**match_details, response_counts=response_counts)
        
        # Create updated embed
        updated_embed = create_ecs_fc_embed(request, response_counts)
        
        # Update the message
        await message.edit(embed=updated_embed)
        
        logger.info(f"Successfully updated ECS FC RSVP embed for match {match_id}")
        
        return UpdateEmbedResponse(
            success=True,
            updated_message_id=str(message_id)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating ECS FC RSVP embed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

async def get_stored_rsvp_message(match_id: int) -> Optional[Dict[str, Any]]:
    """Get stored RSVP message information for a match."""
    try:
        api_url = f"http://webui:5000/api/ecs-fc/rsvp_message/{match_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data')
                else:
                    logger.warning(f"Failed to get stored RSVP message for match {match_id}: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error getting stored RSVP message for match {match_id}: {str(e)}")
        return None

async def get_ecs_fc_match_details(match_id: int) -> Optional[Dict[str, Any]]:
    """Get ECS FC match details for embed creation."""
    try:
        api_url = f"http://webui:5000/api/ecs-fc/matches/{match_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data', {}).get('match')
                else:
                    logger.warning(f"Failed to get match details for match {match_id}: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error getting match details for match {match_id}: {str(e)}")
        return None

@router.post("/send_dm_batch", response_model=DMBatchResponse)
async def send_dm_batch(request: DMBatchRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Send direct messages to multiple players (for RSVP reminders).
    
    This endpoint sends DMs to a list of Discord users with custom messages,
    typically used for RSVP reminders.
    """
    logger.info(f"Received request to send DM batch to {len(request.dm_list)} users")
    
    sent_count = 0
    failed_count = 0
    details = []
    
    for dm_request in request.dm_list:
        discord_id = dm_request.get('discord_id')
        message_content = dm_request.get('message')
        
        if not discord_id or not message_content:
            failed_count += 1
            details.append({
                "discord_id": discord_id or "unknown",
                "status": "failed",
                "error": "Missing discord_id or message"
            })
            continue
        
        try:
            # Get the Discord user
            user = bot.get_user(int(discord_id))
            if not user:
                # Try to fetch the user if not in cache
                try:
                    user = await bot.fetch_user(int(discord_id))
                except discord.NotFound:
                    failed_count += 1
                    details.append({
                        "discord_id": discord_id,
                        "status": "failed",
                        "error": "User not found"
                    })
                    continue
            
            # Send the DM
            await user.send(message_content)
            sent_count += 1
            details.append({
                "discord_id": discord_id,
                "status": "sent"
            })
            
            logger.info(f"Successfully sent DM to user {discord_id}")
            
            # Add small delay to avoid rate limiting
            await asyncio.sleep(0.5)
            
        except discord.Forbidden:
            failed_count += 1
            details.append({
                "discord_id": discord_id,
                "status": "failed",
                "error": "Cannot send DM to user (DMs disabled or not mutual server)"
            })
            logger.warning(f"Cannot send DM to user {discord_id}: DMs disabled or not mutual server")
            
        except discord.HTTPException as e:
            failed_count += 1
            details.append({
                "discord_id": discord_id,
                "status": "failed",
                "error": f"Discord API error: {str(e)}"
            })
            logger.error(f"Discord API error sending DM to user {discord_id}: {str(e)}")
            
        except Exception as e:
            failed_count += 1
            details.append({
                "discord_id": discord_id,
                "status": "failed",
                "error": f"Unexpected error: {str(e)}"
            })
            logger.error(f"Unexpected error sending DM to user {discord_id}: {str(e)}")
    
    logger.info(f"DM batch completed: {sent_count} sent, {failed_count} failed")
    
    return DMBatchResponse(
        success=True,
        sent_count=sent_count,
        failed_count=failed_count,
        details=details
    )

# Health check endpoint for ECS FC functionality
@router.get("/health")
async def ecs_fc_health_check():
    """Health check endpoint for ECS FC functionality."""
    return {"status": "healthy", "service": "ecs_fc", "timestamp": datetime.utcnow().isoformat()}