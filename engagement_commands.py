# engagement_commands.py

"""
Engagement backfill commands.

One-time admin tool to seed Discord message-activity history into the web app's
coach-engagement / channel analytics, since live tracking only counts messages
sent after the bot was updated. Reads real channel history and pushes daily
per-(user, channel) rollups to the internal ingest endpoint with mode='set'
(idempotent — safe to re-run, recomputes each day's true count).
"""

import os
import logging
from collections import defaultdict
from datetime import timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from common import server_id, is_pl_tracked_channel

logger = logging.getLogger(__name__)

# Same leadership roles the other admin commands trust (live + dev servers).
LEADERSHIP_ROLE_IDS = [1321198676369997835, 1337234877543743601]
BATCH_SIZE = 1000


class EngagementCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _has_leadership(self, interaction: discord.Interaction) -> bool:
        return any(r.id in LEADERSHIP_ROLE_IDS for r in getattr(interaction.user, 'roles', []))

    async def _post_batch(self, items) -> bool:
        """POST one batch of rollups to the web app (mode='set')."""
        base = os.getenv("WEBUI_API_URL") or "http://webui:5000/api"
        url = f"{base.rstrip('/')}/v1/internal/discord-message-activity"
        token = os.getenv("FLASK_TOKEN", "")
        if not token:
            logger.warning("FLASK_TOKEN not set; cannot backfill message activity")
            return False
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
                async with http.post(url, json={"items": items, "mode": "set"},
                                     headers={"X-Bot-Token": token}) as resp:
                    if resp.status == 200:
                        return True
                    body = await resp.text()
                    logger.warning("Backfill batch rejected status=%s body=%s", resp.status, body[:200])
                    return False
        except Exception:
            logger.exception("Backfill batch POST failed")
            return False

    @app_commands.command(
        name="backfill_chat_history",
        description="One-time: import recent channel message history into engagement analytics (admin)",
    )
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(days="How many days of history to import (default 30, max 120)")
    async def backfill_chat_history(self, interaction: discord.Interaction, days: int = 30):
        if not self._has_leadership(interaction):
            await interaction.response.send_message(
                "You need a league leadership role to run this.", ephemeral=True)
            return

        days = max(1, min(int(days), 120))
        await interaction.response.send_message(
            f"Importing the last {days} days of channel history… I'll post a summary here when done. "
            f"This can take a few minutes.", ephemeral=True)

        guild = interaction.guild or self.bot.get_guild(server_id)
        if guild is None:
            await interaction.edit_original_response(content="Couldn't resolve the guild.")
            return

        cutoff = discord.utils.utcnow() - timedelta(days=days)
        # key: (user_id, channel_id, 'YYYY-MM-DD') -> {count, last_iso, channel_name, guild_id}
        agg = defaultdict(lambda: {'count': 0, 'last_iso': None, 'channel_name': None, 'guild_id': None})

        channels_scanned = 0
        channels_skipped = 0
        total_messages = 0

        for channel in guild.text_channels:
            # Pub-league channels only (team + PL general chats), gated by
            # category — matches what live tracking records.
            if not is_pl_tracked_channel(channel):
                continue
            perms = channel.permissions_for(guild.me)
            if not (perms.read_messages and perms.read_message_history):
                channels_skipped += 1
                continue
            try:
                async for msg in channel.history(limit=None, after=cutoff, oldest_first=True):
                    if msg.author.bot:
                        continue
                    created = msg.created_at
                    key = (str(msg.author.id), str(channel.id), created.strftime("%Y-%m-%d"))
                    entry = agg[key]
                    entry['count'] += 1
                    iso = created.replace(tzinfo=None).isoformat()
                    if entry['last_iso'] is None or iso > entry['last_iso']:
                        entry['last_iso'] = iso
                    entry['channel_name'] = channel.name
                    entry['guild_id'] = str(guild.id)
                    total_messages += 1
                channels_scanned += 1
            except discord.Forbidden:
                channels_skipped += 1
            except Exception:
                logger.exception("Backfill failed reading channel %s", channel.id)
                channels_skipped += 1

        # Flush in batches.
        items = []
        for (user_id, channel_id, stat_date), e in agg.items():
            items.append({
                'discord_user_id': user_id,
                'channel_id': channel_id,
                'guild_id': e['guild_id'],
                'channel_name': e['channel_name'],
                'stat_date': stat_date,
                'message_count': e['count'],
                'last_message_at': e['last_iso'],
            })

        sent = 0
        failed_batches = 0
        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i:i + BATCH_SIZE]
            ok = await self._post_batch(batch)
            if ok:
                sent += len(batch)
            else:
                failed_batches += 1

        summary = (
            f"**Chat history backfill complete** (last {days} days, pub-league channels)\n"
            f"• Channels scanned: **{channels_scanned}** (skipped {channels_skipped} — no read access)\n"
            f"• Messages counted: **{total_messages:,}**\n"
            f"• Rollup rows written: **{sent:,}**"
            + (f"\n• ⚠️ {failed_batches} batch(es) failed — check logs" if failed_batches else "")
        )
        try:
            await interaction.edit_original_response(content=summary)
        except Exception:
            # Interaction token may have expired on long runs — fall back to channel.
            try:
                await interaction.channel.send(summary)
            except Exception:
                logger.info("Backfill summary (could not deliver to Discord): %s", summary)


async def setup(bot):
    await bot.add_cog(EngagementCommands(bot))
