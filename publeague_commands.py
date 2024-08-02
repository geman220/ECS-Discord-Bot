import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import json
from common import has_admin_role, server_id
from database import load_league_data, insert_coach, insert_member, get_db_connection, PUB_LEAGUE_DB_PATH

class PubLeagueCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setupleague", description="Set up a new league")
    @app_commands.guilds(discord.Object(id=server_id))
    async def setup_league(self, interaction: discord.Interaction, league_type: str, json_file: str = 'publeague_schedule.json'):
        admin_role = discord.utils.get(interaction.guild.roles, name="WG: ECS FC Admin")
        if admin_role not in interaction.user.roles:
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        league_type = league_type.lower()
        if league_type not in ['premier', 'classic']:
            await interaction.response.send_message("Please enter either 'Premier' or 'Classic'.", ephemeral=True)
            return

        if not os.path.exists(json_file):
            await interaction.response.send_message(f"JSON file {json_file} does not exist.", ephemeral=True)
            return

        try:
            with open(json_file, 'r') as file:
                data = json.load(file)
            league_data = data['leagues'].get(league_type.capitalize())
            if not league_data:
                await interaction.response.send_message(f"No data found for {league_type.capitalize()} league.", ephemeral=True)
                return

            load_league_data(json_file)
            await interaction.response.send_message("League schedule loaded successfully. Please wait while I generate the league in Discord.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to load schedule: {e}", ephemeral=True)
            return

        await self.create_league(interaction, league_type, league_data['teams'])

    async def create_league(self, interaction, league_type, teams):
        guild = interaction.guild
        category_name = f"ECS FC PL {league_type.capitalize()}"
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await self.create_category_with_retry(guild, category_name)

        global_admin_role = discord.utils.get(guild.roles, name="WG: ECS FC Admin")
        if not global_admin_role:
            global_admin_role = await self.create_role_with_retry(guild, "WG: ECS FC Admin")

        for team in teams:
            team_name = team['name'].lower().replace(' ', '-')
            role_name = f"ECS-FC-{league_type.capitalize()}-{team_name}"
            coach_role_name = f"{role_name}-Coach"
            player_role_name = f"{role_name}-Player"

            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                print(f"Creating role: {role_name}")
                role = await self.create_role_with_retry(guild, role_name)

            coach_role = discord.utils.get(guild.roles, name=coach_role_name)
            if not coach_role:
                print(f"Creating role: {coach_role_name}")
                coach_role = await self.create_role_with_retry(guild, coach_role_name)

            player_role = discord.utils.get(guild.roles, name=player_role_name)
            if not player_role:
                print(f"Creating role: {player_role_name}")
                player_role = await self.create_role_with_retry(guild, player_role_name)

            channel_name = team_name
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not channel:
                print(f"Creating channel: {channel_name}")
                channel = await self.create_channel_with_retry(category, channel_name)

            await channel.set_permissions(role, read_messages=True, send_messages=True)
            await channel.set_permissions(coach_role, read_messages=True, send_messages=True, manage_channels=True, manage_roles=True)
            await channel.set_permissions(player_role, read_messages=True, send_messages=True)
            await channel.set_permissions(guild.default_role, read_messages=False)
            await channel.set_permissions(global_admin_role, read_messages=True, send_messages=True)

            # Post the schedule in the channel
            schedule_message = self.format_schedule_message(team['schedule'])
            schedule_msg = await channel.send(schedule_message)
            await schedule_msg.pin()

        await interaction.followup.send(f"Created {league_type.capitalize()} league with teams.", ephemeral=True)

    async def create_role_with_retry(self, guild, role_name):
        while True:
            try:
                role = await guild.create_role(name=role_name)
                return role
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.response.headers.get('Retry-After', 1)
                    print(f"Rate limited. Retrying after {retry_after} seconds.")
                    await asyncio.sleep(float(retry_after))
                else:
                    raise e

    async def create_channel_with_retry(self, category, channel_name):
        while True:
            try:
                channel = await category.create_text_channel(channel_name)
                return channel
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.response.headers.get('Retry-After', 1)
                    print(f"Rate limited. Retrying after {retry_after} seconds.")
                    await asyncio.sleep(float(retry_after))
                else:
                    raise e

    async def create_category_with_retry(self, guild, category_name):
        while True:
            try:
                category = await guild.create_category(category_name)
                return category
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.response.headers.get('Retry-After', 1)
                    print(f"Rate limited. Retrying after {retry_after} seconds.")
                    await asyncio.sleep(float(retry_after))
                else:
                    raise e

    def format_schedule_message(self, schedule):
        message = "**Team Schedule**\n"
        for week_info in schedule:
            message += f"**Week {week_info['week']}**\n"
            for match in week_info['matches']:
                message += f"- {match['date']} at {match['time']}: vs {match['opponent']}\n"
        return message

    @app_commands.command(name="assigncoach", description="Assign a coach to a team")
    @app_commands.describe(coach="Mention the coach to assign", team_name="Name of the team")
    @app_commands.guilds(discord.Object(id=server_id))
    async def assign_coach(self, interaction: discord.Interaction, coach: discord.Member, team_name: str):
        admin_role = discord.utils.get(interaction.guild.roles, name="WG: ECS FC Admin")
        if admin_role not in interaction.user.roles:
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        # Normalize the team name to lower case
        team_name = team_name.lower()

        # Fetch league type and team ID from the database
        with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT league_id FROM teams WHERE lower(name)=?", (team_name,))
            result = c.fetchone()
            if result is None:
                await interaction.response.send_message(f"Team {team_name.replace('-', ' ')} not found. Please contact an admin.", ephemeral=True)
                return

            league_id = result[0]
            league_type = "Premier" if league_id == 2 else "Classic"
            team_id = c.execute("SELECT team_id FROM teams WHERE lower(name)=?", (team_name,)).fetchone()[0]

        role_name = f"ECS-FC-{league_type}-{team_name.replace(' ', '-')}-Coach"
        permanent_coach_role_name = f"ECS-FC-{league_type}-Coach"

        role = discord.utils.get(interaction.guild.roles, name=role_name)
        permanent_role = discord.utils.get(interaction.guild.roles, name=permanent_coach_role_name)

        if role and permanent_role:
            await coach.add_roles(role)
            await coach.add_roles(permanent_role)
            await self.remove_conflicting_roles(coach, league_type, 'Coach')

            insert_coach(coach.mention, team_id)

            await interaction.response.send_message(f"{coach.display_name} has been assigned as a coach for {team_name.replace('-', ' ')}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Team or coach role not found for {team_name.replace('-', ' ')}. Please contact an admin.", ephemeral=True)

    async def remove_conflicting_roles(self, member, league_type, role_type):
        other_league_type = "Classic" if league_type == "Premier" else "Premier"
        conflicting_role_name = f"ECS-FC-{other_league_type}-{role_type}"
        conflicting_role = discord.utils.get(member.guild.roles, name=conflicting_role_name)

        if conflicting_role in member.roles:
            await member.remove_roles(conflicting_role)

        if role_type == 'Player':
            coach_role_name = f"ECS-FC-{league_type}-Coach"
            coach_role = discord.utils.get(member.guild.roles, name=coach_role_name)
            if coach_role in member.roles:
                await member.remove_roles(coach_role)

    @app_commands.command(name="invite", description="PL - Invite a player to your team")
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
            league_type = "Premier" if "Premier" in team_role_name else "Classic"
            permanent_player_role_name = f"ECS-FC-{league_type}-Player"
            permanent_role = discord.utils.get(interaction.guild.roles, name=permanent_player_role_name)
            await player.add_roles(permanent_role)
            await self.remove_conflicting_roles(player, league_type, 'Player')

            # Insert player into the database
            with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
                c = conn.cursor()
                c.execute("SELECT team_id FROM teams WHERE lower(name)=?", (team_role_name.split('-')[-1].lower(),))
                team_id = c.fetchone()[0]
                insert_member(player.mention, team_id)
            await interaction.response.send_message(f"{player.display_name} has been added to {team_role.name.replace('-', ' ')}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Team role {team_role_name.replace('-', ' ')} not found. Please contact an admin.", ephemeral=True)

    async def remove_conflicting_roles(self, member, league_type, role_type):
        other_league_type = "Classic" if league_type == "Premier" else "Premier"
        conflicting_role_name = f"ECS-FC-{other_league_type}-{role_type}"
        conflicting_role = discord.utils.get(member.guild.roles, name=conflicting_role_name)

        if conflicting_role in member.roles:
            await member.remove_roles(conflicting_role)

        if role_type == 'Player':
            coach_role_name = f"ECS-FC-{league_type}-Coach"
            coach_role = discord.utils.get(member.guild.roles, name=coach_role_name)
            if coach_role in member.roles:
                await member.remove_roles(coach_role)
                
    @app_commands.command(name="addplayer", description="ECS FC - Add a player to your team")
    @app_commands.describe(player="Mention the player to add to your team")
    @app_commands.guilds(discord.Object(id=server_id))
    async def add_player(self, interaction: discord.Interaction, player: discord.Member):
        if not any(role.name.endswith('-Manager') for role in interaction.user.roles):
            await interaction.response.send_message("You do not have the necessary permissions to add players.", ephemeral=True)
            return

        manager_role = next(role for role in interaction.user.roles if role.name.endswith('-Manager'))
        team_name = manager_role.name.rsplit('-', 1)[0]
        player_role_name = f"{team_name}-Player"
        player_role = discord.utils.get(interaction.guild.roles, name=player_role_name)

        if player_role:
            await player.add_roles(player_role)
            await interaction.response.send_message(f"{player.display_name} has been added to {player_role.name.replace('-', ' ')}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Player role {player_role_name.replace('-', ' ')} not found. Please contact an admin.", ephemeral=True)

    @app_commands.command(name="clearleague", description="Clear the existing league setup")
    @app_commands.guilds(discord.Object(id=server_id))
    async def clear_league(self, interaction: discord.Interaction, league_type: str):
        admin_role = discord.utils.get(interaction.guild.roles, name="WG: ECS FC Admin")
        if admin_role not in interaction.user.roles:
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        league_type = league_type.lower()
        if league_type not in ['premier', 'classic']:
            await interaction.response.send_message("Please enter either 'Premier' or 'Classic'.", ephemeral=True)
            return

        await interaction.response.send_message(f"Clearing {league_type.capitalize()} league...", ephemeral=True)
        await self.clear_league_setup(interaction, league_type)

    async def clear_league_setup(self, interaction, league_type):
        guild = interaction.guild
        category_name = f"ECS FC PL {league_type.capitalize()}"
        category = discord.utils.get(guild.categories, name=category_name)
        
        if category:
            for channel in category.channels:
                await channel.delete()
            await category.delete()

        roles_to_delete = [role for role in guild.roles if role.name.startswith(f"ECS-FC-{league_type.capitalize()}-") and '-' in role.name]

        # Preserve permanent roles
        permanent_roles = [
            f"ECS-FC-Premier-Coach", f"ECS-FC-Classic-Coach",
            f"ECS-FC-Premier-Player", f"ECS-FC-Classic-Player"
        ]
        roles_to_delete = [role for role in roles_to_delete if role.name not in permanent_roles]

        for role in roles_to_delete:
            await role.delete()

        # Clear database entries
        with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                DELETE FROM schedules
                WHERE team_id IN (
                    SELECT team_id FROM teams WHERE league_id IN (
                        SELECT league_id FROM leagues WHERE name=?
                    )
                )
            """, (league_type.capitalize(),))
            c.execute("""
                DELETE FROM coaches
                WHERE team_id IN (
                    SELECT team_id FROM teams WHERE league_id IN (
                        SELECT league_id FROM leagues WHERE name=?
                    )
                )
            """, (league_type.capitalize(),))
            c.execute("""
                DELETE FROM members
                WHERE team_id IN (
                    SELECT team_id FROM teams WHERE league_id IN (
                        SELECT league_id FROM leagues WHERE name=?
                    )
                )
            """, (league_type.capitalize(),))
            c.execute("""
                DELETE FROM teams WHERE league_id IN (
                    SELECT league_id FROM leagues WHERE name=?
                )
            """, (league_type.capitalize(),))
            c.execute("DELETE FROM leagues WHERE name=?", (league_type.capitalize(),))
            conn.commit()

        await interaction.followup.send(f"Cleared {league_type.capitalize()} league setup.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PubLeagueCommands(bot))
