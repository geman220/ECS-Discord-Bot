# app/engagement_service.py

"""
Engagement tracking service.

Two write paths, both daily-rollup upserts (PostgreSQL ON CONFLICT) so repeated
events on the same day collapse into a single counted row:

  upsert_message_stats()   - bulk path fed by the Discord bot via
                             /api/v1/internal/discord-message-activity
  record_coach_engagement()- single-event path called inline from RSVP-view /
                             reminder routes (web + mobile). Best-effort: it
                             never raises into the caller's request.

Read helpers for the analytics pages live in
app/admin_panel/routes/user_management/engagement.py, not here.
"""

import logging
from datetime import datetime, date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.engagement import DiscordMessageStat, CoachEngagementEvent
from app.models.players import Team

logger = logging.getLogger(__name__)


def _channel_team_map(session, channel_ids):
    """{channel_id(str): team_id} for the given Discord channel ids.

    Team.discord_channel_id is the authoritative team<->channel link. Channels
    with no team (general/announcements) are simply absent from the map, so
    their stats land with team_id=NULL and count as community channels.
    """
    if not channel_ids:
        return {}
    rows = (
        session.query(Team.discord_channel_id, Team.id, Team.name)
        .filter(Team.discord_channel_id.in_([str(c) for c in channel_ids]))
        .all()
    )
    return {str(chan): (tid, tname) for chan, tid, tname in rows}


def upsert_message_stats(session, items, mode='add'):
    """Bulk-upsert daily message rollups.

    `items` is a list of dicts:
        {discord_user_id, channel_id, guild_id, channel_name,
         stat_date ('YYYY-MM-DD' or date), message_count, last_message_at (iso/dt)}

    mode:
        'add' (default) — live path; existing day count += this batch's count.
        'set'           — backfill path; existing day count is OVERWRITTEN with
                          this value. The count is recomputed from real channel
                          history, so a day's value is authoritative and the
                          backfill is idempotent (safe to re-run, no double count).

    Returns the number of rows processed. Raises on DB error (caller decides).
    """
    if not items:
        return 0

    channel_ids = {str(it.get('channel_id')) for it in items if it.get('channel_id')}
    chan_map = _channel_team_map(session, channel_ids)

    processed = 0
    for it in items:
        channel_id = str(it.get('channel_id') or '').strip()
        discord_user_id = str(it.get('discord_user_id') or '').strip()
        if not channel_id or not discord_user_id:
            continue

        stat_date = it.get('stat_date')
        if isinstance(stat_date, str):
            stat_date = date.fromisoformat(stat_date[:10])
        elif stat_date is None:
            stat_date = datetime.utcnow().date()

        last_at = it.get('last_message_at')
        if isinstance(last_at, str):
            try:
                last_at = datetime.fromisoformat(last_at.replace('Z', '+00:00'))
                if last_at.tzinfo is not None:
                    last_at = last_at.replace(tzinfo=None)
            except ValueError:
                last_at = None

        team_id, channel_name = chan_map.get(channel_id, (None, None))
        # Prefer the live channel name the bot sent for non-team channels.
        channel_name = channel_name or it.get('channel_name')
        msg_count = int(it.get('message_count') or 0)

        stmt = pg_insert(DiscordMessageStat.__table__).values(
            discord_user_id=discord_user_id,
            channel_id=channel_id,
            guild_id=str(it.get('guild_id')) if it.get('guild_id') else None,
            team_id=team_id,
            channel_name=channel_name,
            stat_date=stat_date,
            message_count=msg_count,
            last_message_at=last_at,
        ).on_conflict_do_update(
            index_elements=['discord_user_id', 'channel_id', 'stat_date'],
            set_={
                # 'set' overwrites (idempotent backfill); 'add' accumulates (live).
                'message_count': (msg_count if mode == 'set'
                                  else DiscordMessageStat.message_count + msg_count),
                # GREATEST ignores NULLs in PostgreSQL, so a missing existing
                # timestamp is fine.
                'last_message_at': func.greatest(
                    DiscordMessageStat.last_message_at,
                    last_at,
                ),
                'team_id': team_id,
                'channel_name': func.coalesce(channel_name, DiscordMessageStat.channel_name),
            },
        )
        session.execute(stmt)
        processed += 1

    return processed


def record_coach_engagement(user_id, team_id, activity_type, source='web', when=None):
    """Best-effort daily-rollup increment for a coach action (RSVP view, etc.).

    Uses its OWN isolated session (not the request's g.db_session) so it commits
    only this single insert and can never prematurely commit or poison the
    caller's request transaction. Swallows all errors — engagement metrics must
    never break a coach's ability to view RSVPs or send a reminder.
    """
    if not user_id or not activity_type:
        return
    session = None
    try:
        from flask import current_app
        when = when or datetime.utcnow()
        stat_date = when.date()
        session = current_app.SessionLocal()
        stmt = pg_insert(CoachEngagementEvent.__table__).values(
            user_id=int(user_id),
            team_id=int(team_id) if team_id else None,
            activity_type=activity_type,
            source=source,
            stat_date=stat_date,
            count=1,
            last_at=when,
        ).on_conflict_do_update(
            index_elements=['user_id', 'team_id', 'activity_type', 'source', 'stat_date'],
            set_={
                'count': CoachEngagementEvent.count + 1,
                'last_at': when,
            },
        )
        session.execute(stmt)
        session.commit()
    except Exception:  # noqa: BLE001 - logging must never break the request
        logger.debug("record_coach_engagement failed (non-fatal)", exc_info=True)
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
