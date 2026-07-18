# nad_commands.py

"""
Discord slash command for the NAD board.

/nads lists Newly Acquired Drinkers — approved players in their first season —
and links out to the web board. /nads <person> filters by name (first, last, or
both, any order). The bot is a thin front-end: it GETs the Flask internal
endpoint, which derives the list from the same service the web board and Flutter
app use, so nothing drifts.

Auth: shared secret in the X-Bot-Token header (FLASK_TOKEN) PLUS the invoking
Discord user must map to an app user with an admin/coach role. Authorization is
done SERVER-SIDE off the real app role model (so a Global Admin in the app can
run it regardless of their Discord roles), and the board is scoped to that viewer.

Restricted to the coaches channels; the wrong-channel nudge is ephemeral, everything
else (the list, plus any error/denial) posts publicly so coaches can collaborate.
"""

import os
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from common import server_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Base already includes /api (e.g. http://webui:5000/api); v1 is the mobile_api mount.
API_BASE_URL = os.getenv("WEBUI_API_URL") or "http://webui:5000/api"
FLASK_TOKEN = os.getenv("FLASK_TOKEN", "")

ECS_GREEN = 0x1A472A

# /nads only works in the coaches channels (keeps the public roster chatter where
# coaches collaborate). Matched case-insensitively by channel name.
ALLOWED_CHANNELS = {"pl-classic-coaches", "pl-premier-coaches", "pl-all-coaches"}


class NadCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="nads",
        description="List new players (NADs), or /nads <name> to search by first/last name",
    )
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(person="Filter by name — first, last, or both (optional)")
    async def nads(self, interaction: discord.Interaction, person: str = None):
        # Restrict to the coaches channels (ephemeral nudge if used elsewhere, so it
        # doesn't spam other channels). This check happens BEFORE we defer so it can
        # stay private.
        channel_name = (getattr(interaction.channel, "name", "") or "").lower()
        if channel_name not in ALLOWED_CHANNELS:
            await interaction.response.send_message(
                "Use `/nads` in a coaches channel: **#pl-classic-coaches**, "
                "**#pl-premier-coaches**, or **#pl-all-coaches**.",
                ephemeral=True,
            )
            return

        # Public "thinking" so the result is visible to the whole channel for collab.
        await interaction.response.defer()

        url = f"{API_BASE_URL.rstrip('/')}/v1/internal/nads"
        params = {"limit": 25, "discord_id": str(interaction.user.id)}
        if person:
            params["search"] = person

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as http:
                async with http.get(url, params=params, headers={"X-Bot-Token": FLASK_TOKEN}) as resp:
                    status = resp.status
                    data = await resp.json() if resp.content_type == "application/json" else {}
        except Exception:
            logger.exception("NAD board fetch failed")
            await interaction.followup.send(
                "Couldn't pull up the board right now — give it a minute and try again."
            )
            return

        if status == 403:
            await interaction.followup.send("This one's for coaches and admins only.")
            return
        if status != 200 or not data.get("success"):
            logger.warning("NAD board returned status %s", status)
            await interaction.followup.send(
                "Couldn't pull up the board right now — give it a minute and try again."
            )
            return

        nads = data.get("nads", [])
        board_url = data.get("board_url")
        season = data.get("season_name")
        total = data.get("total", len(nads))
        detail = bool(data.get("detail"))

        # No results.
        if not nads:
            title = "Newly Acquired Drinkers" + (f" — {season}" if season else "")
            embed = discord.Embed(title=title, color=ECS_GREEN, url=board_url or None)
            msg = f"No new players matching “{person}”." if person else "No new players on the board yet."
            if board_url:
                msg += f"\n\n[Open the NAD board]({board_url})"
            embed.description = msg
            await interaction.followup.send(embed=embed, ephemeral=False)
            return

        # Small set (e.g. a name search): rich cards — photo, info, notes + authors.
        if detail:
            embeds = [self._player_embed(n, board_url) for n in nads[:10]]
            await interaction.followup.send(embeds=embeds, ephemeral=False)
            return

        # Big set: compact roster list.
        title = "Newly Acquired Drinkers" + (f" — {season}" if season else "")
        embed = discord.Embed(title=title, color=ECS_GREEN, url=board_url or None)
        lines = []
        for n in nads:
            pos = n.get("favorite_position") or "—"
            team = n.get("team_name") or "Unassigned"
            notes = n.get("note_count") or 0
            note_str = f" · 📝 {notes}" if notes else ""
            lines.append(f"**{n.get('name')}** · {pos} · {team}{note_str}")
        desc = "\n".join(lines)
        if len(desc) > 3600:
            desc = desc[:3600].rsplit("\n", 1)[0] + "\n…and more"
        desc += "\n\n_Tip: `/nads <name>` for a photo, info, and notes._"
        if board_url:
            desc += f"\n[Open the full NAD board]({board_url})"
        embed.description = desc
        embed.set_footer(text=f"{total} player{'s' if total != 1 else ''}")
        await interaction.followup.send(embed=embed, ephemeral=False)

    def _player_embed(self, n, board_url):
        """A rich per-player card: photo, info, and scouting notes with authors."""
        embed = discord.Embed(title=n.get("name") or "Unknown", color=ECS_GREEN, url=board_url or None)

        photo = n.get("profile_picture_url")
        if photo:
            embed.set_thumbnail(url=photo)

        embed.add_field(name="Team", value=n.get("team_name") or "Unassigned", inline=True)
        if n.get("jersey_size"):
            embed.add_field(name="Jersey", value=n["jersey_size"], inline=True)
        if n.get("pronouns"):
            embed.add_field(name="Pronouns", value=n["pronouns"], inline=True)
        if n.get("favorite_position"):
            embed.add_field(name="Favorite position", value=n["favorite_position"], inline=False)
        if n.get("other_positions"):
            embed.add_field(name="Also plays", value=", ".join(n["other_positions"]), inline=False)
        if n.get("positions_not_to_play"):
            embed.add_field(name="Avoid", value=", ".join(n["positions_not_to_play"]), inline=False)
        if n.get("frequency_play_goal"):
            embed.add_field(name="In goal", value=n["frequency_play_goal"], inline=True)

        notes = n.get("notes") or []
        if notes:
            blocks = []
            for nt in notes:
                author = nt.get("author") or "Unknown"
                when = (nt.get("created_at") or "")[:10]
                head = f"**{author}**" + (f" · {when}" if when else "")
                blocks.append(f"{head}\n{nt.get('content') or ''}")
            body = "\n\n".join(blocks)
            if len(body) > 3800:
                body = body[:3800].rsplit("\n\n", 1)[0] + "\n\n…more on the board"
            embed.description = "📝 **Scouting notes**\n" + body
        else:
            line = "_No notes yet._"
            if board_url:
                line += f" [Add one]({board_url})"
            embed.description = line

        return embed


async def setup(bot):
    await bot.add_cog(NadCommands(bot))
