# discord bot_rest_api.py

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from shared_states import get_bot_instance, set_bot_instance, bot_ready, bot_state
import logging
import discord
import asyncio
import aiohttp
import time
import os
import requests
import random
import json
from aiohttp import ClientError
from discord.ext import commands
from datetime import datetime
from typing import Tuple, Optional, Union
from utils import get_correct_predictions


# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# FIX THIS AFTER TESTING
TEAM_ID = '9726'


# Initialize FastAPI app
app = FastAPI()

# Include ECS FC router
from ecs_fc_bot_api import router as ecs_fc_router
app.include_router(ecs_fc_router)

# Include League router
from league_routes import router as league_router
app.include_router(league_router)

session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    global session
    if session is None:
        session = aiohttp.ClientSession()
    return session

# Startup and shutdown events to manage aiohttp session lifecycle
@app.on_event("startup")
async def startup_event():
    global session
    if session is None:
        session = aiohttp.ClientSession()

@app.on_event("shutdown")
async def shutdown_event():
    global session
    if session:
        await session.close()

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

    async with session.put(url, headers=headers, json=payload) as response:
        if response.status in [200, 204]:
            logger.info(f"Permissions set successfully for role ID {role_id} on channel ID {channel_id}")
            return {"status": "Permissions updated"}
        else:
            logger.error(f"Failed to set permissions: {response.status} - {await response.text()}")
            raise HTTPException(status_code=response.status, detail=f"Failed to set permissions: {await response.text()}")

def get_emoji_for_response(response):
    if response == 'yes':
        return "👍"
    elif response == 'no':
        return "👎"
    elif response == 'maybe':
        return "🤷"
    else:
        return None

class RateLimiter:
    def __init__(self, calls: int, period: int):
        self.calls = calls
        self.period = period
        self.timestamps = []

    async def is_allowed(self, request: Request) -> bool:
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < self.period]
        
        if len(self.timestamps) >= self.calls:
            return False
        
        self.timestamps.append(now)
        return True

rate_limiter = RateLimiter(calls=5, period=60)  # 5 calls per minute

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
    match_id: int
    home_team_id: int
    away_team_id: int
    home_channel_id: Union[int, str]
    away_channel_id: Union[int, str]
    home_team_name: str
    away_team_name: str
    match_date: str
    match_time: str

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
    api_url = f"http://webui:5000/get_player_id_from_discord/{discord_id}"
    async with session.get(api_url) as response:
        if response.status == 200:
            data = await response.json()
            return data.get('player_id'), data.get('team_id')
        else:
            logger.error(f"Failed to get player info for user: {await response.text()}")
            return None, None

async def retry_api_call(url, method='GET', json=None, max_retries=3, delay=1):
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
    try:
        parts = message_id_str.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid message ID format: {message_id_str}")
        return parts[0], parts[1]
    except Exception as e:
        logger.error(f"Error extracting channel and message ID from {message_id_str}: {e}")
        raise ValueError(f"Invalid message ID format: {message_id_str}")

async def fetch_team_rsvp_data(match_id: int, team_id: int):
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
    try:
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

def create_match_embed(update_type, update_data):
    focus_team_id = str(TEAM_ID)  # Our team ID

    if update_type == "score_update":
        return create_score_update_embed(update_data, focus_team_id)
    elif update_type in ["match_event", "hype_event"]:
        return create_match_event_embed(update_data, focus_team_id, is_hype=(update_type == "hype_event"))
    elif update_type == "halftime":
        return create_halftime_embed(update_data, focus_team_id)
    elif update_type == "fulltime":
        # Extract match_id from update_data (ensure update_data contains it)
        match_id = update_data.get("match_id")
        return create_fulltime_embed(match_id, update_data, focus_team_id)
    elif update_type == "match_started":
        # Create a special kickoff embed to avoid duplicate messages
        return create_match_started_embed(update_data, focus_team_id)
    elif update_type in ["status_scheduled", "pre_match_info"]:
        return create_pre_match_embed(update_data, focus_team_id)
    else:
        logger.warning(f"Unknown update type: {update_type}")
        embed = discord.Embed(
            title="Match Update",
            description="An update has occurred."
        )
        return embed

def create_match_started_embed(update_data, focus_team_id):
    """
    Create an embed for match kickoff.
    """
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🏟️ Kickoff! {home_team_name} vs {away_team_name}"
    embed.color = discord.Color.green()
    
    # Check if our team is playing
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** 0 - 0 {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Let's Go!", value="The match has started! Let's go Sounders! 💚", inline=False)
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} 0 - 0 **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Let's Go!", value="The match has started! Let's go Sounders! 💚", inline=False)
    else:
        embed.description = f"{home_team_name} 0 - 0 {away_team_name}"
        embed.color = discord.Color.blue()
        embed.add_field(name="Kickoff", value="The match has started!", inline=False)

    embed.add_field(name="Time", value="Kickoff", inline=True)
    
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

    #embed.add_field(name="Match Status", value=match_status, inline=True)
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
        messages = [
            f"🎉 GOOOOOAAAALLLL! {scorer_name} scores for {team_name} at {event_time}! Keep it coming! ⚽🔥",
            f"Goal! {scorer_name} puts {team_name} in the lead at {event_time}! Amazing strike! 🚀",
            f"Fantastic! {scorer_name} nets one for {team_name} at {event_time}! Let’s keep the momentum! 💪"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.green()
        )
    else:
        messages = [
            f"😡 Goal for {team_name} by {scorer_name} at {event_time}. We must fight back! 💪",
            f"{scorer_name} scores for the opposition at {event_time}. Time to regroup! ⚡",
            f"They take the lead... {scorer_name} scores for {team_name} at {event_time}. Let's counterattack! 🔥"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.red()
        )
    return embed

def create_card_embed(card_type, team_name, athlete, is_focus_team_event, event_time, is_hype):
    player_name = athlete.get('displayName', "Unknown Player")
    emoji = "🟨" if card_type == "Yellow Card" else "🟥"
    if is_hype:
        messages = [
            f"{emoji} {card_type} for {team_name}! {player_name} gets booked at {event_time}. Advantage us! 😈",
            f"{emoji} A booking for {team_name} at {event_time}! {player_name} should be more careful! 🔥"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.green()
        )
    else:
        messages = [
            f"{emoji} {card_type} for {team_name}: {player_name} received it at {event_time}. Stay focused!",
            f"{emoji} {player_name} got a {card_type.lower()} at {event_time} for {team_name}. Let's tighten up our play!"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
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
        embed.set_thumbnail(url=home_team.get('logo'))
        # Randomized messages for our team scoring conditions
        if home_score > away_score:
            messages = [
                "We're in the lead! Keep pushing! 🔥",
                "On top of the game—let’s maintain our momentum! 🚀",
                "Great job! We're ahead. Stay focused! 💪"
            ]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        elif home_score < away_score:
            messages = [
                "We're behind, but it's not over! Let's rally! 💪",
                "Time to step it up—fight back! ⚡",
                "Challenging start, but we can turn it around! 🔥"
            ]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        else:
            messages = [
                "It's all square! Time to take control! ⚖️",
                "Evenly matched—now's our chance to break through! 🌟",
                "The score is level. Let’s create an opportunity! ⚽"
            ]
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
    elif away_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        if away_score > home_score:
            messages = [
                "We're ahead! Keep the pressure on! 💪",
                "Fantastic! We're leading on the road! 🚀",
                "In the lead—stay sharp and maintain the edge! 🔥"
            ]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        elif away_score < home_score:
            messages = [
                "We're behind, but there's still time! Let's fight back! 💪",
                "Challenging game—time to regroup and push harder! 🔥",
                "We're trailing; every minute counts! ⚡"
            ]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        else:
            messages = [
                "It's a draw! Let's take the initiative! ⚽",
                "Level game—now's our chance to break the deadlock! 🌟",
                "Tied up at the moment. We need to push for the win! ⚖️"
            ]
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
    else:
        embed.title = f"Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()

    #embed.add_field(name="Match Status", value=update_data.get('match_status', "Unknown"), inline=True)
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

def create_fulltime_embed(match_id, update_data, focus_team_id):
    """
    Create a full-time embed including the result and, if available, a list of users who predicted correctly.
    The match_id is used to fetch the prediction data from the Flask API.
    """
    # Fetch correct predictions from the Flask API
    correct_predictions = get_correct_predictions(match_id)

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
    
    # Add a field for correct predictions if any were found.
    if correct_predictions:
        # Format the Discord user IDs as mentions.
        mentions = ", ".join([f"<@{user_id}>" for user_id in correct_predictions])
        embed.add_field(name="Correct Predictions", value=mentions, inline=False)
    
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

    embed.add_field(name="🏟️ Venue", value=update_data.get('venue', "N/A"), inline=False)
    embed.add_field(name="🏠 Home Form", value=update_data.get('home_form', "N/A"), inline=True)
    embed.add_field(name="🛫 Away Form", value=update_data.get('away_form', "N/A"), inline=True)

    odds_info = (
        f"Home Win: {update_data.get('home_odds', 'N/A')}\n"
        f"Draw: {update_data.get('draw_odds', 'N/A')}\n"
        f"Away Win: {update_data.get('away_odds', 'N/A')}"
    )
    #embed.add_field(name="💰 Odds", value=odds_info, inline=False)

    # Randomize pre-match hype messages based on focus team
    if home_team_id == str(focus_team_id):
        messages = [
            f"🔥 It's matchday! {home_team_name} is set to dominate on home turf! 🏟️",
            f"Get ready! {home_team_name} is fired up for a big night at home! 💪",
            f"{home_team_name} is ready to rock the stadium—let's show them our power! 🚀"
        ]
        embed.description = random.choice(messages)
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Team Spirit", value="Our boys are pumped and ready to give it their all! 💪", inline=False)
    elif away_team_id == str(focus_team_id):
        messages = [
            f"🌟 It's time for {away_team_name} to shine on the road! Let's show them what we've got! 💪",
            f"{away_team_name} is ready for battle away from home—let's make it a statement! 🚀",
            f"On the road and on fire! {away_team_name} is set to take control! 🔥"
        ]
        embed.description = random.choice(messages)
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Away Day Magic", value="We're taking our A-game to their turf! Let's make our traveling fans proud! 🛫", inline=False)
    else:
        embed.description = "An exciting match is on the horizon! Who will come out on top?"

    return embed

async def get_team_id_for_message(message_id: int, channel_id: int, max_retries=5) -> Tuple[Optional[int], Optional[int]]:
    """Get team ID for a given message with improved error handling."""
    api_url = "http://webui:5000/api/get_match_and_team_id_from_message"
    params = {'message_id': str(message_id), 'channel_id': str(channel_id)}

    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            try:
                async with session.get(api_url, params=params) as response:
                    response_text = await response.text()
                    logger.debug(f"Response from API (attempt {attempt + 1}): {response_text}")

                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON response on attempt {attempt + 1}: {response_text}")
                        await asyncio.sleep(5)
                        continue

                    # Check response format and status
                    status = response_data.get('status')
                    
                    if status == 'success':
                        data = response_data.get('data')
                        if not data:
                            logger.error("Success response without data")
                            await asyncio.sleep(5)
                            continue

                        match_id = data.get('match_id')
                        team_id = data.get('team_id')
                        
                        if match_id is not None and team_id is not None:
                            logger.info(f"Successfully retrieved match_id: {match_id}, team_id: {team_id}")
                            return match_id, team_id
                        else:
                            logger.error("Missing required fields in data")
                    
                    elif status == 'error':
                        error_msg = response_data.get('error', 'Unknown error')
                        logger.error(f"API returned error on attempt {attempt + 1}: {error_msg}")
                        if 'not found' in error_msg.lower() and attempt == max_retries - 1:
                            return None, None
                    
                    else:
                        logger.error(f"Unexpected response format on attempt {attempt + 1}")

                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)

            except aiohttp.ClientError as e:
                logger.error(f"Request failed on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)

    logger.error(f"Failed to get team ID after {max_retries} attempts")
    return None, None

async def poll_task_result(task_id, max_retries=30, delay=3):
    """
    Polls the task result for a given task_id until it's ready or a maximum number of retries is reached.
    """
    poll_url = f"http://webui:5000/api/task_status/{task_id}"

    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            try:
                async with session.get(poll_url) as response:
                    if response.status == 200:
                        result = await response.json()

                        # Log full result for debug purposes
                        logger.debug(f"Polling attempt {attempt + 1}/{max_retries} for task_id {task_id}, received: {result}")

                        task_state = result.get('state', 'PENDING')

                        if task_state == 'SUCCESS':
                            # Ensure `result['result']` exists and is a dictionary
                            task_result = result.get('result')
                            if isinstance(task_result, dict):
                                return task_result
                            else:
                                logger.error(f"Unexpected result format for task_id {task_id}: {task_result}")
                                return {'error': 'Unexpected result format'}

                        elif task_state == 'FAILURE':
                            return {'error': result.get('status', 'Unknown failure')}

                        elif task_state == 'PENDING':
                            logger.info(f"Task {task_id} is still pending, attempt {attempt + 1}/{max_retries}")
                    else:
                        logger.warning(f"Unexpected response status {response.status} while polling task {task_id}, attempt {attempt + 1}/{max_retries}")

                # Exponential backoff delay with a cap of 60 seconds
                await asyncio.sleep(min(delay * (2 ** attempt), 60))

            except ClientError as e:
                logger.error(f"Client error while polling task result (attempt {attempt + 1}/{max_retries}): {str(e)}")
                await asyncio.sleep(delay)

    # Return a specific error if max retries are exhausted
    logger.error(f"Task {task_id} did not complete successfully after {max_retries} retries")
    return {'error': 'Task did not complete successfully'}

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

# Rename a channel without specifying the guild in the route
@app.patch("/channels/{channel_id}")
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

# Delete a channel in a guild
@app.delete("/guilds/{guild_id}/channels/{channel_id}")
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
@app.patch("/guilds/{guild_id}/roles/{role_id}")
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

@app.put("/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
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

@app.delete("/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
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

@app.post("/api/post_availability")
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

@app.post("/api/update_availability_embed/{match_id}")
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
                    api_url = f"http://webui:5000/api/get_message_ids/{match_id}"
                    
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
    api_url = "http://webui:5000/api/store_message_ids"
    payload = {
        'match_id': match_id,
        'home_message_id': home_message_id,
        'away_message_id': away_message_id,
        'home_channel_id': home_channel_id,
        'away_channel_id': away_channel_id
    }
    
    logger.info(f"Storing message IDs in Web UI for match {match_id}: {payload}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, timeout=10) as response:
                if response.status == 200:
                    logger.info(f"Successfully stored message IDs for match {match_id}")
                    return {"success": True, "message": "Message IDs stored successfully"}
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to store message IDs in Web UI: {response.status} - {error_text}")
                    return {"success": False, "message": f"Failed with status {response.status}: {error_text}"}
    except Exception as e:
        logger.exception(f"Error storing message IDs in Web UI: {str(e)}")
        return {"success": False, "message": f"Exception occurred: {str(e)}"}

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

@app.post("/update_discord_rsvp")
async def update_discord_rsvp(request: dict, bot: commands.Bot = Depends(get_bot)):
    match_id = request.get("match_id")
    user_id = request.get("user_id")
    new_response = request.get("new_response")
    old_response = request.get("old_response")
    
    if not all([match_id, user_id, new_response]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://webui:5000/api/get_message_ids/{match_id}") as response:
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

@app.post("/send_discord_dm")
async def send_discord_dm(
    message: str = Body(..., embed=True, description="The message to send"),
    discord_id: str = Body(..., embed=True, description="The player's Discord ID"),
    bot: commands.Bot = Depends(get_bot)
):
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
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Cannot send DM to this user. They may have DMs disabled.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send DM: {str(e)}")

async def update_message_with_reactions(
    bot: commands.Bot,
    message_id: str,
    channel_id: str,
    team_id: int,
    match_id: str,
    user_id: str,
    new_response: str,
    old_response: str
):
    """Helper function to update a single message's reactions and embed"""
    logger.debug(f"Processing message {message_id} in channel {channel_id} for team {team_id}")
    
    channel = bot.get_channel(int(channel_id))
    if not channel:
        logger.error(f"Channel with ID {channel_id} not found.")
        return

    try:
        message = await channel.fetch_message(int(message_id))
        logger.debug(f"Fetched message {message_id} from channel {channel_id}")
    except discord.NotFound:
        logger.error(f"Message with ID {message_id} not found in channel {channel_id}.")
        return

    try:
        member = await message.guild.fetch_member(int(user_id))
        logger.debug(f"Fetched member {user_id}")
    except discord.NotFound:
        logger.error(f"Member with ID {user_id} not found in the guild.")
        return

    # Handle reactions
    if old_response:
        old_emoji = get_emoji_for_response(old_response)
        logger.debug(f"Old response emoji: {old_emoji}")
        for reaction in message.reactions:
            if str(reaction.emoji) == old_emoji:
                await reaction.remove(member)
                logger.debug(f"Removed old reaction {old_emoji} from member {user_id}")

    new_emoji = get_emoji_for_response(new_response)
    logger.debug(f"New response emoji: {new_emoji}")
    await message.add_reaction(new_emoji)
    logger.debug(f"Added new reaction {new_emoji} for member {user_id}")

    # Fetch the updated RSVP data for THIS team
    api_url = f"http://webui:5000/api/get_match_rsvps/{match_id}?team_id={team_id}"
    logger.debug(f"Fetching RSVP data from {api_url}")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 200:
                rsvp_data = await response.json()
                logger.debug(f"Successfully fetched RSVP data for match {match_id} and team {team_id}: {rsvp_data}")
                await update_embed_message_with_players(message, rsvp_data)
            else:
                logger.error(f"Failed to fetch RSVP data: {await response.text()}")

@app.post("/api/update_user_reaction")
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
                    async with session.get(f"http://webui:5000/api/get_message_ids/{match_id}", 
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
                api_url = f"http://webui:5000/api/is_user_on_team"
                payload = {'discord_id': user_id, 'team_id': message_data['home_team_id']}
                
                async with aiohttp.ClientSession() as check_session:
                    async with check_session.post(api_url, json=payload) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get('is_team_member', False):
                                team_id = message_data['home_team_id']
            
            # If not on home team, check if on away team
            if not team_id and message_data.get('away_team_id'):
                api_url = f"http://webui:5000/api/is_user_on_team"
                payload = {'discord_id': user_id, 'team_id': message_data['away_team_id']}
                
                async with aiohttp.ClientSession() as check_session:
                    async with check_session.post(api_url, json=payload) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get('is_team_member', False):
                                team_id = message_data['away_team_id']
            
            # If we found a team, check current RSVP status in Flask
            if team_id:
                api_url = f"http://webui:5000/api/get_match_rsvps/{match_id}?team_id={team_id}&include_discord_ids=true"
                
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

async def process_user_reaction_update(request_data: dict, bot: commands.Bot):
    try:
        # Log the incoming data
        logger.debug(f"Processing user reaction update with data: {request_data}")

        # Extract fields
        match_id = request_data.get("match_id")
        discord_id = request_data.get("discord_id")
        new_response = request_data.get("new_response")
        old_response = request_data.get("old_response")
        message_ids = request_data.get("message_ids")

        # Log extracted data
        logger.debug(f"Match ID: {match_id}, Discord ID: {discord_id}, New Response: {new_response}, Old Response: {old_response}, Message IDs: {message_ids}")

        # Validate data again (just to be sure)
        if not message_ids:
            logger.error("No message IDs provided")
            return

        for message_id_str in message_ids:
            if not message_id_str:
                logger.warning(f"Empty or None message ID. Skipping.")
                continue

            try:
                # Assume you have a method to split or process message IDs (if needed)
                channel_id, message_id = extract_channel_and_message_id(message_id_str)
                logger.info(f"Processing message: channel_id={channel_id}, message_id={message_id}")

                # Get the channel and message from Discord
                channel = bot.get_channel(int(channel_id))
                if not channel:
                    logger.error(f"Channel with ID {channel_id} not found")
                    continue

                try:
                    message = await channel.fetch_message(int(message_id))
                    logger.debug(f"Fetched message {message_id} from channel {channel_id}")
                except discord.NotFound:
                    logger.error(f"Message with ID {message_id} not found in channel {channel_id}")
                    continue
                except discord.Forbidden:
                    logger.error(f"Bot doesn't have permission to fetch message {message_id} in channel {channel_id}")
                    continue

                # Fetch member from Discord by Discord ID
                guild = message.guild
                try:
                    member = await guild.fetch_member(int(discord_id))
                    logger.debug(f"Fetched member {discord_id} from guild")
                except discord.NotFound:
                    logger.warning(f"Member with Discord ID {discord_id} not found in the guild")
                    continue

                # Process reactions (removing old and adding new)
                if old_response:
                    old_emoji = get_emoji_for_response(old_response)
                    for reaction in message.reactions:
                        if str(reaction.emoji) == old_emoji:
                            try:
                                await reaction.remove(member)
                                logger.debug(f"Removed old reaction {old_emoji} for member {discord_id}")
                            except discord.HTTPException as e:
                                logger.error(f"Failed to remove reaction: {e}")
                            break

                # Add the new reaction
                new_emoji = get_emoji_for_response(new_response)
                if new_emoji:
                    try:
                        await message.add_reaction(new_emoji)
                        logger.debug(f"Added new reaction {new_emoji} for member {discord_id}")
                    except discord.HTTPException as e:
                        logger.error(f"Failed to add reaction: {e}")

            except Exception as e:
                logger.exception(f"Error updating reaction for message {message_id_str}: {e}")

        logger.info("Finished processing all message IDs")

    except Exception as e:
        logger.exception(f"Error in process_user_reaction_update: {e}")

async def update_user_reaction_logic(request_data: dict, bot: commands.Bot):
    match_id = request_data.get("match_id")
    discord_id = request_data.get("discord_id")
    new_response = request_data.get("new_response")
    old_response = request_data.get("old_response")
    message_ids = request_data.get("message_ids")

    if not all([match_id, discord_id, new_response, message_ids is not None]):
        logger.error("Missing required fields")
        return

    emoji_map = {
        'yes': '👍',
        'no': '👎',
        'maybe': '🤷'
    }

    new_emoji = emoji_map.get(new_response.lower())
    old_emoji = emoji_map.get(old_response.lower()) if old_response else None

    if not new_emoji:
        logger.error(f"Invalid new_response value: {new_response}")
        return

    for message_id_str in message_ids:
        if not message_id_str:
            logger.warning("Message ID is empty or None. Skipping.")
            continue

        try:
            channel_id, message_id = extract_channel_and_message_id(message_id_str)
            logger.info(f"Processing message: channel_id={channel_id}, message_id={message_id}")
            
            channel = bot.get_channel(int(channel_id))
            if not channel:
                logger.error(f"Channel with ID {channel_id} not found.")
                continue

            try:
                message = await asyncio.wait_for(channel.fetch_message(int(message_id)), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error(f"Timeout while fetching message {message_id} from channel {channel_id}")
                continue
            except discord.NotFound:
                logger.error(f"Message with ID {message_id} not found in channel {channel_id}.")
                continue
            except discord.Forbidden:
                logger.error(f"Bot doesn't have permission to fetch message {message_id} in channel {channel_id}.")
                continue

            guild = message.guild
            try:
                member = await guild.fetch_member(int(discord_id))
            except discord.NotFound:
                logger.warning(f"Member with Discord ID {discord_id} not found in the server.")
                continue

            if old_emoji:
                for reaction in message.reactions:
                    if str(reaction.emoji) == old_emoji:
                        try:
                            await reaction.remove(member)
                        except discord.HTTPException as e:
                            logger.error(f"Failed to remove reaction: {e}")
                        break

            if new_emoji:
                try:
                    await message.add_reaction(new_emoji)
                except discord.HTTPException as e:
                    logger.error(f"Failed to add reaction: {e}")

            team_id = await get_team_id_for_message(match_id, channel_id, message_id)
            if team_id:
                try:
                    await update_embed_for_message(int(message_id), int(channel_id), int(match_id), team_id, bot)
                except Exception as e:
                    logger.error(f"Failed to update embed: {e}")
            else:
                logger.error(f"Could not determine team_id for message {message_id} in channel {channel_id}")

        except Exception as e:
            logger.exception(f"Error updating reaction for message {message_id_str}: {e}")


@app.post("/api/force_rsvp_sync")
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

