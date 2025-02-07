import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from common import server_id

WEBUI_API_URL = os.getenv("WEBUI_API_URL", "http://localhost:5000/api")

class ToggleButton(discord.ui.Button):
    def __init__(self, label: str, initial_value: bool, custom_id: str):
        # Green for enabled, red for disabled.
        style = discord.ButtonStyle.green if initial_value else discord.ButtonStyle.red
        super().__init__(label=label, style=style, custom_id=custom_id)
        self.value = initial_value

    async def callback(self, interaction: discord.Interaction):
        # Toggle the value.
        self.value = not self.value
        self.style = discord.ButtonStyle.green if self.value else discord.ButtonStyle.red
        # Update the view so the button reflects the new state.
        await interaction.response.edit_message(view=self.view)

class NotificationToggleView(discord.ui.View):
    def __init__(self, current_settings: dict):
        super().__init__(timeout=60)
        self.dm_button = ToggleButton("DM Notifications", current_settings.get("discord", False), "toggle_dm")
        self.email_button = ToggleButton("Email Notifications", current_settings.get("email", False), "toggle_email")
        self.sms_button = ToggleButton("SMS Notifications", current_settings.get("sms", False), "toggle_sms")
        self.add_item(self.dm_button)
        self.add_item(self.email_button)
        self.add_item(self.sms_button)
        submit_button = discord.ui.Button(label="Submit", style=discord.ButtonStyle.primary, custom_id="submit_notifications")
        submit_button.callback = self.submit_callback
        self.add_item(submit_button)

    async def submit_callback(self, interaction: discord.Interaction):
        notifications = {
            "discord": self.dm_button.value,
            "email": self.email_button.value,
            "sms": self.sms_button.value,
        }
        payload = {
            "discord_id": str(interaction.user.id),
            "notifications": notifications
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(f"{WEBUI_API_URL}/update_notifications", json=payload) as resp:
                    if resp.status == 200:
                        await interaction.response.send_message("Notification preferences updated successfully.", ephemeral=True)
                    else:
                        data = await resp.json()
                        error_msg = data.get("error", "Unknown error")
                        await interaction.response.send_message(f"Failed to update preferences: {error_msg}", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error connecting to the API: {str(e)}", ephemeral=True)

class TeamRoleSelect(discord.ui.Select):
    def __init__(self, team_roles: list[discord.Role], message_text: str, original_interaction: discord.Interaction):
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
        selected_role_id = int(self.values[0])
        selected_role = discord.utils.get(self.team_roles, id=selected_role_id)
        if not selected_role:
            await interaction.response.send_message("Selected team role not found.", ephemeral=True)
            return
        allowed_mentions = discord.AllowedMentions(roles=[selected_role])
        output = f"{selected_role.mention} {self.message_text}"
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
        allowed_coach_roles = [
            "ECS-FC-PL-PREMIER-COACH",
            "ECS-FC-PL-CLASSIC-COACH"
        ]
        member = interaction.user
        if not any(role.name in allowed_coach_roles for role in member.roles):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        team_roles = [
            role for role in member.roles
            if role.name.startswith("ECS-FC-PL-") and role.name.endswith("-PLAYER")
        ]
        if not team_roles:
            await interaction.response.send_message("No team role found for you. Please ensure you have the appropriate team role.", ephemeral=True)
            return
        if len(team_roles) == 1:
            team_role = team_roles[0]
            allowed_mentions = discord.AllowedMentions(roles=[team_role])
            output = f"{team_role.mention} {message}"
            await interaction.response.send_message(output, allowed_mentions=allowed_mentions)
        else:
            view = TeamRoleSelectView(team_roles, message, interaction)
            await interaction.response.send_message("Multiple team roles found. Please select the team you wish to message:", ephemeral=True, view=view)

    @app_commands.command(name="notifications", description="Manage your notification preferences")
    @app_commands.guilds(discord.Object(id=server_id))
    async def notifications(self, interaction: discord.Interaction):
        current_settings = {"discord": False, "email": False, "sms": False}
        async with aiohttp.ClientSession() as session:
            try:
                url = f"{WEBUI_API_URL}/get_notifications?discord_id={interaction.user.id}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        current_settings = data.get("notifications", current_settings)
            except Exception as e:
                print(f"Error fetching current notifications: {e}")
        view = NotificationToggleView(current_settings)
        await interaction.response.send_message(
            "Adjust your notification preferences using the buttons below and click Submit:",
            ephemeral=True,
            view=view
        )

async def setup(bot):
    await bot.add_cog(PubLeagueCommands(bot))