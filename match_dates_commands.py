# match_dates_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re
from common import has_admin_role, server_id

MATCH_DATES_PATH = "match_dates.json"

class MatchDatesCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def validate_date_format(self, date_str):
        return re.match(r'^\d{8}$', date_str) is not None

    @app_commands.command(name="addmatchdate", description="Add a match date. Examples: usa.1 (MLS), usa.open (US Open Cup)")
    @app_commands.guilds(discord.Object(id=server_id))
    async def add_match_date(self, interaction: discord.Interaction, date: str, competition: str):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        if not self.validate_date_format(date):
            await interaction.response.send_message("Invalid date format. Use YYYYMMDD.", ephemeral=True)
            return

        with open(MATCH_DATES_PATH, 'r') as f:
            data = json.load(f)

        data['matches'].append({"date": date, "competition": competition})

        with open(MATCH_DATES_PATH, 'w') as f:
            json.dump(data, f, indent=4)

        await interaction.response.send_message(f"Added match date {date} for {competition}.", ephemeral=True)
        await self.push_to_github(interaction)

    @app_commands.command(name="updatematchdate", description="Update a match date. Examples: usa.1 (MLS), usa.open (US Open Cup)")
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_match_date(self, interaction: discord.Interaction, old_date: str, new_date: str, competition: str):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        if not self.validate_date_format(new_date):
            await interaction.response.send_message("Invalid date format. Use YYYYMMDD.", ephemeral=True)
            return

        with open(MATCH_DATES_PATH, 'r') as f:
            data = json.load(f)

        for match in data['matches']:
            if match['date'] == old_date and match['competition'] == competition:
                match['date'] = new_date
                break

        with open(MATCH_DATES_PATH, 'w') as f:
            json.dump(data, f, indent=4)

        await interaction.response.send_message(f"Updated match date {old_date} to {new_date} for {competition}.", ephemeral=True)
        await self.push_to_github(interaction)

    @app_commands.command(name="deletematchdate", description="Delete a match date. Examples: usa.1 (MLS), usa.open (US Open Cup)")
    @app_commands.guilds(discord.Object(id=server_id))
    async def delete_match_date(self, interaction: discord.Interaction, date: str, competition: str):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        with open(MATCH_DATES_PATH, 'r') as f:
            data = json.load(f)

        data['matches'] = [match for match in data['matches'] if not (match['date'] == date and match['competition'] == competition)]

        with open(MATCH_DATES_PATH, 'w') as f:
            json.dump(data, f, indent=4)

        await interaction.response.send_message(f"Deleted match date {date} for {competition}.", ephemeral=True)
        await self.push_to_github(interaction)

    async def push_to_github(self, interaction):
        os.system("git add match_dates.json")
        os.system('git commit -m "Update match dates from Discord"')
        os.system("git push")
        await interaction.followup.send("Changes pushed to GitHub.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MatchDatesCommands(bot))