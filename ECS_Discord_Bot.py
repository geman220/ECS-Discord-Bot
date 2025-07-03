﻿# ECS_Discord_Bot.py

from datetime import datetime
import aiohttp
import discord
import asyncio
import os
import logging
import time
import random
import socket
import contextlib
from discord import app_commands
from discord.ext import commands
from common import bot_token, server_id
import uvicorn
from bot_rest_api import app, bot_ready, update_embed_for_message, get_team_id_for_message, poll_task_result, session
import signal
import sys
import traceback
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

class ECSBot(commands.Bot):
    """
    Custom Bot class with improved session management, error handling, and heartbeat monitoring.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = None
        self.api_port = None
        self.last_heartbeat = time.time()
        self.heartbeat_interval = 5  # Check heartbeat every 5 seconds
        self.max_heartbeat_delay = 10  # Maximum allowable delay in seconds
        self.heartbeat_task = None
        self._connection_retry_count = 0
        self._max_connection_retries = 10
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("Setting up bot...")
        
        # Create a session for the bot to use
        self.session = aiohttp.ClientSession()
        
        # Start heartbeat monitoring
        self.heartbeat_task = self.loop.create_task(self._monitor_heartbeat())
        
        logger.info("Bot setup completed")
    
    async def _monitor_heartbeat(self):
        """
        Monitor the bot's heartbeat to detect and recover from blocks.
        This runs in a separate task and won't block the main thread.
        """
        print("Starting heartbeat monitoring task")  # Use print instead of logger to avoid potential deadlock
        
        while not self.is_closed():
            try:
                # Check how long since last heartbeat
                current_time = time.time()
                time_since_last_heartbeat = current_time - self.last_heartbeat
                
                if time_since_last_heartbeat > self.max_heartbeat_delay:
                    # Use print instead of logger to avoid potential deadlock
                    print(f"WARNING: Heartbeat delayed by {time_since_last_heartbeat:.2f}s, exceeds max delay of {self.max_heartbeat_delay}s")
                    
                    # Only get basic task info to avoid potential deadlocks
                    try:
                        task_count = len([t for t in asyncio.all_tasks(self.loop) if not t.done()])
                        print(f"Currently {task_count} active tasks in the event loop")
                    except Exception as task_err:
                        print(f"Error counting tasks: {task_err}")
                    
                    # Check if we need to force reconnection due to extended delay
                    if time_since_last_heartbeat > self.max_heartbeat_delay * 3:
                        print(f"CRITICAL: Heartbeat delayed by {time_since_last_heartbeat:.2f}s - forcing reconnection")
                        # Schedule a reconnection task
                        self.loop.create_task(self._force_reconnect())
                
                # Update the heartbeat time
                self.last_heartbeat = current_time
                
                # Sleep for the monitoring interval - use shorter interval for better responsiveness
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                print("Heartbeat monitoring task cancelled")
                break
            except Exception as e:
                print(f"Error in heartbeat monitoring: {e}")
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _force_reconnect(self):
        """Force a reconnection to Discord when heartbeat fails repeatedly."""
        try:
            print("Forcing reconnection to Discord...")
            # Close the websocket connection to trigger a reconnect
            if hasattr(self, 'ws') and self.ws:
                await self.ws.close(code=1000)
                print("Websocket closed, reconnection should begin shortly")
            
            # If that doesn't work, try to reset the internal state
            if hasattr(self, '_connection'):
                if hasattr(self._connection, 'clear'):
                    self._connection.clear()
                    print("Cleared connection state for reconnection")
        except Exception as e:
            print(f"Error during forced reconnection: {e}")
    
    async def on_socket_response(self, msg):
        """
        Called whenever a message is received from the Discord gateway.
        Used to track heartbeat status.
        """
        # Update the last heartbeat time to indicate we're still receiving messages
        self.last_heartbeat = time.time()
        
        # Pass to the parent method
        await super().on_socket_response(msg)
    
    async def close(self):
        """Called when the bot is shutting down"""
        logger.info("Closing bot and cleaning up resources...")
        
        # Cancel the heartbeat monitoring task
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Close the session to prevent resource leaks
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("Bot session closed")
        
        # Call the parent's close method
        await super().close()
        logger.info("Bot closed successfully")

bot = ECSBot(command_prefix="!", intents=intents)

# Removed separate managed_message_ids set; using bot_state instead

VERIFY_CHANNEL_IDS = {1036026916282585228, 1072279143145799740}

async def load_managed_message_ids():
    global session  # Use the global session variable
    retry_count = 0
    max_retries = 3
    retry_delay = 1

    while retry_count < max_retries:
        # Ensure the session is initialized
        if session is None or session.closed:
            logger.warning("Session is not initialized or closed. Creating new session.")
            try:
                if session and not session.closed:
                    await session.close()
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            except Exception as e:
                logger.error(f"Failed to create session: {e}")
                await asyncio.sleep(retry_delay)
                retry_count += 1
                retry_delay *= 2  # Exponential backoff
                continue

        try:
            # Use timeout context to prevent hanging
            timeout_ctx = aiohttp.ClientTimeout(total=10)
            async with session.get(
                f"{WEBUI_API_URL}/get_scheduled_messages", 
                timeout=timeout_ctx
            ) as response:
                if response.status == 200:
                    try:
                        data = await asyncio.wait_for(response.json(), timeout=5.0)
                        
                        # Count successful additions
                        added_count = 0
                        
                        for msg in data:
                            # Extract match details
                            match_date = msg.get('match_date')
                            home_team_id = msg.get('home_team_id')
                            away_team_id = msg.get('away_team_id')
                            
                            # Add home message ID with metadata
                            if msg.get('home_message_id'):
                                try:
                                    bot_state.add_managed_message_id(
                                        int(msg['home_message_id']),
                                        match_date=match_date,
                                        team_id=home_team_id
                                    )
                                    added_count += 1
                                except (ValueError, TypeError) as e:
                                    logger.error(f"Invalid home message ID: {msg.get('home_message_id')}, error: {e}")
                            
                            # Add away message ID with metadata
                            if msg.get('away_message_id'):
                                try:
                                    bot_state.add_managed_message_id(
                                        int(msg['away_message_id']),
                                        match_date=match_date,
                                        team_id=away_team_id
                                    )
                                    added_count += 1
                                except (ValueError, TypeError) as e:
                                    logger.error(f"Invalid away message ID: {msg.get('away_message_id')}, error: {e}")
                        
                        # Log stats about managed messages
                        all_messages = len(bot_state.get_managed_message_ids())
                        active_messages = len(bot_state.get_managed_message_ids(days_limit=14))
                        
                        logger.info(f"Loaded {added_count} new managed message IDs. Total: {all_messages} ({active_messages} active within 14 days)")
                        
                        # Also load active poll messages
                        await load_poll_message_ids()
                        
                        return  # Success, exit the retry loop
                    except asyncio.TimeoutError:
                        logger.error("Timed out parsing message data")
                    except Exception as e:
                        logger.error(f"Error processing message data: {e}")
                else:
                    logger.error(f"Failed to fetch scheduled messages: {response.status}")
                    try:
                        error_text = await asyncio.wait_for(response.text(), timeout=2.0)
                        logger.error(f"Error response: {error_text[:200]}")
                    except:
                        logger.error("Could not read error response")
            
            # If we got here, we failed but didn't raise an exception
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Error fetching scheduled messages (attempt {retry_count+1}/{max_retries}): {e}")
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                
        except Exception as e:
            logger.error(f"Unexpected error loading message IDs: {e}", exc_info=True)
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
    
    # If we exhaust all retries
    logger.error(f"Failed to load message IDs after {max_retries} attempts")


async def load_poll_message_ids():
    """
    Load active poll message IDs from the Flask app.
    """
    try:
        # Clear existing poll messages to avoid stale data
        bot_state.poll_messages.clear()
        
        # Get active polls from Flask
        async with session.get(f"{WEBUI_API_URL}/api/get_active_poll_messages") as response:
            if response.status == 200:
                data = await response.json()
                poll_count = 0
                
                for poll_msg in data:
                    message_id = poll_msg.get('message_id')
                    if message_id:
                        try:
                            message_id_int = int(message_id)
                            # Track in bot state
                            bot_state.add_managed_message_id(
                                message_id_int,
                                match_date=None,  # Polls don't have match dates
                                team_id=poll_msg.get('team_id')
                            )
                            # Store poll metadata
                            bot_state.poll_messages[message_id_int] = {
                                'poll_id': poll_msg.get('poll_id'),
                                'team_id': poll_msg.get('team_id'),
                                'channel_id': poll_msg.get('channel_id')
                            }
                            poll_count += 1
                            logger.debug(f"Added poll message {message_id_int} to both managed messages and poll_messages")
                        except (ValueError, TypeError) as e:
                            logger.error(f"Invalid poll message ID: {message_id}, error: {e}")
                
                logger.info(f"Loaded {poll_count} active poll message IDs")
            else:
                logger.warning(f"Failed to fetch active poll messages: {response.status}")
                
    except Exception as e:
        logger.error(f"Error loading poll message IDs: {e}")


async def periodic_sync():
    """
    Periodically synchronizes managed_message_ids with the web app.
    """
    consecutive_failures = 0
    while True:
        try:
            # Add timeout to prevent blocking
            await asyncio.wait_for(load_managed_message_ids(), timeout=30.0)
            consecutive_failures = 0  # Reset on success
            logger.debug("Periodic sync completed successfully")
        except asyncio.TimeoutError:
            consecutive_failures += 1
            logger.error(f"Periodic sync timed out after 30 seconds (failure #{consecutive_failures})")
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"Periodic sync failed (failure #{consecutive_failures}): {e}", exc_info=True)
        
        # Use exponential backoff for failures
        sleep_time = 300  # Default: 5 minutes
        if consecutive_failures > 0:
            # Increase delay when having issues (min 60s, max 15 minutes)
            sleep_time = min(max(60, 60 * (2 ** (consecutive_failures - 1))), 900)
            logger.info(f"Using adjusted sync interval of {sleep_time} seconds due to failures")
        
        # Sleep in smaller chunks to be responsive
        chunk_size = 30  # 30 second chunks
        for _ in range(sleep_time // chunk_size):
            if bot.is_closed():
                logger.info("Bot is closed, breaking out of periodic sync")
                return
            await asyncio.sleep(chunk_size)
        
        # Sleep any remaining time
        if sleep_time % chunk_size > 0 and not bot.is_closed():
            await asyncio.sleep(sleep_time % chunk_size)
        
async def full_rsvp_sync(force_sync=False):
    """
    Performs a full synchronization between Discord reactions/embeds and Flask RSVPs.
    This ensures consistency even after bot downtime or network failures.
    
    Args:
        force_sync: If True, update all messages even if no discrepancy detected.
    """
    logger.info(f"Starting full RSVP synchronization (force_sync={force_sync}) - processing only matches from last 7 days")
    message_ids = list(bot_state.get_managed_message_ids())
    synced_count = 0
    failed_count = 0
    
    # Limit concurrent operations to avoid overloading Discord API or causing deadlocks
    # Process messages in batches with semaphores to control concurrency
    semaphore = asyncio.Semaphore(3)  # Process up to 3 messages concurrently
    
    async def process_message(message_id):
        nonlocal synced_count, failed_count
        
        # Using semaphore to limit concurrent processing
        async with semaphore:
            try:
                # For each managed message, get its channel ID with timeout
                try:
                    match_data = await asyncio.wait_for(
                        get_message_channel_from_web_ui(message_id),
                        timeout=10.0
                    )
                    if not match_data or 'channel_id' not in match_data:
                        logger.warning(f"Could not find channel ID for message {message_id}")
                        return
                        
                    # Skip old matches (older than 7 days) to avoid processing massive backlogs
                    if not match_data.get('is_recent_match', True):
                        logger.debug(f"Skipping old match (date: {match_data.get('match_date')}) for message {message_id}")
                        return
                except asyncio.TimeoutError:
                    logger.error(f"Timeout getting channel for message {message_id}")
                    failed_count += 1
                    return
                    
                channel_id = int(match_data['channel_id'])
                match_id = match_data.get('match_id')
                team_id = match_data.get('team_id')
                
                if not match_id or not team_id:
                    logger.warning(f"Missing match_id or team_id for message {message_id}")
                    return
                    
                # Get Discord reactions for this message
                discord_rsvps = await get_message_reactions(channel_id, message_id)
                
                # Get Flask RSVPs for the match
                flask_rsvps = await get_flask_rsvps(match_id, team_id)
                
                if not flask_rsvps:
                    logger.warning(f"Could not fetch RSVPs from Flask for match {match_id}")
                    return
                    
                # Add a short yield to prevent blocking the event loop for too long
                await asyncio.sleep(0.1)
                
                # Compare and reconcile differences
                reconciliation_needed = await reconcile_rsvps(
                    match_id, team_id, discord_rsvps, flask_rsvps, channel_id, message_id, force_sync
                )
                
                # Add another short yield
                await asyncio.sleep(0.1)
                
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
                logger.error(f"Error syncing message {message_id}: {str(e)}")
                failed_count += 1
    
    # Create tasks for all messages and wait for them to complete with a timeout
    tasks = [process_message(message_id) for message_id in message_ids]
    
    # Break the sync operation into smaller chunks with yields to prevent blocking
    # This way even if RSVP sync takes a long time, it won't block the heartbeat
    for i in range(0, len(tasks), 5):
        chunk = tasks[i:i+5]
        try:
            # Process each chunk with a timeout to prevent blocking too long
            await asyncio.gather(*chunk, return_exceptions=True)
            # Short yield after each chunk
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error processing chunk {i//5}: {e}")
    
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
                    # Fetch user object with timeout
                    try:
                        user = await asyncio.wait_for(bot.fetch_user(user_id), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Timed out fetching user {user_id}, skipping")
                        continue
                    except Exception as e:
                        logger.error(f"Could not fetch user {user_id}: {str(e)}")
                        continue
                    
                    # Remove all existing reactions from this user with timeout
                    for reaction in message.reactions:
                        if str(reaction.emoji) in reaction_emoji.values():
                            try:
                                # Fetch users with timeout
                                users = []
                                users_collector = reaction.users()
                                try:
                                    # Get up to 10 users to avoid long operations
                                    users = await asyncio.wait_for(users_collector.flatten(limit=10), timeout=5.0)
                                except asyncio.TimeoutError:
                                    logger.warning(f"Timed out collecting users for reaction {reaction.emoji}")
                                
                                if user in users:
                                    await asyncio.wait_for(reaction.remove(user), timeout=5.0)
                                    logger.debug(f"Removed reaction {reaction.emoji} from user {user_id}")
                            except (asyncio.TimeoutError, Exception) as e:
                                logger.warning(f"Timed out processing reactions for {user_id}: {str(e)}")
                    
                    # Add the correct reaction with timeout
                    try:
                        await asyncio.wait_for(message.add_reaction(emoji), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Timed out adding reaction {emoji} for user {user_id}")
                        continue
                    
                    # Only check bot reaction status with timeout if necessary
                    bot_emoji_added = False
                    for reaction in message.reactions:
                        if str(reaction.emoji) == emoji:
                            try:
                                # Use limited collection with timeout
                                users = await asyncio.wait_for(reaction.users().flatten(limit=5), timeout=5.0)
                                for u in users:
                                    if u.id == bot.user.id:
                                        bot_emoji_added = True
                                        break
                            except (asyncio.TimeoutError, Exception):
                                # Continue even if we couldn't check
                                pass
                    
                    if not bot_emoji_added:
                        try:
                            await asyncio.wait_for(message.add_reaction(emoji), timeout=5.0)
                        except:
                            logger.warning(f"Timed out adding bot reaction {emoji}")
                    
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
    Schedules periodic full RSVP synchronization with improved error handling
    and shorter intervals to prevent blocking the main event loop.
    """
    # Jitter the start time a bit to avoid synchronizing with other periodic tasks
    await asyncio.sleep(random.randint(5, 30))
    
    # Track continuous failures to implement exponential backoff
    consecutive_failures = 0
    
    while True:
        try:
            # Use shorter sleep intervals with periodic checks to be more responsive
            # to cancellation and avoid blocking the event loop for too long
            hours_until_next_sync = 6
            
            # Adjust interval based on failure count (backoff strategy)
            if consecutive_failures > 0:
                hours_until_next_sync = min(1 * (2 ** (consecutive_failures - 1)), 6)
                logger.info(f"Using shortened sync interval of {hours_until_next_sync} hours due to previous failures")
            
            logger.info("Starting scheduled full RSVP synchronization...")
            
            # Use asyncio.wait_for to add a timeout to the sync operation
            try:
                await asyncio.wait_for(
                    full_rsvp_sync(),
                    timeout=10 * 60  # 10 minute timeout
                )
                logger.info("Completed scheduled full RSVP synchronization")
                # Reset failure counter on success
                consecutive_failures = 0
            except asyncio.TimeoutError:
                logger.error("RSVP sync timed out after 10 minutes")
                consecutive_failures += 1
            
        except asyncio.CancelledError:
            logger.info("Periodic sync task cancelled")
            break
        except Exception as e:
            logger.error(f"Error during scheduled full RSVP sync: {str(e)}")
            consecutive_failures += 1
        
        # Sleep in smaller intervals to be responsive to cancellation
        try:
            seconds_to_sleep = int(hours_until_next_sync * 60 * 60)
            # Sleep in 5-minute chunks
            chunk_size = 5 * 60
            chunks = seconds_to_sleep // chunk_size
            
            for _ in range(chunks):
                # Check if we should continue sleeping or break early
                if bot.is_closed():
                    logger.info("Bot is closed, breaking out of periodic sync sleep")
                    break
                    
                await asyncio.sleep(chunk_size)
                
            # Sleep any remaining time
            remaining = seconds_to_sleep % chunk_size
            if remaining > 0 and not bot.is_closed():
                await asyncio.sleep(remaining)
                
        except asyncio.CancelledError:
            logger.info("Periodic sync sleep cancelled")
            break
        except Exception as e:
            logger.error(f"Error during sync sleep: {e}")
            # Use a short fallback sleep to avoid tight looping
            await asyncio.sleep(300)

class RsvpSemaphore:
    """
    Semaphore to limit concurrent RSVP operations per match.
    This prevents too many operations happening at once for the same match.
    """
    def __init__(self):
        self.semaphores = {}  # match_id -> semaphore
        
    def get_semaphore(self, match_id, max_concurrent=2):
        """Get a semaphore for the given match ID, creating one if it doesn't exist."""
        if match_id not in self.semaphores:
            self.semaphores[match_id] = asyncio.Semaphore(max_concurrent)
        return self.semaphores[match_id]
    
    def release_semaphore(self, match_id):
        """Release the semaphore for a match ID if it exists."""
        if match_id in self.semaphores:
            try:
                self.semaphores[match_id].release()
            except ValueError:  # Released too many times
                pass
    
    def cleanup(self, match_id=None):
        """Remove semaphores to free memory."""
        if match_id:
            if match_id in self.semaphores:
                del self.semaphores[match_id]
        else:
            self.semaphores.clear()

# Create a global semaphore manager
rsvp_semaphore = RsvpSemaphore()

async def sync_rsvp_with_web_ui(match_id, discord_id, response):
    """
    Syncs RSVP data with the web UI by sending a POST request.
    Uses a semaphore to limit concurrent operations per match.
    Includes retries with exponential backoff.
    """
    logger.debug(f"Syncing RSVP with Web UI for match {match_id}, user {discord_id}, response {response}")
    api_url = f"{WEBUI_API_URL}/update_availability_from_discord"
    data = {
        "match_id": match_id,
        "discord_id": discord_id,
        "response": response,
        "responded_at": datetime.utcnow().isoformat()
    }

    # Get the semaphore for this match
    semaphore = rsvp_semaphore.get_semaphore(match_id)
    
    # Use the semaphore to limit concurrent operations
    async with semaphore:
        # Try with retries and exponential backoff
        max_retries = 3
        base_delay = 1  # Start with 1 second delay
        
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as local_session:  # Use a new session for each attempt
                    async with local_session.post(api_url, json=data, timeout=10) as resp:
                        resp_text = await resp.text()
                        if resp.status == 200:
                            logger.info(f"RSVP updated successfully for match {match_id} in Web UI. Response: {resp_text}")
                            return True
                        elif resp.status == 429:  # Rate limited
                            retry_after = float(resp.headers.get('Retry-After', base_delay * (2 ** attempt)))
                            logger.warning(f"Rate limited when updating RSVP. Retrying after {retry_after}s (attempt {attempt+1}/{max_retries})")
                            await asyncio.sleep(retry_after)
                        else:
                            logger.error(f"Failed to update RSVP in Web UI: {resp.status}, {resp_text}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(base_delay * (2 ** attempt))
            except aiohttp.ClientError as e:
                logger.error(f"Failed to sync RSVP with Web UI (attempt {attempt+1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"Unexpected error syncing RSVP with Web UI: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
        
        logger.error(f"Failed to update RSVP after {max_retries} attempts for match {match_id}, user {discord_id}")
        return False

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
    Has retry logic for failed connections.
    """
    # Try localhost first, then try the container name
    api_urls = [
        f"http://localhost:5001/api/update_availability_embed/{match_id}",
        f"http://127.0.0.1:5001/api/update_availability_embed/{match_id}",
        f"http://discord-bot:5001/api/update_availability_embed/{match_id}"
    ]
    
    for api_url in api_urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, timeout=10) as response:
                    if response.status == 200:
                        logger.info(f"Discord embed updated for match {match_id}")
                        return True
                    else:
                        logger.warning(f"Failed to update Discord embed using {api_url}. Status: {response.status}")
        except aiohttp.ClientError as e:
            logger.warning(f"Connection error updating Discord embed using {api_url}: {str(e)}")
        except Exception as e:
            logger.warning(f"Unexpected error while updating Discord embed using {api_url}: {str(e)}")
    
    # If we got here, all attempts failed
    logger.error(f"All attempts to update Discord embed for match {match_id} failed")
    return False

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
        'help_commands',
        'clearchat_commands'
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

    # Create a watchdog task to monitor bot health and force restart if needed
    asyncio.create_task(watchdog_task())
    
    try:
        logger.info("Loading managed message IDs from the web app...")
        await load_managed_message_ids()
        logger.info("Managed message IDs loaded successfully.")

        logger.info("Loading cogs/extensions...")
        await load_cogs()
        logger.info("Cogs/extensions loaded successfully.")

        logger.info("Starting periodic synchronization task...")
        periodic_sync_task = asyncio.create_task(periodic_sync())
        # Store task reference to prevent garbage collection
        bot._periodic_sync_task = periodic_sync_task

        logger.info("Setting bot instance in shared_states...")
        set_bot_instance(bot)

        logger.info("Setting bot_ready event...")
        bot_ready.set()

        logger.info("Starting periodic check task...")
        periodic_check_task = asyncio.create_task(periodic_check())
        # Store task reference to prevent garbage collection
        bot._periodic_check_task = periodic_check_task
        
        # Start the full RSVP synchronization task, but don't block on_ready
        logger.info("Performing initial full RSVP synchronization...")
        full_sync_task = asyncio.create_task(full_rsvp_sync(force_sync=True))
        # Store task reference to prevent garbage collection
        bot._full_sync_task = full_sync_task
        
        # Schedule periodic full RSVP synchronization
        logger.info("Starting periodic full RSVP synchronization task...")
        schedule_sync_task = asyncio.create_task(schedule_periodic_sync())
        # Store task reference to prevent garbage collection
        bot._schedule_sync_task = schedule_sync_task

        # Start the REST API server as a task in the bot's event loop
        logger.info("Starting REST API server...")
        api_task = bot.loop.create_task(start_rest_api())
        # Store task reference to prevent garbage collection
        bot._api_task = api_task

        logger.info("Bot initialization completed successfully.")
    except Exception as e:
        logger.exception(f"Error during bot initialization: {e}")
        # If critical initialization fails, schedule a restart after a delay
        asyncio.create_task(delayed_restart(60))

    logger.info("Bot is fully ready.")

async def watchdog_task():
    """
    A watchdog task that monitors the bot's health and forces restart if needed.
    This provides a failsafe against deadlocks and other issues.
    """
    MAX_CONSECUTIVE_FAILURES = 3
    consecutive_failures = 0
    
    # Wait for bot to be fully ready before starting watchdog
    await asyncio.sleep(60)
    
    while not bot.is_closed():
        try:
            # Check heartbeat health
            current_time = time.time()
            time_since_last_heartbeat = current_time - bot.last_heartbeat
            
            if time_since_last_heartbeat > bot.max_heartbeat_delay * 5:
                # Critical situation - heartbeat extremely delayed
                print(f"CRITICAL: Heartbeat delayed by {time_since_last_heartbeat:.2f}s - initiating emergency restart")
                consecutive_failures += 1
                
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"EMERGENCY: {consecutive_failures} consecutive heartbeat failures - forcing process exit")
                    # Force exit the process so Docker can restart cleanly
                    os._exit(1)
                
                # Try to force a reconnection first
                await bot._force_reconnect()
            else:
                # Reset counter if things are working
                consecutive_failures = 0
            
            # Check task health
            try:
                task_count = len([t for t in asyncio.all_tasks() if not t.done()])
                if task_count > 100:  # Arbitrary large number that might indicate a leak
                    print(f"WARNING: Unusually high number of tasks: {task_count}")
            except Exception:
                pass
                
        except Exception as e:
            print(f"Error in watchdog task: {e}")
        
        # Sleep between checks - shorter interval for more responsive monitoring
        await asyncio.sleep(30)

async def delayed_restart(delay_seconds=60):
    """Schedule a clean restart after a delay."""
    logger.warning(f"Scheduling restart in {delay_seconds} seconds")
    await asyncio.sleep(delay_seconds)
    logger.warning("Initiating clean restart")
    # Force exit the process so Docker can restart cleanly
    os._exit(0)

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

async def process_poll_reaction(message_id, emoji, user_id, channel_id, payload):
    """
    Process a reaction on a poll message.
    """
    try:
        # Get poll metadata
        poll_info = bot_state.poll_messages.get(message_id)
        if not poll_info:
            logger.error(f"Poll info not found for message {message_id}")
            return
        
        poll_id = poll_info['poll_id']
        team_id = poll_info['team_id']
        
        # Map emoji to response
        emoji_to_response = {
            "✅": "yes",
            "❌": "no",
            "⚠️": "maybe"
        }
        
        response = emoji_to_response.get(emoji)
        if not response:
            # Remove invalid reactions
            try:
                channel = bot.get_channel(channel_id)
                if channel:
                    message = await channel.fetch_message(message_id)
                    user = await bot.fetch_user(user_id)
                    await message.remove_reaction(payload.emoji, user)
                    logger.info(f"Removed invalid poll reaction {emoji} from user {user_id}")
            except Exception as e:
                logger.error(f"Error removing invalid poll reaction: {e}")
            return
        
        # Get user information
        user = bot.get_user(user_id)
        if not user:
            try:
                user = await bot.fetch_user(user_id)
            except Exception as e:
                logger.error(f"Could not fetch user {user_id}: {e}")
                return
        
        logger.info(f"User {user_id} ({user.name}) reacted with {emoji} ({response}) to poll {poll_id}")
        
        # Send the poll response to the Flask app
        try:
            api_url = f"{WEBUI_API_URL}/update_poll_response_from_discord"
            data = {
                "poll_id": poll_id,
                "discord_id": str(user_id),
                "response": response,
                "responded_at": datetime.utcnow().isoformat()
            }
            
            async with session.post(api_url, json=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    logger.info(f"Poll response recorded successfully: {result}")
                    
                    # Remove other reactions from the same user
                    try:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            message = await channel.fetch_message(message_id)
                            
                            # Remove other emoji reactions from this user
                            for other_emoji, _ in emoji_to_response.items():
                                if other_emoji != emoji:
                                    try:
                                        await message.remove_reaction(other_emoji, user)
                                    except discord.errors.NotFound:
                                        # Reaction doesn't exist, that's fine
                                        pass
                                    except Exception as e:
                                        logger.debug(f"Could not remove reaction {other_emoji}: {e}")
                    except Exception as e:
                        logger.error(f"Error managing user reactions: {e}")
                        
                elif resp.status == 403:
                    # User not authorized to vote (not on team)
                    error_data = await resp.json()
                    logger.warning(f"User {user_id} not authorized to vote: {error_data.get('error')}")
                    
                    # Remove the reaction
                    try:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            message = await channel.fetch_message(message_id)
                            await message.remove_reaction(payload.emoji, user)
                    except Exception as e:
                        logger.error(f"Error removing unauthorized reaction: {e}")
                    
                    # Send DM to user
                    try:
                        await user.send(
                            "You cannot vote in this poll because you are not a member of this team. "
                            "Only team members can participate in team polls."
                        )
                    except discord.Forbidden:
                        logger.debug(f"Could not send DM to user {user_id}")
                        
                else:
                    error_text = await resp.text()
                    logger.error(f"Failed to record poll response: {resp.status} - {error_text}")
                    
        except Exception as e:
            logger.error(f"Error sending poll response to Flask: {e}")
            
    except Exception as e:
        logger.error(f"Error processing poll reaction: {e}", exc_info=True)

@bot.event
async def process_reaction_with_rate_limit(message_id, emoji, user_id, channel_id, payload, retry_count=0):
    """
    Process a reaction with rate limit handling.
    This function will retry with exponential backoff if rate limits are hit.
    """
    MAX_RETRIES = 5
    BASE_DELAY = 1  # Base delay in seconds
    
    try:
        return await process_reaction(message_id, emoji, user_id, channel_id, payload)
    except discord.errors.HTTPException as e:
        if e.status == 429 and retry_count < MAX_RETRIES:  # Rate limited
            retry_after = e.retry_after if hasattr(e, 'retry_after') else BASE_DELAY * (2 ** retry_count)
            logger.warning(f"Rate limited when processing reaction. Retrying after {retry_after:.2f}s (attempt {retry_count+1}/{MAX_RETRIES})")
            await asyncio.sleep(retry_after)
            return await process_reaction_with_rate_limit(message_id, emoji, user_id, channel_id, payload, retry_count + 1)
        else:
            raise  # Re-raise if not a rate limit or we've exceeded retries

async def process_reaction(message_id, emoji, user_id, channel_id, payload):
    """
    Core logic for processing a reaction, separated for better rate limit handling.
    """
    logger.debug(f"Processing reaction for message {message_id}, poll_messages has {len(bot_state.poll_messages)} entries")
    
    # Check if this is a poll message first
    if message_id in bot_state.poll_messages:
        logger.info(f"Processing poll reaction on message {message_id}")
        await process_poll_reaction(message_id, emoji, user_id, channel_id, payload)
        return
    
    # Only look at relevant messages (within 14 days of today)
    active_message_ids = bot_state.get_managed_message_ids(days_limit=14)
    if message_id not in active_message_ids:
        # Check if this might be a poll message that wasn't properly loaded
        all_managed = bot_state.get_managed_message_ids()
        is_in_all_managed = message_id in all_managed
        poll_count = len(bot_state.poll_messages)
        
        logger.debug(f"Message ID {message_id} is not an active managed message. Ignoring reaction. "
                    f"(In all managed: {is_in_all_managed}, Poll messages count: {poll_count})")
        
        # If it's in managed messages but not in poll_messages, try to reload poll messages
        if is_in_all_managed and poll_count > 0:
            logger.warning(f"Message {message_id} is managed but not in poll_messages. Attempting to reload poll messages.")
            await load_poll_message_ids()
            
            # Try again after reloading
            if message_id in bot_state.poll_messages:
                logger.info(f"Found message {message_id} in poll_messages after reload. Processing as poll.")
                await process_poll_reaction(message_id, emoji, user_id, channel_id, payload)
                return
        
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
                # Use a non-blocking task for removing the reaction
                asyncio.create_task(
                    remove_reaction_safely(message, payload.emoji, user, 
                                          f"Removed reaction {emoji} from user {user_id} on message {message_id} (not on team)")
                )
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
            # Process RSVP in a background task to avoid blocking
            asyncio.create_task(
                process_rsvp_background(match_id, user_id, response, channel_id, message_id, payload, user, emoji, emoji_to_response)
            )
            
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
            # Use a non-blocking task for removing the reaction
            asyncio.create_task(
                remove_reaction_safely(message, payload.emoji, user, 
                                      f"Removed invalid reaction {emoji} from user {user_id}")
            )
        except Exception as e:
            logger.error(f"Could not remove invalid reaction: {e}")

async def process_rsvp_background(match_id, user_id, response, channel_id, message_id, payload, user, emoji, emoji_to_response):
    """
    Process an RSVP in the background to avoid blocking the main event loop.
    """
    try:
        # Update the RSVP in the web UI
        await sync_rsvp_with_web_ui(match_id, user_id, response)
        
        # Update the Discord embed to reflect the change (use a retry mechanism)
        success = await update_discord_embed(match_id)
        if not success:
            logger.warning(f"Could not update Discord embed for match {match_id}. Will retry later.")
            # Schedule a retry in the background
            asyncio.create_task(retry_update_embed(match_id))
        
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
        
        # Remove this reaction, but do it in a background task to avoid blocking
        asyncio.create_task(
            remove_reaction_safely(message, payload.emoji, user, 
                                  f"Removed user {user_id}'s {emoji} reaction after processing RSVP")
        )
        
        # Also remove any other reactions this user might have (in background tasks)
        for reaction in message.reactions:
            if str(reaction.emoji) in emoji_to_response.keys() and str(reaction.emoji) != emoji:
                users = [u async for u in reaction.users()]
                if user in users:
                    asyncio.create_task(
                        remove_reaction_safely(message, reaction.emoji, user, 
                                              f"Removed user {user_id}'s other reaction: {reaction.emoji}")
                    )
        
        # No DM notification needed, users can see their status in the embed
        logger.info(f"RSVP for user {user_id} recorded as {response}, visible in the match embed")
    except Exception as e:
        logger.error(f"Error in background RSVP processing for user {user_id}: {str(e)}", exc_info=True)

async def retry_update_embed(match_id, attempt=0, max_attempts=3, delay=5):
    """
    Retry updating the Discord embed with exponential backoff.
    """
    if attempt >= max_attempts:
        logger.error(f"Failed to update Discord embed for match {match_id} after {max_attempts} attempts.")
        return
    
    # Wait with exponential backoff
    await asyncio.sleep(delay * (2 ** attempt))
    
    try:
        success = await update_discord_embed(match_id)
        if success:
            logger.info(f"Successfully updated Discord embed for match {match_id} on retry attempt {attempt+1}")
        else:
            # Schedule another retry
            logger.warning(f"Discord embed update retry {attempt+1} failed for match {match_id}")
            await retry_update_embed(match_id, attempt+1, max_attempts, delay)
    except Exception as e:
        logger.error(f"Error during embed update retry: {str(e)}")
        # Still try again
        await retry_update_embed(match_id, attempt+1, max_attempts, delay)

async def remove_reaction_safely(message, emoji, user, log_message=None):
    """
    Remove a reaction with proper rate limit handling and retries.
    This is done in a separate function to be used as a background task.
    """
    max_retries = 3
    base_delay = 1  # Base delay in seconds
    
    for attempt in range(max_retries):
        try:
            await message.remove_reaction(emoji, user)
            if log_message:
                logger.info(log_message)
            return True
        except discord.errors.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = e.retry_after if hasattr(e, 'retry_after') else base_delay * (2 ** attempt)
                logger.warning(f"Rate limited when removing reaction. Retrying after {retry_after:.2f}s (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"HTTP error when removing reaction: {e}")
                return False
        except Exception as e:
            logger.error(f"Error removing reaction: {e}")
            return False
    
    logger.error(f"Failed to remove reaction after {max_retries} attempts")
    return False

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    message_id = payload.message_id
    emoji = str(payload.emoji)
    user_id = payload.user_id
    channel_id = payload.channel_id

    logger.debug(f"Raw reaction added: {emoji} by user: {user_id} for message_id: {message_id}")
    
    # Process the reaction in a background task
    asyncio.create_task(
        process_reaction_with_rate_limit(message_id, emoji, user_id, channel_id, payload)
    )

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

async def process_reaction_removal(message_id, emoji, user_id, channel_id, payload):
    """
    Process a reaction removal in a background task to avoid blocking the main thread.
    """
    try:
        # Check if this is a poll message first
        if hasattr(bot_state, 'poll_messages') and message_id in bot_state.poll_messages:
            logger.info(f"Poll reaction removed on message {message_id}, but no action needed")
            # For polls, we handle everything in the add reaction event
            return
        
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
                
                # Make sure all vote emojis are present (as background tasks)
                for vote_emoji in emoji_to_response.keys():
                    if vote_emoji not in existing_emojis:
                        logger.info(f"Re-adding missing base emoji {vote_emoji} to message {message_id}")
                        # Use a background task for adding reactions to avoid blocking
                        asyncio.create_task(
                            add_reaction_safely(message, vote_emoji, 
                                               f"Added base emoji {vote_emoji} to message {message_id}")
                        )
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
    except Exception as e:
        logger.error(f"Error processing reaction removal: {e}", exc_info=True)

async def add_reaction_safely(message, emoji, log_message=None):
    """
    Add a reaction with proper rate limit handling and retries.
    This is done in a separate function to be used as a background task.
    """
    max_retries = 3
    base_delay = 1  # Base delay in seconds
    
    for attempt in range(max_retries):
        try:
            await message.add_reaction(emoji)
            if log_message:
                logger.info(log_message)
            # Delay a bit to avoid rate limits with multiple reactions
            await asyncio.sleep(0.5)
            return True
        except discord.errors.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = e.retry_after if hasattr(e, 'retry_after') else base_delay * (2 ** attempt)
                logger.warning(f"Rate limited when adding reaction. Retrying after {retry_after:.2f}s (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"HTTP error when adding reaction: {e}")
                return False
        except Exception as e:
            logger.error(f"Error adding reaction: {e}")
            return False
    
    logger.error(f"Failed to add reaction after {max_retries} attempts")
    return False

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return

    message_id = payload.message_id
    emoji = str(payload.emoji)
    user_id = payload.user_id
    channel_id = payload.channel_id
    logger.debug(f"Raw reaction removed: {emoji} by user: {user_id} for message_id: {message_id}")
    
    # Process in a background task to avoid blocking the main event loop
    asyncio.create_task(
        process_reaction_removal(message_id, emoji, user_id, channel_id, payload)
    )

async def start_rest_api():
    """
    Starts the FastAPI server using Uvicorn with improved retry logic and error handling.
    """
    # Try a wider range of ports starting from 5001
    base_port = 5001
    max_retries = 10  # Increased from 3 to have more ports to try
    
    # Add a delay before trying to bind to any port to allow socket cleanup
    await asyncio.sleep(5)
    
    for attempt in range(max_retries):
        port = base_port + attempt
        try:
            logger.info(f"Attempting to start REST API server on port {port}")
            
            # First check if the port is available without actually binding
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('0.0.0.0', port))
            sock.close()
            
            if result == 0:  # Port is in use
                logger.warning(f"Port {port} is already in use (pre-check). Trying next port.")
                continue
                
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                loop=bot.loop,          # Use the bot's event loop
                lifespan="off",         # Disable lifespan events
            )
            server = uvicorn.Server(config)
            
            # Update the URL for update_discord_embed if we're using a non-default port
            if port != 5001:
                global update_discord_embed
                # Save the original function
                original_update_discord_embed = update_discord_embed
                # Create a new function that uses the current port
                async def updated_update_discord_embed(match_id: int):
                    """Updated function using the current port"""
                    # Try multiple URLs for resiliency
                    api_urls = [
                        f"http://localhost:{port}/api/update_availability_embed/{match_id}",
                        f"http://127.0.0.1:{port}/api/update_availability_embed/{match_id}",
                        f"http://discord-bot:{port}/api/update_availability_embed/{match_id}"
                    ]
                    
                    for api_url in api_urls:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.post(api_url, timeout=10) as response:
                                    if response.status == 200:
                                        logger.info(f"Discord embed updated for match {match_id}")
                                        return True
                                    else:
                                        logger.warning(f"Failed to update Discord embed using {api_url}. Status: {response.status}")
                        except aiohttp.ClientError as e:
                            logger.warning(f"Connection error updating Discord embed using {api_url}: {str(e)}")
                        except Exception as e:
                            logger.warning(f"Unexpected error while updating Discord embed using {api_url}: {str(e)}")
                    
                    # If we got here, all attempts failed
                    logger.error(f"All attempts to update Discord embed for match {match_id} failed")
                    return False
                
                # Replace the function
                update_discord_embed = updated_update_discord_embed
                logger.info(f"Updated update_discord_embed function to use port {port}")
            
            # Store the port so other parts of the application can reference it
            bot.api_port = port
            
            # Try to start the server
            try:
                await server.serve()
                return  # If successful, exit the function
            except SystemExit:
                # Uvicorn calls sys.exit() on certain failures, which we want to catch
                logger.error(f"Uvicorn server exited unexpectedly while binding to port {port}")
                # Continue to the next port
                continue
                
        except OSError as e:
            if e.errno == 98:  # Address already in use
                logger.warning(f"Port {port} is already in use. Trying next port.")
                # Add a small delay before trying the next port
                await asyncio.sleep(1)
                continue
            else:
                logger.error(f"Failed to start REST API server with unexpected error: {e}")
                # Try next port instead of returning
                continue
        except Exception as e:
            logger.error(f"Unexpected error when starting API server on port {port}: {e}")
            # Try next port instead of returning
            continue
    
    # If we get here, we've tried all ports and failed
    logger.error(f"Failed to bind to any port between {base_port} and {base_port + max_retries - 1}. API server will not start.")
    logger.warning("Bot will continue running without the API server, which may affect some functionality.")
    # We'll continue running the bot without the API server
    return

async def cleanup():
    """
    Enhanced cleanup function to run when the bot is shutting down.
    Ensures all resources are properly released and handles TCP socket timeouts.
    """
    logger.info("Cleaning up resources...")
    
    # First cancel any running tasks to prevent them from creating new resources
    try:
        # Get all tasks from the current event loop
        pending_tasks = [task for task in asyncio.all_tasks() 
                        if not task.done() and task != asyncio.current_task()]
        
        if pending_tasks:
            logger.info(f"Cancelling {len(pending_tasks)} pending tasks...")
            # Cancel all pending tasks
            for task in pending_tasks:
                task.cancel()
            
            # Wait for all tasks to be cancelled with a timeout
            await asyncio.wait(pending_tasks, timeout=5)
            logger.info("All pending tasks cancelled or timed out.")
    except Exception as e:
        logger.error(f"Error cancelling pending tasks: {e}")
    
    # Close bot session if it exists
    if hasattr(bot, 'session') and bot.session:
        logger.info("Closing bot session...")
        try:
            await bot.session.close()
            logger.info("Bot session closed successfully.")
        except Exception as e:
            logger.error(f"Error closing bot session: {e}")
    
    # Close the shared session if it exists
    if 'session' in globals() and session:
        logger.info("Closing shared session...")
        try:
            await session.close()
            logger.info("Shared session closed successfully.")
        except Exception as e:
            logger.error(f"Error closing shared session: {e}")
    
    # Clean up semaphore resources
    if 'rsvp_semaphore' in globals():
        try:
            logger.info("Cleaning up RSVP semaphores...")
            rsvp_semaphore.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up RSVP semaphores: {e}")
    
    # Release any socket connections explicitly
    try:
        import socket
        # This will help free up any lingering socket connections
        socket.setdefaulttimeout(1)
    except Exception as e:
        logger.error(f"Error setting socket default timeout: {e}")
    
    logger.info("Cleanup completed.")

def signal_handler(sig, frame):
    """
    Signal handler for graceful shutdown.
    Enhanced to better handle cleanup and exit process.
    """
    logger.info(f"Received signal {sig}. Shutting down gracefully...")
    
    # Schedule the cleanup coroutine if we have an event loop
    try:
        # Check if the bot object exists and is connected
        if 'bot' in globals() and hasattr(bot, 'is_closed') and not bot.is_closed():
            logger.info("Closing bot connection...")
            # Create a new event loop if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # If there's no event loop, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            if loop.is_running():
                # Close the bot connection
                loop.create_task(bot.close())
                # Run the cleanup tasks
                loop.create_task(cleanup())
                # Give tasks a chance to complete
                try:
                    loop.run_until_complete(asyncio.sleep(3))
                except Exception as e:
                    logger.error(f"Error waiting for tasks to complete: {e}")
            else:
                # If loop is not running, run cleanup synchronously
                loop.run_until_complete(cleanup())
                loop.run_until_complete(bot.close())
        else:
            logger.info("Bot not connected, running cleanup only...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(cleanup())
            
    except Exception as e:
        logger.error(f"Error during graceful shutdown: {e}")
    
    # Make sure we exit with success status to prevent Docker from restarting unnecessarily
    logger.info("Exiting bot process...")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    # Create flag to track if this is a restart attempt
    import os
    is_restart_attempt = os.environ.get('BOT_RESTART_ATTEMPT', '0')
    
    # On restart attempts, add a delay to ensure port cleanup
    if is_restart_attempt != '0':
        restart_number = int(is_restart_attempt)
        # Exponential backoff for restart delay
        delay_seconds = min(5 * (2 ** restart_number), 60)  # Cap at 60 seconds
        logger.info(f"This is restart attempt #{restart_number}. Waiting {delay_seconds} seconds before starting...")
        import time
        time.sleep(delay_seconds)
    
    # Set the restart attempt for next time
    os.environ['BOT_RESTART_ATTEMPT'] = str(int(is_restart_attempt) + 1)
    
    try:
        # Run the bot in the main thread
        bot.run(bot_token)
    except KeyboardInterrupt:
        logger.info("Bot shutdown via KeyboardInterrupt")
    except ConnectionResetError as e:
        logger.error(f"Connection reset error: {e}")
        logger.info("This is usually a temporary network issue. The bot will restart automatically.")
    except Exception as e:
        logger.critical(f"Unhandled exception caused bot to crash: {e}", exc_info=True)
    finally:
        # Run cleanup synchronously if needed
        try:
            # Reset the restart attempt counter if we're shutting down properly
            if sys.exc_info()[0] is None or sys.exc_info()[0] == KeyboardInterrupt:
                os.environ['BOT_RESTART_ATTEMPT'] = '0'
                logger.info("Reset restart counter - this was a clean shutdown")
            
            loop = asyncio.new_event_loop()
            loop.run_until_complete(cleanup())
            loop.close()
        except Exception as e:
            logger.error(f"Error during final cleanup: {e}")
        
        # Remove any socket files that might be lingering
        try:
            for port in range(5001, 5011):  # Check ports 5001-5010
                socket_file = f"/tmp/uvicorn_{port}.sock"
                if os.path.exists(socket_file):
                    os.remove(socket_file)
                    logger.info(f"Removed socket file: {socket_file}")
        except Exception as e:
            logger.error(f"Error removing socket files: {e}")
            
        logger.info("Bot process terminated.")
