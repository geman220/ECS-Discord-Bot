# schedule_commands.py

import discord
import os
from discord import app_commands
from discord.ext import commands
import aiohttp
import logging
from datetime import datetime

from common import server_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

API_BASE_URL = os.getenv("WEBUI_API_URL")

# Event type emoji and color mappings (matches communication_routes.py)
LEAGUE_EVENT_ICONS = {
    'party': '\U0001f389',       # 🎉
    'meeting': '\U0001f465',     # 👥
    'social': '\u2764\ufe0f',    # ❤️
    'plop': '\u26bd',            # ⚽
    'tournament': '\U0001f3c6',  # 🏆
    'fundraiser': '\U0001f4b0',  # 💰
    'other': '\U0001f4c5',       # 📅
}

WEEK_TYPE_ICONS = {
    'REGULAR': '\u26bd',         # ⚽
    'PLAYOFF': '\U0001f3c6',     # 🏆
    'FUN': '\U0001f389',         # 🎉
    'TST': '\U0001f3af',         # 🎯
    'PRACTICE': '\U0001f3cb',    # 🏋
    'BONUS': '\u2b50',           # ⭐
    'BYE': '\U0001f634',         # 😴
}


def _format_match_date(date_str, time_str):
    """Format date and time strings into a readable display string in Pacific time."""
    try:
        if date_str and time_str:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}")
        elif date_str:
            dt = datetime.fromisoformat(date_str)
        else:
            return "TBD"
        return dt.strftime("%a, %b %-d \u00b7 %-I:%M %p")
    except (ValueError, TypeError):
        return date_str or "TBD"


def _format_event_datetime(start_iso, end_iso, is_all_day):
    """Format event datetime for display."""
    try:
        start = datetime.fromisoformat(start_iso) if start_iso else None
        if not start:
            return "TBD"

        if is_all_day:
            return f"\U0001f4c5 {start.strftime('%a, %b %-d, %Y')} \u00b7 All Day"

        time_str = start.strftime("%-I:%M %p")
        date_str = start.strftime("%a, %b %-d, %Y")

        if end_iso:
            end = datetime.fromisoformat(end_iso)
            end_time_str = end.strftime("%-I:%M %p")
            return f"\U0001f4c5 {date_str}\n\U0001f552 {time_str} \u2013 {end_time_str}"

        return f"\U0001f4c5 {date_str}\n\U0001f552 {time_str}"
    except (ValueError, TypeError):
        return "TBD"


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
            async with session.get(f"{API_BASE_URL}/player-schedule/{discord_id}") as resp:
                if resp.status == 404:
                    await interaction.response.send_message(
                        "You are not registered as a player in the league portal. "
                        "Please contact an admin if you believe this is an error.",
                        ephemeral=True
                    )
                    return
                if resp.status != 200:
                    logger.error(f"[schedule] API returned status {resp.status} for {discord_id}")
                    await interaction.response.send_message(
                        "Unable to retrieve schedule data. Please try again later.",
                        ephemeral=True
                    )
                    return
                data = await resp.json()
        except Exception as e:
            logger.error(f"[schedule] API call failed: {e}", exc_info=True)
            await interaction.response.send_message(
                "Unable to connect to the league portal. Please try again later.",
                ephemeral=True
            )
            return

        player_name = data.get("player_name", "Player")
        teams = data.get("teams", [])
        matches = data.get("matches", [])

        embed = discord.Embed(
            title="\U0001f4cb Upcoming Match Schedule",
            color=0x1A75FF
        )

        if interaction.guild and interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)

        if not matches:
            embed.description = (
                f"**{player_name}**\n\n"
                "No upcoming matches scheduled.\n"
                "Check back later or visit the league portal for more info."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        team_names = ", ".join(t["name"] for t in teams) if teams else "Unknown"
        embed.description = f"**{player_name}** \u2014 {team_names}"

        multi_team = len(teams) > 1
        team_id_to_name = {t["id"]: t["name"] for t in teams}

        for match in matches:
            week_type = match.get("week_type", "REGULAR")
            icon = WEEK_TYPE_ICONS.get(week_type, "\u26bd")
            is_home = match.get("is_home", True)
            opponent = match.get("away_team") if is_home else match.get("home_team")
            home_away = "Home" if is_home else "Away"

            field_name = f"{icon} vs {opponent}"
            if match.get("is_playoff_game"):
                field_name = f"\U0001f3c6 vs {opponent} (Playoff)"

            date_time = _format_match_date(match.get("date"), match.get("time"))
            location = match.get("location", "TBD")

            value_lines = [
                f"\U0001f4c5 {date_time}",
                f"\U0001f4cd {location} \u00b7 *{home_away}*",
            ]

            if multi_team:
                my_team_id = match.get("home_team_id") if is_home else match.get("away_team_id")
                my_team_name = team_id_to_name.get(my_team_id, "")
                if my_team_name:
                    value_lines.append(f"\U0001f3bd {my_team_name}")

            embed.add_field(name=field_name, value="\n".join(value_lines), inline=False)

        embed.set_footer(text=f"Showing next {len(matches)} match{'es' if len(matches) != 1 else ''} \u00b7 /calendar for league events")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="calendar", description="View upcoming league events")
    @app_commands.guilds(discord.Object(id=server_id))
    async def calendar(self, interaction: discord.Interaction):
        session = await self.get_session()

        try:
            async with session.get(f"{API_BASE_URL}/upcoming-events", params={"limit": 10}) as resp:
                if resp.status != 200:
                    logger.error(f"[calendar] API returned status {resp.status}")
                    await interaction.response.send_message(
                        "Unable to retrieve event data. Please try again later.",
                        ephemeral=True
                    )
                    return
                data = await resp.json()
        except Exception as e:
            logger.error(f"[calendar] API call failed: {e}", exc_info=True)
            await interaction.response.send_message(
                "Unable to connect to the league portal. Please try again later.",
                ephemeral=True
            )
            return

        events = data.get("events", [])

        embed = discord.Embed(
            title="\U0001f4c5 Upcoming League Events",
            color=0x2F3136
        )

        if interaction.guild and interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)

        if not events:
            embed.description = (
                "No upcoming league events scheduled.\n"
                "Check back later or visit the league portal for more info."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        for event in events:
            event_type = event.get("event_type", "other")
            icon = LEAGUE_EVENT_ICONS.get(event_type, "\U0001f4c5")
            title = event.get("title", "Untitled Event")

            field_name = f"{icon} {title}"

            dt_display = _format_event_datetime(
                event.get("start_datetime"),
                event.get("end_datetime"),
                event.get("is_all_day", False)
            )

            value_lines = [dt_display]

            location = event.get("location")
            if location:
                value_lines.append(f"\U0001f4cd {location}")

            description = event.get("description")
            if description:
                truncated = description[:120] + "\u2026" if len(description) > 120 else description
                value_lines.append(f"*{truncated}*")

            embed.add_field(name=field_name, value="\n".join(value_lines), inline=False)

        embed.set_footer(text=f"Showing next {len(events)} event{'s' if len(events) != 1 else ''} \u00b7 Full calendar at portal.ecsfc.com")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScheduleCommands(bot))
