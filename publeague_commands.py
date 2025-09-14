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
        
        # Send push notification to team members
        await self._send_team_push_notification(selected_role.name, self.message_text, self.original_interaction.user.id)
        
        # Check Discord message length limit and split if necessary
        discord_max_length = 2000
        role_mention_text = f"{selected_role.mention} "
        role_mention_length = len(role_mention_text)
        
        # If the first message with role mention fits
        if len(role_mention_text + self.message_text) <= discord_max_length:
            output = f"{role_mention_text}{self.message_text}"
            await self.original_interaction.channel.send(output, allowed_mentions=allowed_mentions)
        else:
            # Split message into chunks
            max_chunk_length = discord_max_length - role_mention_length
            chunks = []
            remaining_message = self.message_text
            
            while remaining_message:
                if len(remaining_message) <= max_chunk_length:
                    chunks.append(remaining_message)
                    break
                else:
                    # Find a good break point (space, newline, etc.)
                    chunk = remaining_message[:max_chunk_length]
                    last_space = chunk.rfind(' ')
                    last_newline = chunk.rfind('\n')
                    break_point = max(last_space, last_newline)
                    
                    if break_point > max_chunk_length * 0.8:  # If break point is reasonable
                        chunks.append(remaining_message[:break_point])
                        remaining_message = remaining_message[break_point:].lstrip()
                    else:
                        # No good break point, just split at max length
                        chunks.append(remaining_message[:max_chunk_length])
                        remaining_message = remaining_message[max_chunk_length:]
            
            # Send first chunk with role mention
            first_output = f"{role_mention_text}{chunks[0]}"
            await self.original_interaction.channel.send(first_output, allowed_mentions=allowed_mentions)
            
            # Send remaining chunks without role mention
            for chunk in chunks[1:]:
                await self.original_interaction.channel.send(chunk)
        await interaction.response.send_message("Team message sent.", ephemeral=True)
        self.view.stop()
    
    async def _send_team_push_notification(self, team_role_name: str, message: str, coach_discord_id: int):
        """Send push notification to team members via Flask API"""
        try:
            payload = {
                'team_name': team_role_name,
                'message': message,
                'coach_discord_id': str(coach_discord_id),
                'title': '⚽ Team Message'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{WEBUI_API_URL}/team-notifications/send",
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Push notification sent successfully: {result}")
                    else:
                        error_text = await response.text()
                        logger.warning(f"Failed to send push notification: {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error sending team push notification: {e}")

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
        
        # Log raw user roles for debugging.
        logger.debug("User roles (raw): %s", [repr(role.name) for role in member.roles])
        
        if not any(role.name in allowed_coach_roles for role in member.roles):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        # Use lower-case for comparison after stripping whitespace.
        team_roles = [
            role for role in member.roles
            if role.name.strip().lower().startswith("ecs-fc-pl-") and role.name.strip().lower().endswith("-player")
        ]
        logger.debug("Filtered team roles (team command): %s", [repr(role.name) for role in team_roles])
        
        if not team_roles:
            await interaction.response.send_message("No team role found for you. Please ensure you have the appropriate team role.", ephemeral=True)
            return

        if len(team_roles) == 1:
            team_role = team_roles[0]
            allowed_mentions = discord.AllowedMentions(roles=[team_role])
            
            # Check Discord message length limit and split if necessary
            discord_max_length = 2000
            role_mention_text = f"{team_role.mention} "
            role_mention_length = len(role_mention_text)
            
            # Send push notification to team members
            await self._send_team_push_notification(team_role.name, message, interaction.user.id)
            
            # If the first message with role mention fits
            if len(role_mention_text + message) <= discord_max_length:
                output = f"{role_mention_text}{message}"
                await interaction.response.send_message(output, allowed_mentions=allowed_mentions)
            else:
                # Split message into chunks
                max_chunk_length = discord_max_length - role_mention_length
                chunks = []
                remaining_message = message
                
                while remaining_message:
                    if len(remaining_message) <= max_chunk_length:
                        chunks.append(remaining_message)
                        break
                    else:
                        # Find a good break point (space, newline, etc.)
                        chunk = remaining_message[:max_chunk_length]
                        last_space = chunk.rfind(' ')
                        last_newline = chunk.rfind('\n')
                        break_point = max(last_space, last_newline)
                        
                        if break_point > max_chunk_length * 0.8:  # If break point is reasonable
                            chunks.append(remaining_message[:break_point])
                            remaining_message = remaining_message[break_point:].lstrip()
                        else:
                            # No good break point, just split at max length
                            chunks.append(remaining_message[:max_chunk_length])
                            remaining_message = remaining_message[max_chunk_length:]
                
                # Send first chunk with role mention
                first_output = f"{role_mention_text}{chunks[0]}"
                await interaction.response.send_message(first_output, allowed_mentions=allowed_mentions)
                
                # Send remaining chunks without role mention
                for chunk in chunks[1:]:
                    await interaction.channel.send(chunk)
        else:
            view = TeamRoleSelectView(team_roles, message, interaction)
            await interaction.response.send_message("Multiple team roles found. Please select the team you wish to message:", ephemeral=True, view=view)
    
    async def _send_team_push_notification(self, team_role_name: str, message: str, coach_discord_id: int):
        """Send push notification to team members via Flask API"""
        try:
            payload = {
                'team_name': team_role_name,
                'message': message,
                'coach_discord_id': str(coach_discord_id),
                'title': '⚽ Team Message'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{WEBUI_API_URL}/team-notifications/send",
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Push notification sent successfully: {result}")
                    else:
                        error_text = await response.text()
                        logger.warning(f"Failed to send push notification: {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error sending team push notification: {e}")

    @app_commands.command(
        name="checkmyteam",
        description="Check which current players on your team(s) are missing from Discord."
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def checkteam(self, interaction: discord.Interaction):
        allowed_coach_roles = ["ECS-FC-PL-CLASSIC-COACH", "ECS-FC-PL-PREMIER-COACH"]
        if not any(role.name in allowed_coach_roles for role in interaction.user.roles):
            await interaction.response.send_message("You do not have permission to execute this command.", ephemeral=True)
            return

        logger.debug("User roles (raw) for checkteam: %s", [repr(role.name) for role in interaction.user.roles])
        
        # Filter using lower-case comparisons.
        team_roles = [
            role for role in interaction.user.roles
            if role.name.strip().lower().startswith("ecs-fc-pl-") and role.name.strip().lower().endswith("-player")
        ]
        logger.debug("Filtered team roles (checkteam command): %s", [repr(role.name) for role in team_roles])
        
        if not team_roles:
            await interaction.response.send_message("No team role found for you. Please ensure you have the appropriate team role.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        results = []
        async with aiohttp.ClientSession() as session:
            for team_role in team_roles:
                role_name = team_role.name.strip()
                # Use fixed prefix and suffix (note: suffix length is 7 regardless of case)
                prefix = "ECS-FC-PL-"
                suffix = "-Player"
                team_name = role_name[len(prefix):-len(suffix)].strip()
                # Replace hyphens with spaces to match database format
                team_name = team_name.replace("-", " ")
                logger.debug("Extracted team name: %s", team_name)
                lookup_url = f"{WEBUI_API_URL}/team_lookup?name={team_name}"
                logger.debug("Lookup URL: %s", lookup_url)
                try:
                    async with session.get(lookup_url) as resp:
                        if resp.status != 200:
                            results.append(f"Team '{team_name}' not found in the database.")
                            continue
                        data = await resp.json()
                except Exception as e:
                    results.append(f"Error connecting to the API for team '{team_name}': {str(e)}")
                    continue

                team_data = data.get("team")
                players = data.get("players", [])
                current_players = [p for p in players if p.get("is_current_player")]
                if not current_players:
                    results.append(f"No current players found for team '{team_name}'.")
                    continue

                unlinked_players = [p for p in current_players if not p.get("discord_id")]
                linked_players = [p for p in current_players if p.get("discord_id")]
                expected_ids = set()
                for player in linked_players:
                    try:
                        expected_ids.add(int(player["discord_id"]))
                    except (ValueError, TypeError):
                        continue

                actual_ids = {member.id for member in team_role.members}
                missing_ids = expected_ids - actual_ids

                not_in_discord_ids = set()
                in_discord_missing_role_ids = set()
                for d_id in missing_ids:
                    member_obj = interaction.guild.get_member(d_id)
                    if member_obj is None:
                        not_in_discord_ids.add(d_id)
                    else:
                        in_discord_missing_role_ids.add(d_id)

                not_in_discord_players = [p for p in linked_players if int(p["discord_id"]) in not_in_discord_ids]
                in_discord_missing_role_players = [p for p in linked_players if int(p["discord_id"]) in in_discord_missing_role_ids]

                block_lines = [
                    f"**Team Check for {team_data['name']}**",
                    f"Total current players (DB): {len(current_players)}"
                ]
                if unlinked_players:
                    unlinked_names = ", ".join(p.get("name", "Unknown") for p in unlinked_players)
                    block_lines.append(f":warning: **Unlinked Accounts:** {unlinked_names} (These players need to link their Discord account.)")
                if not_in_discord_players:
                    not_in_discord_names = ", ".join(p.get("name", "Unknown") for p in not_in_discord_players)
                    block_lines.append(f":x: **Not in Discord:** {not_in_discord_names}")
                if in_discord_missing_role_players:
                    in_discord_names = ", ".join(p.get("name", "Unknown") for p in in_discord_missing_role_players)
                    block_lines.append(f":warning: **In Discord but Missing Role:** {in_discord_names}")
                if not not_in_discord_players and not in_discord_missing_role_players:
                    block_lines.append(":white_check_mark: All linked players are correctly in Discord with the role.")

                results.append("\n".join(block_lines))
        final_report = "\n\n".join(results)
        await interaction.followup.send(final_report, ephemeral=True)

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

        discord_id = player_data.get("discord_id")
        if not discord_id:
            await interaction.response.send_message(
                "Player record found but no discord_id is associated.",
                ephemeral=True
            )
            return

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

        team_role_mentions = [role.mention for role in member.roles if role.name.startswith("ECS-FC-PL")]
        if not team_role_mentions:
            team_role_mentions = ["No matching roles found."]

        message = f"{member.mention}'s roles: {', '.join(team_role_mentions)}"
        await interaction.response.send_message(message, ephemeral=True)

async def setup(bot):
    await bot.add_cog(PubLeagueCommands(bot))