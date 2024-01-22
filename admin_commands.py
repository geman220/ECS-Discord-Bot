# admin_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import json
from datetime import timedelta
from common import server_id, has_admin_role, is_admin_or_owner, dev_id, bot_version, flask_url, flask_token, wp_username, wp_app_password, load_team_schedule
from match_utils import get_matches_for_calendar
from interactions import CheckOrderModal, NewRoleModal

class AdminCommands(commands.Cog, name="Admin Commands"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='update', description="Update the bot from the GitHub repository")
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_bot(self, interaction: discord.Interaction):
        """Update the bot from GitHub repository"""
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        with open('/root/update_channel_id.txt', 'w') as f:
            f.write(str(interaction.channel.id))

        headers = {'Authorization': f'Bearer {flask_token}'}
        async with aiohttp.ClientSession() as session:
            async with session.post(flask_url, headers=headers) as response:
                if response.status == 200:
                    await interaction.response.send_message("Bot is updating...", ephemeral=True)
                else:
                    response_text = await response.text()
                    await interaction.response.send_message(f"Update failed: {response_text}", ephemeral=True)

    @app_commands.command(name='version', description="Get the current bot version")
    @app_commands.guilds(discord.Object(id=server_id))
    async def version(self, interaction: discord.Interaction):
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.send_message(f"ECS Bot - developed by <@{dev_id}> version {bot_version}")

    @app_commands.command(name='checkorder', description="Check an ECS membership order")
    @app_commands.guilds(discord.Object(id=server_id))
    async def check_order(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.send_modal(CheckOrderModal(self.bot))

    @app_commands.command(name='newseason', description="Start a new season with a new ECS membership role")
    @app_commands.guilds(discord.Object(id=server_id))
    async def new_season(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        modal = NewRoleModal(self.bot)
        await interaction.response.send_modal(modal)
        
    @app_commands.command(name='createschedule', description="Create the team schedule file")
    @app_commands.guilds(discord.Object(id=server_id))
    async def create_schedule_command(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return
    
        await interaction.response.defer()
        ctx = interaction

        try:
            matches = await get_matches_for_calendar(ctx)
            if not matches:
                await interaction.followup.send("No match data found.")
                return

            with open('team_schedule.json', 'w') as f:
                json.dump(matches, f, indent=4)
            await interaction.followup.send("Team schedule created successfully.")
        except Exception as e:
            await interaction.followup.send(f"Failed to create schedule: {e}")

    @app_commands.command(name='updatecalendar', description="Update the event calendar with team schedule")
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_calendar_command(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        team_schedule = load_team_schedule()
        api_url = 'https://weareecs.com/wp-json/tribe/events/v1/events'
        auth = aiohttp.BasicAuth(login=wp_username, password=wp_app_password)

        async with aiohttp.ClientSession() as session:
            for match in team_schedule:
                pst_start_time = self.convert_to_pst(match['date_time'])
                pst_end_time = pst_start_time + timedelta(hours=3)

                event_data = {
                    "title": match['name'],
                    "description": f"{match['name']} at {match['venue']}. More details [here]({match['match_summary_link']}).",
                    "start_date": pst_start_time.strftime('%Y-%m-%dT%H:%M:%S'),
                    "end_date": pst_end_time.strftime('%Y-%m-%dT%H:%M:%S'),
                    "image": match['team_logo'],
                    "website": match['match_summary_link'],
                    "timezone": "America/Los_Angeles",
                }

                async with session.post(api_url, json=event_data, auth=auth) as response:
                    if response.status == 201:
                        print(f"Event created successfully for match: {match['name']}")
                    else:
                        print(f"Failed to create event for match: {match['name']}. Status code: {response.status}")
                    await asyncio.sleep(1)

        await interaction.followup.send("Event calendar updated successfully.")