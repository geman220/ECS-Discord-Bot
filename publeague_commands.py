import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from common import has_admin_role, server_id

class PubLeagueCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="newpubleague", description="Set up a new pub league")
    @app_commands.guilds(discord.Object(id=server_id))
    async def newpubleague(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return
        
        await interaction.response.send_message("Select the league type: Premier, Classic, ECS FC", ephemeral=True)
        await self.ask_league_type(interaction)

    async def ask_league_type(self, interaction):
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            league_type = msg.content.lower()
            if league_type not in ['premier', 'classic', 'ecs fc']:
                await interaction.followup.send("Please enter either 'Premier', 'Classic', or 'ECS FC'.", ephemeral=True)
                return await self.ask_league_type(interaction)
            await interaction.followup.send(f"League type set to {league_type.capitalize()}. Now, enter the team names (comma-separated):", ephemeral=True)
            await self.ask_team_names(interaction, league_type)
        except asyncio.TimeoutError:
            await interaction.followup.send("You took too long to respond. Please start again.", ephemeral=True)

    async def ask_team_names(self, interaction, league_type):
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            team_names = [team.strip() for team in msg.content.split(',')]
            await interaction.followup.send(f"Teams set: {', '.join(team_names)}. Now, enter the team admins for each team (mention the users, comma-separated, in the same order as team names):", ephemeral=True)
            await self.ask_team_admins(interaction, league_type, team_names)
        except asyncio.TimeoutError:
            await interaction.followup.send("You took too long to respond. Please start again.", ephemeral=True)

    async def ask_team_admins(self, interaction, league_type, team_names):
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            team_admins_mentions = msg.mentions
            if len(team_admins_mentions) != len(team_names):
                await interaction.followup.send("The number of mentions does not match the number of teams. Please try again.", ephemeral=True)
                return await self.ask_team_admins(interaction, league_type, team_names)
            await interaction.followup.send(f"Admins set. Setting up roles and channels...", ephemeral=True)
            await self.setup_league(interaction, league_type, team_names, team_admins_mentions)
        except asyncio.TimeoutError:
            await interaction.followup.send("You took too long to respond. Please start again.", ephemeral=True)

    async def setup_league(self, interaction, league_type, team_names, team_admins_mentions):
        guild = interaction.guild
        category_name = f"{league_type.capitalize()} Pub League"
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)

        global_admin_role = discord.utils.get(guild.roles, name="WG: ECS FC Managers")
        if not global_admin_role:
            global_admin_role = await guild.create_role(name="WG: ECS FC Managers")

        lobby_channel = discord.utils.get(guild.text_channels, name=f"{league_type.lower()}-lobby")
        if not lobby_channel:
            lobby_channel = await category.create_text_channel(f"{league_type.lower()}-lobby")
            lobby_role = discord.utils.get(guild.roles, name=f"{league_type.capitalize()} League")
            if not lobby_role:
                lobby_role = await guild.create_role(name=f"{league_type.capitalize()} League")
            await lobby_channel.set_permissions(lobby_role, read_messages=True, send_messages=True)
            await lobby_channel.set_permissions(guild.default_role, read_messages=False)
            await lobby_channel.set_permissions(global_admin_role, read_messages=True, send_messages=True)

        for team_name, admin in zip(team_names, team_admins_mentions):
            role_name = f"{league_type.capitalize()}-{team_name}"
            coach_role_name = f"{role_name}-Coach"
            role = discord.utils.get(guild.roles, name=role_name)
            coach_role = discord.utils.get(guild.roles, name=coach_role_name)

            if not role:
                role = await guild.create_role(name=role_name)
            if not coach_role:
                coach_role = await guild.create_role(name=coach_role_name)

            channel_name = team_name.lower().replace(' ', '-')
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not channel:
                channel = await category.create_text_channel(channel_name)

            await channel.set_permissions(role, read_messages=True, send_messages=True)
            await channel.set_permissions(coach_role, read_messages=True, send_messages=True, manage_channels=True, manage_roles=True)
            await channel.set_permissions(guild.default_role, read_messages=False)
            await channel.set_permissions(global_admin_role, read_messages=True, send_messages=True)

            if admin:
                await admin.add_roles(role)
                await admin.add_roles(coach_role)
                await interaction.followup.send(f"Created roles and channel for {team_name}, and assigned admin {admin.display_name}.", ephemeral=True)
            else:
                await interaction.followup.send(f"Could not find admin {admin.display_name}. Please assign manually.", ephemeral=True)

    @app_commands.command(name="clearleague", description="Clear the existing league setup")
    @app_commands.guilds(discord.Object(id=server_id))
    async def clearleague(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return
        
        await interaction.response.send_message("Select the league type to clear: Premier, Classic, ECS FC", ephemeral=True)
        await self.ask_clear_league_type(interaction)

    async def ask_clear_league_type(self, interaction):
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            league_type = msg.content.lower()
            if league_type not in ['premier', 'classic', 'ecs fc']:
                await interaction.followup.send("Please enter either 'Premier', 'Classic', or 'ECS FC'.", ephemeral=True)
                return await self.ask_clear_league_type(interaction)
            await interaction.followup.send(f"Clearing {league_type.capitalize()} league...", ephemeral=True)
            await self.clear_league_setup(interaction, league_type)
        except asyncio.TimeoutError:
            await interaction.followup.send("You took too long to respond. Please start again.", ephemeral=True)

    async def clear_league_setup(self, interaction, league_type):
        guild = interaction.guild
        category_name = f"{league_type.capitalize()} Pub League"
        category = discord.utils.get(guild.categories, name=category_name)
        
        if category:
            for channel in category.channels:
                await channel.delete()
            await category.delete()

        roles_to_delete = [role for role in guild.roles if role.name.startswith(f"{league_type.capitalize()}-")]

        for role in roles_to_delete:
            await role.delete()

        await interaction.followup.send(f"Cleared {league_type.capitalize()} league setup.", ephemeral=True)

    @app_commands.command(name="invite", description="Invite a player to your team")
    @app_commands.describe(player="Mention the player to invite to your team")
    @app_commands.guilds(discord.Object(id=server_id))
    async def invite(self, interaction: discord.Interaction, player: discord.Member):
        if not any(role.name.endswith('-Coach') for role in interaction.user.roles):
            await interaction.response.send_message("You do not have the necessary permissions to invite players.", ephemeral=True)
            return

        coach_role = next(role for role in interaction.user.roles if role.name.endswith('-Coach'))
        team_role_name = coach_role.name.rsplit('-', 1)[0]
        team_role = discord.utils.get(interaction.guild.roles, name=team_role_name)

        if team_role:
            await player.add_roles(team_role)
            await interaction.response.send_message(f"{player.display_name} has been added to {team_role.name}.", ephemeral=True)
        else:
            await interaction.response.send_message("Team role not found. Please contact an admin.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PubLeagueCommands(bot))
