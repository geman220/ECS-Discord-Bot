# app/services/season_phase_service.py

"""
Season phase service (Phase 1 of the registration-lifecycle overhaul).

`Season.phase` (preseason | in_season | break | offseason) is the single driver
for whether the waitlist and registration are open, and whether sub auto-rest runs.
ECS FC is pinned `in_season` and NEVER auto-flips or rolls over (user decision
2026-07-22).

THREE DIFFERENT SCOPES LIVE HERE, and the distinctions are deliberate:

  * **Phase ADVANCEMENT** (`auto_advance_phases`) runs for EVERY phase-governed
    program, resolved from the registry. Without this a newer program's `phase`
    was written once at season creation and then never moved again -- a
    decorative column that said `preseason` through its whole season.
    ⚠️ Phase governance is NOT `rolls_over` alone; see
    `phase_governed_season_types` for why that conflation silently freezes a
    one-off program's phase.

  * **Phase READS** are per-program via `get_program_phase(key)`.
    `get_pub_league_phase()` is specifically the Pub League one and should only
    be used where Pub League genuinely governs (the waitlist, below). Asking it
    "is this program in season?" is confidently wrong whenever two programs sit
    in different parts of their calendars -- which, for a summer sprint running
    against a fall season, is most of the time.

  * **Waitlist SIDE EFFECTS** stay Pub-League-only. `pl-waitlist` is a single
    GLOBAL population, not a per-program one, so clearing it on another
    program's season boundary would wipe the live Pub League waitlist. Until the
    waitlist itself is per-program, only Pub League may trigger those effects.

Behavior is intentionally backward-compatible: the legacy
`waitlist_registration_enabled` AdminConfig toggle survives as an OVERRIDE that can
force the waitlist closed even when the phase would allow it — so existing "close
the waitlist" admin behavior is unchanged, and phase adds automatic offseason
closing on top.

Design: ~/.claude/plans/registration-lifecycle-overhaul.md  §2.4
"""

import logging

from app.core import db
from app.models import Season
from app.models.admin_config import AdminConfig

logger = logging.getLogger(__name__)

# The waitlist is ITSELF a form of registration — it just runs during preseason/in_season
# AND only when the admin flips the waitlist_registration_enabled toggle on (see
# is_waitlist_open). We currently sell out in minutes, so once a season opens we switch
# from open registration to a waitlist that tracks everyone who still wants in. A waitlist
# entry can be an ALREADY-registered+approved player OR a brand-new person who isn't
# approved yet — approval is a SEPARATE axis, not a precondition. If a season ever does
# NOT sell out, we simply leave the toggle off and people keep registering -> approved ->
# drafted straight through preseason/in_season (not a problem we have today).
WAITLIST_OPEN_PHASES = ('preseason', 'in_season')
# Registration = the base intake path (register -> approved -> drafted), INFINITE capacity,
# open in EVERY phase. People sign up year-round: during offseason/break for the upcoming
# season (only ~70 of last season's 100 return, plus new folks), and even during
# preseason/in_season whenever the waitlist toggle is off. Registration never closes on phase.
REGISTRATION_OPEN_PHASES = ('preseason', 'in_season', 'break', 'offseason')
# Sub auto-rest only makes sense once matches are actually running.
AUTO_REST_PHASES = ('in_season',)

VALID_PHASES = ('preseason', 'in_season', 'break', 'offseason')


def _sess(session=None):
    """Prefer the caller's session, then the request's g.db_session, then db.session."""
    if session is not None:
        return session
    try:
        from flask import g
        s = getattr(g, 'db_session', None)
        if s is not None:
            return s
    except Exception:
        pass
    return db.session


def _clear_phase_cache():
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, '_pub_league_phase'):
            del g._pub_league_phase
    except Exception:
        pass


def get_pub_league_phase(session=None):
    """Current Pub League season phase, or None if there is no current Pub League season.

    Cached per request on `g` — the waitlist gate + context processor + login page can
    each call this within one request, and the phase can't change mid-request.
    """
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, '_pub_league_phase'):
            return g._pub_league_phase
    except Exception:
        pass
    row = (_sess(session).query(Season.phase)
           .filter(Season.is_current.is_(True), Season.league_type == 'Pub League')
           .first())
    phase = row[0] if row else None
    try:
        from flask import g, has_request_context
        if has_request_context():
            g._pub_league_phase = phase
    except Exception:
        pass
    return phase


def season_phase_map(session=None):
    """{<membership lane>: <phase|None>} for every program's current season.

    `pub_league` and `ecs_fc` are ALWAYS present (None when there is no current
    season) because the mobile app reads those two keys by name — see
    mobile_api/auth.py. Every other program is added under its own membership
    lane, so a newer program's phase reaches the client instead of being
    silently dropped by an if/elif that only knew two league types.
    """
    out = {'pub_league': None, 'ecs_fc': None}

    # lane per season type, e.g. {'Pub League': 'pub_league', 'PL Third': 'pl_third'}
    #
    # Programs on an ALREADY-MAPPED season type are skipped: Premier and Classic
    # share the 'Pub League' season, so adding 'premier'/'classic' keys would
    # publish two lanes that are permanently null (the season type is already
    # reported as 'pub_league') — a client reading `premier` would see null while
    # the real phase sat under a different key. Only a program with its OWN
    # season type gets its own key.
    lane_by_type = {'Pub League': 'pub_league', 'ECS FC': 'ecs_fc'}
    try:
        from app.services import program_registry
        for p in program_registry.all_programs(session):
            if (p.season_league_type and p.membership_lane
                    and p.season_league_type not in lane_by_type):
                lane_by_type[p.season_league_type] = p.membership_lane
                out.setdefault(p.membership_lane, None)
    except Exception:
        logger.warning("season_phase_map: registry unavailable; "
                       "reporting Pub League + ECS FC only", exc_info=True)

    rows = (_sess(session).query(Season.league_type, Season.phase)
            .filter(Season.is_current.is_(True)).all())
    for ltype, phase in rows:
        lane = lane_by_type.get(ltype)
        if lane:
            out[lane] = phase
    return out


def get_program_phase(program_key, session=None):
    """Current phase of ONE program's season, or None.

    `get_pub_league_phase` remains the right call for the WAITLIST, which is a
    single global population governed by Pub League. Use this wherever the
    question is genuinely per-program ("is Summer Sprint in season?") — asking
    the Pub League phase there gives a confidently wrong answer whenever the two
    programs are in different parts of their calendars, which for a summer
    sprint running against a fall season is most of the time.

    Accepts a program key, membership lane, or League.name.
    """
    if not program_key:
        return None
    try:
        from app.services import program_registry
        pr = (program_registry.by_key(program_key)
              or program_registry.by_membership_lane(program_key)
              or program_registry.by_league_name(program_key))
        if pr is None or not pr.season_league_type:
            return None
        season_type = pr.season_league_type
    except Exception:
        return None

    row = (_sess(session).query(Season.phase)
           .filter(Season.is_current.is_(True), Season.league_type == season_type)
           .first())
    return row[0] if row else None


def is_waitlist_open(session=None):
    """Whether the Pub League waitlist accepts new joins right now.

    = phase allows (preseason/in_season/break) AND the admin override toggle is on.
    If no current Pub League season exists, fall back to the legacy toggle-only
    behavior so nothing silently closes.
    """
    toggle = bool(AdminConfig.get_setting('waitlist_registration_enabled', True))
    phase = get_pub_league_phase(session)
    if phase is None:
        return toggle  # legacy behavior when phase is unknown
    return toggle and (phase in WAITLIST_OPEN_PHASES)


def is_registration_open(session=None):
    """Whether someone can register (register -> approved -> drafted) right now.

    Registration is INFINITE-capacity and open in every phase — offseason/break for the
    upcoming season, and preseason/in_season too (whenever the waitlist toggle is off, or
    for anyone an admin adds directly). It is intentionally NOT gated by the
    waitlist_registration_enabled toggle — that toggle only governs the waitlist. This
    helper therefore returns True in all valid phases today; it exists so a future phase
    that should freeze registration can be excluded from REGISTRATION_OPEN_PHASES in one
    place. Unknown phase -> True (legacy)."""
    phase = get_pub_league_phase(session)
    if phase is None:
        return True
    return phase in REGISTRATION_OPEN_PHASES


def is_auto_rest_active(session=None, program=None):
    """Whether sub auto-rest should run right now.

    Auto-rest means "matches are actually being played", which is a PER-PROGRAM
    fact. Pass `program` (key, lane or League.name) to ask about one program;
    omit it for the legacy Pub League answer.

    Still unwired at the time of writing (see models/core.py), so widening the
    signature here changes no live behaviour — but it means whoever wires it up
    cannot accidentally rest Summer Sprint's subs because Premier happens to be
    between seasons.
    """
    phase = get_program_phase(program, session) if program else get_pub_league_phase(session)
    return phase in AUTO_REST_PHASES


def set_season_phase(session, season_id, phase):
    """Set a season's phase (admin action). Returns the Season. Raises ValueError on bad input."""
    if phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase '{phase}' (expected one of {VALID_PHASES})")
    s = _sess(session)
    season = s.query(Season).get(season_id)
    if season is None:
        raise ValueError(f"Season {season_id} not found")
    old_phase = season.phase
    season.phase = phase
    _clear_phase_cache()  # a same-request read must see the new value
    logger.info("Season %s (%s) phase set to '%s'", season.id, season.league_type, phase)

    # Manually dropping the CURRENT Pub League season into offseason is a season boundary
    # too: clear + route the point-in-time waitlist (idempotent, harmless if already clear).
    # The is_current guard is critical — clear_and_route_waitlist operates on the GLOBAL
    # pl-waitlist population, so firing it while editing a *historical* season's phase would
    # wipe the live waitlist.
    if (phase == 'offseason' and old_phase != 'offseason'
            and season.league_type == 'Pub League' and season.is_current):
        try:
            clear_and_route_waitlist(s, reason='offseason-manual')
        except Exception:
            logger.exception("clear_and_route_waitlist on manual offseason failed")
    return season


def phase_governed_season_types(session=None):
    """Season types whose `phase` is advanced from dates.

    ⚠️ `rolls_over` alone is NOT the right test, even though its column comment
    mentions phase.

    `rolls_over` answers "does this program hand its teams to a next season?",
    which is a DIFFERENT question from "do this season's dates move it through
    preseason -> in_season -> offseason?". They coincide for Premier/Classic
    (both true) and for ECS FC (both false, pinned in_season by an explicit
    2026-07-22 decision), which is why one flag appeared to cover both.

    They come apart for a one-off program. A Summer Sprint that is not intended
    to roll into another Summer is a perfectly reasonable `rolls_over = FALSE`
    — and that single flag would then ALSO silently freeze its phase at whatever
    it was seeded with, for the entire season, with no error. The waitlist and
    registration gates read that phase.

    So: a program is phase-governed if it rolls over OR it is pub-league-like.
    ECS FC is neither and stays excluded; every pub-league-like program is
    covered no matter how its rollover flag is set.
    """
    try:
        from app.services import program_registry
        types = sorted({p.season_league_type for p in
                        program_registry.all_programs(session)
                        if (p.rolls_over or p.is_pub_league_like) and p.season_league_type})
        if types:
            return types
    except Exception:
        pass
    return ['Pub League']


def _default_lead_lag():
    """(preseason_lead_days, offseason_lag_days) — buffers around the season dates.

    'in_season' begins LEAD days before start_date (default 7 = ~a week before the first
    match) and 'offseason' begins LAG days after end_date (~a week after playoffs). Both
    are admin-tunable via AdminConfig so you never touch code to change 'a week'.
    """
    try:
        lead = int(AdminConfig.get_setting('season_phase_preseason_lead_days', 7))
    except Exception:
        lead = 7
    try:
        lag = int(AdminConfig.get_setting('season_phase_offseason_lag_days', 7))
    except Exception:
        lag = 7
    return lead, lag


def compute_phase_for_dates(start_date, end_date, today, lead_days=7, lag_days=7):
    """The phase a season SHOULD be in given its dates. Returns None if start_date is
    unknown (can't compute — leave the admin's manual value alone).

      before (start - lead)         -> preseason   (drafting; waitlist OPEN)
      [start - lead, end + lag]      -> in_season   (matches; waitlist OPEN)
      after (end + lag)              -> offseason   (waitlist CLOSED)
    """
    from datetime import timedelta
    if start_date is None:
        return None
    if end_date is not None and today > end_date + timedelta(days=lag_days):
        return 'offseason'
    if today >= start_date - timedelta(days=lead_days):
        return 'in_season'
    return 'preseason'


def auto_advance_phases(session=None):
    """Date-DRIVEN phase sync for the CURRENT Pub League season only (ECS FC exempt).

    Recomputes the phase from the season's start/end dates each run (idempotent), so it
    both advances forward AND corrects itself if the dates are edited — e.g. push the
    start date out and it drops back to preseason; move playoffs and offseason follows.
    A manually-set 'break' (mid-season pause) is respected and never auto-overridden.
    NEVER tears down Discord (that's the separate rollover process). Returns changes.
    """
    from datetime import date
    s = _sess(session)
    today = date.today()
    changes = []
    seasons = (s.query(Season)
               .filter(Season.is_current.is_(True),
                       Season.league_type.in_(phase_governed_season_types(s)))
               .all())
    if not seasons:
        return changes

    lead, lag = _default_lead_lag()
    for season in seasons:
        changes.extend(_sync_one_season(s, season, today, lead, lag))
    return changes


def _sync_one_season(s, season, today, lead, lag):
    """Advance one season's phase. Extracted so the loop above can cover every
    phase-governed program without duplicating the transition logic."""
    changes = []
    # Respect an admin's deliberate mid-season pause.
    if season.phase == 'break':
        return changes

    desired = compute_phase_for_dates(season.start_date, season.end_date, today, lead, lag)
    if desired and season.phase != desired:
        old = season.phase
        season.phase = desired
        _clear_phase_cache()
        changes.append(f"{season.league_type} season {season.id}: {old} -> {desired} "
                       f"(date-driven, start={season.start_date}, "
                       f"end={season.end_date})")

        # Entering offseason is a season boundary (same as rollover): the point-in-time
        # waitlist clears and everyone routes (unapproved -> approval queue, approved ->
        # normal inactive pool). Idempotent, so if rollover already cleared it this no-ops.
        #
        # ⚠️ PUB LEAGUE ONLY. `pl-waitlist` is one GLOBAL population, not a
        # per-program one, so firing this on another program's season boundary
        # would wipe the live Pub League waitlist. Phase ADVANCEMENT is now
        # per-program; this side effect deliberately is not.
        if (desired == 'offseason' and old != 'offseason'
                and season.league_type == 'Pub League'):
            try:
                routed = clear_and_route_waitlist(s, reason='offseason-auto')
                if routed:
                    changes.append(f"Cleared waitlist on offseason entry: routed {routed} user(s)")
            except Exception:
                logger.exception("[phase auto-advance] waitlist clear on offseason entry failed")

    for c in changes:
        logger.info("[phase auto-advance] %s", c)
    return changes


def clear_and_route_waitlist(session, reason='rollover'):
    """Clear the point-in-time Pub League waitlist and route each person by approval axis.

    The waitlist is a per-SEASON snapshot, not a durable list. At a season boundary
    (rollover) or when the Pub League season enters offseason, EVERYONE currently on the
    waitlist comes off it and routes by whether they're approved:

      * NOT approved -> the APPROVAL QUEUE: approval_status='pending' (approval_league
        seeded from their waitlist lane if unset) so an admin still reviews them. A pending
        user already holds pl-unverified + the ECS-FC-PL-UNVERIFIED Discord role, so no
        Discord change is needed.
      * approved     -> the NORMAL POOL: approved but INACTIVE. They keep their division
        role; they simply hold no waitlist row and no active player row until the new
        season's pass is linked/purchased.

    In BOTH cases the pl-waitlist Flask role + waitlist_league/waitlist_joined_at columns
    are cleared (pl-waitlist has no managed Discord role, so there's nothing to strip on
    Discord), and every active waitlist spine row for the player is explicitly retired to
    'removed' across ALL seasons (resync's retire sweep only scopes to the current season,
    so the old-season row created at signup would otherwise linger 'waiting' after rollover).

    Idempotent: after the first pass there are no pl-waitlist holders, so re-running is a
    no-op — safe to fire from BOTH the rollover and the daily offseason transition without
    double-routing anyone. Pub League only: ECS FC-lane waitlisters are left untouched
    (ECS FC is exempt and never rolls over). Never raises for a single bad user — it logs
    and continues. Returns the number of people routed.
    """
    from app.models import User, Role, LeagueMembership
    from app.services.league_membership_sync import resync_player_memberships, _norm_league_type

    s = _sess(session)
    wl_role = s.query(Role).filter_by(name='pl-waitlist').first()
    if wl_role is None:
        return 0

    users = s.query(User).filter(User.roles.any(Role.name == 'pl-waitlist')).all()
    routed = 0
    for user in users:
        try:
            lane = _norm_league_type(getattr(user, 'waitlist_league', None))
            if lane == 'ecs_fc':
                continue  # ECS FC is exempt from the Pub League waitlist lifecycle

            status = getattr(user, 'approval_status', None)
            approved = bool(getattr(user, 'is_approved', False)) or status == 'approved'
            if not approved and status != 'denied':
                # Unapproved (and NOT deliberately denied) -> the approval queue; preserve
                # which league they were after. A 'denied' user is left denied: they come off
                # the waitlist but are never silently resurrected back into the review queue.
                if status != 'pending':
                    user.approval_status = 'pending'
                if not getattr(user, 'approval_league', None) and getattr(user, 'waitlist_league', None):
                    user.approval_league = user.waitlist_league

            # Come off the waitlist (all cases). Null the columns + remove the role BEFORE
            # resync so the recompute sees no waitlist source.
            if wl_role in user.roles:
                user.roles.remove(wl_role)
            user.waitlist_joined_at = None
            user.waitlist_league = None
            routed += 1

            player = getattr(user, 'player', None)
            if player is not None:
                # Explicitly retire EVERY active waitlist spine row for this player, across
                # ALL seasons. resync's retire sweep only scopes to the CURRENT season, so at
                # rollover (the new season is already current) the OLD-season waitlist row
                # would otherwise linger as 'waiting'. This covers every season uniformly.
                for wl_row in s.query(LeagueMembership).filter(
                        LeagueMembership.player_id == player.id,
                        LeagueMembership.role == 'waitlist',
                        LeagueMembership.status.in_(('waiting', 'offered'))).all():
                    wl_row.status = 'removed'
                resync_player_memberships(s, player.id)
        except Exception:
            logger.exception("clear_and_route_waitlist: failed to route user %s",
                             getattr(user, 'id', '?'))

    s.flush()
    logger.info("clear_and_route_waitlist(%s): routed %s waitlisted user(s)", reason, routed)
    return routed
