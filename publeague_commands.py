import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import json
from common import has_admin_role, server_id
from database import load_league_data, insert_coach, insert_member, get_db_connection, PUB_LEAGUE_DB_PATH

class TeamRoleSelect(discord.ui.Select):
    def __init__(self, team_roles: list[discord.Role], message_text: str, original_interaction: discord.Interaction):
        # Create an option for each team role.
        options = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in team_roles
        ]
        super().__init__(
            placeholder="Select your team role to mention",
            min_values=1,
            max_values=1,
            options=options
        )
        self.team_roles = team_roles
        self.message_text = message_text
        self.original_interaction = original_interaction

    async def callback(self, interaction: discord.Interaction):
        # Get the selected role ID (as string) and find the matching role.
        selected_role_id = int(self.values[0])
        selected_role = discord.utils.get(self.team_roles, id=selected_role_id)
        if not selected_role:
            await interaction.response.send_message("Selected team role not found.", ephemeral=True)
            return

        # Build allowed mentions so that only the selected team role is mentioned.
        allowed_mentions = discord.AllowedMentions(roles=[selected_role])
        output = f"{selected_role.mention} {self.message_text}"
        # Send the public message in the channel where the command was used.
        await self.original_interaction.channel.send(output, allowed_mentions=allowed_mentions)
        await interaction.response.send_message("Team message sent.", ephemeral=True)
        self.view.stop()

class TeamRoleSelectView(discord.ui.View):
    def __init__(self, team_roles: list[discord.Role], message_text: str, original_interaction: discord.Interaction):
        super().__init__(timeout=60)
        self.add_item(TeamRoleSelect(team_roles, message_text, original_interaction))

class PubLeagueCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="team", description="Send a message to your team")
    @app_commands.describe(message="The message to send to your team")
    @app_commands.guilds(discord.Object(id=server_id))
    async def team(self, interaction: discord.Interaction, message: str):
        # List of roles allowed to use this command (coaches).
        allowed_coach_roles = [
            "ECS-FC-PL-PREMIER-COACH",
            "ECS-FC-PL-CLASSIC-COACH"
        ]
        member = interaction.user

        # Check if the invoking user has one of the allowed coach roles.
        if not any(role.name in allowed_coach_roles for role in member.roles):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True
            )
            return

        # Find all team roles matching the pattern "ECS-FC-PL-<TEAMNAME>-PLAYER"
        team_roles = [
            role for role in member.roles
            if role.name.startswith("ECS-FC-PL-") and role.name.endswith("-PLAYER")
        ]

        if not team_roles:
            await interaction.response.send_message(
                "No team role found for you. Please ensure you have the appropriate team role.",
                ephemeral=True
            )
            return

        # If only one team role is found, send the message immediately.
        if len(team_roles) == 1:
            team_role = team_roles[0]
            allowed_mentions = discord.AllowedMentions(roles=[team_role])
            output = f"{team_role.mention} {message}"
            await interaction.response.send_message(output, allowed_mentions=allowed_mentions)
        else:
            # If multiple team roles are found, prompt the user to select which team to message.
            view = TeamRoleSelectView(team_roles, message, interaction)
            await interaction.response.send_message(
                "Multiple team roles found. Please select the team you wish to message:",
                ephemeral=True,
                view=view
            )

async def setup(bot):
    await bot.add_cog(PubLeagueCommands(bot))
