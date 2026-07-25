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

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.models.automation import (
    AutomationRule, AutomationRun, build_scope_key, describe_condition,
    TRIGGER_DRAFT_COMPLETE, TRIGGER_DRAFT_SESSION_COMPLETE,
    TRIGGER_SEASON_PHASE, TRIGGER_SEASON_DATE,
    TRIGGER_USER_APPROVED, TRIGGER_WAITLIST_STUCK, TRIGGER_SUB_NO_REPLY,
    TRIGGER_PLAYER_INACTIVE, TRIGGER_PROFILE_STALE,
    TRIGGER_PASS_NEVER_DOWNLOADED, TRIGGER_PASS_EXPIRING,
    TRIGGER_FEEDBACK_OPEN, TRIGGER_SUB_REQUEST_UNFILLED,
    TRIGGER_SUB_POOL_PENDING, TRIGGER_MATCH_RESCHEDULED,
    TRIGGER_RECURRING_WEEKLY, TRIGGER_RSVP_NOT_RESPONDED,
    TRIGGER_MATCH_DAY_REMINDER,
    RECURRING_TRIGGERS, NATIVE_ACTIONS, NATIVE_ACTION_RSVP_DM,
    NATIVE_ACTION_MATCH_DAY,
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


def _latest_weekly_occurrence(weekdays, hour, now_utc=None):
    """The most recent (weekday, hour) moment that has already passed.

    Returns (naive-UTC datetime, 'YYYY-MM-DD' local date) or None.

    Everything is computed in Pacific local time and converted to UTC at the
    end, so the hour an admin picked is the hour it goes out in — a rule set to
    12:00 must not drift by an hour twice a year when DST flips, which is
    exactly what storing a UTC hour would do.
    """
    try:
        from zoneinfo import ZoneInfo
        pacific = ZoneInfo('America/Los_Angeles')
        utc = ZoneInfo('UTC')
    except Exception:
        logger.debug("No tz data; weekly schedule falls back to UTC", exc_info=True)
        pacific = utc = None

    wanted = set()
    for d in (weekdays or []):
        try:
            wanted.add(int(d) % 7)
        except (TypeError, ValueError):
            continue
    if not wanted:
        return None
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        hour = 12
    hour = max(0, min(23, hour))

    now = datetime.utcnow() if now_utc is None else now_utc
    now_local = (now.replace(tzinfo=utc).astimezone(pacific) if pacific
                 else now.replace(tzinfo=None))

    # Walk back a full week at most: one of the selected weekdays is guaranteed
    # to fall inside it, so the loop always terminates with the newest match.
    for back in range(0, 8):
        day = (now_local - timedelta(days=back)).date()
        if day.weekday() not in wanted:
            continue
        if pacific:
            local_dt = datetime.combine(day, time(hour=hour), tzinfo=pacific)
            candidate = local_dt.astimezone(utc).replace(tzinfo=None)
        else:
            candidate = datetime.combine(day, time(hour=hour))
        if candidate <= now:
            return candidate, day.isoformat()
    return None


def detect_recurring_weekly(session, rule):
    """Fire on a weekly clock: the selected weekdays, at the selected hour.

    Returns at most ONE event — the most recent occurrence that has passed. The
    occurrence date rides on the scope key, so next week is a different scope and
    fires again while re-evaluating this week is a no-op.

    Deliberately does NOT backfill missed occurrences. If the beat was down for
    three days, replaying three weekly sends at once is worse than skipping them;
    the freshness window (1 day by default on these triggers) then records the
    stale one as skipped rather than blasting it late.
    """
    cfg = rule.trigger_config or {}
    found = _latest_weekly_occurrence(cfg.get('weekdays'), cfg.get('hour', 12))
    if not found:
        return []
    event_at, occurrence = found

    season = _current_season(session, cfg.get('league_type', 'Pub League'))
    return [{
        'season_id': season.id if season else None,
        'league_id': None,
        'occurrence': occurrence,
        'event_at': event_at,
        'label': f'Weekly send — {occurrence}',
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


def _horizon(cfg, extra_days=0, extra_hours=0):
    """Lower bound for a detector query.

    Every per-subject detector needs one. Without it the first evaluation sweeps
    up years of history, and evaluate_rule files each one as a 'skipped' run --
    200 junk rows an hour until the backlog drains, plus a heavy query forever.
    """
    max_age = int(cfg.get('max_event_age_days', 14))
    return (datetime.utcnow()
            - timedelta(days=max_age + extra_days)
            - timedelta(hours=extra_hours))


def detect_player_inactive(session, rule):
    """Players who have not turned out for a while this season.

    Anchored to PlayerSeasonParticipation.last_played_date, refreshed nightly at
    03:30 by refresh-participation-rollup.

    Honest caveat, reflected in the copy: that column means "last match they
    RSVP'd yes to", not "last match they physically attended" -- someone who
    shows up without RSVPing looks inactive. matches_played > 0 excludes people
    who have never played at all, who need a different message.
    """
    from app.models.participation import PlayerSeasonParticipation

    cfg = rule.trigger_config or {}
    inactive_days = int(cfg.get('inactive_days', 28))
    now = datetime.utcnow()
    cutoff = (now - timedelta(days=inactive_days)).date()
    floor = _horizon(cfg, extra_days=inactive_days).date()

    season = _current_season(session, cfg.get('league_type', 'Pub League'))
    if not season:
        return []

    rows = (session.query(PlayerSeasonParticipation.player_id,
                          PlayerSeasonParticipation.last_played_date)
            .join(Player, Player.id == PlayerSeasonParticipation.player_id)
            .join(User, User.id == Player.user_id)
            .filter(PlayerSeasonParticipation.season_id == season.id,
                    PlayerSeasonParticipation.matches_played > 0,
                    PlayerSeasonParticipation.last_played_date.isnot(None),
                    PlayerSeasonParticipation.last_played_date <= cutoff,
                    PlayerSeasonParticipation.last_played_date >= floor,
                    User.is_active.is_(True))
            .order_by(PlayerSeasonParticipation.last_played_date)
            .all())

    return [{
        'season_id': season.id, 'league_id': None,
        'subject_type': 'player', 'subject_id': pid,
        'event_at': datetime.combine(last_played, time.min) + timedelta(days=inactive_days),
        'label': f'Player {pid} last played {last_played}',
    } for pid, last_played in rows]


def detect_profile_stale(session, rule):
    """Rostered players whose profile has not been touched in a long time.

    Scoped to players on a team THIS season -- otherwise it would sweep up every
    ex-player in the database. profile_last_updated is bumped by admin edits and
    merges too, so it means "nobody has touched this record", not strictly "the
    player has not reviewed it".
    """
    cfg = rule.trigger_config or {}
    stale_days = int(cfg.get('stale_days', 180))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=stale_days)
    floor = _horizon(cfg, extra_days=stale_days)

    season = _current_season(session, cfg.get('league_type', 'Pub League'))
    if not season:
        return []

    rows = (session.query(Player.id, Player.profile_last_updated)
            .join(User, User.id == Player.user_id)
            .join(player_teams, player_teams.c.player_id == Player.id)
            .join(Team, Team.id == player_teams.c.team_id)
            .join(League, League.id == Team.league_id)
            .filter(League.season_id == season.id,
                    Player.profile_last_updated.isnot(None),
                    Player.profile_last_updated <= cutoff,
                    Player.profile_last_updated >= floor,
                    User.is_active.is_(True))
            .distinct()
            .order_by(Player.profile_last_updated)
            .all())

    return [{
        'season_id': season.id, 'league_id': None,
        'subject_type': 'player', 'subject_id': pid,
        'event_at': updated + timedelta(days=stale_days),
        'label': f'Player {pid} profile untouched since {updated:%Y-%m-%d}',
    } for pid, updated in rows]


def detect_pass_never_downloaded(session, rule):
    """Membership passes issued but never added to a phone.

    download_count is written by record_download() on both the Apple and Google
    paths, so 0 genuinely means never downloaded. It is nullable with a
    Python-side default, hence the NULL-tolerant test.
    """
    from app.models.wallet import WalletPass

    cfg = rule.trigger_config or {}
    wait_days = int(cfg.get('wait_days', 3))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=wait_days)
    floor = _horizon(cfg, extra_days=wait_days)

    rows = (session.query(WalletPass.id, WalletPass.created_at)
            .filter(WalletPass.status == 'active',
                    WalletPass.created_at.isnot(None),
                    WalletPass.created_at <= cutoff,
                    WalletPass.created_at >= floor,
                    or_(WalletPass.download_count.is_(None),
                        WalletPass.download_count == 0))
            .order_by(WalletPass.created_at)
            .all())

    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'wallet_pass', 'subject_id': pid,
        'event_at': created + timedelta(days=wait_days),
        'label': f'Pass {pid} never downloaded',
    } for pid, created in rows]


def detect_pass_expiring(session, rule):
    """Membership passes about to lapse.

    Keyed on valid_until, NOT on status == 'expired' -- nothing in the codebase
    ever writes that status, so it would never fire.
    """
    from app.models.wallet import WalletPass

    cfg = rule.trigger_config or {}
    lead_days = int(cfg.get('lead_days', 14))
    now = datetime.utcnow()
    window_end = now + timedelta(days=lead_days)

    rows = (session.query(WalletPass.id, WalletPass.valid_until)
            .filter(WalletPass.status == 'active',
                    WalletPass.valid_until.isnot(None),
                    WalletPass.valid_until > now,
                    WalletPass.valid_until <= window_end)
            .order_by(WalletPass.valid_until)
            .all())

    # Event = the moment the pass entered the notice window, so the delay stacks
    # on top of lead_days rather than being swallowed by it.
    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'wallet_pass', 'subject_id': pid,
        'event_at': valid_until - timedelta(days=lead_days),
        'label': f'Pass {pid} expires {valid_until:%Y-%m-%d}',
    } for pid, valid_until in rows]


def detect_feedback_open(session, rule):
    """Feedback tickets left open too long.

    Status vocabulary is Title Case with a space: 'Open' | 'In Progress' |
    'Closed'. Anonymous submissions have a NULL user_id and are skipped -- there
    is nobody to reply to.
    """
    from app.models.communication import Feedback

    cfg = rule.trigger_config or {}
    open_days = int(cfg.get('open_days', 7))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=open_days)
    floor = _horizon(cfg, extra_days=open_days)

    rows = (session.query(Feedback.id, Feedback.created_at)
            .join(User, User.id == Feedback.user_id)
            .filter(Feedback.status.in_(('Open', 'In Progress')),
                    Feedback.closed_at.is_(None),
                    Feedback.user_id.isnot(None),
                    Feedback.created_at <= cutoff,
                    Feedback.created_at >= floor,
                    User.is_active.is_(True))
            .order_by(Feedback.created_at)
            .all())

    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'feedback', 'subject_id': fid,
        'event_at': created + timedelta(days=open_days),
        'label': f'Feedback #{fid} still open',
    } for fid, created in rows]


def detect_sub_request_unfilled(session, rule):
    """Substitute requests still open and short of players.

    Status vocabulary is uppercase and only OPEN / FILLED / CANCELLED / EXPIRED
    are ever written -- the 'PENDING'/'APPROVED' filters elsewhere in the app are
    dead. assignments_count is deliberately ignored: its only maintainer counts
    rows from the wrong table, so assignments are counted directly.
    """
    from app.models.substitutes import SubstituteRequest, SubstituteAssignment

    cfg = rule.trigger_config or {}
    unfilled_hours = int(cfg.get('unfilled_hours', 24))
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=unfilled_hours)
    floor = _horizon(cfg, extra_hours=unfilled_hours)

    filled = (session.query(SubstituteAssignment.request_id,
                            func.count(SubstituteAssignment.id).label('n'))
              .group_by(SubstituteAssignment.request_id).subquery())

    rows = (session.query(SubstituteRequest.id,
                          SubstituteRequest.created_at,
                          SubstituteRequest.substitutes_needed,
                          func.coalesce(filled.c.n, 0))
            .outerjoin(filled, filled.c.request_id == SubstituteRequest.id)
            .filter(SubstituteRequest.status == 'OPEN',
                    SubstituteRequest.filled_at.is_(None),
                    SubstituteRequest.cancelled_at.is_(None),
                    SubstituteRequest.requested_by.isnot(None),
                    SubstituteRequest.created_at <= cutoff,
                    SubstituteRequest.created_at >= floor)
            .order_by(SubstituteRequest.created_at)
            .all())

    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'sub_request', 'subject_id': rid,
        'event_at': created + timedelta(hours=unfilled_hours),
        'label': f'Sub request #{rid} still needs {needed - got} player(s)',
    } for rid, created, needed, got in rows if (needed or 1) > (got or 0)]


def detect_sub_pool_pending(session, rule):
    """Substitute-pool applications waiting on approval.

    Pending is approved_at IS NULL -- NOT is_active == False. New rows are
    created with is_active defaulting to True, so is_active alone would match
    approved members too.
    """
    from app.models.substitutes import SubstitutePool

    cfg = rule.trigger_config or {}
    waiting_days = int(cfg.get('waiting_days', 3))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=waiting_days)
    floor = _horizon(cfg, extra_days=waiting_days)

    rows = (session.query(SubstitutePool.id, SubstitutePool.created_at)
            .join(Player, Player.id == SubstitutePool.player_id)
            .join(User, User.id == Player.user_id)
            .filter(SubstitutePool.approved_at.is_(None),
                    SubstitutePool.is_active.is_(True),
                    SubstitutePool.created_at <= cutoff,
                    SubstitutePool.created_at >= floor,
                    User.is_active.is_(True))
            .order_by(SubstitutePool.created_at)
            .all())

    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'substitute_pool', 'subject_id': pid,
        'event_at': created + timedelta(days=waiting_days),
        'label': f'Sub pool application #{pid} awaiting approval',
    } for pid, created in rows]


def detect_match_rescheduled(session, rule):
    """Matches whose date or time was changed.

    rescheduled_at has a single writer (the admin-panel single-match time edit),
    so this covers that path only -- a bulk schedule regeneration does not stamp
    it and will not fire this.
    """
    from app.models.matches import Match

    cfg = rule.trigger_config or {}
    floor = _horizon(cfg)

    rows = (session.query(Match.id, Match.rescheduled_at)
            .filter(Match.rescheduled_at.isnot(None),
                    Match.rescheduled_at >= floor)
            .order_by(Match.rescheduled_at)
            .all())

    return [{
        'season_id': None, 'league_id': None,
        'subject_type': 'match', 'subject_id': mid,
        'event_at': changed,
        'label': f'Match #{mid} rescheduled',
    } for mid, changed in rows]


DETECTORS = {
    TRIGGER_DRAFT_COMPLETE: detect_draft_complete,
    TRIGGER_DRAFT_SESSION_COMPLETE: detect_draft_session_complete,
    TRIGGER_SEASON_PHASE: detect_season_phase,
    TRIGGER_SEASON_DATE: detect_season_date,
    # Both recurring triggers share one clock detector. The RSVP variant differs
    # only in what happens at DISPATCH (a native sender that picks its own
    # recipients), not in when it fires.
    TRIGGER_RECURRING_WEEKLY: detect_recurring_weekly,
    TRIGGER_RSVP_NOT_RESPONDED: detect_recurring_weekly,
    TRIGGER_MATCH_DAY_REMINDER: detect_recurring_weekly,
    TRIGGER_USER_APPROVED: detect_user_approved,
    TRIGGER_WAITLIST_STUCK: detect_waitlist_stuck,
    TRIGGER_SUB_NO_REPLY: detect_sub_no_reply,
    TRIGGER_PLAYER_INACTIVE: detect_player_inactive,
    TRIGGER_PROFILE_STALE: detect_profile_stale,
    TRIGGER_PASS_NEVER_DOWNLOADED: detect_pass_never_downloaded,
    TRIGGER_PASS_EXPIRING: detect_pass_expiring,
    TRIGGER_FEEDBACK_OPEN: detect_feedback_open,
    TRIGGER_SUB_REQUEST_UNFILLED: detect_sub_request_unfilled,
    TRIGGER_SUB_POOL_PENDING: detect_sub_pool_pending,
    TRIGGER_MATCH_RESCHEDULED: detect_match_rescheduled,
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
                              event.get('subject_type'), event.get('subject_id'),
                              event.get('occurrence'))
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

def resolve_subject_user_ids(session, run):
    """Every User this run is about.

    Returns a LIST, not a single id: most subjects are one person, but a match
    is about two whole teams and a sub request is about whoever asked. Subjects
    anchor to whichever row actually carries the trigger's timestamp, so getting
    from there to a User differs per type.

    An unknown subject_type returns [] -- the run then resolves to nobody and is
    recorded as skipped, rather than silently mailing the wrong audience.
    """
    st, sid = run.subject_type, run.subject_id
    if not st or not sid:
        return []

    def _from_player(player_id):
        if not player_id:
            return []
        uid = session.query(Player.user_id).filter(Player.id == player_id).scalar()
        return [uid] if uid else []

    if st == 'user':
        return [sid]

    if st == 'player':
        return _from_player(sid)

    if st == 'sub_response':
        from app.models.substitutes import SubstituteResponse
        return _from_player(session.query(SubstituteResponse.player_id)
                            .filter(SubstituteResponse.id == sid).scalar())

    if st == 'substitute_pool':
        from app.models.substitutes import SubstitutePool
        return _from_player(session.query(SubstitutePool.player_id)
                            .filter(SubstitutePool.id == sid).scalar())

    if st == 'sub_request':
        # requested_by is already a users.id -- the coach who asked for cover.
        from app.models.substitutes import SubstituteRequest
        uid = (session.query(SubstituteRequest.requested_by)
               .filter(SubstituteRequest.id == sid).scalar())
        return [uid] if uid else []

    if st == 'feedback':
        # Feedback.user_id is a users.id and is nullable (anonymous submissions).
        from app.models.communication import Feedback
        uid = session.query(Feedback.user_id).filter(Feedback.id == sid).scalar()
        return [uid] if uid else []

    if st == 'wallet_pass':
        from app.models.wallet import WalletPass
        row = (session.query(WalletPass.user_id, WalletPass.player_id)
               .filter(WalletPass.id == sid).first())
        if not row:
            return []
        return [row[0]] if row[0] else _from_player(row[1])

    if st == 'match':
        # Both teams' current rosters.
        from app.models.matches import Match
        match = (session.query(Match.home_team_id, Match.away_team_id)
                 .filter(Match.id == sid).first())
        if not match:
            return []
        team_ids = [t for t in match if t]
        if not team_ids:
            return []
        rows = (session.query(Player.user_id)
                .join(player_teams, player_teams.c.player_id == Player.id)
                .filter(player_teams.c.team_id.in_(team_ids),
                        Player.user_id.isnot(None))
                .distinct().all())
        return [r[0] for r in rows]

    logger.warning("Unknown subject_type %r on run %s", st, run.id)
    return []



def scope_still_applies(session, rule, run):
    """Re-run the trigger and ask whether THIS run's scope is still in the results.

    This is what stops an escalation ladder nagging someone who already acted --
    the sub request got filled, the player joined Discord, the profile was
    updated. Generic by construction: it reuses the detector, so it works for
    every trigger without per-trigger resolve logic.

    On any error it returns True (keep going) rather than silently cancelling a
    send an admin is expecting.
    """
    # A recurring trigger's "event" is a moment on the clock, and that moment
    # cannot un-happen. Worse, the detector only ever reports the CURRENT week,
    # so a ladder step whose wait crosses into next week would find no match and
    # silently cancel itself. Recurring rules re-check what matters at send time
    # instead: the RSVP sender recomputes who still has not answered.
    if rule.trigger_type in RECURRING_TRIGGERS:
        return True

    detector = DETECTORS.get(rule.trigger_type)
    if not detector:
        return True
    try:
        events = detector(session, rule)
    except Exception:
        logger.exception("Re-check failed for rule %s; continuing the sequence", rule.key)
        return True
    for event in events:
        key = build_scope_key(event['season_id'], event['league_id'],
                              event.get('subject_type'), event.get('subject_id'),
                              event.get('occurrence'))
        if key == run.scope_key:
            return True
    return False

def build_filter_criteria(session, rule, run):
    """Assemble the email_broadcast_service filter_criteria for a run."""
    # Per-subject rules target exactly one person: the one the trigger is about.
    if rule.audience_type == 'the_subject':
        return {'type': 'specific_users',
                'user_ids': resolve_subject_user_ids(session, run)}

    criteria = dict(rule.audience_config or {})
    criteria['type'] = rule.audience_type
    if run.season_id:
        criteria['season_id'] = run.season_id
    if run.league_id:
        criteria['league_ids'] = [run.league_id]

    # by_league defaults active_only=False, which would mail every player EVER
    # assigned to that league, including people who left seasons ago. An
    # unattended rule must not do that.
    if rule.audience_type == 'by_league':
        criteria.setdefault('active_only', True)

    return criteria


def _condition_test(actual, op, expected, now):
    """Evaluate one operator. Unknown operators fail closed."""
    if op == 'is_true':
        return actual is True
    if op == 'is_false':
        # Only an explicit True fails. NULL counts as "not yes", matching how
        # every other nullable boolean is treated in this engine.
        return actual is not True
    if op == 'exists':
        return actual not in (None, '', [])
    if op == 'missing':
        return actual in (None, '', [])
    if op == 'eq':
        return str(actual) == str(expected)
    if op == 'neq':
        return str(actual) != str(expected)
    if op in ('gt', 'lt'):
        try:
            a, b = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return a > b if op == 'gt' else a < b
    if op == 'never':
        return actual is None
    if op in ('older_than_days', 'newer_than_days'):
        if actual is None:
            # "Never happened" is genuinely older than any window, and is
            # definitely not within a recent one.
            return op == 'older_than_days'
        try:
            days = float(expected)
        except (TypeError, ValueError):
            return False
        age = (now - actual).total_seconds() / 86400.0
        return age > days if op == 'older_than_days' else age <= days
    if op == 'has':
        return str(expected) in (actual or set())
    if op == 'not_has':
        return str(expected) not in (actual or set())
    logger.warning("Unknown condition operator %r; failing closed", op)
    return False


def apply_conditions(session, rule, recipients):
    """Narrow a resolved recipient list by the rule's conditions.

    Every condition must pass. Evaluated in Python rather than SQL because the
    fields span User, Player, roles and league membership, and the lists here are
    hundreds of rows -- one extra query beats a pile of conditional joins.

    Failure modes are deliberately CLOSED: an unknown field, an unknown operator
    or a malformed entry excludes everyone rather than being ignored. Silently
    dropping a condition an admin wrote could mail people they explicitly
    excluded, which is the worse mistake.
    """
    from app.models.automation import CONDITION_FIELDS, CONDITION_NEGATIVE_OPS

    conditions = [c for c in (rule.conditions or [])]
    if not conditions or not recipients:
        return recipients

    now = datetime.utcnow()
    user_ids = [r['user_id'] for r in recipients]

    # ── User-level facts ────────────────────────────────────────────────
    user_rows = (session.query(
        User.id, User.approval_status, User.is_active, User.last_login,
        User.created_at, User.has_completed_onboarding,
        User.email_notifications, User.discord_notifications, User.push_notifications,
    ).filter(User.id.in_(user_ids)).all())
    facts = {
        r[0]: {
            'user.approval_status': r[1],
            'user.is_active': r[2],
            'user.last_login': r[3],
            'user.created_at': r[4],
            'user.has_completed_onboarding': r[5],
            'user.email_notifications': r[6],
            'user.discord_notifications': r[7],
            'user.push_notifications': r[8],
            'players': [],
            'membership.role': set(),
            'membership.league': set(),
        } for r in user_rows
    }

    # ── Player-level facts (a user may have MORE THAN ONE Player row) ───
    player_rows = (session.query(
        Player.user_id, Player.discord_in_server, Player.discord_id,
        Player.discord_roles_synced, Player.discord_last_checked,
        Player.is_current_player, Player.is_coach, Player.is_sub, Player.is_ref,
        Player.primary_team_id, Player.profile_last_updated, Player.is_phone_verified,
    ).filter(Player.user_id.in_(user_ids)).all())
    for r in player_rows:
        entry = facts.get(r[0])
        if entry is None:
            continue
        entry['players'].append({
            'player.discord_in_server': r[1],
            'player.discord_id': r[2],
            'player.discord_roles_synced': r[3],
            'player.discord_last_checked': r[4],
            'player.is_current_player': r[5],
            'player.is_coach': r[6],
            'player.is_sub': r[7],
            'player.is_ref': r[8],
            'player.primary_team_id': r[9],
            'player.profile_last_updated': r[10],
            'player.is_phone_verified': r[11],
        })

    # ── Roles, only if a rule actually asks about them ──────────────────
    wanted = {c.get('field') for c in conditions if isinstance(c, dict)}
    if 'membership.role' in wanted:
        for uid, name in (session.query(user_roles.c.user_id, Role.name)
                          .join(Role, Role.id == user_roles.c.role_id)
                          .filter(user_roles.c.user_id.in_(user_ids)).all()):
            if uid in facts:
                facts[uid]['membership.role'].add(name)

    # ── League membership this season, via the live roster ──────────────
    if 'membership.league' in wanted:
        rows = (session.query(Player.user_id, League.name)
                .join(player_teams, player_teams.c.player_id == Player.id)
                .join(Team, Team.id == player_teams.c.team_id)
                .join(League, League.id == Team.league_id)
                .join(Season, Season.id == League.season_id)
                .filter(Player.user_id.in_(user_ids), Season.is_current.is_(True))
                .distinct().all())
        for uid, name in rows:
            if uid in facts:
                facts[uid]['membership.league'].add(name)

    def passes(user_id):
        row = facts.get(user_id)
        if row is None:
            return False
        for cond in conditions:
            if not _eval_condition(cond, row, now, rule):
                return False
        return True

    def _eval_condition(cond, row, now, rule):
        """One condition, or a nested any/all group."""
        if not isinstance(cond, dict):
            logger.warning("Rule %s has a malformed condition %r; failing closed",
                           rule.key, cond)
            return False

        # Groups. 'any' is how an admin expresses OR; 'all' nests an AND.
        # An EMPTY group fails closed -- an admin who added a group and left it
        # blank has expressed nothing, and guessing "match everyone" would be
        # the dangerous reading.
        if 'any' in cond or 'all' in cond:
            inner = cond.get('any') if 'any' in cond else cond.get('all')
            if not isinstance(inner, list) or not inner:
                logger.warning("Rule %s has an empty condition group; failing closed",
                               rule.key)
                return False
            results = (_eval_condition(c, row, now, rule) for c in inner)
            return any(results) if 'any' in cond else all(results)

        field, op = cond.get('field'), cond.get('op')
        if field not in CONDITION_FIELDS:
            logger.warning("Rule %s has an unknown condition field %r; failing closed",
                           rule.key, field)
            return False
        expected = cond.get('value')

        if field.startswith('player.'):
            # POSITIVE tests use any(): a duplicate/orphan Player row alongside
            # the real one should not disqualify someone. NEGATIVE tests MUST use
            # all(), or an all-NULL orphan row would satisfy "is not in the
            # Discord server" for someone who is.
            players = row['players'] or [{}]
            results = [_condition_test(pl.get(field), op, expected, now) for pl in players]
            return all(results) if op in CONDITION_NEGATIVE_OPS else any(results)

        return _condition_test(row.get(field), op, expected, now)

    kept = [r for r in recipients if passes(r['user_id'])]
    if len(kept) != len(recipients):
        logger.info("Rule %s conditions narrowed audience %d -> %d",
                    rule.key, len(recipients), len(kept))
    return kept


def resolve_global_variables(session=None):
    """Current value of every global {variable}, from settings.

    Also what the editor shows admins, so the panel can never claim a different
    value from the one that actually gets sent.
    """
    from app.models.automation import GLOBAL_VARIABLE_SETTINGS

    out = {}
    for name, (setting_key, fallback) in GLOBAL_VARIABLE_SETTINGS.items():
        value = None
        try:
            from app.models.admin_config import AdminConfig
            value = AdminConfig.get_setting(setting_key, None)
        except Exception:
            logger.debug("Could not read setting %s; using the default",
                         setting_key, exc_info=True)
        out[name] = (value or fallback)
    return out


def substitute_placeholders(session, text):
    """Fill the GLOBAL variables. Per-recipient tokens are left alone -- those
    are resolved per person by the send task."""
    if not text:
        return text
    for name, value in resolve_global_variables(session).items():
        text = text.replace('{%s}' % name, value)
    return text


def rule_leaks_team_names(rule, step=None):
    """True if this rule's copy would reveal a team assignment.

    {team} is the only token that resolves to a team name, so its presence is
    the whole test. Checks the given step plus the rule's own columns, and every
    other step too -- a ladder whose step 3 mentions {team} leaks just as hard as
    step 1 doing it.
    """
    parts = [rule.subject or '', rule.body_html or '', rule.short_message or '']
    if step:
        parts += [step.get('subject') or '', step.get('body_html') or '',
                  step.get('short_message') or '']
    try:
        for s in rule.action_steps() or []:
            parts += [s.get('subject') or '', s.get('body_html') or '',
                      s.get('short_message') or '']
    except Exception:
        pass
    return '{team}' in ' '.join(parts)


def _reveal_allows(session, rule, step=None):
    """Whether this send is safe to make while teams may still be hidden.

    Fails OPEN on an unreadable setting: teams_are_public() already defaults to
    True when the config row is missing, and silently freezing every automation
    because a settings lookup hiccuped would be a worse failure than the leak
    this guards.
    """
    if not rule_leaks_team_names(rule, step):
        return True
    try:
        from app.services.team_visibility import teams_are_public
        return bool(teams_are_public())
    except Exception:
        logger.warning("Could not read the team-reveal setting; allowing the send",
                       exc_info=True)
        return True


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
    steps = rule.action_steps()
    step_index = min(run.current_step or 0, len(steps) - 1)
    step = steps[step_index]

    if not force:
        due_at = run.next_step_at or run.scheduled_for
        if due_at > datetime.utcnow():
            return {'success': False, 'error': 'Not due yet'}

    # Before any step AFTER the first, check the situation has not resolved
    # itself. Nagging someone who already filled the sub slot is worse than
    # sending nothing.
    if step_index > 0 and rule.stop_when_resolved:
        if not scope_still_applies(session, rule, run):
            run.status = 'sent'
            run.error_message = (f'Stopped after step {step_index} — the trigger no '
                                 f'longer applies, so the rest was not sent.')
            session.commit()
            logger.info("Automation %s stopped early for scope %s (resolved)",
                        rule.key, run.scope_key)
            return {'success': True, 'stopped_early': True}

    # Native senders build their own message and pick their own recipients, so
    # everything below (reveal guard, audience resolution, campaign creation) is
    # not theirs to run. Branch out BEFORE the reveal check in particular: the
    # RSVP copy legitimately contains {team}, and the generic guard would hold
    # the run forever, while the RSVP sender already suppresses only the Pub
    # League matches that are actually hidden and still chases ECS FC.
    if rule.native_action:
        return _dispatch_native(session, rule, run, step, step_index, len(steps),
                                force=force)

    # Team assignments are hidden until the reveal, and that gate is enforced in
    # the web UI, the mobile API and Discord team channels -- but NOT here. A
    # rule whose copy contains {team} would mail people their team before the
    # reveal party and blow it for everyone.
    #
    # DEFERRED, not skipped: the message becomes correct the moment teams go
    # public, so the run stays pending and the next pass sends it. Marking it
    # skipped would consume the scope permanently and it would never send at all.
    if not _reveal_allows(session, rule, step):
        run.error_message = (
            'Held back: this message contains {team}, and team assignments are '
            'still hidden until the reveal. It will send by itself once you turn '
            'on "Make teams public".')
        if run.status != 'pending':
            run.status = 'pending'
        session.commit()
        logger.info("Automation %s held for scope %s — teams not yet public",
                    rule.key, run.scope_key)
        return {'success': False, 'deferred': True, 'error': run.error_message}

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
    channels = [c for c in (step.get('channels') or rule.channels or ['email'])
                if c != 'sms']
    if not channels:
        channels = ['email']

    # Anything beyond plain email goes through the orchestrator instead of the
    # email-campaign spine.
    if channels != ['email']:
        return _dispatch_multichannel(session, rule, run, criteria, creator_id,
                                      channels, step, step_index, len(steps))

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
    _step_tag = f' (step {step_index + 1}/{len(steps)})' if len(steps) > 1 else ''
    campaign_name = f'[Auto] {rule.name}{_step_tag} — {run.scope_key}'[:200]

    try:
        campaign = service.create_campaign(session, {
            'name': campaign_name,
            'subject': substitute_placeholders(session, step.get('subject') or rule.subject),
            'body_html': substitute_placeholders(
                session, step.get('body_html') or rule.body_html),
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
    _advance_or_finish(session, run, rule, step_index, steps)
    session.commit()

    logger.info("Automation %s dispatched campaign %s to %d recipients",
                rule.key, campaign.id, campaign.total_recipients)
    return {'success': True, 'recipients': campaign.total_recipients,
            'campaign_id': campaign.id}


def _rsvp_reminder_options(session, rule, step):
    """Translate an automation rule into kwargs for the RSVP reminder task.

    The rule owns the schedule, the two behavioural knobs and every string; the
    task owns finding non-responders and talking to the bot. Nothing here has a
    silent fallback to a hardcoded string -- if an admin blanks a field the task
    receives the blank and drops that line, which is a visible outcome rather
    than the old copy quietly reappearing.
    """
    cfg = rule.trigger_config or {}
    step = step or {}

    # body_html is the Discord DM's opening line. It is a plain sentence, not a
    # layout, so strip any markup an admin's editor slipped in rather than
    # letting tags render literally inside a Discord embed.
    intro = substitute_placeholders(session, step.get('body_html') or rule.body_html or '')
    intro = re.sub(r'<[^>]+>', ' ', intro)
    intro = re.sub(r'\s+', ' ', intro).strip()

    return {
        'lookahead_days': int(cfg.get('lookahead_days', 4)),
        'max_reminders_per_match': int(cfg.get('max_reminders_per_match', 1)),
        'title': substitute_placeholders(
            session, step.get('subject') or rule.subject or '')[:200],
        # Per-match line for push / email / SMS. Keeps its {team} {opponent}
        # {date} {time} tokens: the task fills them per match, not per person.
        'message_template': (step.get('short_message') or rule.short_message or ''),
        'dm_description': intro,
        'dm_footer': (cfg.get('dm_footer') or ''),
    }


def _match_day_options(session, rule, step):
    """Translate an automation rule into kwargs for the day-before digest task.

    The digest is assembled from short sentences rather than one body, so the
    copy is split across the rule's fields:

        subject                   -> title when a match still needs an answer
        trigger_config.confirm_title -> title when everything is already confirmed
        short_message             -> the chase sentence
        body_html                 -> the confirmation sentence
        trigger_config.chase_footer  -> the "please RSVP or tell your coach" line

    body_html is plain prose here, not email HTML, so markup is stripped rather
    than rendered literally into a push notification.
    """
    cfg = rule.trigger_config or {}
    step = step or {}

    confirm = substitute_placeholders(session, step.get('body_html') or rule.body_html or '')
    confirm = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', confirm)).strip()

    return {
        'days_before': int(cfg.get('days_before', 1)),
        'reminder_audience': cfg.get('reminder_audience', 'chase_and_confirm'),
        'respect_snooze': bool(cfg.get('respect_snooze', True)),
        'chase_title': substitute_placeholders(
            session, step.get('subject') or rule.subject or '')[:200],
        'confirm_title': (cfg.get('confirm_title') or ''),
        'chase_line': (step.get('short_message') or rule.short_message or ''),
        'confirm_line': confirm,
        'chase_footer': (cfg.get('chase_footer') or ''),
    }


# Each native action names the task to enqueue and how to build its kwargs.
# Both are code, not data: `native_action` only ever selects a row here.
NATIVE_DISPATCHERS = {
    NATIVE_ACTION_RSVP_DM: {
        'task': 'app.tasks.tasks_rsvp_dm_reminders.send_rsvp_dm_reminders',
        'options': _rsvp_reminder_options,
    },
    NATIVE_ACTION_MATCH_DAY: {
        'task': 'app.tasks.tasks_notification_reminders.send_match_reminders_daily',
        'options': _match_day_options,
    },
}


def _dispatch_native(session, rule, run, step, step_index, total_steps, force=False):
    """Hand a run to a purpose-built sender instead of the generic pipeline.

    Same claim-then-enqueue discipline as the other two paths: the run is
    claimed atomically so two overlapping beat passes cannot both send it, and
    the task is enqueued BEFORE the run is marked sent so a broker outage leaves
    it retryable rather than falsely green.

    recipient_count stays 0 until the task reports back -- the sender resolves
    its own audience, and guessing a number here would be a number nobody
    computed.
    """
    spec = NATIVE_DISPATCHERS.get(rule.native_action)
    if not spec:
        run.status = 'failed'
        run.error_message = (f'Unknown built-in action {rule.native_action!r}. '
                             f'Nothing was sent.')
        session.commit()
        logger.error("Rule %s names unknown native_action %r", rule.key, rule.native_action)
        return {'success': False, 'error': run.error_message}

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

    try:
        options = spec['options'](session, rule, step)
    except Exception as e:
        logger.exception("Could not build options for native run %s", run.id)
        run.status = 'failed'
        run.error_message = f'Could not read the rule settings ({str(e)[:200]}).'
        session.commit()
        return {'success': False, 'error': run.error_message}

    from app.core import celery
    try:
        task = celery.send_task(spec['task'], kwargs={'options': options,
                                                      'run_id': run.id})
    except Exception as e:
        logger.exception("Could not enqueue native action for run %s", run.id)
        run.status = 'pending'
        run.error_message = f'Could not queue the send ({str(e)[:200]}); will retry.'
        session.commit()
        return {'success': False, 'error': run.error_message}

    run.dispatched_at = datetime.utcnow()

    # Who owns the terminal status differs from the other two paths, and it
    # matters. The email/multichannel paths know their recipient count before
    # they enqueue; a native sender does NOT -- it works out its own audience
    # inside the task. So:
    #
    #   * more steps to come -> advance the ladder here as usual.
    #   * last step          -> leave the run 'sending' and let the task close
    #                           it out with the real number.
    #
    # Calling _advance_or_finish() unconditionally marked the run 'sent'
    # immediately, and the task's report (which refuses to touch a run that is
    # no longer 'sending') was then silently discarded -- so every RSVP run
    # showed 0 recipients however many DMs it actually sent.
    steps = rule.action_steps()
    if step_index + 1 < len(steps):
        _advance_or_finish(session, run, rule, step_index, steps)
    session.commit()

    logger.info("Automation %s dispatched native action %s (task %s) for scope %s",
                rule.key, rule.native_action, task.id, run.scope_key)
    return {'success': True, 'native_action': rule.native_action, 'task_id': task.id}


def _dispatch_multichannel(session, rule, run, criteria, creator_id, channels,
                           step=None, step_index=0, total_steps=1):
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

    step = step or {}
    body = substitute_placeholders(
        session, step.get('short_message') or rule.short_message or '')
    if not body:
        # Never push raw HTML to a phone notification.
        body = re.sub(r'<[^>]+>', ' ', substitute_placeholders(
            session, step.get('body_html') or rule.body_html or ''))
        body = re.sub(r'\s+', ' ', body).strip()[:900]

    msg = ComposedMessage(
        title=substitute_placeholders(
            session, step.get('subject') or rule.subject or rule.name)[:100],
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
    _advance_or_finish(session, run, rule, step_index, rule.action_steps())
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
        # MUST include the occurrence, like evaluate_rule does. Without it a
        # recurring rule force-runs under a scope key ('5:all') that the real
        # evaluation never produces ('5:all@2026-07-25'), so the forced run is an
        # orphan row that never lines up with the scheduled history.
        key = build_scope_key(event['season_id'], event['league_id'],
                              event.get('subject_type'), event.get('subject_id'),
                              event.get('occurrence'))
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



def _advance_or_finish(session, run, rule, step_index, steps):
    """Move a run to its next step, or mark it done after the last one."""
    if step_index + 1 < len(steps):
        gap = int(steps[step_index + 1].get('wait_hours') or 0)
        run.current_step = step_index + 1
        run.next_step_at = datetime.utcnow() + timedelta(hours=gap)
        run.status = 'pending'          # back in the queue for the next step
        logger.info("Automation %s scope %s advanced to step %d/%d, due %s",
                    rule.key, run.scope_key, step_index + 2, len(steps),
                    run.next_step_at)
    else:
        run.status = 'sent'

def dispatch_due_runs(session):
    """Send every pending run whose scheduled_for has passed."""
    now = datetime.utcnow()
    # next_step_at drives a multi-step ladder; it is NULL on rows created before
    # sequences existed, which fall back to scheduled_for.
    due = (session.query(AutomationRun)
           .filter(AutomationRun.status == 'pending',
                   func.coalesce(AutomationRun.next_step_at,
                                 AutomationRun.scheduled_for) <= now)
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


def _explain_match_day(session, rule, user, stages, add):
    """Trace one person through the day-before digest's real rules."""
    from app.models import Match, EcsFcMatch
    from app.models.communication import MatchReminderLog
    from app.tasks.tasks_notification_reminders import _reminder_audience_status
    from app.utils.pacific_time import pacific_today

    who = user.username
    cfg = rule.trigger_config or {}
    days_before = int(cfg.get('days_before', 1))
    chase_only = cfg.get('reminder_audience', 'chase_and_confirm') == 'chase_only'
    target = pacific_today() + timedelta(days=days_before)
    gap = ('today' if days_before == 0 else 'tomorrow' if days_before == 1
           else f'in {days_before} days')

    player = session.query(Player).filter(Player.user_id == user.id).first()
    if not player:
        add('Has a player profile', False,
            'This account has no player profile, so it is never on a team sheet.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged.'}
    name = player.name or who
    who = name
    add('Has a player profile', True, f'Player profile: {name}.')

    # Every match on the target day this player is rostered for, with their RSVP.
    mine = []
    for m in session.query(Match).filter(
            Match.date == target, Match.is_special_week.is_(False),
            Match.week_type.in_(['REGULAR', 'PLAYOFF'])).all():
        rosters = (list(m.home_team.players) if m.home_team else []) + \
                  (list(m.away_team.players) if m.away_team else [])
        if any(p.id == player.id for p in rosters):
            responses = {a.player_id: a.response for a in (m.availability or []) if a.player_id}
            mine.append(('pub', m.id, responses.get(player.id)))
    for m in session.query(EcsFcMatch).filter(
            EcsFcMatch.match_date == target, EcsFcMatch.status == 'SCHEDULED').all():
        if m.team and any(p.id == player.id for p in m.team.players):
            responses = {a.player_id: a.response for a in (m.availabilities or []) if a.player_id}
            mine.append(('ecs_fc', m.id, responses.get(player.id)))

    if not mine:
        add(f'Has a match {gap}', False,
            f'No match on {target.strftime("%A, %B %d")}. Note that before the team '
            f'reveal, Pub League matches are deliberately held back.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged — no match {gap}.'}
    add(f'Has a match {gap}', True, f'{len(mine)} match(es) on {target.strftime("%A, %B %d")}.')

    eligible = []
    for mtype, mid, resp in mine:
        status = _reminder_audience_status(resp)
        if status is None:
            continue
        if chase_only and status != 'no_response':
            continue
        eligible.append((mtype, mid, status))
    if not eligible:
        said = {r for _, _, r in mine}
        if chase_only:
            detail = ('This rule is set to chase non-responders only, and they have '
                      'already answered every match.')
        else:
            detail = (f'They answered {", ".join(sorted(s or "nothing" for s in said))} '
                      f'— "no" and "maybe" are never reminded.')
        add('RSVP state includes them', False, detail)
        return {'stages': stages, 'verdict': f'{who} would not be messaged.'}
    add('RSVP state includes them', True,
        f'{len(eligible)} match(es) qualify '
        f'({sum(1 for _, _, s in eligible if s == "no_response")} unanswered).')

    if cfg.get('respect_snooze', True):
        from app.services import rsvp_snooze_service
        if player.id in rsvp_snooze_service.get_all_snoozed_player_ids(session=session):
            add('Not snoozed', False,
                f'{name} has paused RSVP reminders, and this rule is set to honour '
                f'that. Turn off "Honour the RSVP Snooze button" to reach them anyway.')
            return {'stages': stages, 'verdict': f'{who} would not be messaged — snoozed.'}
        add('Not snoozed', True, 'Reminders are not paused for this person.')
    else:
        add('Snooze is ignored by this rule', True,
            'This rule is set NOT to honour the Snooze button, so a snoozed player '
            'still gets this reminder.')

    already = {(r.match_id, r.match_type) for r in session.query(
        MatchReminderLog.match_id, MatchReminderLog.match_type).filter(
        MatchReminderLog.user_id == user.id,
        MatchReminderLog.reminder_type == 'daily',
        MatchReminderLog.target_date == target,
        MatchReminderLog.delivery_status == 'sent').all()}
    fresh = [e for e in eligible if (e[1], e[0]) not in already]
    if not fresh:
        add('Not already reminded', False,
            f'{name} has already had this reminder for {target.strftime("%A, %B %d")}. '
            f'It only sends once per match per day.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged — already reminded.'}
    add('Not already reminded', True, f'{len(fresh)} match(es) not yet reminded.')

    if not getattr(user, 'match_reminder_notifications', True):
        add('Match reminders switched on', False,
            f'{name} has turned match reminders off in their own notification settings.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged.'}
    add('Match reminders switched on', True,
        'This person has match reminders enabled.')

    return {'stages': stages,
            'verdict': f'{who} would get one message covering {len(fresh)} match(es) {gap}.'}


def _explain_native(session, rule, user, stages, add):
    """Trace one person through the RSVP reminder's real rules.

    Mirrors send_rsvp_dm_reminders in the order it actually applies things:
    unanswered match in the window -> snoozed? -> repeat cap -> per-user opt-out
    -> which channel they land on. Every stage names the specific thing that
    stopped them, because "not in the audience" is useless when the audience is
    computed rather than filtered.
    """
    who = user.username
    if rule.native_action == NATIVE_ACTION_MATCH_DAY:
        return _explain_match_day(session, rule, user, stages, add)
    if rule.native_action != NATIVE_ACTION_RSVP_DM:
        add('Audience', False, 'No trace is available for this built-in message.')
        return {'stages': stages, 'verdict': 'Cannot say for this automation.'}

    from app.models.communication import RsvpDmReminderLog
    from app.services import rsvp_snooze_service
    from app.tasks.tasks_rsvp_dm_reminders import (
        _collect_pub_league_non_responders, _collect_ecs_fc_non_responders,
        _determine_player_tier)
    from app.utils.pacific_time import pacific_today

    cfg = rule.trigger_config or {}
    lookahead = int(cfg.get('lookahead_days', 4))
    cap = int(cfg.get('max_reminders_per_match', 1))

    player = session.query(Player).filter(Player.user_id == user.id).first()
    if not player:
        add('Has a player profile', False,
            'This account has no player profile, so it is never on a team sheet '
            'and never has a match to RSVP to.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged.'}
    # Player.name is the only real name in the schema -- User.username is a login
    # handle. Once the profile is found, say who this actually is.
    name = player.name or who
    who = name
    add('Has a player profile', True, f'Player profile: {name}.')

    today = pacific_today()
    window_end = today + timedelta(days=lookahead)
    player_data = {}
    _collect_pub_league_non_responders(session, today, window_end, set(), player_data)
    _collect_ecs_fc_non_responders(session, today, window_end, set(), player_data)
    mine = (player_data.get(player.id) or {}).get('matches') or []

    if not mine:
        add('Has an unanswered match', False,
            f'No match in the next {lookahead} day(s) that {name} has not already '
            f'answered. Either they have responded yes/no/maybe to everything, or '
            f'they are not on a team sheet in that window. Note that before the '
            f'team reveal, Pub League matches are deliberately held back.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged — nothing to chase.'}
    add('Has an unanswered match', True,
        f'{len(mine)} unanswered match(es) in the next {lookahead} day(s): '
        + ', '.join(f"{m['team_name']} vs {m['opponent_name']} ({m['match_date']})"
                    for m in mine[:3]))

    snoozed = rsvp_snooze_service.get_all_snoozed_player_ids(session=session)
    if player.id in snoozed:
        add('Not snoozed', False,
            f'{name} has paused RSVP reminders (the Snooze button on the DM, or the '
            f'setting on their account page). Snooze always wins.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged — reminders are snoozed.'}
    add('Not snoozed', True, 'Reminders are not paused for this person.')

    counts = {
        (r.match_id, r.match_type): r.n
        for r in session.query(
            RsvpDmReminderLog.match_id, RsvpDmReminderLog.match_type,
            func.count(RsvpDmReminderLog.id).label('n')
        ).filter(RsvpDmReminderLog.player_id == player.id,
                 RsvpDmReminderLog.delivery_status == 'sent')
         .group_by(RsvpDmReminderLog.match_id, RsvpDmReminderLog.match_type).all()
    }
    fresh = [m for m in mine if counts.get((m['match_id'], m['match_type']), 0) < cap]
    if not fresh:
        add('Under the repeat cap', False,
            f'Every one of those matches has already been chased {cap} time(s), which '
            f'is the limit this rule is set to. Raise "Most reminders per match" to '
            f'chase again.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged — already reminded.'}
    add('Under the repeat cap', True,
        f'{len(fresh)} of {len(mine)} match(es) are still under the {cap}-reminder limit.')

    tier = _determine_player_tier(session, user, player)
    if not tier:
        if not getattr(user, 'rsvp_reminder_notifications', True):
            detail = (f'{name} has switched RSVP reminders off in their own notification '
                      f'settings. This rule deliberately does not override that.')
        else:
            detail = (f'No usable channel: no app installed, no Discord linked, no email, '
                      f'and no verified phone with SMS consent.')
        add('Has a channel to reach them on', False, detail)
        return {'stages': stages, 'verdict': f'{who} would not be messaged.'}

    pretty = {'push': 'a push notification', 'discord': 'a Discord DM with RSVP buttons',
              'email': 'an email', 'sms': 'a text message'}
    add('Has a channel to reach them on', True,
        f'{name} would get {pretty.get(tier, tier)} — the highest channel they have '
        f'enabled. Only one channel is used, not all of them.')
    return {'stages': stages,
            'verdict': f'{who} would be reminded about {len(fresh)} match(es) '
                       f'by {pretty.get(tier, tier)}.'}


def explain_for_user(session, rule, user_id):
    """Walk the whole pipeline for ONE person and say what happened.

    Computed live rather than stored, so it is always accurate even after a rule
    is edited. Mirrors the real dispatch order exactly -- trigger, audience,
    conditions, delivery -- so each stage answers the question the previous one
    raises.

    Returns {'stages': [{'name', 'ok', 'detail'}], 'verdict': str}.
    """
    from app.services.email_broadcast_service import EmailBroadcastService

    service = EmailBroadcastService()
    stages = []

    def add(name, ok, detail):
        stages.append({'name': name, 'ok': bool(ok), 'detail': detail})

    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        return {'stages': [], 'verdict': 'That person could not be found.'}
    who = user.username

    # ── 0. Is the rule even switched on? ────────────────────────────────
    add('Automation is on', rule.enabled,
        'This automation is switched on.' if rule.enabled else
        'This automation is switched OFF, so it never sends on its own. '
        '(You can still test it with Force run.)')

    # ── 1. Did the trigger fire at all? ─────────────────────────────────
    detector = DETECTORS.get(rule.trigger_type)
    events = []
    if detector:
        try:
            events = detector(session, rule)
        except Exception:
            logger.exception("Trace detection failed for rule %s", rule.key)
            add('Trigger fires', False, 'The trigger could not be evaluated — check the logs.')
            return {'stages': stages, 'verdict': f'{who} would not be messaged.'}

    if not events:
        add('Trigger fires', False,
            'The trigger condition is not met right now, so nothing would send to anyone.')
        return {'stages': stages, 'verdict': f'{who} would not be messaged — the trigger is not firing.'}
    add('Trigger fires', True,
        f'The trigger currently fires for {len(events)} scope(s).')

    # A native rule's audience is not a filter, so the generic walk below would
    # resolve nobody and report "not in the audience" for someone who is in fact
    # due a reminder. Hand off to a trace that knows the real rules.
    if rule.native_action:
        return _explain_native(session, rule, user, stages, add)

    # ── 2. Is this person in the audience, for any firing scope? ───────
    from types import SimpleNamespace
    matched_scope = None
    audience_ids = set()
    for event in events:
        pseudo = SimpleNamespace(
            season_id=event['season_id'], league_id=event['league_id'],
            subject_type=event.get('subject_type'), subject_id=event.get('subject_id'))
        criteria = build_filter_criteria(session, rule, pseudo)
        ids = {r['user_id'] for r in
               service.resolve_recipients(session, criteria, bool(rule.force_send))}
        audience_ids |= ids
        if user_id in ids:
            matched_scope = event
            break

    if not matched_scope:
        desc = service.build_filter_description(
            session, build_filter_criteria(session, rule, SimpleNamespace(
                season_id=events[0]['season_id'], league_id=events[0]['league_id'],
                subject_type=events[0].get('subject_type'),
                subject_id=events[0].get('subject_id'))))
        add('In the audience', False,
            f'{who} is not in "{desc}". That is the audience this automation targets, '
            f'so they are excluded before conditions are even checked.')
        return {'stages': stages,
                'verdict': f'{who} would NOT be messaged — they are not in the audience.'}
    add('In the audience', True,
        f'{who} is one of {len(audience_ids)} people the audience resolves to.')

    # ── 3. Which condition, if any, excludes them? ─────────────────────
    conditions = rule.conditions or []
    if not conditions:
        add('Passes conditions', True, 'This automation has no extra conditions.')
    else:
        recipients = [{'user_id': user_id, 'name': who}]
        kept = apply_conditions(session, rule, recipients)
        if kept:
            add('Passes conditions', True,
                f'{who} passes all {len(conditions)} condition(s).')
        else:
            # Re-test one at a time to name the culprit rather than just "failed".
            failed = []
            for cond in conditions:
                probe = SimpleNamespace(
                    key=rule.key, conditions=[cond],
                    audience_type=rule.audience_type, force_send=rule.force_send)
                if not apply_conditions(session, probe, list(recipients)):
                    failed.append(describe_condition(cond))
            detail = ('Excluded by: ' + '; '.join(failed)) if failed else \
                     'Excluded by the conditions.'
            add('Passes conditions', False, detail)
            return {'stages': stages,
                    'verdict': f'{who} would NOT be messaged — a condition excludes them.'}

    # ── 4. Has it already gone out to them? ────────────────────────────
    # Occurrence included, or a recurring rule's trace looks up a scope key that
    # was never written and always reports "never sent".
    scope_key = build_scope_key(
        matched_scope['season_id'], matched_scope['league_id'],
        matched_scope.get('subject_type'), matched_scope.get('subject_id'),
        matched_scope.get('occurrence'))
    run = (session.query(AutomationRun)
           .filter(AutomationRun.rule_id == rule.id,
                   AutomationRun.scope_key == scope_key).first())
    if run:
        add('Already sent', run.status == 'sent',
            f'This scope already has a run, currently "{run.status}"'
            + (f' — {run.error_message}' if run.error_message else '.'))
    else:
        add('Already sent', True,
            'No run yet for this scope; it would be created on the next hourly pass.')

    verdict = (f'{who} WOULD be messaged.' if not run or run.status != 'sent'
               else f'{who} is in the audience and this scope has already been sent.')
    return {'stages': stages, 'verdict': verdict}


def _preview_match_day(session, rule):
    """Who the day-before digest would reach if it ran right now.

    Uses the sender's own audience rules -- RSVP state, the chase-only setting
    and the snooze list -- rather than a second implementation that could drift.
    """
    from app.models import Match, EcsFcMatch
    from app.models.communication import MatchReminderLog
    from app.services.team_visibility import teams_are_public, is_current_pub_league_team
    from app.tasks.tasks_notification_reminders import _reminder_audience_status
    from app.utils.pacific_time import pacific_today

    cfg = rule.trigger_config or {}
    days_before = int(cfg.get('days_before', 1))
    chase_only = cfg.get('reminder_audience', 'chase_and_confirm') == 'chase_only'
    target = pacific_today() + timedelta(days=days_before)

    snoozed = set()
    if cfg.get('respect_snooze', True):
        from app.services import rsvp_snooze_service
        snoozed = rsvp_snooze_service.get_all_snoozed_player_ids(session=session)

    pub = session.query(Match).filter(
        Match.date == target, Match.is_special_week.is_(False),
        Match.week_type.in_(['REGULAR', 'PLAYOFF'])).all()
    if not teams_are_public():
        pub = [m for m in pub
               if not (is_current_pub_league_team(m.home_team)
                       or is_current_pub_league_team(m.away_team))]
    ecs = session.query(EcsFcMatch).filter(
        EcsFcMatch.match_date == target,
        EcsFcMatch.status == 'SCHEDULED').all()

    # Already-reminded users are excluded, so the count is what WOULD go out now
    # rather than the roster size.
    already = {row.user_id for row in session.query(MatchReminderLog.user_id).filter(
        MatchReminderLog.reminder_type == 'daily',
        MatchReminderLog.target_date == target,
        MatchReminderLog.delivery_status == 'sent').all()}

    names = set()
    def _consider(players, responses):
        for p in players:
            if not p.user or p.user.id in already or p.id in snoozed:
                continue
            status = _reminder_audience_status(responses.get(p.id))
            if status is None or (chase_only and status != 'no_response'):
                continue
            names.add(p.name or f'Player {p.id}')

    for m in pub:
        responses = {a.player_id: a.response for a in (m.availability or []) if a.player_id}
        _consider(list(m.home_team.players) if m.home_team else [], responses)
        _consider(list(m.away_team.players) if m.away_team else [], responses)
    for m in ecs:
        if not m.team:
            continue
        responses = {a.player_id: a.response for a in (m.availabilities or []) if a.player_id}
        _consider(list(m.team.players), responses)

    gap = ('today' if days_before == 0 else 'tomorrow' if days_before == 1
           else f'in {days_before} days')
    described = ('Everyone with a match ' + gap
                 + (' who has not responded' if chase_only
                    else ' who has not responded, plus those who said yes')
                 + (', excluding snoozed players' if snoozed else ''))
    return len(names), sorted(names)[:10], described


def _preview_native(session, rule):
    """Who a built-in sender would reach if it ran right now.

    Returns (count, [names], description).

    Deliberately calls the SENDER's own collectors rather than re-implementing
    the query here: a preview that drifts from the real audience is worse than
    no preview, and the whole point of this rule is that an admin can trust the
    numbers before switching the schedule around.

    It applies the snooze list and the repeat cap, so the number matches what
    would actually go out today -- not the raw roster.
    """
    if rule.native_action == NATIVE_ACTION_MATCH_DAY:
        return _preview_match_day(session, rule)
    if rule.native_action != NATIVE_ACTION_RSVP_DM:
        return 0, [], 'Worked out by the built-in sender'

    from datetime import date as _date
    from app.models.communication import RsvpDmReminderLog
    from app.services import rsvp_snooze_service
    from app.tasks.tasks_rsvp_dm_reminders import (
        _collect_pub_league_non_responders, _collect_ecs_fc_non_responders)
    from app.utils.pacific_time import pacific_today

    cfg = rule.trigger_config or {}
    lookahead = int(cfg.get('lookahead_days', 4))
    cap = int(cfg.get('max_reminders_per_match', 1))

    today = pacific_today()
    window_end = today + timedelta(days=lookahead)
    snoozed = rsvp_snooze_service.get_all_snoozed_player_ids(session=session)

    player_data = {}
    _collect_pub_league_non_responders(session, today, window_end, snoozed, player_data)
    _collect_ecs_fc_non_responders(session, today, window_end, snoozed, player_data)

    # Scoped to the matches in the window, same as the real send -- this runs
    # inside a web request, so it must not scan the whole log table.
    # match_id is not unique across match_type, so the IN() is a prefilter only;
    # the dict key still carries match_type and stays exact.
    window_match_ids = {m['match_id'] for d in player_data.values() for m in d['matches']}
    sent_counts = {}
    if window_match_ids:
        sent_counts = {
            (r.player_id, r.match_id, r.match_type): r.n
            for r in session.query(
                RsvpDmReminderLog.player_id, RsvpDmReminderLog.match_id,
                RsvpDmReminderLog.match_type, func.count(RsvpDmReminderLog.id).label('n')
            ).filter(RsvpDmReminderLog.delivery_status == 'sent',
                     RsvpDmReminderLog.match_id.in_(window_match_ids))
             .group_by(RsvpDmReminderLog.player_id, RsvpDmReminderLog.match_id,
                       RsvpDmReminderLog.match_type).all()
        }

    names = []
    for pid, data in player_data.items():
        if any(sent_counts.get((pid, m['match_id'], m['match_type']), 0) < cap
               for m in data['matches']):
            names.append(data['player'].name or f'Player {pid}')

    described = (f'Everyone with an unanswered match in the next {lookahead} '
                 f'day{"s" if lookahead != 1 else ""}, excluding snoozed players '
                 f'and anyone already reminded {cap}x about that match')
    return len(names), sorted(names)[:10], described


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
                                    event.get('subject_type'), event.get('subject_id'),
                                    event.get('occurrence'))
        pseudo_run = SimpleNamespace(
            season_id=event['season_id'], league_id=event['league_id'],
            subject_type=event.get('subject_type'), subject_id=event.get('subject_id'))
        existing = (session.query(AutomationRun)
                    .filter(AutomationRun.rule_id == rule.id,
                            AutomationRun.scope_key == scope_key)
                    .first())

        # A native rule has no audience filter to resolve -- running the generic
        # path would report 0 recipients for a rule that in fact reaches
        # everybody with an unanswered match, which is worse than no preview.
        if rule.native_action:
            count, sample, described = _preview_native(session, rule)
            scopes.append({
                'scope_key': scope_key,
                'label': event.get('label', scope_key),
                'event_at': event['event_at'],
                'scheduled_for': event['event_at'] + timedelta(hours=rule.delay_hours or 0),
                'recipient_count': count,
                'sample': sample,
                'already_run': existing.status if existing else None,
                'filter_description': described,
            })
            continue

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

    # A dry run that says "would send tomorrow" for a rule dispatch will actually
    # hold is a lie, and the dry run is exactly what an admin trusts before
    # enabling. Report the hold alongside the counts.
    held_for_reveal = bool(scopes) and not _reveal_allows(session, rule)

    return {'triggered': bool(scopes), 'scopes': scopes,
            'held_for_reveal': held_for_reveal}
