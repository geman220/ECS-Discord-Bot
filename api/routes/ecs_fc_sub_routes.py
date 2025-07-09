"""
FastAPI Routes for ECS FC Substitute System Discord Bot Integration.

Handles Discord DM responses for substitute availability and notifications.
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from discord.ext import commands
import discord
import logging
from typing import Optional, Dict, Any

from api.utils.discord_utils import get_bot
import aiohttp

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Flask app API endpoint
FLASK_API_URL = "http://flask-app:8080/api"


@router.post("/process_ecs_fc_sub_response")
async def process_ecs_fc_sub_response(
    discord_id: str = Body(..., embed=True, description="The player's Discord ID"),
    response_text: str = Body(..., embed=True, description="The response text"),
    context: Dict[str, Any] = Body(..., embed=True, description="Response context"),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Process a Discord DM response for an ECS FC substitute request.
    
    Args:
        discord_id: The Discord ID of the responding player
        response_text: The response text (e.g., "YES", "NO")
        context: Context containing request_id and response_id
        bot: The Discord bot instance
    """
    try:
        # Validate context
        if not context.get('type') == 'ecs_fc_sub_request':
            raise HTTPException(status_code=400, detail="Invalid context type")
        
        request_id = context.get('request_id')
        response_id = context.get('response_id')
        
        if not request_id or not response_id:
            raise HTTPException(status_code=400, detail="Missing request_id or response_id in context")
        
        # Forward to Flask app for processing
        async with aiohttp.ClientSession() as session:
            payload = {
                'discord_id': discord_id,
                'response_text': response_text,
                'request_id': request_id,
                'response_id': response_id,
                'response_method': 'DISCORD'
            }
            
            async with session.post(f"{FLASK_API_URL}/ecs-fc/process-sub-response", json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Flask API error: {error_text}")
                    raise HTTPException(status_code=resp.status, detail="Failed to process response")
                
                result = await resp.json()
                
                # Send confirmation DM to the player
                if result.get('success'):
                    try:
                        user = await bot.fetch_user(int(discord_id))
                        dm_channel = await user.create_dm()
                        
                        if result.get('is_available'):
                            message = "✅ Thanks! Your availability has been recorded. The coach will contact you if selected."
                        else:
                            message = "👍 Thanks for responding. Your response has been recorded."
                        
                        await dm_channel.send(message)
                    except Exception as e:
                        logger.error(f"Failed to send confirmation DM: {e}")
                
                return result
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing ECS FC sub response: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_ecs_fc_sub_notification")
async def send_ecs_fc_sub_notification(
    discord_id: str = Body(..., embed=True, description="The player's Discord ID"),
    message: str = Body(..., embed=True, description="The notification message"),
    context: Optional[Dict[str, Any]] = Body(None, embed=True, description="Optional context"),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Send an ECS FC substitute notification via Discord DM.
    
    Args:
        discord_id: The Discord ID of the player to notify
        message: The notification message
        context: Optional context for the notification
        bot: The Discord bot instance
    """
    try:
        user = await bot.fetch_user(int(discord_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Create DM channel
        dm_channel = await user.create_dm()
        
        # If context is provided, store it for response handling
        if context:
            # The bot should track this context for when the user responds
            # This would typically be stored in a cache or database
            # For now, we'll include it in the message footer
            message += f"\n\n_Request ID: {context.get('request_id', 'unknown')}_"
        
        # Send the message
        dm_message = await dm_channel.send(message)
        
        logger.info(f"Sent ECS FC sub notification to {discord_id}")
        return {
            "status": "sent",
            "message_id": dm_message.id,
            "discord_id": discord_id
        }
        
    except discord.Forbidden:
        logger.warning(f"Cannot send DM to user {discord_id} - DMs may be disabled")
        raise HTTPException(status_code=403, detail="Cannot send DM to this user. They may have DMs disabled.")
    except Exception as e:
        logger.error(f"Failed to send ECS FC sub notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")


@router.post("/send_ecs_fc_assignment_notification")
async def send_ecs_fc_assignment_notification(
    discord_id: str = Body(..., embed=True, description="The player's Discord ID"),
    match_details: Dict[str, Any] = Body(..., embed=True, description="Match details"),
    assignment_info: Dict[str, Any] = Body(..., embed=True, description="Assignment information"),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Send an assignment notification to an ECS FC substitute.
    
    Args:
        discord_id: The Discord ID of the assigned player
        match_details: Details about the match
        assignment_info: Information about the assignment
        bot: The Discord bot instance
    """
    try:
        user = await bot.fetch_user(int(discord_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Create an embed for the assignment
        embed = discord.Embed(
            title="⚽ You've been assigned as a substitute!",
            color=discord.Color.green()
        )
        
        # Add match details
        embed.add_field(name="Team", value=match_details.get('team_name', 'Unknown'), inline=True)
        embed.add_field(name="Date", value=match_details.get('date', 'TBD'), inline=True)
        embed.add_field(name="Time", value=match_details.get('time', 'TBD'), inline=True)
        embed.add_field(name="Location", value=match_details.get('location', 'TBD'), inline=False)
        
        # Add assignment info if provided
        if assignment_info.get('position'):
            embed.add_field(name="Position", value=assignment_info['position'], inline=True)
        
        if assignment_info.get('notes'):
            embed.add_field(name="Notes", value=assignment_info['notes'], inline=False)
        
        if match_details.get('match_notes'):
            embed.add_field(name="Match Notes", value=match_details['match_notes'], inline=False)
        
        # Send the embed
        dm_channel = await user.create_dm()
        dm_message = await dm_channel.send(embed=embed)
        
        logger.info(f"Sent ECS FC assignment notification to {discord_id}")
        return {
            "status": "sent",
            "message_id": dm_message.id,
            "discord_id": discord_id
        }
        
    except discord.Forbidden:
        logger.warning(f"Cannot send DM to user {discord_id} - DMs may be disabled")
        raise HTTPException(status_code=403, detail="Cannot send DM to this user. They may have DMs disabled.")
    except Exception as e:
        logger.error(f"Failed to send ECS FC assignment notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")