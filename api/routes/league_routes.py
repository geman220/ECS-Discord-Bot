# league_routes.py

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from shared_states import bot_state
import logging
import discord
import asyncio
import aiohttp
from discord.ext import commands
from datetime import datetime

from api.models.schemas import LeaguePollRequest, PollResponseRequest
from api.utils.discord_utils import get_bot
from api.utils.api_client import get_session

# Set up logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Dependencies and utilities imported from other modules

# League poll routes

# Models imported from schemas module

# League poll endpoints
@router.post("/api/send_league_poll")
async def send_league_poll(poll_request: LeaguePollRequest, bot: commands.Bot = Depends(get_bot)):
    """
    Send a league poll to all team channels.
    """
    try:
        logger.info(f"Sending league poll {poll_request.poll_id} to {len(poll_request.teams)} teams")
        
        # Create the poll embed
        embed = discord.Embed(
            title="🗳️ LEAGUE POLL",
            description=f"**{poll_request.title}**\n\n{poll_request.question}",
            color=0x3498db
        )
        embed.add_field(
            name="How to respond:",
            value="✅ React with ✅ for **Yes**\n❌ React with ❌ for **No**\n⚠️ React with ⚠️ for **Maybe**",
            inline=False
        )
        embed.set_footer(text="This is a league-wide poll sent to all teams")
        
        sent_count = 0
        failed_count = 0
        
        for team_info in poll_request.teams:
            try:
                channel_id = int(team_info['channel_id'])
                channel = bot.get_channel(channel_id)
                
                if not channel:
                    logger.warning(f"Channel {channel_id} not found for team {team_info['team_id']}")
                    failed_count += 1
                    continue
                
                # Send the poll message with rate limit handling
                try:
                    message = await channel.send(embed=embed)
                    logger.debug(f"Message sent to channel {channel_id}")
                    
                    # Add reactions with delays between each to avoid rate limits
                    await message.add_reaction("✅")
                    await asyncio.sleep(0.2)  # Small delay between reactions
                    await message.add_reaction("❌")
                    await asyncio.sleep(0.2)
                    await message.add_reaction("⚠️")
                    
                    # Track this poll message in bot state
                    bot_state.add_managed_message_id(
                        message.id,
                        match_date=None,  # Polls don't have match dates
                        team_id=team_info['team_id']
                    )
                    # Also store poll metadata
                    if not hasattr(bot_state, 'poll_messages'):
                        bot_state.poll_messages = {}
                    bot_state.poll_messages[message.id] = {
                        'poll_id': poll_request.poll_id,
                        'team_id': team_info['team_id'],
                        'channel_id': channel_id
                    }
                    
                    # Update the Discord message record in the Flask app
                    try:
                        update_url = "http://webui:5000/api/update_poll_message"
                        update_data = {
                            'message_record_id': team_info['message_record_id'],
                            'message_id': str(message.id),
                            'sent_at': datetime.utcnow().isoformat()
                        }
                        
                        session_client = await get_session()
                        async with session_client.post(update_url, json=update_data) as response:
                            if response.status != 200:
                                logger.warning(f"Failed to update message record: {await response.text()}")
                    
                    except Exception as e:
                        logger.error(f"Error updating message record: {e}")
                    
                    sent_count += 1
                    logger.info(f"Poll sent to channel {channel_id} (team {team_info['team_id']})")
                    
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        retry_after = getattr(e, 'retry_after', 5)
                        logger.warning(f"Rate limited when sending to channel {channel_id}, retrying after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        
                        # Retry once
                        try:
                            message = await channel.send(embed=embed)
                            await message.add_reaction("✅")
                            await asyncio.sleep(0.2)
                            await message.add_reaction("❌")
                            await asyncio.sleep(0.2)
                            await message.add_reaction("⚠️")
                            
                            # Track in bot state
                            bot_state.add_managed_message_id(message.id, match_date=None, team_id=team_info['team_id'])
                            if not hasattr(bot_state, 'poll_messages'):
                                bot_state.poll_messages = {}
                            bot_state.poll_messages[message.id] = {
                                'poll_id': poll_request.poll_id,
                                'team_id': team_info['team_id'],
                                'channel_id': channel_id
                            }
                            
                            sent_count += 1
                            logger.info(f"Poll sent to channel {channel_id} after rate limit retry")
                        except Exception as retry_e:
                            logger.error(f"Failed to send poll after rate limit retry: {retry_e}")
                            failed_count += 1
                    else:
                        raise e
                
                # Dynamic delay between teams based on batch size
                if len(poll_request.teams) > 20:
                    await asyncio.sleep(1.2)  # 1.2 seconds for large batches (>20 teams)
                elif len(poll_request.teams) > 10:
                    await asyncio.sleep(0.8)  # 0.8 seconds for medium batches (11-20 teams)
                else:
                    await asyncio.sleep(0.5)  # 0.5 seconds for small batches (≤10 teams)
                
            except Exception as e:
                logger.error(f"Failed to send poll to team {team_info['team_id']}: {e}")
                failed_count += 1
        
        return {
            "success": True,
            "sent": sent_count,
            "failed": failed_count,
            "total": len(poll_request.teams)
        }
        
    except Exception as e:
        logger.exception(f"Error sending league poll: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/handle_poll_reaction")
async def handle_poll_reaction(
    poll_id: int,
    discord_id: str,
    reaction: str,
    bot: commands.Bot = Depends(get_bot)
):
    """
    Handle a reaction on a poll message.
    """
    try:
        # Map Discord reactions to response values
        reaction_map = {
            "✅": "yes",
            "❌": "no", 
            "⚠️": "maybe"
        }
        
        response = reaction_map.get(reaction)
        if not response:
            logger.warning(f"Unknown reaction: {reaction}")
            return {"success": False, "error": "Unknown reaction"}
        
        # Send the response to the Flask app
        update_url = "http://webui:5000/api/update_poll_response_from_discord"
        update_data = {
            'poll_id': poll_id,
            'discord_id': discord_id,
            'response': response
        }
        
        session_client = await get_session()
        async with session_client.post(update_url, json=update_data) as flask_response:
            if flask_response.status == 200:
                logger.info(f"Poll response recorded: Poll {poll_id}, User {discord_id}, Response {response}")
                return {"success": True}
            else:
                error_text = await flask_response.text()
                logger.error(f"Failed to record poll response: {flask_response.status} - {error_text}")
                return {"success": False, "error": error_text}
                
    except Exception as e:
        logger.exception(f"Error handling poll reaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))