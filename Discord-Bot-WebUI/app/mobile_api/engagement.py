# app/mobile_api/engagement.py

"""
Internal engagement ingest endpoint (bot-fed).

The Discord bot batches per-(user, channel, day) message counts in memory and
flushes them here periodically. Mirrors the /internal/discord-poll-vote trust
boundary: shared FLASK_TOKEN secret in the X-Bot-Token header, no per-user JWT.
Flask owns the channel->team resolution and the daily-rollup upsert.
"""

import logging
import os

from flask import jsonify, request, g

from app.mobile_api import mobile_api_v2
from app.engagement_service import upsert_message_stats

logger = logging.getLogger(__name__)


def _bot_token_ok() -> bool:
    expected = os.getenv('FLASK_TOKEN')
    token = request.headers.get('X-Bot-Token', '')
    return bool(expected) and bool(token) and token == expected


@mobile_api_v2.route('/internal/discord-message-activity', methods=['POST'])
def receive_discord_message_activity():
    """Ingest a batch of daily message-count rollups from the bot.

    Auth: X-Bot-Token == FLASK_TOKEN.
    Body: {
        "items": [
            {
              "discord_user_id": "123",
              "channel_id": "456",
              "guild_id": "789",
              "channel_name": "team-a",
              "stat_date": "2026-06-22",
              "message_count": 14,
              "last_message_at": "2026-06-22T18:03:11Z"
            }, ...
        ]
    }
    Bot-author / system messages must be filtered bot-side before sending.
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    items = data.get('items')
    mode = data.get('mode', 'add')
    if mode not in ('add', 'set'):
        return jsonify({"msg": "mode must be 'add' or 'set'"}), 400
    if not isinstance(items, list):
        return jsonify({"msg": "items must be a list"}), 400
    if not items:
        return jsonify({"success": True, "processed": 0}), 200
    # Guard against an oversized flush wedging a request.
    if len(items) > 5000:
        return jsonify({"msg": "too many items (max 5000)"}), 413

    session = getattr(g, 'db_session', None)
    if session is None:
        return jsonify({"msg": "Database session not available"}), 500

    try:
        processed = upsert_message_stats(session, items, mode=mode)
    except Exception:
        logger.exception("Failed to upsert discord message activity batch")
        return jsonify({"msg": "internal error"}), 500

    return jsonify({"success": True, "processed": processed}), 200
