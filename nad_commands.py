# nad_commands.py

"""
Discord slash command for the NAD board.

/nads lists Newly Acquired Drinkers — approved players in their first season —
and links out to the full web board. The bot is a thin front-end: it GETs the
Flask internal endpoint, which derives the list from the same service the web
board and Flutter app use, so nothing drifts.

Auth to Flask: shared secret in the X-Bot-Token header (FLASK_TOKEN), the same
trust boundary the other internal endpoints use. The bot never holds a JWT.
Command access is gated in Discord to admins / leadership / coaches.
"""

import os
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from common import server_id, has_admin_role

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Base already includes /api (e.g. http://webui:5000/api); v1 is the mobile_api mount.
API_BASE_URL = os.getenv("WEBUI_API_URL") or "http://webui:5000/api"
FLASK_TOKEN = os.getenv("FLASK_TOKEN", "")

LEADERSHIP_ROLE_NAMES = {"WG: ECS FC PL Leadership"}
COACH_ROLE_NAMES = {"ECS-FC-PL-PREMIER-COACH", "ECS-FC-PL-CLASSIC-COACH"}

ECS_GREEN = 0x1A472A


async def _can_view_nads(interaction: discord.Interaction) -> bool:
    """Admins, leadership, and Premier/Classic coaches may view the board."""
    if await has_admin_role(interaction):
        return True
    names = {(r.name or "").strip() for r in getattr(interaction.user, "roles", [])}
    if names & LEADERSHIP_ROLE_NAMES:
        return True
    return bool({n.upper() for n in names} & COACH_ROLE_NAMES)


class NadCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="nads",
        description="List new players (Newly Acquired Drinkers) or grab the board link",
    )
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(search="Filter by name (optional)")
    async def nads(self, interaction: discord.Interaction, search: str = None):
        if not await _can_view_nads(interaction):
            await interaction.response.send_message(
                "This one's for coaches and admins only.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        url = f"{API_BASE_URL.rstrip('/')}/v1/internal/nads"
        params = {"limit": 25}
        if search:
            params["search"] = search

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as http:
                async with http.get(url, params=params, headers={"X-Bot-Token": FLASK_TOKEN}) as resp:
                    if resp.status != 200:
                        logger.warning("NAD board fetch returned %s", resp.status)
                        await interaction.followup.send(
                            "Couldn't pull up the board right now — give it a minute and try again.",
                            ephemeral=True,
                        )
                        return
                    data = await resp.json()
        except Exception:
            logger.exception("NAD board fetch failed")
            await interaction.followup.send(
                "Couldn't pull up the board right now — give it a minute and try again.",
                ephemeral=True,
            )
            return

        nads = data.get("nads", [])
        board_url = data.get("board_url")
        season = data.get("season_name")
        total = data.get("total", len(nads))

        title = "Newly Acquired Drinkers"
        if season:
            title += f" — {season}"
        embed = discord.Embed(title=title, color=ECS_GREEN, url=board_url or None)

        if not nads:
            msg = "No new players on the board yet."
            if search:
                msg = f"No new players matching “{search}”."
            if board_url:
                msg += f"\n\n[Open the NAD board]({board_url})"
            embed.description = msg
        else:
            lines = []
            for n in nads:
                pos = n.get("favorite_position") or "—"
                team = n.get("team_name") or "Unassigned"
                notes = n.get("note_count") or 0
                note_str = f" · 📝 {notes}" if notes else ""
                lines.append(f"**{n.get('name')}** · {pos} · {team}{note_str}")
            desc = "\n".join(lines)
            if len(desc) > 3800:
                desc = desc[:3800].rsplit("\n", 1)[0] + "\n…and more"
            if board_url:
                desc += f"\n\n[Open the full NAD board]({board_url})"
            embed.description = desc
            embed.set_footer(text=f"{total} player{'s' if total != 1 else ''}")

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(NadCommands(bot))
