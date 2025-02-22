# match_commands.py

import discord
import os
from discord import app_commands
from discord.ext import commands
import aiohttp
import logging
import traceback

from common import (
    server_id,
    team_id,
    has_admin_role,
    check_existing_threads,
    prepare_starter_message_away,
    match_channel_id,
)
from match_utils import (
    get_away_match,
    create_match_thread,
    get_next_match,
    closed_matches,
    prepare_match_environment,
    create_and_manage_thread,
    generate_thread_name,
    completed_matches,
    closed_matches,
)
from utils import convert_to_pst

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

API_BASE_URL = os.getenv("WEBUI_API_URL")

async def fetch_match_by_thread(discord_thread_id: str):
    request_url = f"{API_BASE_URL}/match/by_thread/{discord_thread_id}"
    logger.info(f"[fetch_match_by_thread] Requesting match info for thread ID {discord_thread_id} at {request_url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(request_url) as resp:
            logger.info(f"[fetch_match_by_thread] Received response status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                logger.info(f"[fetch_match_by_thread] Received match data: {data}")
                return data
            else:
                logger.error(f"[fetch_match_by_thread] Failed to fetch match info for thread ID {discord_thread_id}")
                return None

class PredictionModal(discord.ui.Modal, title="Match Prediction"):
    def __init__(self, home_team: str, opponent_team: str, match_id: str):
        super().__init__()
        self.home_team = home_team
        self.opponent_team = opponent_team
        self.match_id = match_id

        # Create two dynamic text input fields for scores
        self.home_score = discord.ui.TextInput(
            label=f"{home_team} Score", 
            style=discord.TextStyle.short,
            placeholder="Enter numeric score"
        )
        self.opponent_score = discord.ui.TextInput(
            label=f"{opponent_team} Score", 
            style=discord.TextStyle.short,
            placeholder="Enter numeric score"
        )
        self.add_item(self.home_score)
        self.add_item(self.opponent_score)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            home_score_int = int(self.home_score.value)
            opponent_score_int = int(self.opponent_score.value)
        except ValueError:
            await interaction.response.send_message("Please enter valid numeric scores.", ephemeral=True)
            return

        if self.match_id in closed_matches:
            await interaction.response.send_message("Predictions are closed for this match.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        payload = {
            "match_id": self.match_id,
            "discord_user_id": user_id,
            "home_score": home_score_int,
            "opponent_score": opponent_score_int,
        }
        request_url = f"{API_BASE_URL}/predictions"
        logger.info(f"[PredictionModal] Making POST request to {request_url} with payload: {payload}")
        async with aiohttp.ClientSession() as session:
            async with session.post(request_url, json=payload) as resp:
                data = await resp.json()
                logger.info(f"[PredictionModal] Received response: {data}")
                if resp.status == 200:
                    # Use the returned message to inform the user if their prediction was recorded or updated.
                    message = data.get("message", "Prediction recorded")
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    error_message = data.get("error", "Failed to record prediction.")
                    await interaction.response.send_message(error_message, ephemeral=True)

class MatchCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.team_id = team_id
        
    def is_match_closed(self, match_id):
        return match_id in completed_matches

    @app_commands.command(name="nextmatch", description="List the next scheduled match information")
    @app_commands.guilds(discord.Object(id=server_id))
    async def next_match(self, interaction: discord.Interaction):
        try:
            match_info = await get_next_match(team_id)
            if isinstance(match_info, str):
                await interaction.response.send_message(match_info)
                return

            date_time_pst_obj = convert_to_pst(match_info["date_time"])
            date_time_pst_formatted = date_time_pst_obj.strftime("%m/%d/%Y %I:%M %p PST")
            embed = discord.Embed(title=f"Next Match: {match_info['name']}", color=0x1A75FF)
            embed.add_field(name="Opponent", value=match_info["opponent"], inline=True)
            embed.add_field(name="Date and Time (PST)", value=date_time_pst_formatted, inline=True)
            embed.add_field(name="Venue", value=match_info["venue"], inline=True)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}")

    @app_commands.command(name="predict", description="Predict the score of the match")
    @app_commands.guilds(discord.Object(id=server_id))
    async def predict(self, interaction: discord.Interaction):
        # Ensure the command is used in a match thread
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in match threads.", ephemeral=True)
            return

        thread_id = str(interaction.channel.id)
        # Instead of using a local mapping, fetch the match info via the Flask API
        match = await fetch_match_by_thread(thread_id)
        if not match:
            logger.error(f"Thread ID {thread_id} is not associated with an active match prediction.")
            await interaction.response.send_message("This thread is not associated with an active match prediction.", ephemeral=True)
            return

        match_id = match.get("match_id")
        # Extract team names from the thread title; expected format: "Home Team vs Opponent Team - DATE"
        thread_title = interaction.channel.name
        try:
            parts = thread_title.split(" vs ")
            if len(parts) < 2:
                raise ValueError("Invalid thread title format")
            home_team = parts[0].strip()
            opponent_team = parts[1].split(" - ")[0].strip()
        except Exception:
            home_team = "Home"
            opponent_team = "Opponent"

        # Launch the modal with dynamic input labels
        modal = PredictionModal(home_team, opponent_team, match_id)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="predictions", description="List predictions for the current match thread")
    @app_commands.guilds(discord.Object(id=server_id))
    async def show_predictions(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in match threads.", ephemeral=True)
            return

        thread_id = str(interaction.channel.id)
        match = await fetch_match_by_thread(thread_id)
        if not match:
            logger.error(f"Thread ID {thread_id} is not associated with an active match prediction.")
            await interaction.response.send_message("This thread is not associated with an active match prediction.", ephemeral=True)
            return

        match_id = match.get("match_id")
        request_url = f"{API_BASE_URL}/predictions/{match_id}"
        logger.info(f"[show_predictions] Making GET request to {request_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(request_url) as resp:
                logger.info(f"[show_predictions] Received response status: {resp.status}")
                if resp.status == 200:
                    predictions_data = await resp.json()
                    logger.info(f"[show_predictions] Received predictions: {predictions_data}")
                else:
                    logger.error(f"[show_predictions] Failed to fetch predictions. Status: {resp.status}")
                    await interaction.response.send_message("Failed to fetch predictions.", ephemeral=True)
                    return

        if not predictions_data:
            await interaction.response.send_message("No predictions have been made for this match.", ephemeral=True)
            return

        embed = discord.Embed(title="Match Predictions", color=0x00FF00)
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        else:
            embed.set_author(name=interaction.guild.name)
        embed.set_footer(text="Predictions are subject to change before match kickoff.")

        for pred in predictions_data:
            user_id = pred['discord_user_id']
            # Try to fetch the member object from the guild using the stored Discord ID.
            member = interaction.guild.get_member(int(user_id))
            # Use the member's display name if available; otherwise fallback to the raw ID.
            display_name = member.display_name if member else user_id
            prediction_str = f"{display_name}: {pred['home_score']} - {pred['opponent_score']}"
            embed.add_field(name=prediction_str, value="\u200b", inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MatchCommands(bot))