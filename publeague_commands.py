import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import logging
from common import server_id, has_admin_role

logger = logging.getLogger(__name__)
WEBUI_API_URL = os.getenv("WEBUI_API_URL", "http://localhost:5000/api")

class SMSEnrollmentModal(discord.ui.Modal, title="SMS Enrollment"):
    def __init__(self, default_phone: str = ""):
        super().__init__()
        self.phone = discord.ui.TextInput(
            label="Phone Number",
            placeholder=default_phone if default_phone else "Enter your phone number (e.g., 14255555555)",
            default=default_phone,
            required=True
        )
        self.add_item(self.phone)
    
    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "discord_id": str(interaction.user.id),
            "phone": self.phone.value
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(f"{WEBUI_API_URL}/sms_enroll", json=payload) as resp:
                    if resp.status == 200:
                        await interaction.response.send_message(
                            "Enrollment initiated. Please click the button below to enter the confirmation code.",
                            ephemeral=True,
                            view=EnterCodeView()
                        )
                    else:
                        data = await resp.json()
                        error_msg = data.get("error", "Unknown error")
                        await interaction.response.send_message(
                            f"Enrollment failed: {error_msg}", ephemeral=True
                        )
            except Exception as e:
                await interaction.response.send_message(
                    f"Error connecting to the API: {str(e)}", ephemeral=True
                )

class SMSCodeModal(discord.ui.Modal, title="SMS Confirmation"):
    def __init__(self):
        super().__init__()
        self.code = discord.ui.TextInput(
            label="Confirmation Code",
            placeholder="Enter the code you received via SMS",
            required=True
        )
        self.add_item(self.code)
    
    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "discord_id": str(interaction.user.id),
            "code": self.code.value
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(f"{WEBUI_API_URL}/sms_confirm", json=payload) as resp:
                    if resp.status == 200:
                        await interaction.response.send_message(
                            "SMS enrollment confirmed and notifications enabled.", ephemeral=True
                        )
                    else:
                        data = await resp.json()
                        error_msg = data.get("error", "Unknown error")
                        await interaction.response.send_message(
                            f"Confirmation failed: {error_msg}", ephemeral=True
                        )
            except Exception as e:
                await interaction.response.send_message(
                    f"Error connecting to the API: {str(e)}", ephemeral=True
                )

class EnterCodeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Enter Confirmation Code", style=discord.ButtonStyle.primary, custom_id="enter_code")
    
    async def callback(self, interaction: discord.Interaction):
        modal = SMSCodeModal()
        await interaction.response.send_modal(modal)

class EnterCodeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(EnterCodeButton())

class ToggleButton(discord.ui.Button):
    def __init__(self, label: str, initial_value: bool, custom_id: str):
        style = discord.ButtonStyle.green if initial_value else discord.ButtonStyle.red
        super().__init__(label=label, style=style, custom_id=custom_id)
        self.value = initial_value

    async def callback(self, interaction: discord.Interaction):
        self.value = not self.value
        self.style = discord.ButtonStyle.green if self.value else discord.ButtonStyle.red
        await interaction.response.edit_message(view=self.view)

class EnrollSMSButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Enroll for SMS", style=discord.ButtonStyle.blurple, custom_id="enroll_sms")

    async def callback(self, interaction: discord.Interaction):
        default_phone = ""
        async with aiohttp.ClientSession() as session:
            try:
                url = f"{WEBUI_API_URL}/get_notifications?discord_id={interaction.user.id}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        default_phone = data.get("phone", "")
                        logger.debug(f"[DEBUG] Fetched phone number: {default_phone}")
            except Exception as e:
                logger.error(f"Error fetching phone number: {e}")
        modal = SMSEnrollmentModal(default_phone=default_phone)
        await interaction.response.send_modal(modal)

class NotificationToggleView(discord.ui.View):
    def __init__(self, current_settings: dict, sms_toggle_available: bool):
        super().__init__(timeout=60)
        self.old_dm = current_settings.get("discord", False)
        self.dm_button = ToggleButton("DM Notifications", self.old_dm, "toggle_dm")
        self.email_button = ToggleButton("Email Notifications", current_settings.get("email", False), "toggle_email")
        self.add_item(self.dm_button)
        self.add_item(self.email_button)
        if sms_toggle_available:
            self.sms_button = ToggleButton("SMS Notifications", current_settings.get("sms", False), "toggle_sms")
            self.add_item(self.sms_button)
        else:
            self.add_item(EnrollSMSButton())
        submit_button = discord.ui.Button(label="Submit", style=discord.ButtonStyle.primary, custom_id="submit_notifications")
        submit_button.callback = self.submit_callback
        self.add_item(submit_button)

    async def submit_callback(self, interaction: discord.Interaction):
        notifications = {
            "discord": self.dm_button.value,
            "email": self.email_button.value,
        }
        if hasattr(self, "sms_button"):
            notifications["sms"] = self.sms_button.value
        else:
            notifications["sms"] = False
        payload = {
            "discord_id": str(interaction.user.id),
            "notifications": notifications
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(f"{WEBUI_API_URL}/update_notifications", json=payload) as resp:
                    if resp.status == 200:
                        logger.debug(f"[DEBUG] Old DM: {self.old_dm}, New DM: {self.dm_button.value}")
                        try:
                            dm_channel = await interaction.user.create_dm()
                            logger.debug(f"[DEBUG] DM channel created: {dm_channel.id}")
                            if self.dm_button.value and self.dm_button.value != self.old_dm:
                                response = await dm_channel.send("DM notifications enabled for ECS FC.")
                                logger.debug(f"[DEBUG] DM send response: {response}")
                            elif not self.dm_button.value and self.old_dm:
                                response = await dm_channel.send("DM notifications disabled for ECS FC.")
                                logger.debug(f"[DEBUG] DM send response: {response}")
                        except Exception as e:
                            logger.error(f"[ERROR] Error sending DM confirmation: {e}")
                        await interaction.response.send_message("Notification preferences updated successfully.", ephemeral=True)
                    else:
                        data = await resp.json()
                        error_msg = data.get("error", "Unknown error")
                        await interaction.response.send_message(f"Failed to update preferences: {error_msg}", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error connecting to the API: {str(e)}", ephemeral=True)

class TeamRoleSelect(discord.ui.Select):
    def __init__(self, team_roles: list[discord.Role], message_text: str, original_interaction: discord.Interaction):
        options = [discord.SelectOption(label=role.name, value=str(role.id)) for role in team_roles]
        super().__init__(placeholder="Select your team role to mention", min_values=1, max_values=1, options=options)
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
        allowed_coach_roles = ["ECS-FC-PL-PREMIER-COACH", "ECS-FC-PL-CLASSIC-COACH"]
        member = interaction.user
        if not any(role.name in allowed_coach_roles for role in member.roles):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        team_roles = [role for role in member.roles if role.name.startswith("ECS-FC-PL-") and role.name.endswith("-PLAYER")]
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
        sms_enrolled = False
        phone_verified = False
        async with aiohttp.ClientSession() as session:
            try:
                url = f"{WEBUI_API_URL}/get_notifications?discord_id={interaction.user.id}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        current_settings = data.get("notifications", current_settings)
                        sms_enrolled = data.get("sms_enrolled", False)
                        phone_verified = data.get("phone_verified", False)
                    else:
                        logger.error(f"Error fetching notifications: HTTP {resp.status}")
            except Exception as e:
                logger.error(f"Error fetching current notifications: {e}")
        sms_toggle_available = sms_enrolled and phone_verified
        view = NotificationToggleView(current_settings, sms_toggle_available)
        await interaction.response.send_message(
            "Adjust your notification preferences using the buttons below and click Submit:",
            ephemeral=True,
            view=view
        )

    @app_commands.command(name="checkroles", description="Check a player's Discord roles by player name")
    @app_commands.describe(player_name="Player name (first and last) to look up")
    @app_commands.guilds(discord.Object(id=server_id))
    async def checkroles(self, interaction: discord.Interaction, player_name: str):
        """
        Lookup a player by name via your Flask API, retrieve their discord_id,
        then get and display the member's roles from your Discord guild.
        """
        # Only allow specific roles to execute this command.
        allowed_roles = [
            "ECS-FC-PL-CLASSIC-COACH",
            "ECS-FC-PL-PREMIER-COACH",
            "WG: ECS FC PL Leadership"
        ]
        if not any(role.name in allowed_roles for role in interaction.user.roles):
            await interaction.response.send_message(
                "You do not have permission to execute this command.",
                ephemeral=True
            )
            return

        # Build the API URL using the player_name as a query parameter
        lookup_url = f"{WEBUI_API_URL}/player_lookup?name={player_name}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(lookup_url) as resp:
                    if resp.status != 200:
                        await interaction.response.send_message(
                            f"Player '{player_name}' not found in the database.",
                            ephemeral=True
                        )
                        return
                    player_data = await resp.json()
            except Exception as e:
                await interaction.response.send_message(
                    f"Error connecting to the API: {str(e)}",
                    ephemeral=True
                )
                return

        # Extract the discord_id from the player record
        discord_id = player_data.get("discord_id")
        if not discord_id:
            await interaction.response.send_message(
                "Player record found but no discord_id is associated.",
                ephemeral=True
            )
            return

        # Lookup the member in the guild using the discord_id
        guild = interaction.guild
        member = guild.get_member(int(discord_id))
        if not member:
            try:
                member = await guild.fetch_member(int(discord_id))
            except Exception as e:
                await interaction.response.send_message(
                    f"Could not retrieve member: {str(e)}",
                    ephemeral=True
                )
                return

        if not member:
            await interaction.response.send_message(
                "Member not found in this guild.",
                ephemeral=True
            )
            return

        # Filter roles to include only those starting with "ECS-FC-PL"
        team_role_mentions = [role.mention for role in member.roles if role.name.startswith("ECS-FC-PL")]
        if not team_role_mentions:
            team_role_mentions = ["No matching roles found."]

        # Build the message using the clickable mention (member.mention)
        message = f"{member.mention}'s roles: {', '.join(team_role_mentions)}"

        # Send an ephemeral response (only visible to the command invoker)
        await interaction.response.send_message(message, ephemeral=True)

async def setup(bot):
    await bot.add_cog(PubLeagueCommands(bot))