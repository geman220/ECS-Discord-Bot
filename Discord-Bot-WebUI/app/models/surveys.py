# app/models/surveys.py

"""
Survey & Poll System Models

A general-purpose, in-house survey/poll engine (Google-Forms parity, kept
in-house) that powers:

  - Multi-question surveys with full parity question types
  - Quick single-question polls
  - Multi-channel distribution (web link, Discord embed, native Discord poll,
    email blast, push notification)
  - Per-survey toggles (anonymous vs identified, login-gated vs open,
    scheduling, dedupe, etc.)
  - Response analytics + year-over-year comparison by category

Tables
------
Survey                - the container (title, type, status, all the toggles)
SurveyQuestion        - one ordered question (type + config + branching logic)
SurveyOption          - a choice / matrix cell for a question
SurveyResponse        - one submission (identified or anonymous)
SurveyResponseAnswer  - one answer to one question within a response
SurveyDistribution    - one send event to one channel (web/discord/email/push)

Discord user linkage uses Player.discord_id (the ground truth) so native
Discord poll votes can be mapped back to a Player when a survey is identified.
"""

import logging
import secrets
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB

from app.core import db

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Enumerable value reference (stored as plain strings for forward-compat).
# These are documentation + helpers, not DB-enforced enums, so adding a new
# question type or channel later is purely additive.
# --------------------------------------------------------------------------- #

SURVEY_TYPES = ('survey', 'poll')

SURVEY_STATUSES = ('draft', 'scheduled', 'open', 'closed', 'archived')

QUESTION_TYPES = (
    'single_choice',   # radio - one option
    'multi_choice',    # checkboxes - many options (config.max_selections)
    'dropdown',        # select - one option
    'short_text',      # single-line text (config.char_limit)
    'long_text',       # textarea
    'rating',          # star/heart rating (config.max = N stars)
    'scale',           # linear scale (config.min/max/step + labels)
    'nps',             # 0-10 Net Promoter Score
    'ranking',         # drag to order options (value_json = ordered ids)
    'matrix',          # grid (config.rows + config.cols)
    'yes_no',          # boolean
    'date',            # date picker
    'email',           # validated email text
    'number',          # validated numeric
)

DISTRIBUTION_CHANNELS = (
    'web',             # shareable token URL (no send; link generated)
    'discord_embed',   # bot posts an embed + "Take Survey" button to a channel
    'native_poll',     # bot posts a native Discord poll (single-question only)
    'email',           # email blast via the email-broadcast engine
    'push',            # push notification via the push-campaign engine
)

RESPONSE_SOURCES = ('web', 'discord_embed', 'native_poll', 'email', 'push', 'admin')


def _generate_access_token():
    """URL-safe token for the public survey link (also used to resume)."""
    return secrets.token_urlsafe(24)


class Survey(db.Model):
    """A survey or poll container plus all of its admin-toggleable settings."""
    __tablename__ = 'surveys'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # 'survey' (multi-question) | 'poll' (quick, 1-few questions)
    survey_type = db.Column(db.String(20), nullable=False, default='survey')

    # Free-form grouping label used for year-over-year comparison,
    # e.g. "End of Season", "Coach Feedback", "New Member Onboarding".
    category = db.Column(db.String(100), nullable=True, index=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id', ondelete='SET NULL'), nullable=True, index=True)

    # draft | scheduled | open | closed | archived
    status = db.Column(db.String(20), nullable=False, default='draft', index=True)

    # ----- Toggles (the "robust settings" surface) ----------------------- #
    is_anonymous = db.Column(db.Boolean, nullable=False, default=False)            # strip identity from reports
    require_login = db.Column(db.Boolean, nullable=False, default=True)            # login-gated vs open link
    allow_multiple_submissions = db.Column(db.Boolean, nullable=False, default=False)
    one_per_player = db.Column(db.Boolean, nullable=False, default=True)           # dedupe identified responses
    allow_edit_after_submit = db.Column(db.Boolean, nullable=False, default=False)
    show_progress_bar = db.Column(db.Boolean, nullable=False, default=True)
    randomize_questions = db.Column(db.Boolean, nullable=False, default=False)
    randomize_options = db.Column(db.Boolean, nullable=False, default=False)
    show_results_to_respondents = db.Column(db.Boolean, nullable=False, default=False)

    # Notify-on-distribute channel toggles (defaults; per-distribution still wins)
    notify_email = db.Column(db.Boolean, nullable=False, default=False)
    notify_discord = db.Column(db.Boolean, nullable=False, default=False)
    notify_push = db.Column(db.Boolean, nullable=False, default=False)

    confirmation_message = db.Column(db.Text, nullable=True)  # shown after submit

    # Catch-all for additional toggles/config without a schema change.
    settings = db.Column(JSONB, nullable=True)

    # ----- Scheduling ---------------------------------------------------- #
    open_at = db.Column(db.DateTime, nullable=True)   # auto-open at/after this time
    close_at = db.Column(db.DateTime, nullable=True)  # auto-close at/after this time

    # ----- Access ------------------------------------------------------- #
    access_token = db.Column(db.String(64), nullable=False, unique=True,
                             index=True, default=_generate_access_token)

    # ----- Audit -------------------------------------------------------- #
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    opened_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # ----- Relationships ------------------------------------------------ #
    creator = db.relationship('User', backref=db.backref('surveys_created', lazy='dynamic'))
    questions = db.relationship(
        'SurveyQuestion', back_populates='survey',
        cascade='all, delete-orphan', order_by='SurveyQuestion.order',
        lazy='select',
    )
    responses = db.relationship(
        'SurveyResponse', back_populates='survey',
        cascade='all, delete-orphan', lazy='dynamic',
    )
    distributions = db.relationship(
        'SurveyDistribution', back_populates='survey',
        cascade='all, delete-orphan', lazy='dynamic',
    )

    __table_args__ = (
        db.Index('idx_surveys_status_category', 'status', 'category'),
        db.Index('idx_surveys_season_id', 'season_id'),
    )

    @property
    def is_accepting_responses(self):
        """Whether the survey is currently open for new responses."""
        if self.status != 'open':
            return False
        now = datetime.utcnow()
        if self.open_at and now < self.open_at:
            return False
        if self.close_at and now > self.close_at:
            return False
        return True

    def to_dict(self, include_questions=False):
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'survey_type': self.survey_type,
            'category': self.category,
            'season_id': self.season_id,
            'status': self.status,
            'is_anonymous': self.is_anonymous,
            'require_login': self.require_login,
            'allow_multiple_submissions': self.allow_multiple_submissions,
            'one_per_player': self.one_per_player,
            'allow_edit_after_submit': self.allow_edit_after_submit,
            'show_progress_bar': self.show_progress_bar,
            'randomize_questions': self.randomize_questions,
            'randomize_options': self.randomize_options,
            'show_results_to_respondents': self.show_results_to_respondents,
            'notify_email': self.notify_email,
            'notify_discord': self.notify_discord,
            'notify_push': self.notify_push,
            'confirmation_message': self.confirmation_message,
            'settings': self.settings or {},
            'open_at': self.open_at.isoformat() if self.open_at else None,
            'close_at': self.close_at.isoformat() if self.close_at else None,
            'access_token': self.access_token,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'is_accepting_responses': self.is_accepting_responses,
        }
        if include_questions:
            data['questions'] = [q.to_dict(include_options=True) for q in self.questions]
        return data

    def __repr__(self):
        return f"<Survey {self.id}: {self.title} ({self.status})>"


class SurveyQuestion(db.Model):
    """One ordered question within a survey."""
    __tablename__ = 'survey_questions'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    order = db.Column(db.Integer, nullable=False, default=0)

    # See QUESTION_TYPES
    question_type = db.Column(db.String(30), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    help_text = db.Column(db.Text, nullable=True)
    is_required = db.Column(db.Boolean, nullable=False, default=False)

    # Type-specific config, e.g.
    #   scale:  {"min": 1, "max": 5, "step": 1, "min_label": "...", "max_label": "..."}
    #   rating: {"max": 5, "icon": "star"}
    #   text:   {"char_limit": 500, "placeholder": "..."}
    #   matrix: {"rows": ["..."], "cols": ["..."], "single": true}
    #   multi:  {"max_selections": 3, "allow_other": true}
    config = db.Column(JSONB, nullable=True)

    # Branching/skip logic, e.g.
    #   {"show_if": {"question_id": 4, "op": "equals", "value": "yes"}}
    logic = db.Column(JSONB, nullable=True)

    survey = db.relationship('Survey', back_populates='questions')
    options = db.relationship(
        'SurveyOption', back_populates='question',
        cascade='all, delete-orphan', order_by='SurveyOption.order',
        lazy='select',
    )

    def to_dict(self, include_options=False):
        data = {
            'id': self.id,
            'survey_id': self.survey_id,
            'order': self.order,
            'question_type': self.question_type,
            'prompt': self.prompt,
            'help_text': self.help_text,
            'is_required': self.is_required,
            'config': self.config or {},
            'logic': self.logic or {},
        }
        if include_options:
            data['options'] = [o.to_dict() for o in self.options]
        return data

    def __repr__(self):
        return f"<SurveyQuestion {self.id} ({self.question_type}) survey={self.survey_id}>"


class SurveyOption(db.Model):
    """A selectable choice (or matrix cell) for a question."""
    __tablename__ = 'survey_options'

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('survey_questions.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    label = db.Column(db.String(500), nullable=False)
    value = db.Column(db.String(255), nullable=True)   # defaults to label if null
    is_other = db.Column(db.Boolean, nullable=False, default=False)  # free-text "Other"
    score = db.Column(db.Integer, nullable=True)       # optional weighting/scoring

    question = db.relationship('SurveyQuestion', back_populates='options')

    def to_dict(self):
        return {
            'id': self.id,
            'question_id': self.question_id,
            'order': self.order,
            'label': self.label,
            'value': self.value if self.value is not None else self.label,
            'is_other': self.is_other,
            'score': self.score,
        }

    def __repr__(self):
        return f"<SurveyOption {self.id} q={self.question_id}: {self.label}>"


class SurveyResponse(db.Model):
    """One submission to a survey (identified or anonymous)."""
    __tablename__ = 'survey_responses'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'),
                          nullable=False, index=True)

    # Identity (all nullable; absent for anonymous surveys). Even on identified
    # surveys these may be null when a response comes from an unlinked Discord
    # user. player_id is the canonical link; discord_id supports native-poll
    # reconciliation before/without a Player match.
    player_id = db.Column(db.Integer, db.ForeignKey('player.id', ondelete='SET NULL'),
                          nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    discord_id = db.Column(db.String(20), nullable=True, index=True)

    # Per-response token for resume + dedupe of anonymous/web submissions.
    submission_token = db.Column(db.String(64), nullable=False, unique=True,
                                 index=True, default=_generate_access_token)

    status = db.Column(db.String(20), nullable=False, default='in_progress')  # in_progress | complete
    source = db.Column(db.String(20), nullable=False, default='web')          # see RESPONSE_SOURCES
    ip_hash = db.Column(db.String(64), nullable=True)  # hashed; for light anonymous dedupe only

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    survey = db.relationship('Survey', back_populates='responses')
    player = db.relationship('Player', backref=db.backref('survey_responses', lazy='dynamic'))
    answers = db.relationship(
        'SurveyResponseAnswer', back_populates='response',
        cascade='all, delete-orphan', lazy='select',
    )

    __table_args__ = (
        db.Index('idx_survey_responses_survey_status', 'survey_id', 'status'),
        db.Index('idx_survey_responses_survey_player', 'survey_id', 'player_id'),
    )

    def to_dict(self, include_answers=False, anonymize=False):
        data = {
            'id': self.id,
            'survey_id': self.survey_id,
            'status': self.status,
            'source': self.source,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }
        if not anonymize:
            data['player_id'] = self.player_id
            data['user_id'] = self.user_id
            data['discord_id'] = self.discord_id
        if include_answers:
            data['answers'] = [a.to_dict() for a in self.answers]
        return data

    def __repr__(self):
        return f"<SurveyResponse {self.id} survey={self.survey_id} ({self.status})>"


class SurveyResponseAnswer(db.Model):
    """One answer to one question within a response.

    Value storage is polymorphic by question type:
      - choice/dropdown/yes_no:  option_id (+ value_text for "Other")
      - short_text/long_text:    value_text
      - rating/scale/nps/number: value_number
      - date:                    value_text (ISO date)
      - multi_choice:            value_json = [option_id, ...]
      - ranking:                 value_json = [option_id, ...] (ordered)
      - matrix:                  value_json = {"<row>": "<col>", ...}
    """
    __tablename__ = 'survey_response_answers'

    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('survey_responses.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('survey_questions.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    option_id = db.Column(db.Integer, db.ForeignKey('survey_options.id', ondelete='SET NULL'),
                          nullable=True)

    value_text = db.Column(db.Text, nullable=True)
    value_number = db.Column(db.Float, nullable=True)
    value_json = db.Column(JSONB, nullable=True)

    response = db.relationship('SurveyResponse', back_populates='answers')
    question = db.relationship('SurveyQuestion')
    option = db.relationship('SurveyOption')

    def to_dict(self):
        return {
            'id': self.id,
            'response_id': self.response_id,
            'question_id': self.question_id,
            'option_id': self.option_id,
            'value_text': self.value_text,
            'value_number': self.value_number,
            'value_json': self.value_json,
        }

    def __repr__(self):
        return f"<SurveyResponseAnswer {self.id} q={self.question_id} r={self.response_id}>"


class SurveyDistribution(db.Model):
    """One send/publish event of a survey to one channel."""
    __tablename__ = 'survey_distributions'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'),
                          nullable=False, index=True)

    channel = db.Column(db.String(20), nullable=False)  # see DISTRIBUTION_CHANNELS

    # Audience targeting reuses the email-broadcast filter shape, e.g.
    #   {"type": "by_league", "league_id": 3}
    target_criteria = db.Column(JSONB, nullable=True)
    target_description = db.Column(db.String(500), nullable=True)

    # Discord specifics (embed + native poll)
    discord_channel_key = db.Column(db.String(50), nullable=True)
    discord_channel_id = db.Column(db.String(20), nullable=True)
    discord_message_id = db.Column(db.String(20), nullable=True)
    discord_message_url = db.Column(db.Text, nullable=True)
    # Link to the native DiscordPoll row when channel == 'native_poll'
    discord_poll_id = db.Column(db.Integer, db.ForeignKey('discord_polls.id', ondelete='SET NULL'),
                                nullable=True)

    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|sending|sent|failed
    total_recipients = db.Column(db.Integer, nullable=False, default=0)
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)

    celery_task_id = db.Column(db.String(155), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)

    survey = db.relationship('Survey', back_populates='distributions')
    discord_poll = db.relationship('DiscordPoll')

    def to_dict(self):
        return {
            'id': self.id,
            'survey_id': self.survey_id,
            'channel': self.channel,
            'target_criteria': self.target_criteria,
            'target_description': self.target_description,
            'discord_channel_key': self.discord_channel_key,
            'discord_message_url': self.discord_message_url,
            'discord_poll_id': self.discord_poll_id,
            'status': self.status,
            'total_recipients': self.total_recipients,
            'sent_count': self.sent_count,
            'failed_count': self.failed_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
        }

    def __repr__(self):
        return f"<SurveyDistribution {self.id} survey={self.survey_id} {self.channel} ({self.status})>"
