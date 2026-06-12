# app/models/discord_polls.py

"""
Native Discord Poll Tracking Models

Backs the /api/v1/substitutes/discord/availability-poll feature.

DiscordPoll        - one row per poll posted via the mobile sub center
DiscordPollVote    - one row per add/remove vote event from the bot
"""

from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB

from app.core import db


class DiscordPoll(db.Model):
    __tablename__ = 'discord_polls'

    id = db.Column(db.Integer, primary_key=True)
    discord_message_id = db.Column(db.String(20), nullable=False, unique=True, index=True)
    channel_id = db.Column(db.String(20), nullable=False)
    channel_key = db.Column(db.String(50), nullable=False, index=True)
    guild_id = db.Column(db.String(20), nullable=True)
    title = db.Column(db.Text, nullable=False)
    match_date = db.Column(db.Date, nullable=True, index=True)
    options = db.Column(JSONB, nullable=False)  # [{"answer_id": 1, "text": "...", "emoji": "..."}, ...]
    # 'generic' = an ad-hoc poll; 'availability' = a reconcilable sub-availability
    # poll whose slot_map ties each answer_id to real match_ids + league.
    poll_kind = db.Column(db.String(20), nullable=True, default='generic')
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)
    # slot_map: {"<answer_id>": {"league_type": "Premier", "label": "...",
    #            "slots": ["08:20","09:30"], "match_ids": [123,124]}}
    # Keys are STRINGS (JSON) — always look up via str(vote.answer_id).
    slot_map = db.Column(JSONB, nullable=True)
    duration_hours = db.Column(db.Integer, nullable=False)
    allow_multiselect = db.Column(db.Boolean, nullable=False, default=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    discord_message_url = db.Column(db.Text, nullable=True)

    creator = db.relationship('User', backref=db.backref('discord_polls_created', lazy='dynamic'))
    votes = db.relationship(
        'DiscordPollVote',
        backref='poll',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    def __repr__(self):
        return f"<DiscordPoll {self.id} msg={self.discord_message_id}>"


class DiscordPollVote(db.Model):
    __tablename__ = 'discord_poll_votes'

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(
        db.Integer,
        db.ForeignKey('discord_polls.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    discord_user_id = db.Column(db.String(20), nullable=False, index=True)
    answer_id = db.Column(db.Integer, nullable=False)
    voted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    removed_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        active = "active" if self.removed_at is None else "removed"
        return f"<DiscordPollVote poll={self.poll_id} user={self.discord_user_id} ans={self.answer_id} {active}>"
