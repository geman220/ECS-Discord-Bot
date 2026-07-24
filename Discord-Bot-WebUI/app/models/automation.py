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
TRIGGER_PLAYER_INACTIVE = 'player_inactive'
TRIGGER_PROFILE_STALE = 'profile_stale'
TRIGGER_PASS_NEVER_DOWNLOADED = 'pass_never_downloaded'
TRIGGER_PASS_EXPIRING = 'pass_expiring'
TRIGGER_FEEDBACK_OPEN = 'feedback_open'
TRIGGER_SUB_REQUEST_UNFILLED = 'sub_request_unfilled'
TRIGGER_SUB_POOL_PENDING = 'sub_pool_pending'
TRIGGER_MATCH_RESCHEDULED = 'match_rescheduled'

TRIGGER_TYPES = {
    TRIGGER_DRAFT_COMPLETE: 'Draft finished (roster filled, per league)',
    TRIGGER_DRAFT_SESSION_COMPLETE: 'Draft clock marked complete (per league)',
    TRIGGER_SEASON_PHASE: 'Season enters a phase',
    TRIGGER_SEASON_DATE: 'Season start / end date',
    TRIGGER_USER_APPROVED: 'Someone was approved',
    TRIGGER_WAITLIST_STUCK: 'Stuck on the waitlist too long',
    TRIGGER_SUB_NO_REPLY: 'Sub was asked and never replied',
    TRIGGER_PLAYER_INACTIVE: "Player hasn't turned out in a while",
    TRIGGER_PROFILE_STALE: 'Profile details have gone stale',
    TRIGGER_PASS_NEVER_DOWNLOADED: 'Membership pass never added to a phone',
    TRIGGER_PASS_EXPIRING: 'Membership pass about to expire',
    TRIGGER_FEEDBACK_OPEN: 'Feedback ticket left open',
    TRIGGER_SUB_REQUEST_UNFILLED: 'Sub request still unfilled',
    TRIGGER_SUB_POOL_PENDING: 'Sub application waiting for approval',
    TRIGGER_MATCH_RESCHEDULED: 'Match was rescheduled',
}

# Triggers that fire once per PERSON rather than once per league/season. Their
# runs carry subject_type/subject_id and their audience is that person.
PER_SUBJECT_TRIGGERS = (
    TRIGGER_USER_APPROVED, TRIGGER_WAITLIST_STUCK, TRIGGER_SUB_NO_REPLY,
    TRIGGER_PLAYER_INACTIVE, TRIGGER_PROFILE_STALE,
    TRIGGER_PASS_NEVER_DOWNLOADED, TRIGGER_PASS_EXPIRING,
    TRIGGER_FEEDBACK_OPEN, TRIGGER_SUB_REQUEST_UNFILLED,
    TRIGGER_SUB_POOL_PENDING, TRIGGER_MATCH_RESCHEDULED,
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
        'group': 'Draft',
        'default_audience': 'drafted_not_in_discord',
    },
    TRIGGER_DRAFT_SESSION_COMPLETE: {
        'label': 'Draft clock marked complete',
        'help': ('Fires per league the moment an admin ends the live draft. Exact, but '
                 'only works if you actually ran the draft through the clock.'),
        'fields': ['max_event_age_days'],
        'scope': 'Per league, per season',
        'group': 'Draft',
        'default_audience': 'drafted_not_in_discord',
    },
    TRIGGER_SEASON_PHASE: {
        'label': 'Season enters a phase',
        'help': ('Fires once when the season sits in the chosen phase. There is no '
                 'phase-change audit column, so the event time is when we first '
                 'observe it rather than the exact flip.'),
        'fields': ['phase', 'max_event_age_days'],
        'scope': 'Whole season',
        'group': 'Season',
        'default_audience': 'current_season_players',
    },
    TRIGGER_SEASON_DATE: {
        'label': 'Season start / end date',
        'help': ('Fires relative to the season start or end date — e.g. 3 days before '
                 'the season starts, or the day after it ends.'),
        'fields': ['date_anchor', 'days_offset', 'max_event_age_days'],
        'scope': 'Whole season',
        'group': 'Season',
        'default_audience': 'current_season_players',
    },
    TRIGGER_USER_APPROVED: {
        'label': 'Someone was approved',
        'help': ('Fires once per person, when their account is approved. Uses the real '
                 'approved_at timestamp, so the delay is measured from the approval '
                 'itself. Ideal for a welcome / what-happens-next email.'),
        'fields': ['max_event_age_days'],
        'scope': 'Per person',
        'group': 'Joining',
        'default_audience': 'the_subject',
    },
    TRIGGER_WAITLIST_STUCK: {
        'label': 'Stuck on the waitlist too long',
        'help': ('Fires once per person who has been on the waitlist longer than the '
                 'threshold and is still waiting. A reassurance / status nudge.'),
        'fields': ['stuck_days', 'max_event_age_days'],
        'scope': 'Per person',
        'group': 'Joining',
        'default_audience': 'the_subject',
    },
    TRIGGER_SUB_NO_REPLY: {
        'label': 'Sub was asked and never replied',
        'help': ('Fires once per person per request when we asked them to sub and got '
                 'silence for longer than the threshold. '
                 'Pub League only \u2014 ECS FC substitute requests are not covered yet.'),
        'fields': ['silence_hours', 'max_event_age_days'],
        'scope': 'Per person, per request',
        'group': 'Substitutes',
        'default_audience': 'the_subject',
    },
    TRIGGER_PLAYER_INACTIVE: {
        'label': "Player hasn't turned out in a while",
        'help': ("Fires per player who has not played for the chosen number of days. "
                 "Heads up: this reads 'last match they RSVP'd yes to', so someone who "
                 "turns up without RSVPing will look inactive."),
        'fields': ['inactive_days', 'max_event_age_days'],
        'scope': 'Per person',
        'group': 'Engagement',
        'default_audience': 'the_subject',
    },
    TRIGGER_PROFILE_STALE: {
        'label': 'Profile details have gone stale',
        'help': ("Fires per rostered player whose profile has not been touched in a long "
                 "time. Good for a yearly 'check your shirt size and phone number' nudge."),
        'fields': ['stale_days', 'max_event_age_days'],
        'scope': 'Per person',
        'group': 'Engagement',
        'default_audience': 'the_subject',
    },
    TRIGGER_PASS_NEVER_DOWNLOADED: {
        'label': 'Membership pass never added to a phone',
        'help': ("Fires when someone was issued a pass but never added it to Apple or "
                 "Google Wallet, so they will turn up without it."),
        'fields': ['wait_days', 'max_event_age_days'],
        'scope': 'Per person',
        'group': 'Membership',
        'default_audience': 'the_subject',
    },
    TRIGGER_PASS_EXPIRING: {
        'label': 'Membership pass about to expire',
        'help': 'Fires the chosen number of days before a membership pass lapses.',
        'fields': ['lead_days', 'max_event_age_days'],
        'scope': 'Per person',
        'group': 'Membership',
        'default_audience': 'the_subject',
    },
    TRIGGER_FEEDBACK_OPEN: {
        'label': 'Feedback ticket left open',
        'help': ("Fires when someone's feedback has sat open without being closed. "
                 "Anonymous submissions are skipped, since there is nobody to reply to."),
        'fields': ['open_days', 'max_event_age_days'],
        'scope': 'Per ticket',
        'group': 'Support',
        'default_audience': 'the_subject',
    },
    TRIGGER_SUB_REQUEST_UNFILLED: {
        'label': 'Sub request still unfilled',
        'help': ("Fires when a request for cover is still short of players after the "
                 "chosen number of hours. Goes to whoever asked for the sub. "
                 "Especially useful in Pub League, where creating a request does NOT "
                 "notify the sub pool \u2014 that is still a manual broadcast. "
                 "Pub League only."),
        'fields': ['unfilled_hours', 'max_event_age_days'],
        'scope': 'Per request',
        'group': 'Substitutes',
        'default_audience': 'the_subject',
    },
    TRIGGER_SUB_POOL_PENDING: {
        'label': 'Sub application waiting for approval',
        'help': ("Fires when someone applied to join the substitute pool and is still "
                 "waiting to be approved. Note this messages the APPLICANT, who cannot "
                 "act on it \u2014 use it as reassurance, not as an admin to-do."),
        'fields': ['waiting_days', 'max_event_age_days'],
        'scope': 'Per person',
        'group': 'Substitutes',
        'default_audience': 'the_subject',
    },
    TRIGGER_MATCH_RESCHEDULED: {
        'label': 'Match was rescheduled',
        'help': ("Fires when a match date or time is changed, and messages both teams. "
                 "Only covers the admin panel's single-match time edit -- a bulk "
                 "schedule rebuild does not record a reschedule."),
        'fields': ['max_event_age_days'],
        'scope': 'Both teams',
        'group': 'Matches',
        'default_audience': 'the_subject',
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# CONDITIONS — the "only if" leg of Event / Condition / Action.
#
# Each field declares a TYPE, and the type decides which operators are offered.
# Offering every operator for every field lets an admin build something that can
# never be true (e.g. a status string tested with "is yes"), and the rule then
# quietly mails nobody. The UI narrows the operator list from the type.
#
# Fields are grouped so the dropdown reads like a form, not a database schema.
# ('label', 'type', 'group')
# ─────────────────────────────────────────────────────────────────────────────

CONDITION_TYPE_BOOL = 'bool'      # nullable booleans: NULL is treated as "not yes"
CONDITION_TYPE_EXISTS = 'exists'  # presence-only (ids, free text)
CONDITION_TYPE_STR = 'str'
CONDITION_TYPE_NUM = 'num'
CONDITION_TYPE_DATE = 'date'      # compared by age in days
CONDITION_TYPE_ROLE = 'role'      # membership in user_roles
CONDITION_TYPE_LEAGUE = 'league'  # league membership this season

# NOTE: Player.discord_roles_synced is deliberately absent. Nothing in the
# codebase ever sets it True -- the sync worker clears discord_needs_update
# instead -- so any condition using it would silently match nobody.
CONDITION_FIELDS = {
    # ── Discord ──────────────────────────────────────────────────────────
    'player.discord_in_server':   ('Is in the Discord server', CONDITION_TYPE_BOOL, 'Discord'),
    'player.discord_id':          ('Discord account linked', CONDITION_TYPE_EXISTS, 'Discord'),
    'player.discord_last_checked': ('Discord status last checked', CONDITION_TYPE_DATE, 'Discord'),

    # ── Player ───────────────────────────────────────────────────────────
    'player.is_current_player':   ('Active player this season', CONDITION_TYPE_BOOL, 'Player'),
    'player.is_coach':            ('Is a coach', CONDITION_TYPE_BOOL, 'Player'),
    'player.is_sub':              ('Is a substitute', CONDITION_TYPE_BOOL, 'Player'),
    'player.is_ref':              ('Is a referee', CONDITION_TYPE_BOOL, 'Player'),
    'player.primary_team_id':     ('On a team', CONDITION_TYPE_EXISTS, 'Player'),
    'player.profile_last_updated': ('Profile last updated', CONDITION_TYPE_DATE, 'Player'),
    'player.is_phone_verified':   ('Phone verified', CONDITION_TYPE_BOOL, 'Player'),

    # ── Account ──────────────────────────────────────────────────────────
    'user.approval_status':       ('Approval status', CONDITION_TYPE_STR, 'Account'),
    'user.is_active':             ('Account is active', CONDITION_TYPE_BOOL, 'Account'),
    'user.last_login':            ('Last signed in', CONDITION_TYPE_DATE, 'Account'),
    'user.created_at':            ('Account created', CONDITION_TYPE_DATE, 'Account'),
    'user.has_completed_onboarding': ('Finished onboarding', CONDITION_TYPE_BOOL, 'Account'),

    # ── Contact preferences ──────────────────────────────────────────────
    'user.email_notifications':   ('Email notifications on', CONDITION_TYPE_BOOL, 'Contact'),
    'user.discord_notifications': ('Discord notifications on', CONDITION_TYPE_BOOL, 'Contact'),
    'user.push_notifications':    ('Push notifications on', CONDITION_TYPE_BOOL, 'Contact'),

    # ── Membership ───────────────────────────────────────────────────────
    'membership.role':            ('Role', CONDITION_TYPE_ROLE, 'Membership'),
    'membership.league':          ('League', CONDITION_TYPE_LEAGUE, 'Membership'),
}

CONDITION_OPS = {
    'is_true':         'is yes',
    'is_false':        'is no',
    'exists':          'is set',
    'missing':         'is not set',
    'eq':              'is',
    'neq':             'is not',
    'gt':              'is more than',
    'lt':              'is less than',
    'older_than_days': 'was more than (days) ago',
    'newer_than_days': 'was within the last (days)',
    'never':           'never happened',
    'has':             'includes',
    'not_has':         'does not include',
}

# Which operators each field type may use, and which of those need a value box.
CONDITION_OPS_BY_TYPE = {
    CONDITION_TYPE_BOOL:   ['is_true', 'is_false'],
    CONDITION_TYPE_EXISTS: ['exists', 'missing'],
    CONDITION_TYPE_STR:    ['eq', 'neq', 'exists', 'missing'],
    CONDITION_TYPE_NUM:    ['eq', 'neq', 'gt', 'lt'],
    CONDITION_TYPE_DATE:   ['older_than_days', 'newer_than_days', 'never', 'exists'],
    CONDITION_TYPE_ROLE:   ['has', 'not_has'],
    CONDITION_TYPE_LEAGUE: ['has', 'not_has'],
}

# Sentence forms for the summary line. The dropdown labels above are terse
# because they sit next to a field name; these read as prose. {v} is the value.
CONDITION_OP_PHRASES = {
    'is_true':         'is yes',
    'is_false':        'is no',
    'exists':          'is set',
    'missing':         'is not set',
    'eq':              'is {v}',
    'neq':             'is not {v}',
    'gt':              'is more than {v}',
    'lt':              'is less than {v}',
    'older_than_days': 'was more than {v} days ago',
    'newer_than_days': 'was within the last {v} days',
    'never':           'never happened',
    'has':             'includes {v}',
    'not_has':         'excludes {v}',
}

CONDITION_OPS_NEEDING_VALUE = (
    'eq', 'neq', 'gt', 'lt', 'older_than_days', 'newer_than_days', 'has', 'not_has')

# Operators whose meaning is NEGATIVE. These must be evaluated with all() across
# a person's duplicate Player rows, not any() -- an all-NULL orphan row would
# otherwise satisfy "is not in the Discord server" for someone who plainly is.
CONDITION_NEGATIVE_OPS = ('is_false', 'missing', 'neq', 'never', 'not_has')


def condition_ops_for(field):
    """Operators valid for one condition field."""
    meta = CONDITION_FIELDS.get(field)
    if not meta:
        return []
    return CONDITION_OPS_BY_TYPE.get(meta[1], [])


def describe_condition(cond):
    """Plain-English rendering of one condition or condition group."""
    if not isinstance(cond, dict):
        return 'an invalid condition'
    if 'any' in cond or 'all' in cond:
        joiner = ' or ' if 'any' in cond else ' and '
        inner = cond.get('any') or cond.get('all') or []
        parts = [describe_condition(c) for c in inner]
        if not parts:
            return 'an empty group'
        body = joiner.join(parts)
        return f'({body})' if len(parts) > 1 else body
    meta = CONDITION_FIELDS.get(cond.get('field'))
    label = meta[0] if meta else cond.get('field', '?')
    phrase = CONDITION_OP_PHRASES.get(cond.get('op'), cond.get('op') or '?')
    return (label + ' ' + phrase.format(v=cond.get('value', ''))).strip()


def summarize_rule(rule, audience_label=None):
    """One plain-English sentence describing what this automation does.

    Shown at the top of the builder so an admin can read back the whole rule
    without decoding four separate dropdowns. Deliberately assembled from the
    same metadata the form uses, so it cannot drift from the actual behaviour.
    """
    def _plural(n, word):
        n = int(n or 0)
        return '%d %s%s' % (n, word, '' if n == 1 else 's')

    cat = TRIGGER_CATALOG.get(rule.trigger_type, {})
    cfg = rule.trigger_config or {}
    when = cat.get('label', rule.trigger_type)
    # Catalog labels are Title Case for the dropdown; lower the first letter
    # so they read as prose inside the sentence.
    if when and when[:1].isupper() and not when[:2].isupper():
        when = when[0].lower() + when[1:]

    # Fold the trigger's own tuning into the sentence where it changes meaning.
    if rule.trigger_type == TRIGGER_DRAFT_COMPLETE:
        when = (f"every active team in a league has "
                f"{cfg.get('min_players_per_team', 6)} or more players")
    elif rule.trigger_type == TRIGGER_SEASON_PHASE:
        when = f"the season enters {str(cfg.get('phase', 'offseason')).replace('_', ' ')}"
    elif rule.trigger_type == TRIGGER_SEASON_DATE:
        off = int(cfg.get('days_offset', 0) or 0)
        anchor_txt = 'starts' if cfg.get('date_anchor', 'start') == 'start' else 'ends'
        if off < 0:
            when = "it is %s before the season %s" % (_plural(abs(off), "day"), anchor_txt)
        elif off > 0:
            when = "it is %s after the season %s" % (_plural(off, "day"), anchor_txt)
        else:
            when = f"the season {anchor_txt}"
    elif rule.trigger_type == TRIGGER_WAITLIST_STUCK:
        when = "someone has been on the waitlist for " + _plural(cfg.get("stuck_days", 14), "day")
    elif rule.trigger_type == TRIGGER_SUB_NO_REPLY:
        when = ("a sub has not answered a request for "
                + _plural(cfg.get("silence_hours", 24), "hour"))

    delay = rule.delay_hours or 0
    if delay == 0:
        wait = 'immediately'
    elif delay % 24 == 0:
        days = delay // 24
        wait = f"wait {days} day{'s' if days != 1 else ''}, then"
    else:
        wait = f"wait {delay} hour{'s' if delay != 1 else ''}, then"

    who = audience_label or rule.audience_type
    channels = rule.channels or ['email']
    pretty = {'in_app': 'in-app alert', 'push': 'push', 'discord': 'Discord DM', 'email': 'email'}
    names = [pretty.get(c, c) for c in channels]
    how = names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]

    sentence = f"When {when}, {wait} message {who} by {how}."

    conds = rule.conditions or []
    if conds:
        parts = [describe_condition(c) for c in conds]
        # lower-case the first letter so it reads as prose mid-sentence
        parts = [(p[0].lower() + p[1:]) if p else p for p in parts]
        joined = parts[0] if len(parts) == 1 else ', and '.join(parts)
        sentence += f' Only if {joined}.'
    return sentence


# ─────────────────────────────────────────────────────────────────────────────
# TRIGGER FIELD SPECS — the single source of truth for every trigger knob.
#
# Before this existed, adding one knob meant editing FIVE places: the catalog's
# field list, a defaults dict in the routes, a separate validation tuple in the
# routes, a labels map in the JS, and a hardcoded input block in the template.
# They drifted. Now the catalog names the fields and this dict describes them;
# the routes validate from it, and the UI renders from it.
#
# 'int'    -> number input, clamped to min/max
# 'choice' -> select, options are (value, label) pairs
# ─────────────────────────────────────────────────────────────────────────────

TRIGGER_FIELD_SPECS = {
    'max_event_age_days': {
        'label': 'Freshness window (days)', 'type': 'int',
        'default': 14, 'min': 1, 'max': 365,
        'help': ('Safety valve. If you switch this on long after the trigger already '
                 'happened, the stale event is recorded as skipped instead of blasting '
                 'everyone. You can still send it with Force run.'),
    },
    'min_players_per_team': {
        'label': 'Players per team before the draft counts as done', 'type': 'int',
        'default': 6, 'min': 1, 'max': 30,
        'help': ('EVERY active team in the league must reach this many non-coach '
                 'players. Coaches are drafted about a week early, so a low number '
                 'risks firing on the coach draft instead of the real one.'),
    },
    'phase': {
        'label': 'Fires when the season enters', 'type': 'choice',
        'default': 'offseason',
        'choices': [('preseason', 'Preseason'), ('in_season', 'In season'),
                    ('break', 'Break'), ('offseason', 'Offseason')],
    },
    'date_anchor': {
        'label': 'Anchor', 'type': 'choice', 'default': 'start',
        'choices': [('start', 'Season start date'), ('end', 'Season end date')],
    },
    'days_offset': {
        'label': 'Days offset', 'type': 'int', 'default': 0, 'min': -365, 'max': 365,
        'help': '-3 means three days before, +1 means the day after. Counted from local midnight.',
    },
    'stuck_days': {
        'label': 'Waiting longer than (days)', 'type': 'int',
        'default': 14, 'min': 1, 'max': 365,
        'help': 'The wait below is counted from the moment they cross this line, not from when they joined.',
    },
    'silence_hours': {
        'label': 'Silent for (hours)', 'type': 'int', 'default': 24, 'min': 1, 'max': 8760,
    },
    'inactive_days': {
        'label': "Hasn't played for (days)", 'type': 'int',
        'default': 28, 'min': 1, 'max': 365,
        'help': ("Reads 'last match they RSVP'd yes to', so someone who turns up "
                 "without RSVPing will look inactive."),
    },
    'stale_days': {
        'label': 'Profile untouched for (days)', 'type': 'int',
        'default': 180, 'min': 1, 'max': 3650,
    },
    'wait_days': {
        'label': 'Wait after issuing (days)', 'type': 'int', 'default': 3, 'min': 1, 'max': 365,
    },
    'lead_days': {
        'label': 'Notice before expiry (days)', 'type': 'int', 'default': 14, 'min': 1, 'max': 365,
    },
    'open_days': {
        'label': 'Open for (days)', 'type': 'int', 'default': 7, 'min': 1, 'max': 365,
    },
    'unfilled_hours': {
        'label': 'Unfilled for (hours)', 'type': 'int', 'default': 24, 'min': 1, 'max': 8760,
    },
    'waiting_days': {
        'label': 'Waiting for (days)', 'type': 'int', 'default': 3, 'min': 1, 'max': 365,
    },
}


def trigger_fields_for(trigger_type):
    """[(field_name, spec)] for a trigger, in catalog order."""
    meta = TRIGGER_CATALOG.get(trigger_type) or {}
    out = []
    for name in meta.get('fields', []):
        spec = TRIGGER_FIELD_SPECS.get(name)
        if spec:
            out.append((name, spec))
    return out


def default_trigger_config(trigger_type, league_type='Pub League'):
    """A complete, valid trigger_config for a newly created rule."""
    cfg = {'league_type': league_type}
    for name, spec in trigger_fields_for(trigger_type):
        cfg[name] = spec['default']
    cfg.setdefault('max_event_age_days',
                   TRIGGER_FIELD_SPECS['max_event_age_days']['default'])
    return cfg

# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE VARIABLES — the {tokens} an admin can put in copy.
#
# Single source of truth. Before this, the list lived in four places (the editor
# template, two separate "known" sets in the routes, and the personalisation
# helper) and they had already drifted.
#
# scope:
#   'recipient' -> filled per person at send time by personalize_content.
#                  ONLY works in Individual send mode; in BCC mode everyone gets
#                  one identical email so there is nobody to personalise for.
#   'global'    -> filled once at send time from settings (see GLOBAL_VARIABLE_
#                  SETTINGS). Safe in any send mode.
# ─────────────────────────────────────────────────────────────────────────────

MESSAGE_VARIABLES = {
    'first_name': {
        'label': 'First name', 'scope': 'recipient',
        'description': "The recipient's first name. Falls back to their full name.",
        'example': 'Alex',
    },
    'name': {
        'label': 'Full name', 'scope': 'recipient',
        'description': "The recipient's full name.",
        'example': 'Alex Morgan',
    },
    'team': {
        'label': 'Team', 'scope': 'recipient',
        'description': "The team they are on this season. Blank if they are not rostered.",
        'example': 'Sharks',
    },
    'league': {
        'label': 'League', 'scope': 'recipient',
        'description': 'Their league this season, e.g. Premier or Classic.',
        'example': 'Premier',
    },
    'season': {
        'label': 'Season', 'scope': 'recipient',
        'description': 'The current season name.',
        'example': '2026 Spring',
    },
    'discord_invite_url': {
        'label': 'Discord invite link', 'scope': 'global',
        'description': 'Your Discord server invite. Change it in one place and every '
                       'automation picks it up.',
        'setting': 'discord_invite_url',
    },
    'support_email': {
        'label': 'Support email', 'scope': 'global',
        'description': 'The address you tell people to contact for help.',
        'setting': 'support_email',
    },
}

# Which AdminConfig key backs each global variable, and its fallback.
GLOBAL_VARIABLE_SETTINGS = {
    'discord_invite_url': ('discord_invite_url', 'https://discord.gg/weareecs'),
    'support_email': ('support_email', 'ecspubleague@gmail.com'),
}


def known_variable_names():
    """Every {token} the engine knows how to fill.

    The enable-guard uses this to spot placeholders that would otherwise ship
    literally -- like a {survey_url} that was never filled in.
    """
    return set(MESSAGE_VARIABLES)

# ─────────────────────────────────────────────────────────────────────────────
# OVERLAP WARNINGS
#
# Parts of this app already send messages on their own -- the substitute system,
# the RSVP reminders, the match-day digest. An admin building an automation has
# no way to know that, and the failure mode is silent: the member just gets two
# messages about the same thing.
#
# Keyed by trigger_type. Shown in the editor and again when enabling. Advisory,
# never blocking -- the admin may genuinely want a second touch on a different
# channel, and we should not pretend to know better.
# ─────────────────────────────────────────────────────────────────────────────

TRIGGER_OVERLAPS = {
    TRIGGER_USER_APPROVED: {
        'text': ("Approval already sends a push notification and an in-app alert "
                 "(\"You're in!\") the moment it happens. Email is deliberately left "
                 "out there, so an email here adds the detail that one cannot — which "
                 "is usually exactly what you want."),
        'avoid_channels': ['push', 'in_app'],
        'avoid_reason': ("they already get a push and an in-app alert on approval, so "
                         "adding those here means being told twice"),
        'where': 'Sent automatically on approval (no setting to change).',
    },
    TRIGGER_SUB_NO_REPLY: {
        'text': ("The substitute system sends the FIRST ask itself, and its wording, "
                 "channels and timing are configured in Substitutes \u2192 Settings. "
                 "This rule is the follow-up nudge when nobody answers."),
        'avoid_channels': [],
        'where': 'Substitutes \u2192 Settings (reach-out channels and message).',
    },
    TRIGGER_SUB_REQUEST_UNFILLED: {
        'text': ("This warns whoever ASKED for the sub. It does not reach out to the "
                 "sub pool \u2014 that is still a manual step on the request itself, "
                 "and its message is configured in Substitutes \u2192 Settings."),
        'avoid_channels': [],
        'where': 'Substitutes \u2192 Settings (reach-out defaults).',
    },
    TRIGGER_MATCH_RESCHEDULED: {
        'text': ("Players already get a day-before reminder that carries the current "
                 "kick-off time, so a very late reschedule is covered either way. This "
                 "tells them as soon as it changes, which is the point."),
        'avoid_channels': [],
        'where': 'Daily match reminder (18:00).',
    },
}


def overlap_warning(trigger_type):
    """Advisory note about existing behaviour this trigger sits near, or None."""
    return TRIGGER_OVERLAPS.get(trigger_type)


def channel_clashes(trigger_type, channels):
    """Channels on this rule that would double-notify, given what already exists.

    Advisory only. An admin may genuinely want a second touch, and we should not
    pretend to know their situation better than they do.
    """
    meta = TRIGGER_OVERLAPS.get(trigger_type) or {}
    avoid = set(meta.get('avoid_channels') or [])
    return sorted(avoid & set(channels or []))

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

    # Optional extra narrowing, applied AFTER the audience resolves.
    #
    # A list whose entries are either a plain condition
    #     {'field': ..., 'op': ..., 'value': ...}
    # or a GROUP
    #     {'any': [ ...conditions... ]}   -- at least one must pass
    #     {'all': [ ...conditions... ]}   -- every one must pass
    # Top-level entries are ANDed together, so 'any' groups are how an admin
    # expresses OR without needing to think about nesting.
    conditions = db.Column(db.JSON, nullable=True)

    # ── Action: a SEQUENCE of steps ──────────────────────────────────────────
    #
    # [{"wait_hours": 0,  "channels": ["email"], "subject": ..., "body_html": ...,
    #   "short_message": ...},
    #  {"wait_hours": 72, "channels": ["email","push"], ...}]
    #
    # wait_hours on step 0 is the delay from the trigger; on later steps it is the
    # gap since the previous step. This is what makes escalation ladders possible
    # ("ask, then widen, then all-hands") instead of one flat send.
    #
    # NULL/empty means "legacy single-step rule" and is materialised on read from
    # delay_hours/channels/subject/body_html, so rules written before sequences
    # existed keep working untouched.
    steps = db.Column(db.JSON, nullable=True)

    # Re-check the trigger before every step AFTER the first, and stop the ladder
    # if the situation resolved itself -- the sub request got filled, the player
    # joined Discord, the profile was updated. Without this an escalation keeps
    # nagging people who already did the thing.
    stop_when_resolved = db.Column(db.Boolean, nullable=False, default=True,
                                   server_default='true')

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


    def action_steps(self):
        """The action sequence, always as a list of at least one step.

        A rule created before sequences existed has steps = NULL; its single
        send is materialised here from the flat columns so every caller can
        treat rules uniformly.
        """
        raw = self.steps
        if isinstance(raw, list) and raw:
            return raw
        return [{
            'wait_hours': self.delay_hours or 0,
            'channels': self.channels or ['email'],
            'subject': self.subject,
            'body_html': self.body_html,
            'short_message': self.short_message,
        }]

    @property
    def step_count(self):
        return len(self.action_steps())

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
            'steps': self.action_steps(),
            'stop_when_resolved': self.stop_when_resolved,
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

    # Which step of the action sequence runs next (0-based).
    current_step = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # When that step is due. scheduled_for stays as the ORIGINAL first-send time
    # so the history still shows when the automation first fired.
    next_step_at = db.Column(db.DateTime, nullable=True)

    # pending | sending | sent | failed | cancelled | skipped
    # A multi-step run returns to 'pending' between steps and only reaches 'sent'
    # after the last one.
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
            'current_step': self.current_step,
            'error_message': self.error_message,
        }

    def __repr__(self):
        return f'<AutomationRun rule={self.rule_id} scope={self.scope_key} status={self.status}>'
