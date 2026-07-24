# app/models/automation.py

"""
Automated Messaging Models
==========================

A small rules engine for lifecycle messaging: "when X happens, wait N hours,
then email audience Y".

Two tables:

    AutomationRule  - the configuration an admin edits (trigger, delay, audience,
                      subject/body). One row per automation.
    AutomationRun   - one row per (rule, scope) that has fired. Scope is a season,
                      optionally a league (so Premier and Classic fire
                      independently), and optionally a subject person (so a
                      per-person rule fires once each).

Delivery itself is NOT reimplemented here. A run creates an EmailCampaign via
email_broadcast_service and dispatches it with the normal send task, so audience
resolution, opt-out gating, throttling and per-recipient delivery rows
(EmailCampaignRecipient) all come from the one existing spine.

Idempotency is the AutomationRun.scope_key unique constraint: a rule can fire at
most once per scope, ever. Postgres treats NULLs as distinct in unique indexes,
so the nullable league_id can't carry the constraint itself -- scope_key is a
NOT NULL string built from (season_id, league_id[, subject]) instead.
"""

import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


# Trigger types. Two shapes:
#   * league/season-wide -- one run per (season, league)
#   * per-subject        -- one run per person (see PER_SUBJECT_TRIGGERS), with
#     subject_type/subject_id on the run and the audience being that person.
TRIGGER_DRAFT_COMPLETE = 'draft_complete'
TRIGGER_DRAFT_SESSION_COMPLETE = 'draft_session_complete'
TRIGGER_SEASON_PHASE = 'season_phase'
TRIGGER_SEASON_DATE = 'season_date'
# Per-subject triggers: one run per person, audience = that person.
TRIGGER_USER_APPROVED = 'user_approved'
TRIGGER_WAITLIST_STUCK = 'waitlist_stuck'
TRIGGER_SUB_NO_REPLY = 'sub_no_reply'

TRIGGER_TYPES = {
    TRIGGER_DRAFT_COMPLETE: 'Draft finished (roster filled, per league)',
    TRIGGER_DRAFT_SESSION_COMPLETE: 'Draft clock marked complete (per league)',
    TRIGGER_SEASON_PHASE: 'Season enters a phase',
    TRIGGER_SEASON_DATE: 'Season start / end date',
    TRIGGER_USER_APPROVED: 'Someone was approved',
    TRIGGER_WAITLIST_STUCK: 'Stuck on the waitlist too long',
    TRIGGER_SUB_NO_REPLY: 'Sub was asked and never replied',
}

# Triggers that fire once per PERSON rather than once per league/season. Their
# runs carry subject_type/subject_id and their audience is that person.
PER_SUBJECT_TRIGGERS = (
    TRIGGER_USER_APPROVED, TRIGGER_WAITLIST_STUCK, TRIGGER_SUB_NO_REPLY,
)

# NOT offered: a "survey started but never finished" trigger. SurveyResponse.status
# defaults to 'in_progress', but survey_service.record_response always overwrites it
# to 'complete' (app/services/survey_service.py:386) and there is no partial-save or
# resume endpoint, so no row can ever hold that state. Shipping it would have been a
# dropdown option that silently never fires.

# UI metadata for the "new automation" builder: what each trigger means, which
# extra config fields it takes, and a sensible default audience.
TRIGGER_CATALOG = {
    TRIGGER_DRAFT_COMPLETE: {
        'label': 'Draft finished (roster filled)',
        'help': ('Fires per league once EVERY active team holds at least N non-coach '
                 'players. Survives the coach pre-draft, and works even if the live '
                 'draft clock was never used.'),
        'fields': ['min_players_per_team', 'max_event_age_days'],
        'scope': 'Per league, per season',
        'default_audience': 'drafted_not_in_discord',
    },
    TRIGGER_DRAFT_SESSION_COMPLETE: {
        'label': 'Draft clock marked complete',
        'help': ('Fires per league the moment an admin ends the live draft. Exact, but '
                 'only works if you actually ran the draft through the clock.'),
        'fields': ['max_event_age_days'],
        'scope': 'Per league, per season',
        'default_audience': 'drafted_not_in_discord',
    },
    TRIGGER_SEASON_PHASE: {
        'label': 'Season enters a phase',
        'help': ('Fires once when the season sits in the chosen phase. There is no '
                 'phase-change audit column, so the event time is when we first '
                 'observe it rather than the exact flip.'),
        'fields': ['phase', 'max_event_age_days'],
        'scope': 'Whole season',
        'default_audience': 'current_season_players',
    },
    TRIGGER_SEASON_DATE: {
        'label': 'Season start / end date',
        'help': ('Fires relative to the season start or end date — e.g. 3 days before '
                 'the season starts, or the day after it ends.'),
        'fields': ['date_anchor', 'days_offset', 'max_event_age_days'],
        'scope': 'Whole season',
        'default_audience': 'current_season_players',
    },
    TRIGGER_USER_APPROVED: {
        'label': 'Someone was approved',
        'help': ('Fires once per person, when their account is approved. Uses the real '
                 'approved_at timestamp, so the delay is measured from the approval '
                 'itself. Ideal for a welcome / what-happens-next email.'),
        'fields': ['max_event_age_days'],
        'scope': 'Per person',
        'default_audience': 'the_subject',
    },
    TRIGGER_WAITLIST_STUCK: {
        'label': 'Stuck on the waitlist too long',
        'help': ('Fires once per person who has been on the waitlist longer than the '
                 'threshold and is still waiting. A reassurance / status nudge.'),
        'fields': ['stuck_days', 'max_event_age_days'],
        'scope': 'Per person',
        'default_audience': 'the_subject',
    },
    TRIGGER_SUB_NO_REPLY: {
        'label': 'Sub was asked and never replied',
        'help': ('Fires once per person per request when we asked them to sub and got '
                 'silence for longer than the threshold. Anchored to the real '
                 'notification_sent_at.'),
        'fields': ['silence_hours', 'max_event_age_days'],
        'scope': 'Per person, per request',
        'default_audience': 'the_subject',
    },
}


# Conditions an admin can bolt onto any rule. Each entry is
# {'field': ..., 'op': ..., 'value': ...} and ALL must pass for a person to be
# kept in the audience. Evaluated in Python against the resolved recipients,
# which stays cheap because audiences here are hundreds, not millions.
CONDITION_FIELDS = {
    'player.discord_in_server': ('Is in the Discord server', 'bool'),
    'player.discord_id':        ('Has a Discord account linked', 'exists'),
    'player.is_current_player': ('Is an active player this season', 'bool'),
    'player.is_coach':          ('Is a coach', 'bool'),
    'player.is_sub':            ('Is a substitute', 'bool'),
    'user.approval_status':     ('Approval status', 'str'),
    'user.email_notifications': ('Has email notifications on', 'bool'),
}

CONDITION_OPS = {
    'is_true':  'is yes',
    'is_false': 'is no',
    'exists':   'is set',
    'missing':  'is not set',
    'eq':       'equals',
    'neq':      'does not equal',
}


def build_scope_key(season_id, league_id, subject_type=None, subject_id=None):
    """Stable scope identifier for an AutomationRun.

    league_id is None for season-wide triggers; 'all' keeps those rows unique
    under the (rule_id, scope_key) constraint, which a NULL column would not.

    Per-SUBJECT triggers ("this person was approved", "this sub never replied")
    append the entity, so one rule can fire once per person instead of once per
    league. The two-part form is preserved verbatim when there is no subject, so
    scope keys written before per-subject triggers existed still match and those
    rules cannot re-fire.
    """
    base = f"{season_id or 'none'}:{league_id or 'all'}"
    if subject_type and subject_id:
        return f"{base}:{subject_type}:{subject_id}"
    return base


class AutomationRule(db.Model):
    """One configurable automated message."""
    __tablename__ = 'automation_rule'

    id = db.Column(db.Integer, primary_key=True)
    # Stable slug so seeded rules can be found in code without depending on a
    # display name the admin is free to rename.
    key = db.Column(db.String(64), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Off by default: a freshly seeded rule must never fire before an admin has
    # read the copy and turned it on.
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    # ── Trigger ──────────────────────────────────────────────────────────────
    trigger_type = db.Column(db.String(32), nullable=False)
    # draft_complete: {"league_type": "Pub League", "min_players_per_team": 6,
    #                  "league_names": ["Premier", "Classic"]}
    # season_phase:   {"league_type": "Pub League", "phase": "offseason"}
    trigger_config = db.Column(db.JSON, nullable=False, default=dict)
    # Hours to wait after the trigger event before sending.
    delay_hours = db.Column(db.Integer, nullable=False, default=24, server_default='24')

    # ── Audience ─────────────────────────────────────────────────────────────
    # A filter_criteria 'type' understood by email_broadcast_service.
    audience_type = db.Column(db.String(64), nullable=False, default='drafted_not_in_discord')
    # Extra keys merged into filter_criteria. The engine injects season_id /
    # league_id at fire time so the rule itself stays season-agnostic.
    audience_config = db.Column(db.JSON, nullable=True)

    # Optional extra narrowing, applied AFTER the audience resolves. A list of
    # {'field', 'op', 'value'} dicts; every one must pass. See CONDITION_FIELDS.
    conditions = db.Column(db.JSON, nullable=True)

    # ── Action: which channels to deliver on ─────────────────────────────────
    # Allow-list, e.g. ["email"] or ["email", "push", "discord"].
    #
    # 'email' alone takes the EmailCampaign path: HTML body, wrapper layout,
    # per-recipient delivery rows. Any other combination goes through the
    # notification orchestrator (via ComposedMessage), which is genuinely
    # multi-channel but only records per-channel counters, not per-person rows.
    #
    # 'sms' is deliberately NOT offered: sends are capped system-wide at 100/hour
    # (app/sms_helpers.py:88), so an unattended blast would silently start
    # failing partway through with no backoff.
    channels = db.Column(db.JSON, nullable=False, default=lambda: ['email'])

    # ── Message ──────────────────────────────────────────────────────────────
    subject = db.Column(db.String(500), nullable=False)
    # Short plain-text body for push / Discord DM / in-app. HTML is meaningless
    # on those channels, so they get their own copy rather than a stripped body.
    short_message = db.Column(db.String(1000), nullable=True)
    body_html = db.Column(db.Text, nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('email_templates.id', ondelete='SET NULL'),
                            nullable=True)
    # 'individual' so {first_name} personalization works; bcc_batch would send
    # one identical mail to everyone.
    send_mode = db.Column(db.String(20), nullable=False, default='individual')
    # Operational onboarding mail -- default to ignoring email-notification
    # opt-out, but leave it per-rule so a marketing-ish rule can respect it.
    force_send = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    # ── Audit ────────────────────────────────────────────────────────────────
    # Nullable: seeded rules have no human creator. Dispatch falls back to an
    # admin account when stamping the generated EmailCampaign.
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    last_evaluated_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    template = db.relationship('EmailTemplate', foreign_keys=[template_id])
    runs = db.relationship('AutomationRun', back_populates='rule',
                           cascade='all, delete-orphan', lazy='dynamic',
                           passive_deletes=True)

    @property
    def trigger_label(self):
        return TRIGGER_TYPES.get(self.trigger_type, self.trigger_type)

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'trigger_type': self.trigger_type,
            'trigger_label': self.trigger_label,
            'trigger_config': self.trigger_config or {},
            'delay_hours': self.delay_hours,
            'audience_type': self.audience_type,
            'audience_config': self.audience_config or {},
            'conditions': self.conditions or [],
            'channels': self.channels or ['email'],
            'subject': self.subject,
            'short_message': self.short_message,
            'send_mode': self.send_mode,
            'force_send': self.force_send,
            'template_id': self.template_id,
            'last_evaluated_at': self.last_evaluated_at.isoformat() if self.last_evaluated_at else None,
        }

    def __repr__(self):
        return f'<AutomationRule {self.key} enabled={self.enabled}>'


class AutomationRun(db.Model):
    """One firing of a rule for one scope (season, and optionally league)."""
    __tablename__ = 'automation_run'
    __table_args__ = (
        # The idempotency guarantee: a rule fires at most once per scope.
        db.UniqueConstraint('rule_id', 'scope_key', name='uq_automation_run_rule_scope'),
        db.Index('idx_automation_run_status_scheduled', 'status', 'scheduled_for'),
    )

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('automation_rule.id', ondelete='CASCADE'),
                        nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='CASCADE'), nullable=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id', ondelete='CASCADE'), nullable=True)
    # The person this run is about, for per-subject triggers. NULL for
    # league/season-wide rules. Not a FK to player/users because the subject can
    # be either, and a deleted person should not cascade away the audit trail.
    subject_type = db.Column(db.String(20), nullable=True)   # 'player' | 'user'
    subject_id = db.Column(db.Integer, nullable=True)
    scope_key = db.Column(db.String(128), nullable=False)

    # When the trigger condition actually became true (derived from real data,
    # e.g. the draft pick that tipped the league over) -- NOT when the beat task
    # happened to notice. This keeps scheduling deterministic and backfill-safe.
    event_at = db.Column(db.DateTime, nullable=False)
    scheduled_for = db.Column(db.DateTime, nullable=False)

    # pending | sent | failed | cancelled | skipped
    status = db.Column(db.String(20), nullable=False, default='pending')
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaigns.id', ondelete='SET NULL'),
                            nullable=True)
    recipient_count = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.String(500), nullable=True)

    detected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    dispatched_at = db.Column(db.DateTime, nullable=True)

    rule = db.relationship('AutomationRule', back_populates='runs')
    season = db.relationship('Season', foreign_keys=[season_id])
    league = db.relationship('League', foreign_keys=[league_id])
    campaign = db.relationship('EmailCampaign', foreign_keys=[campaign_id])

    def to_dict(self):
        return {
            'id': self.id,
            'rule_id': self.rule_id,
            'season_id': self.season_id,
            'league_id': self.league_id,
            'subject_type': self.subject_type,
            'subject_id': self.subject_id,
            'scope_key': self.scope_key,
            'event_at': self.event_at.isoformat() if self.event_at else None,
            'scheduled_for': self.scheduled_for.isoformat() if self.scheduled_for else None,
            'status': self.status,
            'campaign_id': self.campaign_id,
            'recipient_count': self.recipient_count,
            'error_message': self.error_message,
        }

    def __repr__(self):
        return f'<AutomationRun rule={self.rule_id} scope={self.scope_key} status={self.status}>'
