# app/models/engagement.py

"""
Engagement Tracking Models

Backs the Coach Engagement + community Discord analytics on the admin panel.
Both tables are DAILY ROLLUPS (one row per entity per day) rather than
per-event rows, so volume stays bounded no matter how chatty a channel is.

DiscordMessageStat   - per-(discord_user, channel, day) message counts. Fed by
                       the bot via the /api/v1/internal/discord-message-activity
                       endpoint. team_id is resolved server-side from channel_id
                       (null = a non-team / community channel).
CoachEngagementEvent - per-(user, team, activity_type, source, day) counts of
                       coach actions that have no other audit trail, primarily
                       RSVP viewing and reminder sends across web/mobile.
"""

from datetime import datetime

from app.core import db


class DiscordMessageStat(db.Model):
    """Daily message-count rollup per Discord user per channel.

    A row is upserted (count += n, last_message_at = max) by the internal
    bot-fed endpoint. Aggregations:
      - coach participation in a team channel: filter team_id + discord_user_id
      - general channel usage: group by channel_id / team_id over stat_date
    """
    __tablename__ = 'discord_message_stats'

    id = db.Column(db.Integer, primary_key=True)
    discord_user_id = db.Column(db.String(30), nullable=False, index=True)
    channel_id = db.Column(db.String(30), nullable=False, index=True)
    guild_id = db.Column(db.String(30), nullable=True)
    # Resolved by Flask from channel_id at write time. Null = community / non-team
    # channel (general, announcements, etc.) — still counted for usage metrics.
    team_id = db.Column(
        db.Integer,
        db.ForeignKey('team.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # Snapshot of the channel name so community metrics can label non-team
    # channels without a live Discord lookup.
    channel_name = db.Column(db.String(120), nullable=True)
    stat_date = db.Column(db.Date, nullable=False, index=True)
    message_count = db.Column(db.Integer, nullable=False, default=0)
    last_message_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            'discord_user_id', 'channel_id', 'stat_date',
            name='uq_discord_message_stats_user_channel_day',
        ),
        db.Index('idx_discord_message_stats_team_date', 'team_id', 'stat_date'),
        db.Index('idx_discord_message_stats_channel_date', 'channel_id', 'stat_date'),
    )

    def __repr__(self):
        return (f"<DiscordMessageStat user={self.discord_user_id} "
                f"chan={self.channel_id} {self.stat_date} x{self.message_count}>")


class CoachEngagementEvent(db.Model):
    """Daily rollup of coach actions that aren't otherwise audited.

    Match reports / lineups already carry per-user attribution
    (PlayerEvent.reported_by, Match.*_verified_by, MatchLineup.created_by), so
    those are read directly. This table captures the gaps — chiefly RSVP
    *viewing* (web + mobile coach surfaces) and reminder sends — which leave no
    trace anywhere else.
    """
    __tablename__ = 'coach_engagement_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    team_id = db.Column(
        db.Integer,
        db.ForeignKey('team.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # e.g. 'rsvp_view', 'rsvp_reminder', 'rsvp_override'
    activity_type = db.Column(db.String(40), nullable=False, index=True)
    # 'web' | 'mobile' | 'discord'
    source = db.Column(db.String(20), nullable=False, default='web')
    stat_date = db.Column(db.Date, nullable=False, index=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    last_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'team_id', 'activity_type', 'source', 'stat_date',
            name='uq_coach_engagement_user_team_type_source_day',
        ),
        db.Index('idx_coach_engagement_team_date', 'team_id', 'stat_date'),
    )

    def __repr__(self):
        return (f"<CoachEngagementEvent user={self.user_id} team={self.team_id} "
                f"{self.activity_type}/{self.source} {self.stat_date} x{self.count}>")

class DiscordChannelRole(db.Model):
    """Classifies the COACH Discord channels for the involvement metric.

    Team channels are derived from ``team.discord_channel_id`` and are NOT stored
    here. This table only records the coaches channels and which cohort each one
    belongs to, so a coach is measured against the channels they can actually
    reach:

        coach_global  -> the all-coaches channel (both divisions can post)
        coach_premier -> Premier coaches channel
        coach_classic -> Classic coaches channel

    Matched by ``channel_id`` (stable) rather than name, so a Discord rename does
    not silently drop the channel from tracking.
    """
    __tablename__ = 'discord_channel_role'

    ROLE_GLOBAL = 'coach_global'
    ROLE_PREMIER = 'coach_premier'
    ROLE_CLASSIC = 'coach_classic'
    ROLES = (ROLE_GLOBAL, ROLE_PREMIER, ROLE_CLASSIC)

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.String(30), nullable=False, unique=True)
    channel_name = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(20), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<DiscordChannelRole {self.role} {self.channel_name} ({self.channel_id})>"

class CoachAttentionReview(db.Model):
    """Marks a coach as 'reviewed' in the support queue for a season.

    Set when an admin has acted on a coach the Needs-attention queue surfaced, so
    they drop off the list. Per-season (unique on season_id + player_id), so a new
    season starts the queue clean.
    """
    __tablename__ = 'coach_attention_review'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='CASCADE'), nullable=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    note = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('season_id', 'player_id', name='uq_coach_attention_review'),
        db.Index('ix_coach_attention_review_season', 'season_id'),
    )

    def __repr__(self):
        return f"<CoachAttentionReview season={self.season_id} player={self.player_id}>"
