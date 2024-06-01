# admin_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from interactions import CheckOrderModal, NewRoleModal
from common import (
    server_id,
    has_admin_role,
    is_admin_or_owner,
    dev_id,
    bot_version,
    flask_url,
    flask_token,
)
from match_utils import get_matches_for_calendar



class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="update", description="Update the bot from the GitHub repository"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_bot(self, interaction: discord.Interaction):
        """Update the bot from GitHub repository"""
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        with open("/root/update_channel_id.txt", "w") as f:
            f.write(str(interaction.channel.id))

        headers = {"Authorization": f"Bearer {flask_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.post(flask_url, headers=headers) as response:
                if response.status == 200:
                    await interaction.response.send_message(
                        "Bot is updating...", ephemeral=True
                    )
                else:
                    response_text = await response.text()
                    await interaction.response.send_message(
                        f"Update failed: {response_text}", ephemeral=True
                    )

    @app_commands.command(name="version", description="Get the current bot version")
    @app_commands.guilds(discord.Object(id=server_id))
    async def version(self, interaction: discord.Interaction):
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"ECS Bot - developed by <@{dev_id}> version {bot_version}"
        )

    @app_commands.command(
        name="checkorder", description="Check an ECS membership order"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def check_order(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.send_modal(CheckOrderModal(self.bot))

    @app_commands.command(
        name="newseason",
        description="Start a new season with a new ECS membership role",
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def new_season(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        modal = NewRoleModal(self.bot)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="createschedule", description="Create or update the team schedule database"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def create_schedule_command(self, interaction: discord.Interaction):
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            matches = await get_matches_for_calendar()
            if not matches:
                await interaction.followup.send("No match data found.")
                return

            await interaction.followup.send("Team schedule created and stored successfully.")

        except Exception as e:
            await interaction.followup.send(f"Failed to create schedule: {e}")
            
async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
