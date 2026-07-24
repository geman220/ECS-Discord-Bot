# app/services/automation_service.py

"""
Automated Messaging Engine
==========================

Evaluates AutomationRules, records AutomationRuns, and dispatches due runs as
EmailCampaigns.

Design notes worth knowing before changing anything here:

* **Season resolution uses the passed session, not Season.query.** `is_current`
  is per league_type (both a Pub League and an ECS FC season are current at
  once), so every lookup is league_type-scoped. The helpers in
  app/utils/season_context.py do the same thing but go through `Season.query`
  (db.session); mixing that with the Celery task's session silently discards
  writes, so they are deliberately not used here.

* **event_at is derived from data, not from when the beat task ran.** For a
  draft that means the timestamp of the pick that pushed the last team over the
  threshold. Two consequences: the send time is the same no matter when the task
  first notices, and re-running evaluation is harmless.

* **Idempotency is the AutomationRun (rule_id, scope_key) unique constraint.**
  Evaluation only ever INSERTs a run that does not exist; it never re-fires one.

* **Freshness guard.** A rule enabled long after its trigger already happened
  would otherwise fire immediately for a stale event. Runs whose event is older
  than `max_event_age_days` are recorded as 'skipped' instead of 'pending', so
  the scope is consumed (no surprise send) but visible in the run history. An
  admin can still force-run from the UI.

* **Delivery is not reimplemented.** A run creates an EmailCampaign through
  email_broadcast_service and hands it to the existing send task, which owns
  audience resolution, opt-out gating, throttling, and the per-recipient
  EmailCampaignRecipient rows that answer "who got this".
"""

import logging
import re
from datetime import datetime, timedelta, time
from types import SimpleNamespace

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.automation import (
    AutomationRule, AutomationRun, build_scope_key,
    TRIGGER_DRAFT_COMPLETE, TRIGGER_DRAFT_SESSION_COMPLETE,
    TRIGGER_SEASON_PHASE, TRIGGER_SEASON_DATE,
    TRIGGER_USER_APPROVED, TRIGGER_WAITLIST_STUCK, TRIGGER_SUB_NO_REPLY,
)
from app.models.core import Season, League, User, Role, user_roles
from app.models.players import Player, Team, player_teams
from app.models.league_features import DraftOrderHistory, DraftSession
from app.models.email_templates import EmailTemplate
from app.services.automation_defaults import SUPPORT_EMAIL, DEFAULT_DISCORD_INVITE

logger = logging.getLogger(__name__)

# How many stale Discord-membership rows to refresh against the bot in one pass.
# Each is a separate HTTP call to the bot (there is no bulk guild-member
# endpoint), and the sync client's circuit breaker trips after 2 consecutive
# failures, so this is a cost ceiling rather than a correctness knob.
MAX_MEMBERSHIP_REFRESH = 400

# Ceiling on AutomationRuns created in a single evaluation pass. Per-subject
# triggers can return hundreds of events the first time a rule is enabled;
# the overflow is deferred to the next pass and logged, never dropped silently.
MAX_RUNS_PER_PASS = 200

# The admin "live check" preview runs inside a web request, so it gets a much
# lower ceiling than the Celery dispatch path. At ~1 bot round-trip each this
# keeps the page responsive; the real send refreshes the full set anyway.
PREVIEW_MEMBERSHIP_REFRESH = 60

# Reuse the staleness policy already established in app/teams.py:231-273 so the
# whole app agrees on when a cached membership answer is too old to trust.
_STALENESS = {
    True: timedelta(days=30),    # confirmed in server -> re-check monthly
    False: timedelta(hours=24),  # confirmed absent -> re-check daily
    None: timedelta(days=7),     # never resolved -> re-check weekly
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _current_season(session, league_type):
    """The current season for one league_type, using the caller's session."""
    return (session.query(Season)
            .filter(Season.is_current.is_(True), Season.league_type == league_type)
            .first())


def _leagues_for(session, season, league_names=None):
    """Active leagues in a season, optionally narrowed to specific names."""
    q = session.query(League).filter(League.season_id == season.id)
    # is_active is nullable on League; NULL means active.
    q = q.filter((League.is_active.is_(True)) | (League.is_active.is_(None)))
    leagues = q.all()
    if league_names:
        wanted = {n.strip().lower() for n in league_names if n and n.strip()}
        leagues = [lg for lg in leagues if lg.name.lower() in wanted]
    return leagues


def _fallback_creator_id(session, rule):
    """User id to stamp on generated campaigns.

    EmailCampaign.created_by_id is NOT NULL, but a seeded rule has no author, so
    fall back to any Global Admin.
    """
    if rule.created_by_id:
        return rule.created_by_id
    admin_id = (session.query(User.id)
                .join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id)
                .filter(Role.name == 'Global Admin')
                .order_by(User.id)
                .limit(1)
                .scalar())
    return admin_id


# ─────────────────────────────────────────────────────────────────────────────
# Trigger detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_draft_complete(session, rule):
    """Leagues whose draft looks finished.

    "Finished" means every active team in the league has at least
    `min_players_per_team` non-coach players on its roster. Roster count comes
    from player_teams (the live roster) rather than DraftOrderHistory, because
    draft-history writes are best-effort -- the socket draft path wraps them in a
    swallowed SAVEPOINT -- so a player can legitimately be rostered with no
    history row. Counting history would under-count and stall the trigger
    forever.

    Returns:
        list[dict]: {'season_id', 'league_id', 'event_at'} per finished league.
    """
    cfg = rule.trigger_config or {}
    league_type = cfg.get('league_type', 'Pub League')
    min_players = int(cfg.get('min_players_per_team', 6))

    season = _current_season(session, league_type)
    if not season:
        logger.debug("No current %s season; draft trigger inert", league_type)
        return []

    results = []
    for league in _leagues_for(session, season, cfg.get('league_names')):
        teams = (session.query(Team)
                 .filter(Team.league_id == league.id)
                 .filter((Team.is_active.is_(True)) | (Team.is_active.is_(None)))
                 .all())
        if not teams:
            continue

        team_ids = [t.id for t in teams]
        counts = dict(
            session.query(player_teams.c.team_id, func.count(player_teams.c.player_id))
            .filter(player_teams.c.team_id.in_(team_ids))
            # isnot(True), NOT is_(False): is_coach is nullable with only a
            # Python-side default, so rows written by raw SQL or older code hold
            # NULL. is_(False) would drop those players from the count and the
            # threshold could never be reached.
            .filter(player_teams.c.is_coach.isnot(True))
            .group_by(player_teams.c.team_id)
            .all()
        )

        short = [t for t in teams if counts.get(t.id, 0) < min_players]
        if short:
            logger.debug(
                "League %s draft not complete: %d/%d teams under %d players",
                league.name, len(short), len(teams), min_players
            )
            continue

        event_at = _draft_event_time(session, season, league, team_ids, min_players)
        results.append({
            'season_id': season.id,
            'league_id': league.id,
            'event_at': event_at,
            'label': f'{league.name} — {season.name}',
        })

    return results


def _draft_event_time(session, season, league, team_ids, min_players):
    """When this league's draft crossed the threshold.

    Preference order:
      1. DraftSession.completed_at -- the live draft clock was used and an admin
         explicitly ended it. Most authoritative.
      2. The tip-over pick: for each team the drafted_at of its Nth non-coach
         pick; the event is the LAST of those, i.e. the moment the final team
         reached the threshold.
      3. The most recent pick in the league, if history is too sparse for (2).
      4. Now -- only when the league has no draft history at all (rosters were
         built by hand). Stable regardless, because it is persisted on the run.
    """
    ds = (session.query(DraftSession)
          .filter(DraftSession.season_id == season.id,
                  DraftSession.league_id == league.id,
                  DraftSession.status == 'complete',
                  DraftSession.completed_at.isnot(None))
          .first())
    if ds:
        return ds.completed_at

    # Non-coach picks only, so the coach pre-draft a week earlier cannot supply
    # the tip-over timestamp.
    rows = (session.query(DraftOrderHistory.team_id, DraftOrderHistory.drafted_at)
            .join(player_teams,
                  (player_teams.c.player_id == DraftOrderHistory.player_id) &
                  (player_teams.c.team_id == DraftOrderHistory.team_id))
            .filter(DraftOrderHistory.season_id == season.id,
                    DraftOrderHistory.league_id == league.id,
                    player_teams.c.is_coach.isnot(True))  # nullable: NULL == not a coach
            .order_by(DraftOrderHistory.drafted_at)
            .all())

    if not rows:
        return datetime.utcnow()

    by_team = {}
    for team_id, drafted_at in rows:
        by_team.setdefault(team_id, []).append(drafted_at)

    nth_times = []
    for team_id in team_ids:
        picks = by_team.get(team_id, [])
        if len(picks) >= min_players:
            nth_times.append(picks[min_players - 1])

    if len(nth_times) == len(team_ids):
        return max(nth_times)

    # History is sparser than the roster (admin adds, swallowed history writes).
    # Fall back to the last recorded pick rather than inventing a time.
    return max(drafted_at for _, drafted_at in rows)


def detect_season_phase(session, rule):
    """Fire when a season is sitting in the configured phase.

    There is no phase-transition audit column, so the event time is when we first
    observe the phase. That timestamp is persisted on the AutomationRun, so it
    stays stable across later evaluations.
    """
    cfg = rule.trigger_config or {}
    league_type = cfg.get('league_type', 'Pub League')
    target_phase = cfg.get('phase', 'offseason')

    season = _current_season(session, league_type)
    if not season or season.phase != target_phase:
        return []

    return [{
        'season_id': season.id,
        'league_id': None,
        'event_at': datetime.utcnow(),
        'label': f'{season.name} → {target_phase}',
    }]


def detect_draft_session_complete(session, rule):
    """Fire when the live draft clock was explicitly ended for a league.

    Exact — `completed_at` is a real timestamp written when an admin ends the
    draft. The trade-off versus detect_draft_complete is coverage: if the draft
    was run without the clock there is no DraftSession row and this never fires.
    """
    cfg = rule.trigger_config or {}
    league_type = cfg.get('league_type', 'Pub League')

    season = _current_season(session, league_type)
    if not season:
        return []

    wanted_ids = {lg.id: lg for lg in _leagues_for(session, season, cfg.get('league_names'))}
    if not wanted_ids:
        return []

    rows = (session.query(DraftSession)
            .filter(DraftSession.season_id == season.id,
                    DraftSession.league_id.in_(list(wanted_ids.keys())),
                    DraftSession.status == 'complete',
                    DraftSession.completed_at.isnot(None))
            .all())

    return [{
        'season_id': season.id,
        'league_id': ds.league_id,
        'event_at': ds.completed_at,
        'label': f'{wanted_ids[ds.league_id].name} — {season.name}',
    } for ds in rows]


def _pacific_midnight_utc(d):
    """Naive-UTC instant corresponding to local midnight on date `d`.

    Falls back to treating the date as UTC if tz data is unavailable, which is
    still correct to within the offset rather than silently wrong by a day.
    """
    try:
        from zoneinfo import ZoneInfo
        local = datetime.combine(d, time.min, tzinfo=ZoneInfo('America/Los_Angeles'))
        return local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    except Exception:
        logger.debug("No tz data; treating %s as UTC midnight", d, exc_info=True)
        return datetime.combine(d, time.min)


def detect_season_date(session, rule):
    """Fire relative to the season's start or end date.

    `days_offset` is signed: -3 means three days BEFORE the anchor, +1 means the
    day after. The event time is the anchor date shifted by the offset, so the
    delay stacks on top of a real calendar date rather than a discovery time.
    Nothing fires until that moment has actually passed.
    """
    cfg = rule.trigger_config or {}
    league_type = cfg.get('league_type', 'Pub League')
    anchor = cfg.get('date_anchor', 'start')
    offset_days = int(cfg.get('days_offset', 0))

    season = _current_season(session, league_type)
    if not season:
        return []

    anchor_date = season.start_date if anchor == 'start' else season.end_date
    if not anchor_date:
        logger.debug("Season %s has no %s_date; date trigger inert", season.id, anchor)
        return []

    # Season start/end are calendar dates in LOCAL (Pacific) terms, but every
    # timestamp in this engine is naive UTC. Combining the date with UTC midnight
    # would fire 7-8 hours early -- a "day of season start" rule would go out at
    # 4-5pm the previous local afternoon. Convert local midnight to UTC instead.
    event_at = _pacific_midnight_utc(anchor_date) + timedelta(days=offset_days)

    # Do not fire ahead of the date itself. Without this a "3 days before the
    # season starts" rule would schedule the moment the season row was created.
    if event_at > datetime.utcnow():
        return []

    direction = 'after' if offset_days > 0 else ('before' if offset_days < 0 else 'on')
    label = f'{season.name} — {abs(offset_days)}d {direction} {anchor}' if offset_days \
        else f'{season.name} — {anchor} date'

    return [{
        'season_id': season.id,
        'league_id': None,
        'event_at': event_at,
        'label': label,
    }]


# ─────────────────────────────────────────────────────────────────────────────
# Per-subject detectors — one event per person
#
# These can legitimately return hundreds of events the first time a rule is
# enabled, so evaluate_rule caps how many runs a single pass will create and
# logs what it left behind (never a silent truncation).
# ─────────────────────────────────────────────────────────────────────────────

def detect_user_approved(session, rule):
    """One event per user whose account was approved.

    `approved_at` is a real timestamp (app/models/core.py:140), so the delay is
    measured from the approval itself rather than from when we noticed.
    """
    cfg = rule.trigger_config or {}
    horizon = datetime.utcnow() - timedelta(days=int(cfg.get('max_event_age_days', 14)))

    rows = (session.query(User.id, User.username, User.approved_at)
            .filter(User.approval_status == 'approved',
                    User.approved_at.isnot(None),
                    User.approved_at >= horizon,
                    User.is_active.is_(True))
            .order_by(User.approved_at)
            .all())

    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'user', 'subject_id': uid,
        'event_at': approved_at,
        'label': f'{username} approved',
    } for uid, username, approved_at in rows]


def detect_waitlist_stuck(session, rule):
    """One event per user still waiting after `stuck_days`."""
    cfg = rule.trigger_config or {}
    stuck_days = int(cfg.get('stuck_days', 14))
    max_age_days = int(cfg.get('max_event_age_days', 14))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=stuck_days)
    # Lower bound so the first evaluation does not sweep up years of history.
    # Anything older than this crosses the threshold outside the freshness
    # window, so evaluate_rule would only file it as 'skipped' -- 200 junk rows
    # an hour until the backlog is chewed through, plus a heavy query forever.
    horizon = now - timedelta(days=stuck_days + max_age_days)

    rows = (session.query(User.id, User.username, User.waitlist_joined_at)
            .filter(User.waitlist_joined_at.isnot(None),
                    User.waitlist_joined_at <= cutoff,
                    User.waitlist_joined_at >= horizon,
                    User.is_active.is_(True),
                    # Several bulk-approve paths set approval_status='approved'
                    # WITHOUT clearing waitlist_joined_at, so the timestamp alone
                    # would tell someone already placed on a team that they are
                    # still stuck waiting.
                    User.approval_status != 'approved')
            .order_by(User.waitlist_joined_at)
            .all())

    # The event is the moment they CROSSED the threshold, not when they joined,
    # so the configured delay stacks on top of stuck_days instead of being
    # swallowed by however long they have already been waiting.
    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'user', 'subject_id': uid,
        'event_at': joined + timedelta(days=stuck_days),
        'label': f'{username} waiting {stuck_days}d+',
    } for uid, username, joined in rows]


def detect_sub_no_reply(session, rule):
    """One event per (player, sub request) asked and never answered."""
    from app.models.substitutes import SubstituteResponse

    cfg = rule.trigger_config or {}
    silence_hours = int(cfg.get('silence_hours', 24))
    max_age_days = int(cfg.get('max_event_age_days', 14))
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=silence_hours)
    # Bounded for the same reason as the waitlist detector: unanswered sub
    # requests accumulate forever, and every historical one would otherwise
    # become a 'skipped' run.
    horizon = now - timedelta(hours=silence_hours) - timedelta(days=max_age_days)

    from app.models.substitutes import SubstituteRequest

    rows = (session.query(SubstituteResponse.id,
                          SubstituteResponse.player_id,
                          SubstituteResponse.request_id,
                          SubstituteResponse.notification_sent_at)
            .join(SubstituteRequest, SubstituteRequest.id == SubstituteResponse.request_id)
            .join(Player, Player.id == SubstituteResponse.player_id)
            .join(User, User.id == Player.user_id)
            .filter(SubstituteResponse.notification_sent_at.isnot(None),
                    SubstituteResponse.notification_sent_at <= cutoff,
                    SubstituteResponse.notification_sent_at >= horizon,
                    SubstituteResponse.responded_at.is_(None),
                    SubstituteResponse.is_available.is_(None),
                    # Don't chase people about a request that no longer needs
                    # them -- someone else already covered it or it was pulled.
                    SubstituteRequest.status == 'OPEN',
                    SubstituteRequest.filled_at.is_(None),
                    SubstituteRequest.cancelled_at.is_(None),
                    # These detectors feed the 'specific_users' audience, which
                    # bypasses the usual is_active/is_approved gate, so filter here.
                    User.is_active.is_(True))
            .order_by(SubstituteResponse.notification_sent_at)
            .all())

    # Subject is the response row, not the player: the same person can be asked
    # for several different matches and each deserves its own nudge.
    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'sub_response', 'subject_id': resp_id,
        'recipient_player_id': player_id,
        'event_at': sent_at + timedelta(hours=silence_hours),
        'label': f'No reply to sub request #{request_id}',
    } for resp_id, player_id, request_id, sent_at in rows]


DETECTORS = {
    TRIGGER_DRAFT_COMPLETE: detect_draft_complete,
    TRIGGER_DRAFT_SESSION_COMPLETE: detect_draft_session_complete,
    TRIGGER_SEASON_PHASE: detect_season_phase,
    TRIGGER_SEASON_DATE: detect_season_date,
    TRIGGER_USER_APPROVED: detect_user_approved,
    TRIGGER_WAITLIST_STUCK: detect_waitlist_stuck,
    TRIGGER_SUB_NO_REPLY: detect_sub_no_reply,
}


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_rule(session, rule):
    """Detect triggers for one rule and record any new AutomationRuns.

    Returns:
        list[AutomationRun]: newly created runs (pending or skipped).
    """
    detector = DETECTORS.get(rule.trigger_type)
    if not detector:
        logger.warning("Rule %s has unknown trigger_type %r", rule.key, rule.trigger_type)
        return []

    try:
        events = detector(session, rule)
    except Exception:
        # Still stamp the evaluation time, otherwise a permanently-broken rule
        # reads as "never evaluated" in the UI instead of "failing every hour".
        logger.exception("Trigger detection failed for rule %s", rule.key)
        rule.last_evaluated_at = datetime.utcnow()
        return []

    cfg = rule.trigger_config or {}
    max_age_days = cfg.get('max_event_age_days', 14)
    now = datetime.utcnow()
    created = []

    # Drop events that already have a run BEFORE applying the cap. Capping first
    # was a starvation bug: detectors sort ascending, so every pass truncated to
    # the same oldest N -- which already had runs -- and everything past N was
    # never created, then aged out of the freshness window permanently.
    fresh_events = []
    for event in events:
        key = build_scope_key(event['season_id'], event['league_id'],
                              event.get('subject_type'), event.get('subject_id'))
        if not (session.query(AutomationRun.id)
                .filter(AutomationRun.rule_id == rule.id,
                        AutomationRun.scope_key == key)
                .first()):
            fresh_events.append((key, event))

    if len(fresh_events) > MAX_RUNS_PER_PASS:
        logger.warning(
            "Rule %s has %d new events; creating %d this pass, %d deferred to the next",
            rule.key, len(fresh_events), MAX_RUNS_PER_PASS,
            len(fresh_events) - MAX_RUNS_PER_PASS)
        fresh_events = fresh_events[:MAX_RUNS_PER_PASS]

    for scope_key, event in fresh_events:
        event_at = event['event_at']
        scheduled_for = event_at + timedelta(hours=rule.delay_hours or 0)

        status = 'pending'
        error_message = None
        if max_age_days is not None:
            age = now - event_at
            if age > timedelta(days=int(max_age_days)):
                status = 'skipped'
                error_message = (
                    f'Trigger fired {age.days}d ago, older than the '
                    f'{max_age_days}d freshness window. Not sent automatically.'
                )

        run = AutomationRun(
            rule_id=rule.id,
            season_id=event['season_id'],
            league_id=event['league_id'],
            subject_type=event.get('subject_type'),
            subject_id=event.get('subject_id'),
            scope_key=scope_key,
            event_at=event_at,
            scheduled_for=scheduled_for,
            status=status,
            error_message=error_message,
        )
        # SAVEPOINT, not a bare flush: if another worker inserted this scope
        # concurrently the unique constraint fires, and a plain session.rollback()
        # here would discard every run created earlier in this same pass.
        try:
            with session.begin_nested():
                session.add(run)
        except IntegrityError:
            # The unique constraint is the authority; drop ours and move on.
            logger.info("Run for rule %s scope %s already created concurrently",
                        rule.key, scope_key)
            continue

        created.append(run)
        logger.info("Automation %s scheduled for %s (scope %s, status %s)",
                    rule.key, scheduled_for, scope_key, status)

    rule.last_evaluated_at = now
    return created


def evaluate_all(session):
    """Evaluate every enabled rule. Returns a summary dict."""
    rules = session.query(AutomationRule).filter(AutomationRule.enabled.is_(True)).all()
    total = 0
    for rule in rules:
        total += len(evaluate_rule(session, rule))
    return {'rules_evaluated': len(rules), 'runs_created': total}


# ─────────────────────────────────────────────────────────────────────────────
# Discord membership freshness
# ─────────────────────────────────────────────────────────────────────────────

def refresh_membership_for_scope(session, season_id, league_ids=None,
                                 limit=MAX_MEMBERSHIP_REFRESH):
    """Re-check Discord membership for rostered players with stale answers.

    Without this the audience is only as good as the last role sync, and we would
    email people who joined Discord yesterday. Runs immediately before audience
    resolution at dispatch.

    Only players with a linked discord_id can be checked; players with no
    discord_id are already in the audience by definition and need no call.
    """
    # Select scalar columns, NOT the Player entity. `query(Player).distinct()`
    # emits SELECT DISTINCT over every mapped column, which includes
    # Player.discord_roles -- a `json` column (app/models/players.py:250).
    # Postgres has no equality operator for `json`, so that form dies with
    # "could not identify an equality operator for type json" and leaves the
    # transaction aborted.
    q = (session.query(Player.id, Player.discord_in_server, Player.discord_last_checked)
         .join(player_teams, player_teams.c.player_id == Player.id)
         .join(Team, Team.id == player_teams.c.team_id)
         .join(League, League.id == Team.league_id)
         .filter(Player.discord_id.isnot(None))
         .filter(League.season_id == season_id))
    if league_ids:
        q = q.filter(League.id.in_(list(league_ids)))

    now = datetime.utcnow()
    candidates = []
    for player_id, in_server, last_checked in q.distinct().all():
        window = _STALENESS.get(in_server, timedelta(days=7))
        if last_checked is None or (now - last_checked) > window:
            candidates.append(player_id)

    # Release the read transaction BEFORE making any HTTP calls. Transaction hold
    # time is the scarce resource here (PgBouncer transaction pooling, 1 vCPU),
    # and each check below is a separate round-trip to the bot -- batching them
    # inside one open transaction would pin a pooled connection for minutes.
    session.commit()

    attempted = 0
    resolved = 0
    for player_id in candidates[:limit]:
        player = session.query(Player).get(player_id)
        if not player:
            continue
        attempted += 1
        try:
            # Returns True only when the bot actually answered. False means the
            # call failed or the circuit breaker is open -- count those
            # separately, because "we asked and learned nothing" is what the
            # caller needs to know before deciding to send.
            if player.check_discord_status(fast_fail=True):
                resolved += 1
        except Exception:
            logger.exception("Discord status check failed for player %s", player_id)
        # Commit per player so the HTTP call for the NEXT player happens with no
        # transaction open.
        session.commit()

    logger.info("Discord membership refresh: %d stale, %d attempted, %d resolved",
                len(candidates), attempted, resolved)
    return {'stale': len(candidates), 'attempted': attempted, 'resolved': resolved}


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

def resolve_subject_user_id(session, run):
    """The User this per-subject run is about, or None.

    Subjects come in three flavours because the triggers anchor to whatever row
    actually carries the timestamp: a User directly, or a substitute-response /
    survey-response row that points at a Player.
    """
    if run.subject_type == 'user':
        return run.subject_id

    player_id = None
    if run.subject_type == 'player':
        player_id = run.subject_id
    elif run.subject_type == 'sub_response':
        from app.models.substitutes import SubstituteResponse
        player_id = (session.query(SubstituteResponse.player_id)
                     .filter(SubstituteResponse.id == run.subject_id).scalar())
    elif run.subject_type == 'survey_response':
        from app.models.surveys import SurveyResponse
        player_id = (session.query(SurveyResponse.player_id)
                     .filter(SurveyResponse.id == run.subject_id).scalar())

    if not player_id:
        return None
    return (session.query(Player.user_id)
            .filter(Player.id == player_id).scalar())


def build_filter_criteria(session, rule, run):
    """Assemble the email_broadcast_service filter_criteria for a run."""
    # Per-subject rules target exactly one person: the one the trigger is about.
    if rule.audience_type == 'the_subject':
        user_id = resolve_subject_user_id(session, run)
        return {'type': 'specific_users', 'user_ids': [user_id] if user_id else []}

    criteria = dict(rule.audience_config or {})
    criteria['type'] = rule.audience_type
    if run.season_id:
        criteria['season_id'] = run.season_id
    if run.league_id:
        criteria['league_ids'] = [run.league_id]
    return criteria


def apply_conditions(session, rule, recipients):
    """Narrow a resolved recipient list by the rule's conditions.

    Every condition must pass. Evaluated in Python rather than SQL because the
    fields span Player and User and the lists here are hundreds of rows, so one
    extra query beats a pile of conditional joins.

    A condition naming an unknown field is treated as FAILING CLOSED (nobody
    passes) rather than being ignored -- silently dropping a condition an admin
    wrote could send to an audience they explicitly excluded.
    """
    from app.models.automation import CONDITION_FIELDS

    conditions = rule.conditions or []
    if not conditions or not recipients:
        return recipients

    user_ids = [r['user_id'] for r in recipients]
    rows = (session.query(User.id, User.approval_status, User.email_notifications,
                          Player.discord_in_server, Player.discord_id,
                          Player.is_current_player, Player.is_coach, Player.is_sub)
            .outerjoin(Player, Player.user_id == User.id)
            .filter(User.id.in_(user_ids))
            .all())
    # A User can legitimately have MORE THAN ONE Player row in this database
    # (known duplicate/orphan player records), so the outer join fans out. A
    # plain dict comprehension would keep whichever row happened to come last.
    # Collect every player row per user instead and satisfy a player condition
    # if ANY of them does: duplicates are a data defect, and someone should not
    # be excluded from a mailing because of one.
    facts = {}
    for r in rows:
        entry = facts.setdefault(r[0], {
            'user.approval_status': r[1],
            'user.email_notifications': r[2],
            'players': [],
        })
        entry['players'].append({
            'player.discord_in_server': r[3],
            'player.discord_id': r[4],
            'player.is_current_player': r[5],
            'player.is_coach': r[6],
            'player.is_sub': r[7],
        })

    def _test(actual, op, expected):
        if op == 'is_true':
            return actual is True
        if op == 'is_false':
            # Only an explicit True fails. NULL counts as "not true", matching
            # how every other nullable boolean is treated in this engine.
            return actual is not True
        if op == 'exists':
            return actual not in (None, '')
        if op == 'missing':
            return actual in (None, '')
        if op == 'eq':
            return str(actual) == str(expected)
        if op == 'neq':
            return str(actual) != str(expected)
        return False

    def passes(user_id):
        row = facts.get(user_id)
        if row is None:
            return False
        for cond in conditions:
            if not isinstance(cond, dict):
                logger.warning("Rule %s has a malformed condition %r; failing closed",
                               rule.key, cond)
                return False
            field = cond.get('field')
            op = cond.get('op')
            if field not in CONDITION_FIELDS:
                logger.warning("Rule %s has an unknown condition field %r; "
                               "failing closed", rule.key, field)
                return False
            expected = cond.get('value')

            if field.startswith('player.'):
                # POSITIVE tests (is_true / exists / eq) use any(): with a
                # duplicate/orphan Player row alongside the real one, the person
                # still qualifies.
                #
                # NEGATIVE tests (is_false / missing / neq) MUST use all().
                # any() here inverted them -- an all-NULL orphan row would
                # satisfy "is not in the Discord server" for someone who
                # demonstrably is, which is exactly the audience this engine's
                # flagship rule targets.
                players = row['players']
                if op in ('is_false', 'missing', 'neq'):
                    ok = all(_test(p.get(field), op, expected) for p in players)
                else:
                    ok = any(_test(p.get(field), op, expected) for p in players)
                if not ok:
                    return False
                continue

            actual = row.get(field)
            if not _test(actual, op, expected):
                return False
        return True

    kept = [r for r in recipients if passes(r['user_id'])]
    if len(kept) != len(recipients):
        logger.info("Rule %s conditions narrowed audience %d -> %d",
                    rule.key, len(recipients), len(kept))
    return kept


def substitute_placeholders(session, text):
    """Fill non-personalization placeholders from admin config.

    {first_name}/{team}/etc. are intentionally left alone -- those are resolved
    per-recipient by the send task.
    """
    if not text:
        return text
    invite = DEFAULT_DISCORD_INVITE
    try:
        from app.models.admin_config import AdminConfig
        invite = AdminConfig.get_setting('discord_invite_url', None) or DEFAULT_DISCORD_INVITE
    except Exception:
        logger.debug("Falling back to default Discord invite URL", exc_info=True)
    return (text
            .replace('{discord_invite_url}', invite)
            .replace('{support_email}', SUPPORT_EMAIL))


def dispatch_run(session, run, force=False):
    """Turn a due AutomationRun into a sent EmailCampaign.

    Args:
        run: the AutomationRun to send.
        force: bypass the scheduled_for check and the 'pending' status gate
               (used by the admin "run now" action).

    Returns:
        dict: {'success': bool, ...}
    """
    from app.services.email_broadcast_service import EmailBroadcastService
    from app.tasks.tasks_email_broadcast import send_email_broadcast

    rule = run.rule
    if not force:
        if run.scheduled_for > datetime.utcnow():
            return {'success': False, 'error': 'Not due yet'}

    # CLAIM the run atomically before doing anything expensive. The work below
    # (up to 400 sequential bot calls, then campaign creation) can outlast the
    # hourly beat interval, so without this a second pass would find the run
    # still 'pending' and send the same campaign again. The UPDATE ... WHERE
    # status IN (...) is the lock: exactly one worker can win it.
    allowed_from = ('pending', 'skipped', 'failed') if force else ('pending',)
    claimed = (session.query(AutomationRun)
               .filter(AutomationRun.id == run.id,
                       AutomationRun.status.in_(allowed_from))
               .update({'status': 'sending'}, synchronize_session=False))
    session.commit()
    if not claimed:
        session.refresh(run)
        return {'success': False,
                'error': f'Run is {run.status} — another send already claimed it'}
    session.refresh(run)

    service = EmailBroadcastService()

    # Make the membership answers current before resolving the audience, so we
    # do not email someone who joined Discord since the last sync.
    if rule.audience_type == 'drafted_not_in_discord' and run.season_id:
        try:
            stats = refresh_membership_for_scope(
                session, run.season_id,
                [run.league_id] if run.league_id else None
            )
            # If the bot was unreachable we learned nothing, and the audience
            # treats "unknown" as "not in Discord" — so sending now would tell
            # people who ARE in the server that we can't find them. Abort and
            # leave the run claimable on the next pass.
            if stats['attempted'] and not stats['resolved']:
                run.status = 'pending'
                run.error_message = (
                    f"Discord was unreachable ({stats['attempted']} checks, none "
                    f"answered). Not sending — the audience would be wrong. "
                    f"Will retry."
                )
                session.commit()
                return {'success': False, 'error': run.error_message}
        except Exception:
            logger.exception("Membership refresh failed for run %s", run.id)
            run.status = 'pending'
            run.error_message = 'Discord membership refresh failed; will retry.'
            session.commit()
            return {'success': False, 'error': run.error_message}

    criteria = build_filter_criteria(session, rule, run)
    # Describe the audience BEFORE conditions pin it to explicit ids, so the
    # campaign still reads "Rostered players not in Discord" rather than
    # "Specific users (N selected)".
    filter_description = service.build_filter_description(session, criteria)

    # Conditions must be applied HERE. create_campaign re-resolves recipients
    # from filter_criteria on its own and knows nothing about conditions, so
    # handing it the unpinned criteria would mail the whole audience while the
    # dry run (which does apply them) showed a smaller number.
    if rule.conditions:
        pinned = service.resolve_recipients(session, criteria, bool(rule.force_send))
        pinned = apply_conditions(session, rule, pinned)
        criteria = {'type': 'specific_users',
                    'user_ids': [r['user_id'] for r in pinned]}
        filter_description = f'{filter_description} + {len(rule.conditions)} condition(s)'

    creator_id = _fallback_creator_id(session, rule)
    channels = [c for c in (rule.channels or ['email']) if c != 'sms']
    if not channels:
        channels = ['email']

    # Anything beyond plain email goes through the orchestrator instead of the
    # email-campaign spine.
    if channels != ['email']:
        return _dispatch_multichannel(session, rule, run, criteria, creator_id, channels)

    if not creator_id:
        run.status = 'failed'
        run.error_message = 'No Global Admin account to attribute the campaign to'
        session.commit()
        return {'success': False, 'error': run.error_message}

    # Fall back to the default wrapper so automated mail is branded like every
    # other blast instead of arriving as bare HTML.
    template_id = rule.template_id
    if not template_id:
        # .limit(1): is_default has no unique constraint in older installs, and
        # two defaults would raise MultipleResultsFound outside the try below,
        # killing the whole dispatch pass.
        template_id = (session.query(EmailTemplate.id)
                       .filter(EmailTemplate.is_default.is_(True),
                               EmailTemplate.is_deleted.is_(False))
                       .order_by(EmailTemplate.id)
                       .limit(1)
                       .scalar())

    # EmailCampaign.name is String(200); prefix + a 200-char rule name + scope
    # key overflows it and Postgres raises StringDataRightTruncation.
    campaign_name = f'[Auto] {rule.name} — {run.scope_key}'[:200]

    try:
        campaign = service.create_campaign(session, {
            'name': campaign_name,
            'subject': substitute_placeholders(session, rule.subject),
            'body_html': substitute_placeholders(session, rule.body_html),
            'template_id': template_id,
            'send_mode': rule.send_mode or 'individual',
            'force_send': bool(rule.force_send),
            'filter_criteria': criteria,
            'filter_description': filter_description[:500],
        }, creator_id)
    except Exception as e:
        logger.exception("Campaign creation failed for run %s", run.id)
        run.status = 'failed'
        run.error_message = str(e)[:500]
        session.commit()
        return {'success': False, 'error': str(e)}

    run.campaign_id = campaign.id
    run.recipient_count = campaign.total_recipients
    run.dispatched_at = datetime.utcnow()

    if campaign.total_recipients == 0:
        # Recorded as 'skipped', NOT 'sent'. Zero recipients can mean "everyone
        # is already in Discord" (fine) or "the audience filter matched nobody"
        # (a misconfiguration, e.g. a season-wrap rule firing after rollover has
        # already cleared is_current_player). Calling that 'sent' hides the
        # second case behind a green tick.
        campaign.status = 'sent'
        run.status = 'skipped'
        run.error_message = ('Nobody matched the audience, so nothing was sent. '
                             'Either everyone is already covered, or the audience '
                             'filter is wrong for this trigger — check the dry run.')
        session.commit()
        return {'success': True, 'recipients': 0, 'campaign_id': campaign.id}

    campaign.status = 'scheduled'
    session.commit()

    # Enqueue BEFORE marking the run sent. If the broker is down (Redis OOM is a
    # documented incident here), .delay() raises, the run stays claimable, and the
    # next pass retries — instead of a run permanently marked 'sent' against a
    # campaign that never left 'scheduled'.
    try:
        task = send_email_broadcast.delay(campaign.id)
    except Exception as e:
        logger.exception("Could not enqueue send for campaign %s", campaign.id)
        run.status = 'pending'
        run.error_message = f'Could not queue the send ({str(e)[:200]}); will retry.'
        session.commit()
        return {'success': False, 'error': run.error_message}

    campaign.celery_task_id = task.id
    run.status = 'sent'
    session.commit()

    logger.info("Automation %s dispatched campaign %s to %d recipients",
                rule.key, campaign.id, campaign.total_recipients)
    return {'success': True, 'recipients': campaign.total_recipients,
            'campaign_id': campaign.id}


def _dispatch_multichannel(session, rule, run, criteria, creator_id, channels):
    """Send a run across several channels via ComposedMessage + the orchestrator.

    The audience is resolved HERE (using the email service's richer filter set,
    which knows about drafted_not_in_discord) and pinned onto the ComposedMessage
    as an explicit user-id list, because audience_service does not understand
    those filter types.

    Trade-off versus the email path, stated plainly: the orchestrator reports
    per-channel counters only, so `recipient_count` is the audience size and
    there are no per-person delivery rows.
    """
    from app.models.composed_message import ComposedMessage
    from app.services.email_broadcast_service import EmailBroadcastService
    from app.tasks.tasks_composed_messages import send_composed_message

    service = EmailBroadcastService()
    recipients = service.resolve_recipients(session, criteria, bool(rule.force_send))
    # criteria arrives already pinned by dispatch_run when the rule has
    # conditions, so applying them again here would be a no-op at best.
    if rule.conditions and criteria.get('type') != 'specific_users':
        recipients = apply_conditions(session, rule, recipients)
    user_ids = [r['user_id'] for r in recipients]

    run.recipient_count = len(user_ids)
    run.dispatched_at = datetime.utcnow()

    if not user_ids:
        run.status = 'skipped'
        run.error_message = ('Nobody matched the audience, so nothing was sent. '
                             'Check the dry run — the audience filter may not fit '
                             'this trigger.')
        session.commit()
        return {'success': True, 'recipients': 0}

    body = substitute_placeholders(session, rule.short_message or '')
    if not body:
        # Never push raw HTML to a phone notification.
        body = re.sub(r'<[^>]+>', ' ', substitute_placeholders(session, rule.body_html or ''))
        body = re.sub(r'\s+', ' ', body).strip()[:900]

    msg = ComposedMessage(
        title=substitute_placeholders(session, rule.subject or rule.name)[:100],
        message=body,
        channels=channels,
        audience_type='users',
        audience_ids=user_ids,
        audience_description=service.build_filter_description(session, criteria)[:300],
        priority='normal',
        force_delivery=bool(rule.force_send),
        status='scheduled',
        total_recipients=len(user_ids),
        created_by_id=creator_id,
    )
    session.add(msg)
    session.commit()

    # Enqueue before marking sent, so a broker outage leaves the run retryable.
    try:
        task = send_composed_message.delay(msg.id)
    except Exception as e:
        logger.exception("Could not enqueue composed message %s", msg.id)
        run.status = 'pending'
        run.error_message = f'Could not queue the send ({str(e)[:200]}); will retry.'
        session.commit()
        return {'success': False, 'error': run.error_message}

    msg.celery_task_id = task.id
    run.status = 'sent'
    session.commit()

    logger.info("Automation %s dispatched composed message %s on %s to %d users",
                rule.key, msg.id, channels, len(user_ids))
    return {'success': True, 'recipients': len(user_ids), 'composed_message_id': msg.id}


def force_run_rule(session, rule, scope_key=None):
    """Run a rule right now, ignoring its delay, freshness window and enabled flag.

    The case this exists for: the trigger already happened before the rule was
    written. Normal evaluation would either not fire (the scope is already
    consumed) or record the stale event as 'skipped', so there would be nothing
    to send. This detects the current scopes, materialises a run for each, and
    dispatches immediately.

    Args:
        rule: the AutomationRule to run.
        scope_key: limit to one scope; None runs every currently-triggered scope.

    Returns:
        dict: {'success': bool, 'results': [...]} with one entry per scope.
    """
    detector = DETECTORS.get(rule.trigger_type)
    if not detector:
        return {'success': False, 'error': f'Unknown trigger type {rule.trigger_type}'}

    try:
        events = detector(session, rule)
    except Exception as e:
        logger.exception("Force-run detection failed for rule %s", rule.key)
        return {'success': False, 'error': str(e)}

    if not events:
        return {'success': False,
                'error': 'The trigger condition is not met, so there is nothing to send.'}

    results = []
    for event in events:
        key = build_scope_key(event['season_id'], event['league_id'],
                              event.get('subject_type'), event.get('subject_id'))
        if scope_key and key != scope_key:
            continue

        run = (session.query(AutomationRun)
               .filter(AutomationRun.rule_id == rule.id,
                       AutomationRun.scope_key == key)
               .first())

        if run and run.status == 'sent':
            results.append({'scope_key': key, 'success': False,
                            'error': 'Already sent — not sending twice.'})
            continue

        if not run:
            run = AutomationRun(
                rule_id=rule.id,
                season_id=event['season_id'],
                league_id=event['league_id'],
                subject_type=event.get('subject_type'),
                subject_id=event.get('subject_id'),
                scope_key=key,
                event_at=event['event_at'],
                scheduled_for=datetime.utcnow(),
                status='pending',
            )
            # SAVEPOINT, mirroring evaluate_rule: two concurrent force-runs race
            # on the unique constraint, and a bare flush would raise an uncaught
            # IntegrityError and poison the session.
            try:
                with session.begin_nested():
                    session.add(run)
            except IntegrityError:
                run = (session.query(AutomationRun)
                       .filter(AutomationRun.rule_id == rule.id,
                               AutomationRun.scope_key == key)
                       .first())
                if not run:
                    results.append({'scope_key': key, 'success': False,
                                    'error': 'Could not claim this scope.'})
                    continue

        result = dispatch_run(session, run, force=True)
        results.append({'scope_key': key, **result})

    if not results:
        return {'success': False, 'error': 'No matching scope to run.'}

    return {'success': any(r.get('success') for r in results), 'results': results}


def dispatch_due_runs(session):
    """Send every pending run whose scheduled_for has passed."""
    due = (session.query(AutomationRun)
           .filter(AutomationRun.status == 'pending',
                   AutomationRun.scheduled_for <= datetime.utcnow())
           .all())
    sent = 0
    for run in due:
        # Isolate each run: without this, one exception aborts the loop, every
        # later run silently never dispatches, and the managed session rolls back
        # so the failure is not even recorded -- so it re-poisons the next pass.
        try:
            result = dispatch_run(session, run)
            if result.get('success'):
                sent += 1
        except Exception as e:
            logger.exception("Dispatch failed for automation run %s", run.id)
            try:
                session.rollback()
                fresh = session.query(AutomationRun).get(run.id)
                if fresh:
                    fresh.status = 'failed'
                    fresh.error_message = str(e)[:500]
                    session.commit()
            except Exception:
                logger.exception("Could not record failure for run %s", run.id)
                session.rollback()
    return {'due': len(due), 'dispatched': sent}


# ─────────────────────────────────────────────────────────────────────────────
# Admin-facing preview
# ─────────────────────────────────────────────────────────────────────────────

def preview_rule(session, rule, refresh=False):
    """What this rule would do right now, without sending anything.

    Used by the admin UI's "preview audience" action so the copy and the
    recipient list can be sanity-checked before the rule is enabled.
    """
    from app.services.email_broadcast_service import EmailBroadcastService

    detector = DETECTORS.get(rule.trigger_type)
    events = []
    if detector:
        try:
            events = detector(session, rule)
        except Exception:
            logger.exception("Preview detection failed for rule %s", rule.key)

    service = EmailBroadcastService()
    scopes = []
    for event in events:
        # Must include the subject, exactly as evaluate_rule does -- otherwise
        # 'already_run' never matches a real run and the modal claims nothing
        # has ever been sent.
        scope_key = build_scope_key(event['season_id'], event['league_id'],
                                    event.get('subject_type'), event.get('subject_id'))
        pseudo_run = SimpleNamespace(
            season_id=event['season_id'], league_id=event['league_id'],
            subject_type=event.get('subject_type'), subject_id=event.get('subject_id'))
        existing = (session.query(AutomationRun)
                    .filter(AutomationRun.rule_id == rule.id,
                            AutomationRun.scope_key == scope_key)
                    .first())

        if refresh and rule.audience_type == 'drafted_not_in_discord':
            try:
                refresh_membership_for_scope(
                    session, event['season_id'],
                    [event['league_id']] if event['league_id'] else None,
                    limit=PREVIEW_MEMBERSHIP_REFRESH,
                )
            except Exception:
                logger.exception("Preview membership refresh failed")

        # Reuse build_filter_criteria rather than assembling this inline: it is
        # the ONLY place that translates the 'the_subject' audience into real
        # user ids. Building criteria by hand here meant every per-person rule
        # previewed as 0 recipients while the real send worked fine.
        criteria = build_filter_criteria(session, rule, pseudo_run)

        recipients = service.resolve_recipients(session, criteria, bool(rule.force_send))
        recipients = apply_conditions(session, rule, recipients)
        scopes.append({
            'scope_key': scope_key,
            'label': event.get('label', scope_key),
            'event_at': event['event_at'],
            'scheduled_for': event['event_at'] + timedelta(hours=rule.delay_hours or 0),
            'recipient_count': len(recipients),
            'sample': [r['name'] for r in recipients[:10]],
            'already_run': existing.status if existing else None,
            'filter_description': service.build_filter_description(session, criteria),
        })

    return {'triggered': bool(scopes), 'scopes': scopes}
