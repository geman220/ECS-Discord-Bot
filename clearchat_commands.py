# clearchat_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from common import server_id


class ConfirmClearChatView(discord.ui.View):
    def __init__(self, original_channel):
        super().__init__(timeout=60.0)
        self.original_channel = original_channel
        self.confirmed = False

    @discord.ui.button(
        label="Confirm Clear Chat", 
        style=discord.ButtonStyle.danger, 
        emoji="⚠️"
    )
    async def confirm_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(
            content="Clearing chat history... This may take a few minutes.", 
            view=None
        )

    @discord.ui.button(
        label="Cancel", 
        style=discord.ButtonStyle.secondary, 
        emoji="❌"
    )
    async def cancel_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.edit_message(
            content="Chat clear operation cancelled.", 
            view=None
        )

    async def on_timeout(self):
        self.confirmed = False
        self.stop()


class ClearChatCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def has_leadership_role(self, interaction: discord.Interaction) -> bool:
        """Check if user has the required leadership role"""
        leadership_role_ids = [1321198676369997835, 1337234877543743601]  # Live and Dev server IDs
        return any(role.id in leadership_role_ids for role in interaction.user.roles)

    async def is_allowed_channel(self, channel) -> bool:
        """Check if command is being used in allowed channels"""
        allowed_channel_names = ["pl-classic-coaches", "pl-premier-coaches"]
        return channel.name in allowed_channel_names

    async def clone_channel_with_permissions(self, original_channel):
        """Clone a channel with all its permissions and settings"""
        try:
            # Get all overwrites from the original channel
            overwrites = original_channel.overwrites

            # Create new channel with same settings
            new_channel = await original_channel.guild.create_text_channel(
                name=original_channel.name,
                category=original_channel.category,
                topic=original_channel.topic,
                slowmode_delay=original_channel.slowmode_delay,
                nsfw=original_channel.nsfw,
                overwrites=overwrites,
                position=original_channel.position,
                reason="Channel cleared via /clearchat command"
            )

            return new_channel

        except Exception as e:
            raise Exception(f"Failed to clone channel: {str(e)}")

    @app_commands.command(
        name="clearchat", 
        description="Clear all messages in this channel (DESTRUCTIVE - Requires confirmation)"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def clear_chat(self, interaction: discord.Interaction):
        """Clear all chat history in allowed channels with role restrictions"""
        
        # Check if user has required role
        if not await self.has_leadership_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions. This command requires the 'WG: ECS FC PL Leadership' role.",
                ephemeral=True
            )
            return

        # Check if channel is allowed
        if not await self.is_allowed_channel(interaction.channel):
            await interaction.response.send_message(
                "This command can only be used in #pl-classic-coaches or #pl-premier-coaches channels.",
                ephemeral=True
            )
            return

        # Send confirmation prompt
        view = ConfirmClearChatView(interaction.channel)
        
        warning_message = (
            "⚠️ **WARNING: DESTRUCTIVE ACTION** ⚠️\n\n"
            f"You are about to clear ALL chat history in #{interaction.channel.name}.\n\n"
            "**This action will:**\n"
            "• Delete ALL messages in this channel (including messages from 60+ days ago)\n"
            "• Clone the channel with identical permissions and settings\n"
            "• Delete the original channel\n\n"
            "**This action cannot be undone!**\n\n"
            "Are you absolutely sure you want to proceed?"
        )

        await interaction.response.send_message(
            content=warning_message,
            view=view,
            ephemeral=True
        )

        # Wait for user confirmation
        await view.wait()

        if not view.confirmed:
            if not interaction.is_expired():
                try:
                    await interaction.edit_original_response(
                        content="Chat clear operation cancelled or timed out.",
                        view=None
                    )
                except:
                    pass
            return

        try:
            # Store original channel info
            original_channel = interaction.channel
            guild = interaction.guild

            # Update the user that we're starting the process
            try:
                await interaction.edit_original_response(
                    content="🔄 Starting channel clone process...",
                    view=None
                )
            except:
                pass

            # Clone the channel with all permissions
            new_channel = await self.clone_channel_with_permissions(original_channel)

            # Send a message to the new channel indicating the clear was successful
            await new_channel.send(
                f"✅ **Chat history cleared successfully!**\n\n"
                f"This channel was cleared by {interaction.user.mention} using the `/clearchat` command.\n"
                f"All previous chat history has been removed.\n\n"
                f"*Channel cleared on: <t:{int(discord.utils.utcnow().timestamp())}:F>*"
            )

            # Delete the original channel
            await original_channel.delete(reason="Channel cleared via /clearchat command")

        except Exception as e:
            # If something goes wrong, try to inform the user
            try:
                if not interaction.is_expired():
                    await interaction.edit_original_response(
                        content=f"❌ Error during channel clear operation: {str(e)}",
                        view=None
                    )
                else:
                    # Try to send a message to the original channel if interaction expired
                    await original_channel.send(
                        f"❌ Error during channel clear operation: {str(e)}\n"
                        f"Requested by: {interaction.user.mention}"
                    )
            except:
                pass


async def setup(bot):
    await bot.add_cog(ClearChatCommands(bot))