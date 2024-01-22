# match_commands.py

import discord
from discord import app_commands
from discord.ext import commands
from common import server_id, team_id, team_name, has_admin_role, convert_to_pst, get_weather_forecast, venue_lat, venue_long, create_event_if_necessary, check_existing_threads, prepare_starter_message, prepare_starter_message_away, create_match_thread, get_next_match, get_away_match, closed_matches, match_thread_map
from datetime import datetime, timedelta
from database import get_predictions, insert_prediction

class MatchCommands(commands.Cog, name="Match Commands"):
    def __init__(self, bot):
        self.bot = bot
        self.match_thread_map = match_thread_map
        self.team_id = team_id

    def update_thread_map(self, thread_id, match_id):
        self.match_thread_map[thread_id] = match_id

    @app_commands.command(name='nextmatch', description="List the next scheduled match information")
    @app_commands.guilds(discord.Object(id=server_id))
    async def next_match(self, interaction: discord.Interaction):
        match_info = await get_next_match(interaction, team_id)

        if isinstance(match_info, str):
            await interaction.response.send_message(match_info)
            return

        date_time_pst_obj = convert_to_pst(match_info['date_time'])
        date_time_pst_formatted = date_time_pst_obj.strftime('%m/%d/%Y %I:%M %p PST')

        embed = discord.Embed(title=f"Next Match: {match_info['name']}", color=0x1a75ff)
        embed.add_field(name="Opponent", value=match_info['opponent'], inline=True)
        embed.add_field(name="Date and Time (PST)", value=date_time_pst_formatted, inline=True)
        embed.add_field(name="Venue", value=match_info['venue'], inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='newmatch', description="Create a new match thread")
    @app_commands.guilds(discord.Object(id=server_id))
    async def new_match(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            match_info = await get_next_match(interaction, self.team_id)
            if isinstance(match_info, str):
                await interaction.followup.send(match_info, ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"Failed to process the command: {e}", ephemeral=True)

        date_time_pst = convert_to_pst(match_info['date_time'])
        date_time_pst_formatted = date_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
        thread_name = f"Match Thread: {match_info['name']} - {date_time_pst_formatted}"
    
        weather_forecast = ""
        if match_info['is_home_game']:
            weather_forecast = await get_weather_forecast(date_time_pst, venue_lat, venue_long)
            event_response = await create_event_if_necessary(interaction, match_info, date_time_pst)
            if event_response:
                await interaction.followup.send(event_response)
                return

        if await check_existing_threads(interaction, thread_name, "match-thread"):
            await interaction.followup.send("A thread for this match has already been created.")
            return

        starter_message, embed = await prepare_starter_message(match_info, date_time_pst_formatted, match_info['team_logo'], weather_forecast, thread_name)
        thread_response = await create_match_thread(interaction, thread_name, embed, match_info, self, "match-thread")
        await interaction.followup.send(thread_response)

    @app_commands.command(name='awaymatch', description="Create a new away match thread, create ticket item in store first!")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(opponent='The name of the opponent team (optional)')
    async def away_match(self, interaction: discord.Interaction, opponent: str = None):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        match_ticket_info = await get_away_match(interaction, opponent)
        if not match_ticket_info:
            await interaction.followup.send("No relevant away match or ticket info found.", ephemeral=True)
            return

        match_name, match_link = match_ticket_info

        try:
            match_info = await get_next_match(interaction, self.team_id, opponent)
            if isinstance(match_info, str):
                await interaction.followup.send(match_info, ephemeral=True)
                return

            match_id = match_info['match_id']
            match_name = match_info['name']
            match_venue = match_info['venue']
            match_opponent = match_info['opponent']
            match_date_time_utc = match_info['date_time']

            date_time_pst = convert_to_pst(match_date_time_utc)
            date_time_pst_formatted = date_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
            thread_name = f"Away Travel: {match_name} - {date_time_pst_formatted}"

            if await check_existing_threads(interaction, thread_name, "away-travel"):
                await interaction.followup.send("A thread for this away match has already been created.")
                return

            starter_message, embed = await prepare_starter_message_away(interaction, match_info, date_time_pst_formatted, thread_name, match_link)
            thread_response = await create_match_thread(interaction, thread_name, embed, match_info, self, channel_name='away-travel')
        
            await interaction.followup.send(thread_response)
        except Exception as e:
            await interaction.followup.send(f"Failed to process the command: {e}", ephemeral=True)

    @app_commands.command(name='predictions', description='List predictions for the current match thread')
    @app_commands.guilds(discord.Object(id=server_id))
    async def show_predictions(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in match threads.", ephemeral=True)
            return

        match_id = self.match_thread_map.get(str(interaction.channel.id))
        if not match_id:
            await interaction.response.send_message("This thread is not associated with an active match prediction.", ephemeral=True)
            return

        predictions = get_predictions(match_id)
        if not predictions:
            await interaction.response.send_message("No predictions have been made for this match.", ephemeral=True)
            return

        embed = discord.Embed(title="Match Predictions", color=0x00ff00)
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        else:
            embed.set_author(name=interaction.guild.name)

        embed.set_footer(text="Predictions are subject to change before match kickoff.")

        for prediction, count in predictions:
            embed.add_field(name=prediction, value=f"{count} prediction(s)", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='predict', description='Predict the score of the match')
    @app_commands.describe(prediction='Your prediction (e.g., 3-0)')
    @app_commands.guilds(discord.Object(id=server_id))
    async def predict(self, interaction: discord.Interaction, prediction: str):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in match threads.", ephemeral=True)
            return

        match_id = self.match_thread_map.get(str(interaction.channel.id))
        if not match_id:
            await interaction.response.send_message("This thread is not associated with an active match prediction.", ephemeral=True)
            return

        if match_id in closed_matches:
            await interaction.response.send_message("Predictions are closed for this match.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if insert_prediction(match_id, user_id, prediction):
            await interaction.response.send_message("Prediction recorded!", ephemeral=True)
        else:
            await interaction.response.send_message("You have already made a prediction for this match.", ephemeral=True)