# general_commands.py

import discord
from discord import app_commands
from discord.ext import commands
from common import server_id, team_id, team_name, format_stat_name
from match_utils import get_away_match, get_team_record
from interactions import VerifyModal


class GeneralCommands(commands.Cog, name="General Commands"):
    def __init__(self, bot):
        self.bot = bot
        self.team_id = team_id

    @app_commands.command(name="record", description="Lists the Sounders season stats")
    @app_commands.guilds(discord.Object(id=server_id))
    async def team_record(self, interaction: discord.Interaction):
        record_info, team_logo_url = await get_team_record(interaction, self.team_id)
        if record_info != "Record not available":
            embed = discord.Embed(title=f"{team_name} Record", color=0x00FF00)
            if team_logo_url:
                embed.set_thumbnail(url=team_logo_url)
            for stat, value in record_info.items():
                readable_stat = format_stat_name(stat)
                embed.add_field(name=readable_stat, value=str(value), inline=True)

            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Error fetching record.")

    @app_commands.command(
        name="awaytickets", description="Get a link to the latest away tickets"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(opponent="The name of the opponent team (optional)")
    async def away_tickets(
        self, interaction: discord.Interaction, opponent: str = None
    ):
        closest_match = await get_away_match(interaction, opponent)
        if closest_match:
            match_name, match_link = closest_match
            await interaction.response.send_message(
                f"Away match: {match_name}\nTickets: {match_link}"
            )
        else:
            await interaction.response.send_message("No upcoming away matches found.")

    @app_commands.command(
        name="verify", description="Verify your ECS membership with your Order #"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def verify_order(self, interaction: discord.Interaction):
        modal = VerifyModal(title="Verify Membership", bot=self.bot)
        await interaction.response.send_modal(modal)
