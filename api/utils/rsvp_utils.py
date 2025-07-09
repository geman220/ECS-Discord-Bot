# rsvp_utils.py - RSVP-specific utilities extracted from bot_rest_api.py

import logging
import discord
import asyncio
import aiohttp
from datetime import datetime
from typing import Tuple, Optional, Union
from pydantic import BaseModel, Field
from discord.ext import commands
from aiohttp import ClientError
from api.models.schemas import AvailabilityRequest, EmbedField, EmbedData

# Set up logging
logger = logging.getLogger(__name__)

# Global session variable (similar to bot_rest_api.py)
session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    """Get or create an aiohttp session."""
    global session
    if session is None:
        session = aiohttp.ClientSession()
    return session


# Helper functions
def get_emoji_for_response(response):
    """Get emoji for RSVP response status."""
    if response == 'yes':
        return "👍"
    elif response == 'no':
        return "👎"
    elif response == 'maybe':
        return "🤷"
    else:
        return None

async def retry_api_call(url, method='GET', json=None, max_retries=3, delay=1):
    """Retry API calls with exponential backoff."""
    session = await get_session()
    for attempt in range(max_retries):
        try:
            async with session.request(method, url, json=json) as response:
                response.raise_for_status()
                return await response.json()
        except ClientError as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            await asyncio.sleep(delay * (2 ** attempt))  # Exponential backoff

def extract_channel_and_message_id(message_id_str):
    """Extract channel and message ID from combined string."""
    try:
        parts = message_id_str.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid message ID format: {message_id_str}")
        return parts[0], parts[1]
    except Exception as e:
        logger.error(f"Error extracting channel and message ID from {message_id_str}: {e}")
        raise ValueError(f"Invalid message ID format: {message_id_str}")

# Main RSVP functions
async def update_embed_message_with_players(message, rsvp_data):
    """
    Update the embed with both the current reaction counts and the player names.
    """
    yes_players = ', '.join([player['player_name'] for player in rsvp_data.get('yes', [])]) or "None"
    no_players = ', '.join([player['player_name'] for player in rsvp_data.get('no', [])]) or "None"
    maybe_players = ', '.join([player['player_name'] for player in rsvp_data.get('maybe', [])]) or "None"

    yes_count = len(rsvp_data.get('yes', []))
    no_count = len(rsvp_data.get('no', []))
    maybe_count = len(rsvp_data.get('maybe', []))

    # Assuming there's one embed in the message
    embed = message.embeds[0]

    # Update the reaction counts and player names
    embed.set_field_at(0, name=f"👍 Yes ({yes_count})", value=yes_players, inline=False)
    embed.set_field_at(1, name=f"👎 No ({no_count})", value=no_players, inline=False)
    embed.set_field_at(2, name=f"🤷 Maybe ({maybe_count})", value=maybe_players, inline=False)

    # Edit the message with the updated embed
    await message.edit(embed=embed)
    logger.debug(f"Embed updated with Yes: {yes_count} ({yes_players}), No: {no_count} ({no_players}), Maybe: {maybe_count} ({maybe_players})")

async def get_player_info_from_discord(discord_id: str):
    """Get player information from Discord ID."""
    session = await get_session()
    api_url = f"http://webui:5000/get_player_id_from_discord/{discord_id}"
    async with session.get(api_url) as response:
        if response.status == 200:
            data = await response.json()
            return data.get('player_id'), data.get('team_id')
        else:
            logger.error(f"Failed to get player info for user: {await response.text()}")
            return None, None

async def fetch_team_rsvp_data(match_id: int, team_id: int):
    """Fetch RSVP data for a specific team and match."""
    try:
        api_url = f"http://webui:5000/api/get_match_rsvps/{match_id}?team_id={team_id}"
        logger.info(f"Fetching RSVP data from {api_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                response_text = await response.text()  # Capture the raw response text for logging
                
                if response.status == 200:
                    rsvp_data = await response.json()
                    logger.debug(f"Successfully fetched RSVP data for match {match_id} and team {team_id}: {rsvp_data}")
                    return rsvp_data
                else:
                    logger.error(f"Failed to fetch RSVPs for match {match_id} and team {team_id}. "
                                 f"Status: {response.status}, Response: {response_text}")
                    return None
    except Exception as e:
        logger.exception(f"Error in fetch_team_rsvp_data for match {match_id} and team {team_id}: {e}")
        return None

async def fetch_match_data(match_id: int):
    """Fetch match information by match ID."""
    try:
        api_url = f"http://webui:5000/api/get_match_request/{match_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to fetch match data: {await response.text()}")
                    return None
    except Exception as e:
        logger.exception(f"Error in fetch_match_data: {e}")
        return None

def create_team_embed(match_request: AvailabilityRequest, rsvp_data, team_type='home'):
    """Create a team embed for match RSVP display."""
    team_name = match_request.home_team_name if team_type == 'home' else match_request.away_team_name
    opponent_name = match_request.away_team_name if team_type == 'home' else match_request.home_team_name
    match_date = match_request.match_date
    match_time = match_request.match_time
    
    embed = discord.Embed(title=f"{team_name} vs {opponent_name}",
                          description=f"Date: {match_date}\nTime: {match_time}",
                          color=0x00ff00)
    
    if rsvp_data:
        for status in ['yes', 'no', 'maybe']:
            players = rsvp_data.get(status, [])
            player_names = ', '.join([player['player_name'] for player in players])
            emoji = get_emoji_for_response(status)
            embed.add_field(name=f"{emoji} {status.capitalize()} ({len(players)})", 
                            value=player_names or "None", 
                            inline=False)
    
    return embed

async def update_embed_for_message(message_id: str, channel_id: str, match_id: int, team_id: int, bot: commands.Bot):
    """
    Enhanced version of update_embed_for_message with better error handling.
    """
    logger.debug(f"Updating embed for message_id={message_id}, channel_id={channel_id}, match_id={match_id}, team_id={team_id}")
    
    try:
        # Fetch the channel directly
        channel = bot.get_channel(int(channel_id))
        if not channel:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except discord.NotFound:
                logger.error(f"Channel with ID {channel_id} not found.")
                return False
            except discord.Forbidden:
                logger.error(f"Bot doesn't have permission to access channel {channel_id}.")
                return False

        # Fetch the message directly in the channel
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            logger.error(f"Message with ID {message_id} not found in channel {channel_id}.")
            return False
        except discord.Forbidden:
            logger.error(f"Bot doesn't have permission to access message {message_id} in channel {channel_id}.")
            return False

        # Fetch team-specific RSVP data with retry logic
        rsvp_data = None
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                api_url = f"http://webui:5000/api/get_match_rsvps/{match_id}?team_id={team_id}"
                logger.debug(f"Fetching RSVP data (attempt {attempt+1}/{max_retries}) from {api_url}")
                
                async with aiohttp.ClientSession() as session:
                    timeout = 10 * (attempt + 1)  # Increase timeout with each attempt
                    async with session.get(api_url, timeout=timeout) as response:
                        if response.status == 200:
                            rsvp_data = await response.json()
                            logger.debug(f"Successfully fetched RSVP data for match {match_id} and team {team_id}")
                            break  # Success, exit retry loop
                        else:
                            error_text = await response.text()
                            logger.error(f"Failed to fetch RSVP data (attempt {attempt+1}/{max_retries}): {error_text}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                                continue
                            else:
                                return False
            except Exception as e:
                logger.error(f"Error fetching RSVP data (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    return False
        
        if not rsvp_data:
            logger.error(f"Failed to fetch RSVP data for match {match_id} and team {team_id} after {max_retries} attempts")
            return False

        # Fetch the match data for team names
        match_data = None
        for attempt in range(max_retries):
            try:
                api_url = f"http://webui:5000/api/get_match_request/{match_id}"
                logger.debug(f"Fetching match data (attempt {attempt+1}/{max_retries}) from {api_url}")
                
                async with aiohttp.ClientSession() as session:
                    timeout = 10 * (attempt + 1)  # Increase timeout with each attempt
                    async with session.get(api_url, timeout=timeout) as response:
                        if response.status == 200:
                            match_data = await response.json()
                            logger.debug(f"Successfully fetched match data for match {match_id}")
                            break  # Success, exit retry loop
                        else:
                            error_text = await response.text()
                            logger.error(f"Failed to fetch match data (attempt {attempt+1}/{max_retries}): {error_text}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                                continue
                            else:
                                # We can still proceed without match data
                                logger.warning(f"Will update embed without match metadata")
                                break
            except Exception as e:
                logger.error(f"Error fetching match data (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    # We can still proceed without match data
                    logger.warning(f"Will update embed without match metadata due to error: {e}")
                    break

        # Determine if this is the home or away team
        is_home_team = False
        team_name = "Team"
        opponent_name = "Opponent"
        match_date = "TBD"
        match_time = "TBD"
        
        if match_data:
            is_home_team = team_id == match_data.get('home_team_id')
            team_name = match_data.get('home_team_name', "Home Team") if is_home_team else match_data.get('away_team_name', "Away Team")
            opponent_name = match_data.get('away_team_name', "Away Team") if is_home_team else match_data.get('home_team_name', "Home Team")
            match_date = match_data.get('match_date', "TBD")
            match_time = match_data.get('match_time', "TBD")

        # Create the embed
        embed = discord.Embed(
            title=f"{team_name} vs {opponent_name}",
            description=f"Date: {match_date}\nTime: {match_time}",
            color=0x00ff00
        )

        # Add fields for each RSVP status with proper player lists
        for status in ['yes', 'no', 'maybe']:
            players = rsvp_data.get(status, [])
            player_names = ', '.join([player.get('player_name', 'Unknown') for player in players]) or "None"
            emoji = get_emoji_for_response(status)
            embed.add_field(
                name=f"{emoji} {status.capitalize()} ({len(players)})",
                value=player_names,
                inline=False
            )
            logger.debug(f"Added {status} field with {len(players)} players")

        # Update the message with the new embed
        try:
            await message.edit(embed=embed)
            logger.info(f"Successfully updated embed for message {message_id} in channel {channel_id}")
            return True
        except discord.HTTPException as e:
            logger.error(f"Error updating message {message_id}: {e}")
            return False

    except Exception as e:
        logger.exception(f"Error updating embed: {e}")
        return False

async def fetch_match_request_data(match_id: int):
    """Fetch match request data by match ID."""
    try:
        session = await get_session()
        api_url = f"http://webui:5000/api/get_match_request/{match_id}"
        async with session.get(api_url) as response:
            if response.status == 200:
                return await response.json()
            else:
                logger.error(f"Failed to fetch match request data: {await response.text()}")
                return None
    except Exception as e:
        logger.exception(f"Error in fetch_match_request_data: {e}")
        return None

# Session cleanup utility
async def cleanup_session():
    """Clean up the aiohttp session."""
    global session
    if session:
        await session.close()
        session = None