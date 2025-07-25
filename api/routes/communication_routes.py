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

from api.utils.discord_utils import get_bot

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


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