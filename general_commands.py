# general_commands.py

import discord
from discord import app_commands
from discord.ext import commands
from common import server_id, team_id, team_name, format_stat_name
from match_utils import get_away_match, get_team_record
import aiohttp
import os
import re
from interactions import VerifyModal

WEBUI_API_URL = os.getenv("WEBUI_API_URL")
LEADERSHIP_ROLE_NAME = "WG: ECS FC PL Leadership"
TEAM_ROLE_PATTERN = r"^ECS-FC-PL-.*-PLAYER$"

class GeneralCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.team_id = team_id

    def _get_team_roles(self, member: discord.Member) -> set:
        """
        Returns the set of role names that match ECS-FC-PL-...-PLAYER
        """
        matches = set()
        for role in member.roles:
            if re.match(TEAM_ROLE_PATTERN, role.name):
                matches.add(role.name)
        return matches

    @app_commands.command(name="record", description="Lists the Sounders season stats")
    @app_commands.guilds(discord.Object(id=server_id))
    async def team_record(self, interaction: discord.Interaction):
        record_info, team_logo_url = await get_team_record(self.team_id)
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

    @app_commands.command(name="awaytickets", description="Get a link to the latest away tickets")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(opponent="The name of the opponent team (optional)")
    async def away_tickets(self, interaction: discord.Interaction, opponent: str = None):
        closest_match = await get_away_match(opponent)
        if closest_match:
            match_name, match_link = closest_match
            await interaction.response.send_message(f"Away match: {match_name}\nTickets: {match_link}")
        else:
            await interaction.response.send_message("No upcoming away matches found.")

    @app_commands.command(name="verify", description="Verify your ECS membership with your Order #")
    @app_commands.guilds(discord.Object(id=server_id))
    async def verify_order(self, interaction: discord.Interaction):
        modal = VerifyModal(title="Verify Membership", bot=self.bot)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="lookup", description="Look up a player by Discord user.")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(person="The user you want to look up")
    async def whois(self, interaction: discord.Interaction, person: discord.Member):
        """
        /lookup <@DiscordUser>
        
        - If the invoker has the WG: ECS FC PL Leadership role, they can look up anyone.
        - Otherwise, the invoker and target user must share at least one exact ECS-FC-PL-TEAM-...-PLAYER role.
        - If the user is not found in the portal, respond with "Player not found".
        """
        invoker = interaction.user  # The user invoking the command

        # Check leadership
        invoker_role_names = [r.name for r in invoker.roles]
        if LEADERSHIP_ROLE_NAME not in invoker_role_names:
            # Not leadership => must share a team role
            my_team_roles = self._get_team_roles(invoker)
            their_team_roles = self._get_team_roles(person)

            # If there's no overlap, deny immediately
            if my_team_roles.isdisjoint(their_team_roles):
                return await interaction.response.send_message(
                    content="You do not have permission to look up that user.",
                    ephemeral=True
                )

        # If we reach here, the user is allowed to proceed
        discord_id = str(person.id)
        api_url = f"{WEBUI_API_URL}/get_player_id_from_discord/{discord_id}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(api_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        player_name = data.get("player_name", "Unknown")
                        teams = data.get("teams", [])
                        profile_pic_url = data.get("profile_picture_url", "")

                        embed = discord.Embed(
                            title="Player Lookup",
                            description=f"**Discord User:** {person.mention}",
                            color=discord.Color.blue()
                        )

                        if profile_pic_url:
                            embed.set_thumbnail(url=profile_pic_url)

                        embed.add_field(name="Player Name", value=player_name, inline=False)

                        if teams:
                            embed.add_field(
                                name="Teams",
                                value=", ".join(teams),
                                inline=False
                            )
                        else:
                            embed.add_field(name="Teams", value="No teams found", inline=False)

                        await interaction.response.send_message(embed=embed, ephemeral=True)

                    elif resp.status == 404:
                        # The Flask API specifically returns 404 if "Player not found"
                        await interaction.response.send_message(
                            content="Player not found in the portal.",
                            ephemeral=True
                        )

                    else:
                        # Possibly another error code
                        error_text = await resp.text()
                        msg = (
                            f"Could not find a player for ID `{discord_id}`.\n"
                            f"API responded with status {resp.status}: {error_text}"
                        )
                        await interaction.response.send_message(content=msg, ephemeral=True)

            except Exception as e:
                error_msg = f"Error contacting the API: {str(e)}"
                await interaction.response.send_message(content=error_msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(GeneralCommands(bot))
