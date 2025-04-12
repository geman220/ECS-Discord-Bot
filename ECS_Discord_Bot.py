# ECS_Discord_Bot.py

from datetime import datetime
import aiohttp
import discord
import asyncio
import os
import logging
from discord import app_commands
from discord.ext import commands
from common import bot_token, server_id
import uvicorn
from bot_rest_api import app, bot_ready, update_embed_for_message, get_team_id_for_message, poll_task_result, session
from shared_states import bot_ready, bot_state, set_bot_instance, periodic_check

WEBUI_API_URL = os.getenv("WEBUI_API_URL")

# Configure logging
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

# Initialize Discord bot with intents
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Removed separate managed_message_ids set; using bot_state instead

VERIFY_CHANNEL_IDS = {1036026916282585228, 1072279143145799740}

async def load_managed_message_ids():
    global session  # Use the global session variable

    # Ensure the session is initialized
    if session is None:
        logger.warning("Session is not initialized. Initializing session now.")
        session = aiohttp.ClientSession()

    try:
        async with session.get(f"{WEBUI_API_URL}/get_scheduled_messages") as response:
            if response.status == 200:
                data = await response.json()
                for msg in data:
                    # Extract match details
                    match_date = msg.get('match_date')
                    home_team_id = msg.get('home_team_id')
                    away_team_id = msg.get('away_team_id')
                    
                    # Add home message ID with metadata
                    if msg.get('home_message_id'):
                        bot_state.add_managed_message_id(
                            int(msg['home_message_id']),
                            match_date=match_date,
                            team_id=home_team_id
                        )
                    
                    # Add away message ID with metadata
                    if msg.get('away_message_id'):
                        bot_state.add_managed_message_id(
                            int(msg['away_message_id']),
                            match_date=match_date,
                            team_id=away_team_id
                        )
                
                # Log stats about managed messages
                all_messages = len(bot_state.get_managed_message_ids())
                this_week = len(bot_state.get_managed_message_ids(days_limit=7))
                
                logger.info(f"Loaded {all_messages} managed messages ({this_week} for the next 7 days)")
            else:
                logger.error(f"Failed to fetch scheduled messages: {response.status}, {await response.text()}")
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching scheduled messages: {e}")

async def periodic_sync():
    """
    Periodically synchronizes managed_message_ids with the web app.
    """
    while True:
        await load_managed_message_ids()
        await asyncio.sleep(300)  # Sync every 5 minutes
        
async def full_rsvp_sync(force_sync=False):
    """
    Performs a full synchronization between Discord reactions/embeds and Flask RSVPs.
    This ensures consistency even after bot downtime or network failures.
    
    Args:
        force_sync: If True, update all messages even if no discrepancy detected.
    """
    logger.info(f"Starting full RSVP synchronization (force_sync={force_sync})")
    message_ids = list(bot_state.get_managed_message_ids())
    synced_count = 0
    failed_count = 0
    
    for message_id in message_ids:
        try:
            # For each managed message, get its channel ID
            match_data = await get_message_channel_from_web_ui(message_id)
            if not match_data or 'channel_id' not in match_data:
                logger.warning(f"Could not find channel ID for message {message_id}")
                continue
                
            channel_id = int(match_data['channel_id'])
            match_id = match_data.get('match_id')
            team_id = match_data.get('team_id')
            
            if not match_id or not team_id:
                logger.warning(f"Missing match_id or team_id for message {message_id}")
                continue
                
            # Get Discord reactions for this message
            discord_rsvps = await get_message_reactions(channel_id, message_id)
            
            # Get Flask RSVPs for the match
            flask_rsvps = await get_flask_rsvps(match_id, team_id)
            
            if not flask_rsvps:
                logger.warning(f"Could not fetch RSVPs from Flask for match {match_id}")
                continue
                
            # Compare and reconcile differences
            reconciliation_needed = await reconcile_rsvps(
                match_id, team_id, discord_rsvps, flask_rsvps, channel_id, message_id, force_sync
            )
            
            if reconciliation_needed or force_sync:
                # Update the embed with latest data from Flask (source of truth)
                success = await update_embed_for_message(message_id, channel_id, match_id, team_id, bot)
                if success:
                    synced_count += 1
                    logger.info(f"Successfully synced RSVPs for match {match_id}, message {message_id}")
                else:
                    failed_count += 1
                    logger.error(f"Failed to sync RSVPs for match {match_id}, message {message_id}")
            else:
                synced_count += 1
                logger.debug(f"No sync needed for match {match_id}, message {message_id}")
                
        except Exception as e:
            logger.error(f"Error syncing message {message_id}: {str(e)}", exc_info=True)
            failed_count += 1
    
    logger.info(f"RSVP sync completed: {synced_count} synced, {failed_count} failed")
    return {'synced': synced_count, 'failed': failed_count}

async def get_message_channel_from_web_ui(message_id):
    """
    Gets the channel ID for a message ID from the web UI.
    """
    # Convert message ID to string to match database storage
    message_id_str = str(message_id)
    
    # Use a hardcoded URL to ensure it's correct
    api_url = f"http://webui:5000/api/get_message_info/{message_id_str}"
    try:
        logger.info(f"Fetching message info from: {api_url}")
        async with session.get(api_url) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(f"Got message info: {data}")
                return data
            else:
                logger.error(f"Failed to get message info: {await response.text()}")
                return None
    except Exception as e:
        logger.error(f"Error fetching message info: {str(e)}")
        return None

async def get_message_reactions(channel_id, message_id):
    """
    Gets all reactions for a given message from Discord.
    Returns a dictionary mapping user IDs to their reaction.
    """
    result = {}
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except:
                logger.error(f"Could not fetch channel {channel_id}")
                return result
                
        message = await channel.fetch_message(message_id)
        if not message:
            logger.error(f"Could not fetch message {message_id}")
            return result
            
        emoji_to_response = {"👍": "yes", "👎": "no", "🤷": "maybe"}
        
        # Process all reactions
        for reaction in message.reactions:
            emoji = str(reaction.emoji)
            if emoji in emoji_to_response:
                response = emoji_to_response[emoji]
                async for user in reaction.users():
                    if user.id != bot.user.id:  # Skip bot's own reactions
                        result[str(user.id)] = response
        
        return result
    except Exception as e:
        logger.error(f"Error getting message reactions: {str(e)}", exc_info=True)
        return result

async def get_flask_rsvps(match_id, team_id):
    """
    Gets all RSVPs from Flask for a given match and team.
    Returns a dictionary mapping user discord IDs to their response.
    """
    # WEBUI_API_URL already includes '/api', so we don't need to include it again
    api_url = f"{WEBUI_API_URL}/get_match_rsvps/{match_id}?team_id={team_id}&include_discord_ids=true"
    logger.info(f"Fetching RSVPs from Flask at: {api_url}")
    try:
        async with session.get(api_url) as response:
            if response.status == 200:
                data = await response.json()
                result = {}
                
                # Process yes responses
                for player in data.get('yes', []):
                    if player.get('discord_id'):
                        result[player['discord_id']] = 'yes'
                        
                # Process no responses
                for player in data.get('no', []):
                    if player.get('discord_id'):
                        result[player['discord_id']] = 'no'
                        
                # Process maybe responses
                for player in data.get('maybe', []):
                    if player.get('discord_id'):
                        result[player['discord_id']] = 'maybe'
                
                logger.info(f"Retrieved {len(result)} RSVPs from Flask for match {match_id}, team {team_id}")
                return result
            else:
                logger.error(f"Failed to fetch Flask RSVPs: {await response.text()}")
                return None
    except Exception as e:
        logger.error(f"Error fetching Flask RSVPs: {str(e)}", exc_info=True)
        return None

async def reconcile_rsvps(match_id, team_id, discord_rsvps, flask_rsvps, channel_id, message_id, force_update=False):
    """
    Reconciles differences between Discord reactions and Flask RSVPs.
    Returns True if any reconciliation was needed, False otherwise.
    
    This improved function fixes a race condition that previously
    caused reaction loops. It now focuses on detecting actual mismatches
    and only performs the minimum necessary changes.
    """
    reconciliation_needed = False
    
    # Get all users in either system
    all_users = set(discord_rsvps.keys()) | set(flask_rsvps.keys())
    
    # Dictionary to track users who need reaction updates in Discord
    reaction_updates = {}
    # Dictionary to track users who need RSVP updates in Flask
    flask_updates = {}
    
    # First check: handle users who are in both systems or either system
    for user_id in all_users:
        discord_response = discord_rsvps.get(user_id)
        flask_response = flask_rsvps.get(user_id)
        
        # Skip users who aren't on the team
        is_team_member = await is_user_on_team(user_id, team_id)
        if not is_team_member:
            continue
        
        # Case 1: User in both systems with different responses
        if discord_response and flask_response and discord_response != flask_response:
            # Flask is the source of truth, update Discord
            reaction_updates[user_id] = flask_response
            reconciliation_needed = True
            logger.info(f"Conflict detected for user {user_id}: Discord={discord_response}, Flask={flask_response}. " +
                        f"Updating Discord to match Flask.")
            
        # Case 2: User in Discord but not in Flask
        elif discord_response and not flask_response:
            # Add to Flask
            flask_updates[user_id] = discord_response
            reconciliation_needed = True
            logger.info(f"User {user_id} has Discord reaction {discord_response} but no Flask entry. Updating Flask.")
            
        # Case 3: User in Flask but not in Discord
        elif flask_response and not discord_response:
            # Add to Discord
            reaction_updates[user_id] = flask_response
            reconciliation_needed = True
            logger.info(f"User {user_id} has Flask response {flask_response} but no Discord reaction. Updating Discord.")
    
    # Apply updates to Discord reactions
    if reaction_updates or force_update:
        try:
            # Fetch channel and message once for efficiency
            channel = bot.get_channel(int(channel_id))
            if not channel:
                channel = await bot.fetch_channel(int(channel_id))
                
            message = await channel.fetch_message(int(message_id))
            
            # Get all reactions on this message and index them by user
            user_reactions = {}
            reaction_emoji = {"yes": "👍", "no": "👎", "maybe": "🤷"}
            
            # Build a dictionary of user reactions
            for reaction in message.reactions:
                if str(reaction.emoji) in reaction_emoji.values():
                    async for user in reaction.users():
                        if user.id == bot.user.id:
                            continue  # Skip the bot's own reactions
                        
                        user_id_str = str(user.id)
                        if user_id_str not in user_reactions:
                            user_reactions[user_id_str] = []
                        
                        user_reactions[user_id_str].append(str(reaction.emoji))
            
            # Process only users who need fixes
            users_to_fix = set()
            
            # Find users with multiple/incorrect reactions
            for user_id_str, emojis in user_reactions.items():
                # Skip users who aren't on our tracking lists
                if user_id_str not in flask_rsvps and user_id_str not in reaction_updates:
                    continue
                
                # Determine the correct emoji
                expected_response = flask_rsvps.get(user_id_str) or reaction_updates.get(user_id_str)
                if not expected_response:
                    continue
                
                expected_emoji = reaction_emoji.get(expected_response)
                if not expected_emoji:
                    continue
                
                # Check if the user has incorrect reactions
                incorrect_reactions = len(emojis) > 1 or (emojis and emojis[0] != expected_emoji)
                if incorrect_reactions:
                    users_to_fix.add(int(user_id_str))
                    logger.debug(f"User {user_id_str} has incorrect reactions: {emojis}, expected: {expected_emoji}")
            
            # Add users who are missing reactions completely
            for user_id_str in reaction_updates:
                if user_id_str not in user_reactions:
                    users_to_fix.add(int(user_id_str))
                    logger.debug(f"User {user_id_str} is missing reactions completely")
            
            # Fix reactions only for users who actually need it
            for user_id in users_to_fix:
                user_id_str = str(user_id)
                response = flask_rsvps.get(user_id_str) or reaction_updates.get(user_id_str)
                emoji = reaction_emoji.get(response)
                
                if not emoji:
                    continue
                
                try:
                    # Fetch user object
                    user = await bot.fetch_user(user_id)
                    
                    # Remove all existing reactions from this user
                    for reaction in message.reactions:
                        if str(reaction.emoji) in reaction_emoji.values():
                            users = [u async for u in reaction.users()]
                            if user in users:
                                await reaction.remove(user)
                                logger.debug(f"Removed reaction {reaction.emoji} from user {user_id}")
                    
                    # Add the correct reaction
                    await message.add_reaction(emoji)
                    
                    # Make sure the bot adds the reaction if not already present
                    bot_emoji_added = False
                    for reaction in message.reactions:
                        if str(reaction.emoji) == emoji:
                            bot_users = [u async for u in reaction.users()]
                            if bot.user in bot_users:
                                bot_emoji_added = True
                                break
                    
                    if not bot_emoji_added:
                        await message.add_reaction(emoji)
                    
                    logger.info(f"Fixed reactions for user {user_id} to match {response}")
                    reconciliation_needed = True
                except Exception as e:
                    logger.error(f"Error fixing reactions for user {user_id}: {str(e)}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error processing message {message_id} in channel {channel_id}: {str(e)}", exc_info=True)
    
    # Apply updates to Flask
    if flask_updates:
        for user_id, response in flask_updates.items():
            try:
                await update_user_rsvp(match_id, int(user_id), response)
                logger.info(f"Updated Flask RSVP for user {user_id} to {response}")
            except Exception as e:
                logger.error(f"Error updating Flask RSVP for user {user_id}: {str(e)}", exc_info=True)
    
    return reconciliation_needed

async def schedule_periodic_sync():
    """
    Schedules periodic full RSVP synchronization.
    """
    while True:
        try:
            logger.info("Starting scheduled full RSVP synchronization...")
            await full_rsvp_sync()
            logger.info("Completed scheduled full RSVP synchronization")
        except Exception as e:
            logger.error(f"Error during scheduled full RSVP sync: {str(e)}", exc_info=True)
        
        # Run every 6 hours
        await asyncio.sleep(6 * 60 * 60)

async def sync_rsvp_with_web_ui(match_id, discord_id, response):
    """
    Syncs RSVP data with the web UI by sending a POST request.
    """
    logger.debug(f"Syncing RSVP with Web UI for match {match_id}, user {discord_id}, response {response}")
    api_url = f"{WEBUI_API_URL}/update_availability_from_discord"
    data = {
        "match_id": match_id,
        "discord_id": discord_id,
        "response": response,
        "responded_at": datetime.utcnow().isoformat()
    }

    try:
        async with session.post(api_url, json=data) as resp:
            resp_text = await resp.text()
            if resp.status == 200:
                logger.info(f"RSVP updated successfully for match {match_id} in Web UI. Response: {resp_text}")
            else:
                logger.error(f"Failed to update RSVP in Web UI: {resp.status}, {resp_text}")
    except aiohttp.ClientError as e:
        logger.error(f"Failed to sync RSVP with Web UI: {str(e)}")

async def get_match_and_team_id_from_message(message_id: int, channel_id: int):
    """
    Retrieves match_id and team_id for a given message_id and channel_id via the web app's API.
    """
    logger.debug(f"Fetching match and team ID for message_id: {message_id}, channel_id: {channel_id}")
    api_url = f"{WEBUI_API_URL}/get_match_and_team_id_from_message"
    params = {'message_id': str(message_id), 'channel_id': str(channel_id)}

    try:
        async with session.get(api_url, params=params) as response:
            if response.status == 202:
                # Task is in progress
                response_data = await response.json()
                task_id = response_data.get('task_id')
                logger.info(f"Task is still processing. Task ID: {task_id}")
                return "PROCESSING", task_id  # Return task_id to keep track

            elif response.status == 200:
                # Task completed and data is ready
                data = await response.json()
                logger.debug(f"Received match_id: {data.get('match_id')}, team_id: {data.get('team_id')}")
                return data.get('match_id'), data.get('team_id')

            else:
                # Unexpected response
                resp_text = await response.text()
                logger.error(f"Failed to fetch match and team ID: {response.status}, {resp_text}")
                return None, None

    except aiohttp.ClientError as e:
        logger.error(f"Failed to fetch match and team ID: {str(e)}")
        return None, None

async def is_user_on_team(discord_id: str, team_id: int) -> bool:
    api_url = f"http://webui:5000/api/is_user_on_team"
    payload = {'discord_id': str(discord_id), 'team_id': team_id}
    try:
        async with session.post(api_url, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('is_team_member', False)
            else:
                logger.error(f"Failed to verify team membership: {await response.text()}")
                return False
    except aiohttp.ClientError as e:
        logger.error(f"Error verifying team membership: {str(e)}")
        return False

async def update_user_rsvp(match_id: int, discord_id: int, response: str):
    """
    Updates the user's RSVP in the web app via the API.
    Checks for existing RSVP value to avoid unnecessary updates.
    
    If response is "no_response", this function will check the current RSVP state
    in Flask before removing the entry, to ensure we don't accidentally delete
    valid RSVPs from the database.
    """
    logger.debug(f"Updating RSVP for match {match_id}, user {discord_id}, response {response}")
    
    # First get the current RSVP value to compare
    current_response = None
    team_id = None
    
    try:
        # Determine which team the user is on
        team_id = await get_user_team_id(str(discord_id), match_id)
        if not team_id:
            logger.warning(f"Could not determine team for user {discord_id} in match {match_id}")
            # Proceed with update since we don't know the current value
        else:
            # Get current responses
            flask_rsvps = await get_flask_rsvps(match_id, team_id)
            current_response = flask_rsvps.get(str(discord_id))
            
            # If the response is the same, no need to update
            if current_response == response:
                logger.debug(f"User {discord_id} already has RSVP value '{response}'. Skipping update.")
                return
            
            # IMPORTANT: If trying to set to no_response but user has a valid RSVP in Flask,
            # we should keep the Flask value and update Discord to match instead
            if response == "no_response" and current_response:
                logger.info(f"User {discord_id} has RSVP value '{current_response}' in Flask but no reaction in Discord. " +
                           f"Keeping Flask value and setting correct reaction.")
                
                # Add the correct reaction based on current_response
                reaction_emoji = {"yes": "👍", "no": "👎", "maybe": "🤷"}
                emoji = reaction_emoji.get(current_response)
                
                # Find the message and channel
                message_info = await get_message_channel_from_web_ui(match_id)
                if message_info and 'channel_id' in message_info:
                    channel_id = int(message_info['channel_id'])
                    message_id = int(message_info.get('message_id', 0))
                    
                    # Now add the correct reaction
                    try:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            message = await channel.fetch_message(message_id)
                            if message:
                                # Add the correct reaction
                                user = await bot.fetch_user(discord_id)
                                await message.add_reaction(emoji)
                                logger.info(f"Added {emoji} reaction for user {discord_id} to match Flask value")
                    except Exception as e:
                        logger.error(f"Error adding reaction to match Flask value: {str(e)}")
                
                # Skip updating to no_response
                return
    except Exception as e:
        logger.error(f"Error checking current RSVP status: {str(e)}")
        # Continue with the update as a fallback
    
    # Only update if we need to
    api_url = f"{WEBUI_API_URL}/update_availability_from_discord"
    payload = {
        "match_id": match_id,
        "discord_id": str(discord_id),
        "response": response,
        "responded_at": datetime.utcnow().isoformat()
    }
    try:
        async with session.post(api_url, json=payload) as resp:
            resp_text = await resp.text()
            if resp.status == 200:
                logger.info(f"RSVP updated successfully for match {match_id}, user {discord_id}")
                # Update the Discord embed after a successful update
                await update_discord_embed(match_id)
                
                # If we're setting an actual response (not no_response), make sure the reaction is correct
                if response != "no_response" and team_id:
                    # Add the correct reaction based on the response
                    reaction_emoji = {"yes": "👍", "no": "👎", "maybe": "🤷"}
                    emoji = reaction_emoji.get(response)
                    
                    # Get the message info
                    message_info = await get_message_channel_from_web_ui(match_id)
                    if message_info and 'channel_id' in message_info:
                        channel_id = int(message_info['channel_id'])
                        message_id = int(message_info.get('message_id', 0))
                        
                        # Now add the correct reaction
                        try:
                            channel = bot.get_channel(channel_id)
                            if channel:
                                message = await channel.fetch_message(message_id)
                                if message:
                                    # Add the correct reaction
                                    user = await bot.fetch_user(discord_id)
                                    await message.add_reaction(emoji)
                                    logger.info(f"Added {emoji} reaction for user {discord_id} to match their new RSVP")
                        except Exception as e:
                            logger.error(f"Error adding reaction for new RSVP: {str(e)}")
            else:
                logger.error(f"Failed to update RSVP: {resp.status}, {resp_text}")
    except aiohttp.ClientError as e:
        logger.error(f"Failed to update RSVP: {str(e)}")

async def get_user_team_id(discord_id: str, match_id: int) -> int:
    """
    Helper function to determine which team a user belongs to for a specific match.
    
    Args:
        discord_id: The Discord ID of the user
        match_id: The ID of the match
        
    Returns:
        The team ID if found, None otherwise
    """
    try:
        # Get match data to determine teams
        match_data = await get_message_channel_from_web_ui(match_id)
        if not match_data or 'home_team_id' not in match_data or 'away_team_id' not in match_data:
            logger.warning(f"Could not fetch match data for match {match_id}")
            return None
        
        home_team_id = match_data.get('home_team_id')
        away_team_id = match_data.get('away_team_id')
        
        # Check if user is on either team
        for team_id in [home_team_id, away_team_id]:
            is_member = await is_user_on_team(discord_id, team_id)
            if is_member:
                return team_id
        
        return None
    except Exception as e:
        logger.error(f"Error determining team for user {discord_id}: {str(e)}")
        return None

async def update_discord_embed(match_id: int):
    """
    Updates the Discord embed for a given match.
    """
    api_url = f"http://localhost:5001/api/update_availability_embed/{match_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to update Discord embed. Status: {response.status}, Response: {await response.text()}")
                else:
                    logger.info(f"Discord embed updated for match {match_id}")
    except aiohttp.ClientError as e:
        logger.error(f"Failed to update Discord embed. RequestException: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while updating Discord embed: {str(e)}")

async def load_cogs():
    """
    Loads all the bot's cogs/extensions.
    """
    cog_extensions = [
        'general_commands',
        'woocommerce_commands',
        'admin_commands',
        'match_commands',
        'easter_egg_commands',
        'publeague_commands',
        'match_dates_commands',
        'help_commands'
    ]
    
    for extension in cog_extensions:
        try:
            await bot.load_extension(extension)
            logger.info(f"Loaded {extension} cog")
        except Exception as e:
            logger.error(f"Failed to load {extension} cog: {e}")
    
    # Optionally sync commands with Discord
    try:
        await bot.tree.sync(guild=discord.Object(id=server_id))
        logger.info(f"Commands registered after syncing: {[cmd.name for cmd in bot.tree.walk_commands()]}")
    except Exception as e:
        logger.error(f"Error syncing commands: {e}")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user.name} (ID: {bot.user.id})")

    # Force update bot username
    try:
        if bot.user.name != "ECSBot":
            await bot.user.edit(username="ECSBot")
            logger.info(f"Username updated to ECSBot")
        else:
            logger.info("Bot username is already ECSBot")
    except discord.errors.HTTPException as e:
        logger.error(f"Failed to update username: {e}")

    guild = bot.get_guild(server_id)
    if guild:
        logger.info(f"Connected to guild: {guild.name} (ID: {guild.id})")
    else:
        logger.error(f"Guild with ID {server_id} not found.")

    try:
        logger.info("Loading managed message IDs from the web app...")
        await load_managed_message_ids()
        logger.info("Managed message IDs loaded successfully.")

        logger.info("Loading cogs/extensions...")
        await load_cogs()
        logger.info("Cogs/extensions loaded successfully.")

        logger.info("Starting periodic synchronization task...")
        asyncio.create_task(periodic_sync())

        logger.info("Setting bot instance in shared_states...")
        set_bot_instance(bot)

        logger.info("Setting bot_ready event...")
        bot_ready.set()

        logger.info("Starting periodic check task...")
        asyncio.create_task(periodic_check())
        
        # Start the full RSVP synchronization task
        logger.info("Performing initial full RSVP synchronization...")
        asyncio.create_task(full_rsvp_sync(force_sync=True))
        
        # Schedule periodic full RSVP synchronization
        logger.info("Starting periodic full RSVP synchronization task...")
        asyncio.create_task(schedule_periodic_sync())

        # Start the REST API server as a task in the bot's event loop
        logger.info("Starting REST API server...")
        bot.loop.create_task(start_rest_api())

        logger.info("Bot initialization completed successfully.")
    except Exception as e:
        logger.exception(f"Error during bot initialization: {e}")

    logger.info("Bot is fully ready.")

@bot.event
async def on_message(message):
    """
    Event handler for when a message is sent in a guild.
    """
    if message.author == bot.user:
        return

    # Check if the message is sent in one of the verification channels.
    if message.channel.id in VERIFY_CHANNEL_IDS:
        try:
            await message.delete()
        except discord.Forbidden:
            logging.error("Missing permission to delete messages in the verification channel.")
        else:
            dm_text = (
                "Hi there! It looks like you sent a message in a verification channel. "
                "Please use the `/verify` command to verify your ECS membership. "
                "A window will popup and you can enter your Order ID."
            )
            try:
                await message.author.send(dm_text)
            except discord.Forbidden:
                logging.warning("Unable to send DM to the user.")
        return  # Stop processing further if this was in a verification channel

    # Process other messages as usual
    await bot.process_commands(message)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    """
    Event handler for errors in application commands.
    """
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"This command is on cooldown. Please try again after {error.retry_after:.2f} seconds.",
            ephemeral=True,
        )
    else:
        logger.error(f"Unhandled interaction command error: {error}")
        await interaction.response.send_message(
            "An error occurred while processing the command.", ephemeral=True
        )

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    message_id = payload.message_id
    emoji = str(payload.emoji)
    user_id = payload.user_id
    channel_id = payload.channel_id

    logger.debug(f"Raw reaction added: {emoji} by user: {user_id} for message_id: {message_id}")

    # Only look at relevant messages (within 14 days of today)
    active_message_ids = bot_state.get_managed_message_ids(days_limit=14)
    if message_id not in active_message_ids:
        logger.debug(f"Message ID {message_id} is not an active managed message. Ignoring reaction.")
        return

    # Fetch match_id and team_id from the web app
    match_id, team_id = await get_team_id_for_message(message_id, channel_id)
    if match_id == "PROCESSING":
        task_id = team_id  # In this case, team_id is actually task_id
        logger.info(f"Task is still processing for message_id {message_id}. Task ID: {task_id}")

        # Poll the task result asynchronously without creating a new session
        result = await poll_task_result(session, task_id, max_retries=30, delay=3)
        if not result or 'error' in result:
            logger.error(f"Could not fetch match and team ID for message {message_id}. Error: {result.get('error', 'Unknown error')}")
            return
        else:
            match_id, team_id = result['match_id'], result['team_id']
    
    if not match_id or not team_id:
        logger.error(f"Could not find match or team for message {message_id}")
        return

    # Fetch user object
    user = bot.get_user(user_id)
    if not user:
        logger.error(f"User with ID {user_id} not found.")
        return

    # Check if user is on the team
    is_team_member = await is_user_on_team(user_id, team_id)
    if not is_team_member:
        # Remove the reaction
        channel = bot.get_channel(channel_id)
        if channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.remove_reaction(payload.emoji, user)
                logger.info(f"Removed reaction {emoji} from user {user_id} on message {message_id}")
            except Exception as e:
                logger.error(f"Error removing reaction: {e}")

        # Just log the restriction, no need for DM
        logger.info(f"User {user_id} cannot RSVP for team {team_id} (not their team)")
        return

    # Process the RSVP using simplified approach
    emoji_to_response = {
        "👍": "yes",
        "👎": "no",
        "🤷": "maybe"
    }
    response = emoji_to_response.get(emoji, None)
    if response:
        logger.info(f"Processing RSVP for user {user_id} with response {response} using simplified approach")
        
        try:
            # Always update Flask (source of truth) with the user's reaction choice
            logger.info(f"Updating Flask with user {user_id}'s choice: {response}")
            await sync_rsvp_with_web_ui(match_id, user_id, response)
            
            # Update the Discord embed to reflect the change
            await update_discord_embed(match_id)
            
            # Get the channel and message
            channel = bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except Exception as e:
                    logger.error(f"Could not fetch channel {channel_id}: {e}")
                    return
                    
            # Get the message
            try:
                message = await channel.fetch_message(message_id)
            except Exception as e:
                logger.error(f"Could not fetch message {message_id}: {e}")
                return
            
            # NEW APPROACH: Always remove the user's reaction after processing it
            # This way, only the bot's base reactions remain, avoiding confusion
            await asyncio.sleep(1.0)  # Small delay to ensure RSVP processing completes
            try:
                # Remove this reaction
                await message.remove_reaction(payload.emoji, user)
                logger.info(f"Removed user {user_id}'s {emoji} reaction after processing RSVP")
                
                # Also remove any other reactions this user might have
                for reaction in message.reactions:
                    if str(reaction.emoji) in emoji_to_response.keys() and str(reaction.emoji) != emoji:
                        users = [u async for u in reaction.users()]
                        if user in users:
                            await reaction.remove(user)
                            logger.info(f"Removed user {user_id}'s other reaction: {reaction.emoji}")
            except Exception as e:
                logger.error(f"Error removing reactions: {e}")
            
            # No DM notification needed, users can see their status in the embed
            logger.info(f"RSVP for user {user_id} recorded as {response}, visible in the match embed")
                
        except Exception as e:
            logger.error(f"Error processing reaction add for user {user_id}: {str(e)}", exc_info=True)
    else:
        # Remove invalid reactions
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception as e:
                logger.error(f"Could not fetch channel {channel_id}: {e}")
                return
                
        try:
            message = await channel.fetch_message(message_id)
            await message.remove_reaction(payload.emoji, user)
            logger.info(f"Removed invalid reaction {emoji} from user {user_id}")
        except Exception as e:
            logger.error(f"Could not remove invalid reaction: {e}")

@bot.event
async def on_member_join(member: discord.Member):
    """
    When a member joins the server, check with the Flask app if the member is linked.
    If linked, retrieve the expected roles and assign them using Discord API calls.
    """
    logger.info(f"Member join event triggered for {member.id} - {member.name}")
    # Wait a few seconds to allow for any asynchronous linking in Flask to complete.
    await asyncio.sleep(5)
    
    flask_url = f"{WEBUI_API_URL}/player/by_discord/{member.id}"
    logger.info(f"Requesting expected roles from Flask at {flask_url}")
    
    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.get(flask_url) as resp:
                logger.info(f"Flask API response status: {resp.status} for member {member.id}")
                response_text = await resp.text()
                logger.debug(f"Raw response text: {response_text}")
                
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        logger.debug(f"Response JSON for member {member.id}: {data}")
                    except Exception as json_error:
                        logger.error(f"Failed to parse JSON response for member {member.id}: {json_error}")
                        return  # Exit if we can't parse the JSON
                    
                    if data.get("exists"):
                        expected_roles = data.get("expected_roles", [])
                        if expected_roles:
                            logger.info(f"Linked player found for {member.id} ({data.get('player_name')}). Expected roles: {expected_roles}")
                            for role_name in expected_roles:
                                # Look up the role by name in the guild.
                                role = discord.utils.get(member.guild.roles, name=role_name)
                                if role:
                                    try:
                                        await member.add_roles(role)
                                        logger.info(f"Assigned role '{role_name}' to member {member.id}")
                                    except Exception as e:
                                        logger.error(f"Failed to assign role '{role_name}' to member {member.id}: {e}")
                                else:
                                    logger.error(f"Role '{role_name}' not found in guild {member.guild.name} for member {member.id}.")
                        else:
                            logger.info(f"No expected roles for linked player {member.id}.")
                    else:
                        logger.info(f"No linked player record found for member {member.id}.")
                else:
                    logger.error(f"Flask API returned status {resp.status} for member {member.id}. Response: {response_text}")
    except Exception as e:
        logger.exception(f"Error processing member join for {member.id}: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return

    message_id = payload.message_id
    emoji = str(payload.emoji)
    user_id = payload.user_id
    channel_id = payload.channel_id
    logger.debug(f"Raw reaction removed: {emoji} by user: {user_id} for message_id: {message_id}")

    # Only look at relevant messages (within 14 days of today)
    active_message_ids = bot_state.get_managed_message_ids(days_limit=14)
    if message_id not in active_message_ids:
        logger.debug(f"Message ID {message_id} is not an active managed message. Ignoring reaction removal.")
        return

    match_id, team_id = await get_team_id_for_message(message_id, channel_id)
    if match_id == "PROCESSING":
        task_id = team_id  # In this case, team_id is actually task_id
        logger.info(f"Task is still processing for message_id {message_id}. Task ID: {task_id}")

        result = await poll_task_result(session, task_id, max_retries=30, delay=3)
        if not result or 'error' in result:
            logger.error(f"Could not fetch match and team ID for message {message_id}. Error: {result.get('error', 'Unknown error')}")
            return
        else:
            match_id, team_id = result['match_id'], result['team_id']

    if match_id is None or team_id is None:
        logger.error(f"Could not find match or team for message {message_id}")
        return

    # Check if user is on the team
    is_team_member = await is_user_on_team(str(user_id), team_id)
    if not is_team_member:
        logger.debug(f"User {user_id} is not on team {team_id}. Ignoring reaction removal.")
        return

    user = bot.get_user(user_id)
    if not user:
        logger.error(f"User with ID {user_id} not found.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.error(f"Channel with ID {channel_id} not found: {e}")
            return

    # With the simplified approach, reaction removals don't change RSVP status
    # Just log it, and make sure the base emoji reactions are still present
    emoji_to_response = {
        "👍": "yes",
        "👎": "no",
        "🤷": "maybe"
    }
    
    if emoji in emoji_to_response:
        logger.info(f"User {user_id} removed {emoji} reaction, checking if it's a vote change")
        
        # If this was a user removing their vote, we don't need to do anything special
        # They will add another reaction if they want to change their vote
        
        # Just make sure all 3 base emoji reactions are still on the message
        try:
            message = await channel.fetch_message(message_id)
            
            # Check which emoji are missing from the message
            existing_emojis = [str(r.emoji) for r in message.reactions]
            
            # Make sure all vote emojis are present
            for vote_emoji in emoji_to_response.keys():
                if vote_emoji not in existing_emojis:
                    logger.info(f"Re-adding missing base emoji {vote_emoji} to message {message_id}")
                    await message.add_reaction(vote_emoji)
                    await asyncio.sleep(0.5)  # Small delay between adding reactions
        except Exception as e:
            logger.error(f"Error ensuring base emojis are present: {e}")
            
        # No DM reminders needed, users can see their status in the embed
        try:
            # Get current Flask status (source of truth) for logging purposes only
            flask_rsvps = await get_flask_rsvps(match_id, team_id)
            current_response = flask_rsvps.get(str(user_id))
            
            if current_response:
                logger.info(f"User {user_id} removed their reaction but their RSVP is still recorded as {current_response}")
        except Exception as e:
            logger.error(f"Error checking RSVP status: {e}")
    
    # With the simplified approach, we don't need to process reaction removal further
    # The on_raw_reaction_add handler will handle any new RSVP choices

async def start_rest_api():
    """
    Starts the FastAPI server using Uvicorn.
    """
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=5001,
        log_level="info",
        loop=bot.loop,          # Use the bot's event loop
        lifespan="off",         # Disable lifespan events
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    # Run the bot in the main thread
    bot.run(bot_token)
