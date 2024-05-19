# ECS_Bot.py

import discord
import asyncio
import os
import logging
from discord import app_commands
from discord.ext import commands
from database import (
    get_db_connection, 
    PREDICTIONS_DB_PATH,
)
from common import (
    bot_token, 
    server_id,
)

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_thread_id_for_match(match_id):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT thread_id FROM match_threads WHERE match_id = ?", (match_id,))
        result = c.fetchone()
        return result[0] if result else None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")

    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT match_id FROM match_schedule WHERE live_updates_active = 1")
        active_matches = c.fetchall()

    for match in active_matches:
        match_id = match[0]
        thread_id = get_thread_id_for_match(match_id)
        thread = bot.get_channel(thread_id)
        match_commands_cog = bot.get_cog("Match Commands")
        if thread and match_commands_cog:
            asyncio.create_task(post_live_updates(match_id, thread, match_commands_cog))
        
    from woocommerce_commands import WooCommerceCommands
    from general_commands import GeneralCommands
    from admin_commands import AdminCommands
    from match_commands import MatchCommands
    from automations import periodic_check
    from match_utils import post_live_updates

    await bot.add_cog(MatchCommands(bot))
    await bot.add_cog(AdminCommands(bot))
    await bot.add_cog(GeneralCommands(bot))
    await bot.add_cog(WooCommerceCommands(bot))
    await bot.tree.sync(guild=discord.Object(id=server_id))

    if os.path.exists("/root/update_channel_id.txt"):
        with open("/root/update_channel_id.txt", "r") as f:
            channel_id = int(f.read())
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send("Update complete. Bot restarted successfully.")
        os.remove("/root/update_channel_id.txt")
        
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
        print(f"Unhandled interaction command error: {error}")
        await interaction.response.send_message(
            "An error occurred while processing the command.", ephemeral=True
        )


bot.run(bot_token)