# ECS_Discord_Bot.py

from datetime import datetime
import discord
import asyncio
import os
import logging
import requests
from discord import app_commands
from discord.ext import commands
from database import get_db_connection, PREDICTIONS_DB_PATH
from common import bot_token, server_id
import threading
import uvicorn
from bot_rest_api import app, bot_ready 
from shared_states import bot_ready, bot_state

WEBUI_API_URL = os.getenv("WEBUI_API_URL")

if __name__ == "__main__":
    logging.basicConfig(
        filename='bot.log',
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

# Initialize bot instance
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Shared FastAPI app setup
from bot_rest_api import app, set_bot_instance  # Import the FastAPI app and setter function

def get_match_id_from_message(message_id):
    api_url = f"http://webui:5000/api/get_match_id_from_message/{message_id}"
    response = requests.get(api_url)

    if response.status_code == 200:
        data = response.json()
        return data.get('match_id')
    return None

def get_thread_id_for_match(match_id):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT thread_id FROM match_threads WHERE match_id = ?", (match_id,))
        result = c.fetchone()
        return result[0] if result else None

async def load_cogs():
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

    await bot.tree.sync(guild=discord.Object(id=server_id))
    logger.info(f"Commands registered after syncing: {[cmd.name for cmd in bot.tree.walk_commands()]}")

@bot.event
async def on_ready():
    global bot_ready

    from automations import periodic_check
    from match_utils import post_live_updates
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")

    guild = bot.get_guild(server_id)
    if guild:
        print(f"Connected to guild: {guild.name} (ID: {guild.id})")
    else:
        print(f"Guild with ID {server_id} not found.")
    
    await load_cogs()

    await asyncio.sleep(5)

    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT match_id FROM match_schedule WHERE live_updates_active = 1")
        active_matches = c.fetchall()

    for match in active_matches:
        match_id = match[0]
        thread_id = get_thread_id_for_match(match_id)
        thread = bot.get_channel(thread_id)
        match_commands_cog = bot.get_cog("MatchCommands")
        if thread and match_commands_cog:
            asyncio.create_task(post_live_updates(match_id, thread, match_commands_cog))

    if os.path.exists("/root/update_channel_id.txt"):
        with open("/root/update_channel_id.txt", "r") as f:
            channel_id = int(f.read())
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send("Update complete. Bot restarted successfully.")
        os.remove("/root/update_channel_id.txt")

    # Perform additional setup if necessary
    bot_ready.set()
    set_bot_instance(bot)  # Pass the initialized bot instance to FastAPI
    print("Bot is fully ready.")

    asyncio.create_task(periodic_check(bot))

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
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

# A set to store message IDs that require reaction management
managed_message_ids = set()

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    message_id = reaction.message.id
    channel = reaction.message.channel
    emoji = reaction.emoji

    print(f"Reaction received: {emoji} by user: {user.id} in channel: {channel.id}")

    # Check if this message is in the set of managed messages
    if message_id in bot_state.get_managed_message_ids():
        # Remove any other reactions by the user on the same message
        for react in reaction.message.reactions:
            if react.emoji != emoji:
                try:
                    await reaction.message.remove_reaction(react.emoji, user)
                except discord.errors.HTTPException:
                    pass  # Ignore if the reaction was already removed

        # Get the match ID associated with this message
        match_id = get_match_id_from_message(message_id)
        if not match_id:
            print(f"No match found for message ID: {message_id}")
            return

        # Map the emoji to an availability status
        status = None
        if emoji == '\U0001F44D':
            status = 'yes'
        elif emoji == '\U0001F44E':
            status = 'no'
        elif emoji == '\U0001F937':
            status = 'maybe'

        if status:
            # Send a POST request to your web UI's API to update availability
            api_url = f"{WEBUI_API_URL}/update_availability"
            payload = {
                'match_id': match_id,
                'discord_id': str(user.id),
                'response': status,
                'responded_at': datetime.utcnow().isoformat()
            }
            response = requests.post(api_url, json=payload)

            if response.status_code == 200:
                print(f"Availability updated successfully for user {user.id} with status {status}.")
            else:
                print(f"Failed to update availability: {response.text}")

@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        return
    
    message_id = reaction.message.id
    print(f"Reaction removed by user: {user.id}")

    # Check if this message is in the set of managed messages
    if message_id in bot_state.get_managed_message_ids():
        # Get the match ID associated with this message
        match_id = get_match_id_from_message(message_id)
        if not match_id:
            print(f"No match found for message ID: {message_id}")
            return

        # Check if the user has any other reactions left on this message
        has_other_reactions = False
        for react in reaction.message.reactions:
            async for reacting_user in react.users():
                if reacting_user == user:
                    has_other_reactions = True
                    break
            if has_other_reactions:
                break

        # If the user has no other reactions, set their status to "no_response"
        if not has_other_reactions:
            api_url = f"{WEBUI_API_URL}/update_availability"
            payload = {
                'match_id': match_id,
                'discord_id': str(user.id),
                'response': 'no_response',
                'responded_at': datetime.utcnow().isoformat()
            }
            response = requests.post(api_url, json=payload)
            
            if response.status_code == 200:
                print(f"Availability updated successfully to no response for user {user.id}.")
            else:
                print(f"Failed to update availability: {response.text}")

async def start_fastapi():
    config = uvicorn.Config(app, host="0.0.0.0", port=5001, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(
        start_fastapi(),
        bot.start(bot_token)
    )

if __name__ == "__main__":
    asyncio.run(main())