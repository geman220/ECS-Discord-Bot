# ECS_Bot.py

import discord
from discord import app_commands
from discord.ext import commands
import os
from common import bot_token, server_id

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.wait_until_ready()

    from woocommerce_commands import WooCommerceCommands
    from general_commands import GeneralCommands
    from admin_commands import AdminCommands
    from match_commands import MatchCommands

    await bot.add_cog(MatchCommands(bot))
    await bot.add_cog(AdminCommands(bot))
    await bot.add_cog(GeneralCommands(bot))
    await bot.add_cog(WooCommerceCommands(bot))
    await bot.tree.sync(guild=discord.Object(id=server_id))

    if os.path.exists('/root/update_channel_id.txt'):
        with open('/root/update_channel_id.txt', 'r') as f:
            channel_id = int(f.read())
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send("Update complete. Bot restarted successfully.")
        os.remove('/root/update_channel_id.txt')

    print(f'Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"This command is on cooldown. Please try again after {error.retry_after:.2f} seconds.", ephemeral=True)
    else:
        print(f"Unhandled interaction command error: {error}")
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

bot.run(bot_token)