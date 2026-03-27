# schedule_commands.py

import discord
import io
import os
from discord import app_commands
from discord.ext import commands
import aiohttp
import logging

from common import server_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

API_BASE_URL = os.getenv("WEBUI_API_URL")


class ScheduleCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._session = None

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def cog_unload(self):
        if self._session and not self._session.closed:
            import asyncio
            asyncio.create_task(self._session.close())

    @app_commands.command(name="schedule", description="View your team's upcoming match schedule")
    @app_commands.guilds(discord.Object(id=server_id))
    async def schedule(self, interaction: discord.Interaction):
        discord_id = str(interaction.user.id)
        session = await self.get_session()

        try:
            async with session.get(f"{API_BASE_URL}/player-schedule-image/{discord_id}") as resp:
                if resp.status == 404:
                    data = await resp.json()
                    error = data.get("error", "")
                    if "Player not found" in error:
                        msg = ("You are not registered as a player in the league portal. "
                               "Please contact an admin if you believe this is an error.")
                    elif "no teams" in error.lower():
                        msg = "You are not currently assigned to any teams."
                    else:
                        msg = "No upcoming matches found for your team(s)."
                    await interaction.response.send_message(msg, ephemeral=True)
                    return

                if resp.status != 200:
                    logger.error(f"[schedule] API returned status {resp.status} for {discord_id}")
                    await interaction.response.send_message(
                        "Unable to retrieve schedule data. Please try again later.",
                        ephemeral=True
                    )
                    return

                image_bytes = await resp.read()

        except Exception as e:
            logger.error(f"[schedule] API call failed: {e}", exc_info=True)
            await interaction.response.send_message(
                "Unable to connect to the league portal. Please try again later.",
                ephemeral=True
            )
            return

        file = discord.File(io.BytesIO(image_bytes), filename="schedule.png")
        embed = discord.Embed(color=0x1A4A2A)
        embed.set_image(url="attachment://schedule.png")

        if interaction.guild and interaction.guild.icon:
            embed.set_footer(
                text="ECS Pub League • /calendar for league events",
                icon_url=interaction.guild.icon.url
            )
        else:
            embed.set_footer(text="ECS Pub League • /calendar for league events")

        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)

    @app_commands.command(name="calendar", description="View upcoming league events")
    @app_commands.guilds(discord.Object(id=server_id))
    async def calendar(self, interaction: discord.Interaction):
        session = await self.get_session()

        try:
            async with session.get(f"{API_BASE_URL}/upcoming-events-image", params={"limit": 15}) as resp:
                if resp.status == 404:
                    await interaction.response.send_message(
                        "No upcoming league events scheduled. Check back later!",
                        ephemeral=True
                    )
                    return

                if resp.status != 200:
                    logger.error(f"[calendar] API returned status {resp.status}")
                    await interaction.response.send_message(
                        "Unable to retrieve event data. Please try again later.",
                        ephemeral=True
                    )
                    return

                image_bytes = await resp.read()

        except Exception as e:
            logger.error(f"[calendar] API call failed: {e}", exc_info=True)
            await interaction.response.send_message(
                "Unable to connect to the league portal. Please try again later.",
                ephemeral=True
            )
            return

        file = discord.File(io.BytesIO(image_bytes), filename="calendar.png")
        embed = discord.Embed(color=0x1A4A2A)
        embed.set_image(url="attachment://calendar.png")

        if interaction.guild and interaction.guild.icon:
            embed.set_footer(
                text="ECS Pub League • Full calendar at portal.ecsfc.com",
                icon_url=interaction.guild.icon.url
            )
        else:
            embed.set_footer(text="ECS Pub League • Full calendar at portal.ecsfc.com")

        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScheduleCommands(bot))
