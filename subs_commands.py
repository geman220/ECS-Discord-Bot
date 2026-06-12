# subs_commands.py

"""
Discord slash commands for the substitute system.

Phase 1: /subs request — a coach requests substitute(s) for their team's
upcoming match(es). The bot is a thin front-end: it resolves the coach,
shows pickers, and POSTs to the Flask internal endpoints, which own all
authorization and write into the same SubstituteRequest backend the WebUI
and Flutter app use. Pub League only for now (ECS FC is deferred).

Auth to Flask: shared secret in the X-Bot-Token header (FLASK_TOKEN), the
same trust boundary the poll-vote webhook uses. The bot never holds a JWT.

Custom IDs for any future persistent components must use the frozen grammar
SUBS_CID_PREFIX below so already-posted messages keep working across restarts.
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

# Base already includes /api (e.g. http://webui:5000/api); v1 is the mobile_api_v2 mount.
API_BASE_URL = os.getenv("WEBUI_API_URL") or "http://webui:5000/api"
FLASK_TOKEN = os.getenv("FLASK_TOKEN", "")

# Frozen custom_id grammar for future persistent views (sub answer buttons, etc.)
SUBS_CID_PREFIX = "subs:v1:"

# How many upcoming matches a coach may flag in one request.
MAX_MATCHES_PER_REQUEST = 5

# Discord coach roles allowed to use /subs request. These are synced FROM the
# backend player_teams.is_coach flag (see webui app/discord_utils.py), so a real
# coach has them. This is a fast first-line gate; the Flask endpoint still
# re-verifies is_coach_for_team(coach, team) before writing anything.
COACH_ROLE_NAMES = {"ECS-FC-PL-PREMIER-COACH", "ECS-FC-PL-CLASSIC-COACH"}


def _has_coach_role(member) -> bool:
    """True if the member holds a Premier/Classic coach Discord role."""
    roles = getattr(member, "roles", None)
    if not roles:
        return False
    return any((r.name or "").strip().upper() in COACH_ROLE_NAMES for r in roles)


def _internal_url(path: str) -> str:
    return f"{API_BASE_URL.rstrip('/')}/v1/internal/subs/{path.lstrip('/')}"


def _format_match_label(m: dict) -> str:
    """e.g. 'Sun Jun 14 · 8:20am vs Radiator Sprints'."""
    date_str = m.get("date") or "TBD"
    time_str = m.get("time") or ""
    # date arrives as ISO 'YYYY-MM-DD'; render a short human form without extra deps.
    try:
        from datetime import date as _date
        d = _date.fromisoformat(date_str)
        date_str = d.strftime("%a %b %-d")
    except Exception:
        pass
    if time_str:
        try:
            hh, mm = time_str.split(":")[:2]
            h = int(hh)
            ampm = "am" if h < 12 else "pm"
            h12 = h % 12 or 12
            time_str = f"{h12}:{mm}{ampm}"
        except Exception:
            pass
    opp = m.get("opponent_name") or "TBD"
    side = "vs" if m.get("is_home") else "at"
    bits = [date_str]
    if time_str:
        bits.append(time_str)
    return f"{' · '.join(bits)} {side} {opp}"


class SubsRequestModal(discord.ui.Modal):
    """Collects how many subs + positions + notes, then files the request(s)."""

    def __init__(self, cog, user_id, team_id, team_name, selected_matches):
        super().__init__(title="Substitute request")
        self.cog = cog
        self.user_id = user_id
        self.team_id = team_id
        self.team_name = team_name
        self.selected_matches = selected_matches

        self.count = discord.ui.TextInput(
            label="How many subs?",
            default="1",
            required=True,
            max_length=2,
            style=discord.TextStyle.short,
        )
        self.positions = discord.ui.TextInput(
            label="Positions (optional)",
            placeholder="e.g. Keeper, or any",
            required=False,
            max_length=120,
            style=discord.TextStyle.short,
        )
        self.notes = discord.ui.TextInput(
            label="Notes (optional)",
            placeholder="e.g. regular keeper is out injured",
            required=False,
            max_length=400,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.count)
        self.add_item(self.positions)
        self.add_item(self.notes)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            # Clamp to the same 1..10 range the backend enforces, so the
            # confirmation message can't promise more than gets stored.
            count = max(1, min(int(str(self.count.value).strip()), 10))
        except (TypeError, ValueError):
            count = 1

        positions = str(self.positions.value or "").strip()
        notes = str(self.notes.value or "").strip()

        created, duplicates, failed = [], [], []
        board_url = None
        for m in self.selected_matches:
            body = {
                "acting_coach_user_id": self.user_id,
                "team_id": self.team_id,
                "match_id": m["match_id"],
                "substitutes_needed": count,
                "positions_needed": positions,
                "notes": notes,
                "discord_channel_id": str(interaction.channel_id) if interaction.channel_id else None,
                "discord_message_id": None,
            }
            status, data = await self.cog.api_post("requests", body)
            if status in (200, 201) and data.get("success"):
                board_url = data.get("board_url") or board_url
                (duplicates if data.get("duplicate") else created).append(m)
            else:
                failed.append((m, (data or {}).get("msg", f"HTTP {status}")))

        await interaction.followup.send(
            content=self.cog.build_result_message(self.team_name, count, created, duplicates, failed),
            ephemeral=True,
        )

        # Echo a coordinator-actionable summary into the channel it was filed in
        # (best-effort; the request already exists regardless). Other coaches can
        # see it for transparency but the WebUI link is admin-gated.
        if created and interaction.channel is not None:
            try:
                embed = discord.Embed(
                    title=f"Sub request — {self.team_name}",
                    description=f"Requested by {interaction.user.mention}",
                    color=0x1A4A2A,
                )
                needs = "\n".join(
                    f"• {_format_match_label(m)} — {count} sub{'s' if count != 1 else ''}"
                    for m in created
                )
                embed.add_field(name="Needs", value=needs, inline=False)
                if positions:
                    embed.add_field(name="Positions", value=positions, inline=True)
                if notes:
                    embed.add_field(name="Notes", value=notes, inline=False)
                embed.set_footer(text="Sub coordinators can pick this up on the board")

                view = discord.ui.View()
                if board_url:
                    view.add_item(discord.ui.Button(
                        style=discord.ButtonStyle.link, label="Open in WebUI", url=board_url
                    ))
                if view.children:
                    await interaction.channel.send(embed=embed, view=view)
                else:
                    await interaction.channel.send(embed=embed)
            except Exception:
                pass


class MatchSelect(discord.ui.Select):
    def __init__(self, cog, user_id, team_id, team_name, matches):
        self.cog = cog
        self.user_id = user_id
        self.team_id = team_id
        self.team_name = team_name
        self.matches_by_id = {str(m["match_id"]): m for m in matches}

        options = [
            discord.SelectOption(label=_format_match_label(m)[:100], value=str(m["match_id"]))
            for m in matches[:25]
        ]
        super().__init__(
            placeholder="Which match(es) need subs?",
            min_values=1,
            max_values=min(len(options), MAX_MATCHES_PER_REQUEST),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = [self.matches_by_id[v] for v in self.values if v in self.matches_by_id]
        await interaction.response.send_modal(
            SubsRequestModal(self.cog, self.user_id, self.team_id, self.team_name, selected)
        )


class MatchSelectView(discord.ui.View):
    def __init__(self, cog, user_id, team_id, team_name, matches):
        super().__init__(timeout=180)
        self.add_item(MatchSelect(cog, user_id, team_id, team_name, matches))


class TeamSelect(discord.ui.Select):
    def __init__(self, cog, user_id, teams):
        self.cog = cog
        self.user_id = user_id
        self.teams_by_id = {str(t["team_id"]): t for t in teams}
        options = [
            discord.SelectOption(
                label=t["team_name"][:100],
                description=(t.get("league_name") or None),
                value=str(t["team_id"]),
            )
            for t in teams[:25]
        ]
        super().__init__(placeholder="Which team are you requesting for?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        team = self.teams_by_id[self.values[0]]
        await interaction.response.defer()
        matches = await self.cog.fetch_upcoming(team["team_id"])
        if not matches:
            await interaction.edit_original_response(
                content=f"No upcoming matches found for **{team['team_name']}**.", view=None
            )
            return
        await interaction.edit_original_response(
            content=f"**{team['team_name']}** — pick the match(es) you need subs for:",
            view=MatchSelectView(self.cog, self.user_id, team["team_id"], team["team_name"], matches),
        )


class TeamSelectView(discord.ui.View):
    def __init__(self, cog, user_id, teams):
        super().__init__(timeout=180)
        self.add_item(TeamSelect(cog, user_id, teams))


class SubsCommands(commands.Cog):
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

    # ---- Flask internal API helpers (X-Bot-Token trust boundary) ----

    async def api_get(self, path, params=None):
        session = await self.get_session()
        try:
            async with session.get(
                _internal_url(path),
                params=params or {},
                headers={"X-Bot-Token": FLASK_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                return resp.status, data
        except Exception as e:
            logger.error(f"[subs] GET {path} failed: {e}", exc_info=True)
            return 0, {}

    async def api_post(self, path, body, timeout=10):
        session = await self.get_session()
        try:
            async with session.post(
                _internal_url(path),
                json=body,
                headers={"X-Bot-Token": FLASK_TOKEN},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                return resp.status, data
        except Exception as e:
            logger.error(f"[subs] POST {path} failed: {e}", exc_info=True)
            return 0, {}

    async def fetch_upcoming(self, team_id):
        status, data = await self.api_get("upcoming", {"team_id": team_id})
        if status == 200:
            return data.get("matches", [])
        return []

    @staticmethod
    def build_result_message(team_name, count, created, duplicates, failed):
        lines = []
        if created:
            plural = "sub" if count == 1 else "subs"
            lines.append(
                f"Got it — logged {len(created)} request(s) for **{team_name}** "
                f"({count} {plural} each). The coordinators will take it from here."
            )
        if duplicates:
            lines.append(f"{len(duplicates)} match(es) already had an open request, so I left those as-is.")
        if failed:
            detail = "; ".join(f"{_format_match_label(m)} ({reason})" for m, reason in failed)
            lines.append(f"Couldn't file {len(failed)}: {detail}")
        if not lines:
            lines.append("Nothing was submitted.")
        return "\n".join(lines)

    # ---- /subs request ----

    subs = app_commands.Group(
        name="subs",
        description="Substitute requests",
        guild_ids=[server_id],
    )

    @subs.command(name="request", description="Request substitute(s) for your team's upcoming match")
    async def request(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Hard gate: must hold a Premier/Classic coach role before any backend call.
        if not _has_coach_role(interaction.user):
            await interaction.followup.send(
                "This one's for team coaches — you'll need the Premier or Classic coach role to "
                "request subs. If you coach and you're seeing this, ping a sub coordinator so they "
                "can sort your roles out.",
                ephemeral=True,
            )
            return

        status, ctx = await self.api_get("coach-context", {"discord_id": str(interaction.user.id)})
        if status != 200:
            await interaction.followup.send(
                "Couldn't reach the league portal just now — give it a minute and try again.",
                ephemeral=True,
            )
            return

        if not ctx.get("linked"):
            await interaction.followup.send(
                "I couldn't find your portal account linked to this Discord. "
                "Link it on your profile at the portal, then try again.",
                ephemeral=True,
            )
            return

        teams = ctx.get("teams") or []
        if not teams:
            await interaction.followup.send(
                "You're not listed as a coach for a Pub League team this season, "
                "so there's nothing to request subs for. Reach out to an admin if that's wrong.",
                ephemeral=True,
            )
            return

        user_id = ctx["user_id"]

        if len(teams) > 1:
            await interaction.followup.send(
                "Which team is this for?",
                view=TeamSelectView(self, user_id, teams),
                ephemeral=True,
            )
            return

        team = teams[0]
        matches = await self.fetch_upcoming(team["team_id"])
        if not matches:
            await interaction.followup.send(
                f"No upcoming matches found for **{team['team_name']}**.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            content=f"**{team['team_name']}** — pick the match(es) you need subs for:",
            view=MatchSelectView(self, user_id, team["team_id"], team["team_name"], matches),
            ephemeral=True,
        )

    @subs.command(
        name="poll",
        description="Post a sub-availability poll to #pl-subs (sub coordinators only)",
    )
    @app_commands.describe(date="Sunday to poll for as YYYY-MM-DD (defaults to the next Sunday)")
    async def poll(self, interaction: discord.Interaction, date: str = None):
        await interaction.response.defer(ephemeral=True, thinking=True)

        body = {"discord_id": str(interaction.user.id)}
        if date:
            body["match_date"] = date.strip()

        # Flask's own call to the bot allows 15s, so this must be longer or a
        # slow post looks like a failure and a retry double-posts the poll.
        status, data = await self.api_post("poll", body, timeout=30)
        if status != 200 or not isinstance(data, dict):
            await interaction.followup.send(
                "Couldn't post the poll just now — try again in a minute.",
                ephemeral=True,
            )
            return

        if not data.get("success"):
            reason = data.get("reason")
            if reason == "not_linked":
                msg = ("I couldn't find your portal account linked to this Discord. "
                       "Link it on your profile, then try again.")
            elif reason == "not_authorized":
                msg = "Only sub coordinators can post availability polls."
            elif reason == "no_matches":
                md = data.get("match_date", "that day")
                msg = f"No Pub League matches are scheduled for {md}, so there's nothing to poll for."
            elif reason == "duplicate":
                md = data.get("match_date", "that day")
                url = data.get("discord_message_url") or ""
                msg = f"There's already a live availability poll for {md}."
                if url:
                    msg += f"\n{url}"
            else:
                msg = data.get("msg") or "Couldn't post the poll."
            await interaction.followup.send(msg, ephemeral=True)
            return

        buckets = data.get("buckets") or []
        url = data.get("discord_message_url") or ""
        lines = [f"Posted the availability poll for **{data.get('match_date', '')}** in #pl-subs."]
        if buckets:
            lines.append("Slots: " + ", ".join(buckets))
        if url:
            lines.append(url)
        await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot):
    await bot.add_cog(SubsCommands(bot))
