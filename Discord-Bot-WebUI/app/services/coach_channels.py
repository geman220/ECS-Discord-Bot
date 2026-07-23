# app/services/coach_channels.py

"""
Admin management of the coach-channel classification (DiscordChannelRole).

The coach-engagement chat signal counts only a coach's REACHABLE channels: their
team channel plus their division and global coaches channels. Team channels are
derived from ``team.discord_channel_id``; this module lets an admin classify the
COACH channels (global / premier / classic) that can't be derived from a team.

Matching downstream is by ``channel_id``, so a Discord rename never silently drops
a channel from tracking — the admin only re-touches it if the id itself changes.
"""

import logging

from sqlalchemy import func

logger = logging.getLogger(__name__)


def list_classifiable_channels(session):
    """Every channel we've seen activity in, with its current classification.

    Returns dicts sorted so classified coaches channels come first, then team
    channels (shown but not classifiable), then the rest by volume.
    """
    from app.models import DiscordMessageStat, DiscordChannelRole, Team

    rows = (
        session.query(
            DiscordMessageStat.channel_id,
            func.max(DiscordMessageStat.channel_name).label('name'),
            func.coalesce(func.sum(DiscordMessageStat.message_count), 0).label('msgs'),
            func.max(DiscordMessageStat.last_message_at).label('last_at'),
        )
        .group_by(DiscordMessageStat.channel_id)
        .all()
    )
    roles = {
        str(cid): role
        for cid, role in session.query(DiscordChannelRole.channel_id, DiscordChannelRole.role).all()
    }
    team_chans = {
        str(cid): name
        for cid, name in session.query(Team.discord_channel_id, Team.name)
        .filter(Team.discord_channel_id.isnot(None)).all()
    }

    out = []
    for r in rows:
        cid = str(r.channel_id)
        out.append({
            'channel_id': cid,
            'channel_name': r.name,
            'messages': int(r.msgs or 0),
            'last_at': r.last_at.isoformat() if r.last_at else None,
            'role': roles.get(cid),                 # None = untracked
            'is_team': cid in team_chans,
            'team_name': team_chans.get(cid),
        })

    # A classified coach channel that ALSO shows up as a team channel is a conflict
    # the read path strips defensively; surface it here so an admin can fix it.
    for c in out:
        c['conflict'] = bool(c['role'] and c['is_team'])

    out.sort(key=lambda c: (0 if c['role'] else (1 if c['is_team'] else 2), -c['messages']))
    return out


def set_channel_role(session, channel_id, role, channel_name=None):
    """Classify a channel as a coaches channel. Returns (ok, message).

    Refuses team channels: a team channel is already tracked via
    ``team.discord_channel_id``, and letting it also be a coaches channel would
    double-count its activity in the chat pillar.
    """
    from app.models import DiscordChannelRole, Team

    channel_id = str(channel_id)
    if role not in DiscordChannelRole.ROLES:
        return False, 'Unknown role.'

    is_team = session.query(Team.id).filter(Team.discord_channel_id == channel_id).first()
    if is_team:
        return False, ('That is a team channel — team channels are tracked automatically '
                       'and cannot also be a coaches channel.')

    existing = session.query(DiscordChannelRole).filter_by(channel_id=channel_id).first()
    if existing:
        existing.role = role
        if channel_name:
            existing.channel_name = channel_name
    else:
        session.add(DiscordChannelRole(channel_id=channel_id, channel_name=channel_name, role=role))
    logger.info(f"Coach channel {channel_id} classified as {role}")
    return True, 'Channel classified.'


def clear_channel_role(session, channel_id):
    """Remove a channel's coach classification. Returns (ok, message)."""
    from app.models import DiscordChannelRole
    session.query(DiscordChannelRole).filter_by(channel_id=str(channel_id)).delete()
    return True, 'Classification cleared.'
