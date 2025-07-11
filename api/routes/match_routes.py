"""
Match and RSVP related routes extracted from bot_rest_api.py
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import JSONResponse
from typing import List, Optional, Union
from shared_states import get_bot_instance, set_bot_instance, bot_ready, bot_state
import logging
import discord
import asyncio
import aiohttp
import time
import json
import os
from aiohttp import ClientError

# Environment variables
WEBUI_API_URL = os.getenv("WEBUI_API_URL")
from discord.ext import commands
from datetime import datetime

from api.models.schemas import AvailabilityRequest, ThreadRequest, MessageContent
from api.utils.discord_utils import get_bot, get_team_id_for_message, poll_task_result
from api.utils.api_client import get_session, retry_api_call
from api.utils.rsvp_utils import fetch_team_rsvp_data, update_embed_for_message, fetch_match_data
from api.utils.embeds import create_team_embed, create_match_embed, get_emoji_for_response

# Set up logging
logger = logging.getLogger(__name__)

# Create the router
router = APIRouter()

# Extract channel and message ID from combined string
def extract_channel_and_message_id(message_id_str):
    if '-' in message_id_str:
        parts = message_id_str.split('-')
        return parts[0], parts[1]
    else:
        return None, message_id_str


@router.post("/api/post_availability")
async def post_availability(request: AvailabilityRequest, bot: commands.Bot = Depends(get_bot)):
    logger.info(f"Received request to post availability for match_id={request.match_id}. Home team: {request.home_team_name}, Away team: {request.away_team_name}")
    try:
        home_channel = bot.get_channel(int(request.home_channel_id))
        away_channel = bot.get_channel(int(request.away_channel_id))

        if not home_channel:
            logger.error(f"Home channel not found for ID: {request.home_channel_id}")
            raise HTTPException(status_code=404, detail=f"Home channel not found for ID: {request.home_channel_id}")
        if not away_channel:
            logger.error(f"Away channel not found for ID: {request.away_channel_id}")
            raise HTTPException(status_code=404, detail=f"Away channel not found for ID: {request.away_channel_id}")

        match_datetime = datetime.strptime(f"{request.match_date} {request.match_time}", "%Y-%m-%d %H:%M:%S")
        formatted_date = match_datetime.strftime('%-m/%-d/%y')
        formatted_time = match_datetime.strftime('%-I:%M %p')
        
        # Fetch existing RSVP data for both teams
        home_rsvp_data = await fetch_team_rsvp_data(request.match_id, request.home_team_id)
        away_rsvp_data = await fetch_team_rsvp_data(request.match_id, request.away_team_id)
        
        logger.debug("Creating embeds for home and away teams with existing RSVP data")
        home_embed = create_team_embed(request, home_rsvp_data, team_type='home')
        away_embed = create_team_embed(request, away_rsvp_data, team_type='away')

        home_message = await home_channel.send(
            f"\u26BD **{request.home_team_name}** - Are you available for the match on {formatted_date} at {formatted_time}? "
            "React with 👍 for Yes, 👎 for No, or 🤷 for Maybe.",
            embed=home_embed
        )
        
        away_message = await away_channel.send(
            f"\u26BD **{request.away_team_name}** - Are you available for the match on {formatted_date} at {formatted_time}? "
            "React with 👍 for Yes, 👎 for No, or 🤷 for Maybe.",
            embed=away_embed
        )
        
        for message in [home_message, away_message]:
            logger.debug(f"Adding reactions to message {message.id}")
            await message.add_reaction("👍")
            await message.add_reaction("👎")
            await message.add_reaction("🤷")
            bot_state.add_managed_message_id(message.id)
        
        logger.debug("Storing message and channel IDs in web UI")
        await store_message_ids_in_web_ui(
            request.match_id, 
            home_channel_id=request.home_channel_id, 
            home_message_id=str(home_message.id), 
            away_channel_id=request.away_channel_id, 
            away_message_id=str(away_message.id)
        )
        logger.info(f"Stored IDs: Home msg={home_message.id}, Away msg={away_message.id}")
        
        logger.info(f"Successfully posted availability for match {request.match_id}")
        return {"home_message_id": home_message.id, "away_message_id": away_message.id}
    except Exception as e:
        logger.exception(f"Error in posting availability for match {request.match_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/api/update_availability_embed/{match_id}")
async def update_availability_embed(match_id: str, bot: commands.Bot = Depends(get_bot)):
    """
    Updates the Discord embed for a match with current RSVP data.
    Enhanced with better error handling and retry logic.
    
    Args:
        match_id: The ID of the match to update.
        
    Returns:
        A JSON response indicating success or failure.
    """
    logger.info(f"Received request to update availability embed for match {match_id}")
    
    try:
        # Fetch message data with retry logic
        max_retries = 3
        message_data = None
        
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    timeout = 10 * (attempt + 1)  # Increase timeout with each attempt
                    api_url = f"{WEBUI_API_URL}/get_message_ids/{match_id}"
                    
                    logger.debug(f"Fetching message IDs (attempt {attempt+1}/{max_retries}) from {api_url}")
                    async with session.get(api_url, timeout=timeout) as response:
                        response_text = await response.text()
                        
                        if response.status == 200:
                            try:
                                message_data = json.loads(response_text)
                                logger.debug(f"Successfully fetched message data: {message_data}")
                                break  # Success, exit retry loop
                            except json.JSONDecodeError:
                                logger.error(f"Invalid JSON response: {response_text}")
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                                    continue
                                else:
                                    return {"status": "error", "message": "Invalid JSON response from WebUI"}
                        elif response.status == 404:
                            logger.warning(f"No scheduled message found for match {match_id}")
                            return {"status": "warning", "message": "No scheduled message found"}
                        else:
                            logger.error(f"Failed to fetch message IDs (attempt {attempt+1}/{max_retries}): {response.status} - {response_text}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                                continue
                            else:
                                return {"status": "error", "message": f"Failed to fetch message IDs: {response.status}"}
            except aiohttp.ClientError as e:
                logger.error(f"API error fetching message IDs (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    return {"status": "error", "message": f"API error: {str(e)}"}
        
        if not message_data:
            logger.error(f"Failed to fetch message data for match {match_id} after {max_retries} attempts")
            return {"status": "error", "message": "Failed to fetch message data"}
        
        # Extract message IDs and check if they exist
        home_message_id = message_data.get('home_message_id')
        home_channel_id = message_data.get('home_channel_id')
        home_team_id = message_data.get('home_team_id')
        away_message_id = message_data.get('away_message_id')
        away_channel_id = message_data.get('away_channel_id')
        away_team_id = message_data.get('away_team_id')
        
        logger.debug(f"Extracted IDs - home: {home_message_id}/{home_channel_id}/{home_team_id}, "
                    f"away: {away_message_id}/{away_channel_id}/{away_team_id}")
        
        if not (home_message_id and home_channel_id or away_message_id and away_channel_id):
            logger.warning(f"No valid message IDs found for match {match_id}")
            return {"status": "warning", "message": "No valid message IDs found"}
        
        # Update home and away embeds in parallel
        tasks = []
        
        if home_message_id and home_channel_id and home_team_id:
            tasks.append(update_embed_for_message(
                home_message_id, home_channel_id, match_id, home_team_id, bot
            ))
        
        if away_message_id and away_channel_id and away_team_id:
            tasks.append(update_embed_for_message(
                away_message_id, away_channel_id, match_id, away_team_id, bot
            ))
        
        if tasks:
            # Run updates in parallel
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"Updated availability embeds for match {match_id}")
            return {"status": "success", "message": "Embeds updated successfully"}
        else:
            logger.warning(f"No embed updates performed for match {match_id}")
            return {"status": "warning", "message": "No embed updates performed"}
        
    except Exception as e:
        logger.exception(f"Error updating availability embed for match {match_id}: {e}")
        return {"status": "error", "message": f"Internal error: {str(e)}"}


@router.post("/channels/{channel_id}/threads")
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


@router.post("/channels/{thread_id}/messages")
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


@router.post("/post_match_update")
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


@router.post("/update_discord_rsvp")
async def update_discord_rsvp(request: dict, bot: commands.Bot = Depends(get_bot)):
    match_id = request.get("match_id")
    user_id = request.get("user_id")
    new_response = request.get("new_response")
    old_response = request.get("old_response")
    
    if not all([match_id, user_id, new_response]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WEBUI_API_URL}/get_message_ids/{match_id}") as response:
                if response.status != 200:
                    raise HTTPException(status_code=404, detail="Message IDs not found")
                message_data = await response.json()
        
        messages_to_update = [
            (message_data['home_message_id'], message_data['home_channel_id'], message_data['home_team_id']),
            (message_data['away_message_id'], message_data['away_channel_id'], message_data['away_team_id'])
        ]

        for message_id, channel_id, team_id in messages_to_update:
            channel = bot.get_channel(int(channel_id))
            if not channel:
                logger.error(f"Channel with ID {channel_id} not found.")
                continue

            try:
                message = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                logger.error(f"Message with ID {message_id} not found in channel {channel_id}.")
                continue

            member = await message.guild.fetch_member(int(user_id))
            
            if old_response:
                old_emoji = get_emoji_for_response(old_response)
                for reaction in message.reactions:
                    if str(reaction.emoji) == old_emoji:
                        await reaction.remove(member)
            
            new_emoji = get_emoji_for_response(new_response)
            await message.add_reaction(new_emoji)
            
            await update_embed_for_message(int(message_id), int(channel_id), match_id, int(team_id), bot)

        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error updating Discord RSVP: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update Discord RSVP: {str(e)}")


@router.post("/api/update_user_reaction")
async def update_user_reaction(request: dict, bot: commands.Bot = Depends(get_bot)):
    """
    Updates a user's reaction on Discord messages.
    Enhanced with better error handling, retry logic, and race condition prevention.
    Fixed to ensure reactions are always properly updated when RSVPs change in the Flask app.
    
    Args:
        request: A dictionary containing match_id, discord_id, new_response, and optional old_response.
        
    Returns:
        A JSON response indicating success or failure.
    """
    logger.debug(f"User reaction endpoint hit with request data: {request}")

    match_id = request.get("match_id")
    user_id = request.get("discord_id")
    new_response = request.get("new_response")
    old_response = request.get("old_response")

    if not all([match_id, user_id, new_response]):
        logger.error(f"Missing required fields: match_id={match_id}, user_id={user_id}, new_response={new_response}")
        raise HTTPException(status_code=400, detail="Missing required fields")

    # Ensure discord_id is a string
    if not isinstance(user_id, str):
        user_id = str(user_id)
        logger.debug(f"Converted user_id to string: {user_id}")

    try:
        # Fetch message IDs from the web API
        logger.debug(f"Fetching message IDs for match_id {match_id}")
        async with aiohttp.ClientSession() as session:
            # Retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    timeout = 10 * (attempt + 1)  # Increase timeout with each attempt
                    async with session.get(f"{WEBUI_API_URL}/get_message_ids/{match_id}", 
                                        timeout=timeout) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Failed to fetch message IDs (attempt {attempt+1}/{max_retries}): {error_text}")
                            
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                                continue
                            else:
                                raise HTTPException(status_code=404, detail="Message IDs not found")
                            
                        message_data = await response.json()
                        logger.debug(f"Message data received: {message_data}")
                        break  # Success, exit retry loop
                except aiohttp.ClientError as e:
                    logger.error(f"API error fetching message IDs (attempt {attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    else:
                        raise HTTPException(status_code=500, detail=f"API error: {str(e)}")

        # Map responses to emojis
        response_emoji = {
            'yes': '👍',
            'no': '👎',
            'maybe': '🤷',
            'no_response': None
        }
        
        new_emoji = response_emoji.get(new_response)
        old_emoji = response_emoji.get(old_response) if old_response else None
        
        logger.debug(f"Emoji mapping: new={new_emoji}, old={old_emoji}")

        # Process each message (home and away) if available
        success = True
        errors = []
        processed_messages = 0
        
        # Helper function to handle reaction updates
        async def process_message_reactions(channel_id, message_id, user_id, new_emoji, old_emoji):
            """
            Process message reactions using the simplified approach:
            - Only keep the three base emoji reactions (👍, 👎, 🤷) on the message, added by the bot
            - No user reactions are kept, to avoid conflicts
            - Only update the embed with the user's RSVP status
            """
            if not channel_id or not message_id:
                logger.debug(f"Skipping message due to missing IDs: channel={channel_id}, message={message_id}")
                return True, None  # Skip but don't count as error
                
            try:
                # Get channel with fallback
                channel = bot.get_channel(int(channel_id))
                if not channel:
                    try:
                        logger.info(f"Attempting to fetch channel {channel_id} directly")
                        channel = await bot.fetch_channel(int(channel_id))
                    except Exception as e:
                        logger.error(f"Failed to fetch channel {channel_id}: {e}")
                        return False, f"Channel {channel_id} not found or inaccessible"
                
                if not channel:
                    logger.error(f"Channel {channel_id} not found")
                    return False, f"Channel {channel_id} not found"
                
                # Get message
                try:
                    message = await channel.fetch_message(int(message_id))
                except discord.NotFound:
                    logger.error(f"Message {message_id} not found in channel {channel_id}")
                    return False, f"Message {message_id} not found"
                
                # Get user object (only for debugging/logging)
                try:
                    user = await bot.fetch_user(int(user_id))
                except discord.NotFound:
                    logger.error(f"User {user_id} not found")
                    return False, f"User {user_id} not found"
                
                # Simplified approach: Only update embed data in Flask, don't mess with user reactions
                logger.info(f"Using simplified reaction approach for user {user_id} with response {new_emoji}")
                
                # Just make sure the three base reactions exist on the message (added by bot only)
                valid_emojis = ['👍', '👎', '🤷']
                existing_emojis = [str(r.emoji) for r in message.reactions]
                
                # Add any missing base emojis (these are just the voting options)
                for emoji in valid_emojis:
                    if emoji not in existing_emojis:
                        logger.info(f"Adding base emoji {emoji} to message {message_id}")
                        try:
                            await message.add_reaction(emoji)
                            await asyncio.sleep(0.5)  # Small delay between adding reactions
                        except Exception as e:
                            logger.error(f"Error adding base emoji {emoji}: {e}")
                            # Continue with the rest of the emojis
                
                # Update the embed directly (this is handled elsewhere by update_embed_for_message)
                # No need to do anything specific here for the user's reaction
                
                # Always consider the operation successful since we don't manage user reactions anymore
                logger.info(f"Successfully processed simplified reactions approach for user {user_id}")
                return True, None
                
            except Exception as e:
                logger.error(f"Error processing message reactions: {e}")
                return False, str(e)
                
                # Only update the embed if we actually changed reactions
                team_id = message_data.get('home_team_id') if str(channel_id) == message_data.get('home_channel_id') else message_data.get('away_team_id')
                if team_id:
                    try:
                        await update_embed_for_message(message_id, channel_id, match_id, team_id, bot)
                    except Exception as e:
                        logger.warning(f"Non-critical error updating embed: {e}")
                        # Don't fail the operation just because embed update failed
                
                return True, None
            except Exception as e:
                logger.error(f"Error processing message reactions: {e}")
                return False, str(e)
        
        # Check current RSVP status from Flask (the source of truth)
        try:
            # Determine which team the user belongs to first
            team_id = None
            
            # Try to determine if user is on home team
            if message_data.get('home_team_id'):
                api_url = f"{WEBUI_API_URL}/is_user_on_team"
                payload = {'discord_id': user_id, 'team_id': message_data['home_team_id']}
                
                async with aiohttp.ClientSession() as check_session:
                    async with check_session.post(api_url, json=payload) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get('is_team_member', False):
                                team_id = message_data['home_team_id']
            
            # If not on home team, check if on away team
            if not team_id and message_data.get('away_team_id'):
                api_url = f"{WEBUI_API_URL}/is_user_on_team"
                payload = {'discord_id': user_id, 'team_id': message_data['away_team_id']}
                
                async with aiohttp.ClientSession() as check_session:
                    async with check_session.post(api_url, json=payload) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get('is_team_member', False):
                                team_id = message_data['away_team_id']
            
            # If we found a team, check current RSVP status in Flask
            if team_id:
                api_url = f"{WEBUI_API_URL}/get_match_rsvps/{match_id}?team_id={team_id}&include_discord_ids=true"
                
                async with aiohttp.ClientSession() as check_session:
                    async with check_session.get(api_url) as response:
                        if response.status == 200:
                            rsvp_data = await response.json()
                            
                            # Check each list to find the user's current status
                            current_status = None
                            
                            for status in ['yes', 'no', 'maybe']:
                                for player in rsvp_data.get(status, []):
                                    if player.get('discord_id') == user_id:
                                        current_status = status
                                        break
                                if current_status:
                                    break
                            
                            # Even if the requested status matches current status, still update reactions to ensure consistency
                            if current_status == new_response:
                                logger.info(f"User {user_id} already has RSVP status '{new_response}' in database, but will still update reactions to ensure they match")
                                # Continue with processing to ensure reactions are properly set
                                # Don't return here, so we process the reactions
        except Exception as e:
            logger.error(f"Error checking current RSVP status: {e}")
            # Continue with the update as a fallback
        
        # Process home message
        if message_data.get('home_message_id') and message_data.get('home_channel_id'):
            home_success, home_error = await process_message_reactions(
                message_data['home_channel_id'],
                message_data['home_message_id'],
                user_id,
                new_emoji,
                old_emoji
            )
            
            if not home_success:
                success = False
                errors.append(f"Home: {home_error}")
            else:
                processed_messages += 1
        
        # Process away message
        if message_data.get('away_message_id') and message_data.get('away_channel_id'):
            away_success, away_error = await process_message_reactions(
                message_data['away_channel_id'],
                message_data['away_message_id'],
                user_id,
                new_emoji,
                old_emoji
            )
            
            if not away_success:
                success = False
                errors.append(f"Away: {away_error}")
            else:
                processed_messages += 1
        
        if processed_messages == 0:
            logger.warning("No messages were processed")
            return {"status": "warning", "message": "No messages were processed"}
            
        if success:
            logger.info(f"Successfully updated reactions for user {user_id} in match {match_id}")
            return {"status": "success", "message": "Reactions updated successfully"}
        else:
            error_msg = "; ".join(errors)
            logger.error(f"Failed to update reactions: {error_msg}")
            return {"status": "error", "message": f"Failed to update reactions: {error_msg}"}

    except Exception as e:
        logger.exception(f"Unexpected error updating user reactions: {e}")
        return {"status": "error", "message": f"Internal error: {str(e)}"}


@router.post("/api/force_rsvp_sync")
async def force_rsvp_sync_endpoint(bot: commands.Bot = Depends(get_bot), throttled: bool = False):
    """
    Endpoint to force a full synchronization of RSVPs between Discord and Flask.
    This is useful after bot restarts or network failures to ensure consistency.
    
    Args:
        bot: The Discord bot instance
        throttled: If True, adds delays between operations to avoid rate limiting
    """
    try:
        # Get the full_rsvp_sync function from the main module
        import sys
        import ECS_Discord_Bot
        
        if hasattr(ECS_Discord_Bot, 'full_rsvp_sync'):
            logger.info("Starting forced full RSVP synchronization...")
            
            # Create a task with a background sync that has throttling options
            # The background sync process will handle all the updates with the rate limit protections
            task = asyncio.create_task(ECS_Discord_Bot.full_rsvp_sync(force_sync=True))
            
            # We don't await the task because we want it to run in the background
            # This way the API can respond immediately while the sync happens asynchronously
            
            return {
                "success": True,
                "message": "Full RSVP synchronization started in the background",
                "timestamp": datetime.utcnow().isoformat(),
                "throttled": throttled
            }
        else:
            logger.error("full_rsvp_sync function not found in ECS_Discord_Bot module")
            raise HTTPException(status_code=500, detail="Synchronization function not available")
    except Exception as e:
        logger.exception(f"Error forcing RSVP sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper function to store message IDs in the Web UI
async def store_message_ids_in_web_ui(match_id, home_channel_id=None, home_message_id=None, away_channel_id=None, away_message_id=None):
    """
    Store message IDs in the web UI for future reference.
    This function has been updated to use aiohttp for async requests.
    
    Args:
        match_id: ID of the match
        home_channel_id: ID of the home team's channel
        home_message_id: ID of the message in the home channel
        away_channel_id: ID of the away team's channel  
        away_message_id: ID of the message in the away channel
    
    Returns:
        dict: A dictionary with the status of the operation
    """
    api_url = f"{WEBUI_API_URL}/store_message_ids"
    payload = {
        'match_id': match_id,
        'home_message_id': home_message_id,
        'away_message_id': away_message_id,
        'home_channel_id': home_channel_id,
        'away_channel_id': away_channel_id
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Successfully stored message IDs in Web UI for match {match_id}")
                    return {"success": True, "message": "Message IDs stored successfully"}
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to store message IDs in Web UI: {response.status} - {error_text}")
                    return {"success": False, "message": f"Failed with status {response.status}: {error_text}"}
    except Exception as e:
        logger.exception(f"Error storing message IDs in Web UI: {str(e)}")
        return {"success": False, "message": f"Exception occurred: {str(e)}"}