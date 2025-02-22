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
                    # Add both home and away message IDs
                    if msg.get('home_message_id'):
                        bot_state.add_managed_message_id(int(msg['home_message_id']))
                    if msg.get('away_message_id'):
                        bot_state.add_managed_message_id(int(msg['away_message_id']))
                logger.info(f"Managed message IDs loaded: {bot_state.get_managed_message_ids()}")
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
    """
    logger.debug(f"Updating RSVP for match {match_id}, user {discord_id}, response {response}")
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
            else:
                logger.error(f"Failed to update RSVP: {resp.status}, {resp_text}")
    except aiohttp.ClientError as e:
        logger.error(f"Failed to update RSVP: {str(e)}")

    # After updating the RSVP, update the Discord embed
    await update_discord_embed(match_id)

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

    if message_id not in bot_state.get_managed_message_ids():
        logger.debug(f"Message ID {message_id} is not managed. Ignoring reaction.")
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

        # Notify the user
        try:
            await user.send(f"You can only RSVP for your own team's matches.")
            logger.info(f"Sent DM to user {user_id} regarding RSVP restriction for team {team_id}")
        except discord.Forbidden:
            logger.warning(f"Could not send DM to user {user_id}")
        return

    # Process the RSVP
    emoji_to_response = {
        "👍": "yes",
        "👎": "no",
        "🤷": "maybe"
    }
    response = emoji_to_response.get(emoji, None)
    if response:
        logger.debug(f"Processing RSVP for user {user_id} with response {response}")
        
        # Remove other reactions from the same user
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        for reaction in message.reactions:
            if str(reaction.emoji) in emoji_to_response.keys() and str(reaction.emoji) != emoji:
                await reaction.remove(user)
        
        # Update the RSVP in the web UI
        await sync_rsvp_with_web_ui(match_id, user_id, response)
        
        # Update the Discord embed
        await update_discord_embed(match_id)
    else:
        # Remove invalid reactions
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.remove_reaction(payload.emoji, user)

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

    if message_id not in bot_state.get_managed_message_ids():
        logger.debug(f"Message ID {message_id} is not managed. Ignoring reaction removal.")
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

    user = bot.get_user(user_id)
    if not user:
        logger.error(f"User with ID {user_id} not found.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Channel with ID {channel_id} not found.")
        return

    message = await channel.fetch_message(message_id)
    
    # Check if the user has any other valid reactions
    valid_emojis = ['👍', '👎', '🤷']
    user_reactions = [reaction for reaction in message.reactions if str(reaction.emoji) in valid_emojis]
    
    for reaction in user_reactions:
        users = [user async for user in reaction.users()]
        if user in users and str(reaction.emoji) != emoji:
            logger.debug(f"User {user_id} still has a valid reaction: {reaction.emoji}")
            return  # User still has a valid reaction, so we don't need to update anything

    # If we get here, the user has no valid reactions left
    logger.debug(f"Updating RSVP to 'no_response' for user {user_id}")
    await update_user_rsvp(match_id, user_id, "no_response")

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
