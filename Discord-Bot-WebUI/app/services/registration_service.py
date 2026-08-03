# app/services/registration_service.py

"""
Registration & Waitlist Service — the one copy of "can I sign up, and how?"

Mobile Discord OAuth already CREATES accounts (``process_discord_user()`` ->
``User(is_approved=False, approval_status='pending')`` + a restricted JWT). So
during a full season an app signup landed in the approvals queue — the queue
``User.pending_approval_criteria()`` deliberately excludes waitlisted people
from — and waited on a decision nobody was going to make. The web had a waitlist
to park those people; mobile had no way to reach it.

This module holds the two pieces that were missing, so both surfaces can share
them:

* :func:`registration_status` — what a prospective member may do right now
  (unauthenticated; the caller has no account yet, by definition).
* :func:`join_waitlist` — put a signed-in member on the waitlist, idempotently.

Both return plain dicts / ``(payload, status)`` so the route only jsonifies.

⚠️ SESSION: ``join_waitlist`` takes the request session explicitly and its
caller must be ``@transactional`` — same contract as the web
``auth.waitlist_register`` route it mirrors.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# lane vocabulary
# ---------------------------------------------------------------------------

# `waitlist_league` stores the HYPHEN spelling of the membership lane
# ('ecs-fc', 'pl-third'), because that is what `approvals.waitlist_league_map()`
# maps its `waitlist-<lane>` outcomes onto and what the member-hub lane filter
# matches against. Every other vocabulary in this codebase spells lanes with
# underscores, so normalize on the way IN rather than storing whatever a client
# happened to send — a row stored as 'ecs_fc' would never match the hyphen
# clause the waitlist tab filters with.
def _hyphen(lane):
    return (lane or '').strip().replace('_', '-').lower()


def waitlist_lane_options(session=None):
    """[{value, label}] — the lanes a member may be waitlisted into.

    Derived from the program registry, so a newly registered program is
    offerable the day it is seeded rather than the day someone remembers to
    edit a literal. ``value`` is exactly what :func:`join_waitlist` accepts and
    what lands in ``users.waitlist_league``.
    """
    out = []
    try:
        from app.services import program_registry
        for p in program_registry.all_programs(session):
            lane = _hyphen(p.membership_lane or p.form_value)
            if not lane:
                continue
            out.append({
                'value': lane,
                'label': p.display_name or p.league_name or lane,
            })
    except Exception:
        logger.warning("waitlist lane options fell back to the legacy three",
                       exc_info=True)
    if not out:
        out = [
            {'value': 'premier', 'label': 'Premier'},
            {'value': 'classic', 'label': 'Classic'},
            {'value': 'ecs-fc', 'label': 'ECS FC'},
        ]
    return out


def resolve_waitlist_lane(value, session=None):
    """Any reasonable spelling of a lane -> the canonical stored one, or None.

    Accepts the membership lane ('ecs_fc'), its hyphen twin ('ecs-fc'), the
    program key, the form value, and the display name — the five spellings that
    already circulate in this codebase — case- and whitespace-insensitively.
    Returns None for an unknown value so the caller can 400 with the real list
    instead of silently parking someone in a lane that does not exist.
    """
    raw = (value or '').strip()
    if not raw:
        return None
    want = _hyphen(raw)

    try:
        from app.services import program_registry
        for p in program_registry.all_programs(session):
            candidates = {
                _hyphen(p.membership_lane),
                _hyphen(p.form_value),
                _hyphen(p.key),
                _hyphen(p.display_name),
                _hyphen(p.short_name),
                _hyphen(p.league_name),
            }
            candidates.discard('')
            if want in candidates:
                return _hyphen(p.membership_lane or p.form_value or p.key)
    except Exception:
        logger.warning("waitlist lane resolution fell back to literals",
                       exc_info=True)

    # Registry unreachable (or a program row missing) — still honour the three
    # lanes that predate the registry rather than rejecting a valid signup.
    if want in ('premier', 'classic', 'ecs-fc'):
        return want
    return None


# ---------------------------------------------------------------------------
# GET /registration/status
# ---------------------------------------------------------------------------

# Admin-settable banner shown verbatim by the client ("Spring registration
# closes March 1"). Nothing writes it today, so it is simply absent from the
# payload until someone sets it.
REGISTRATION_MESSAGE_KEY = 'registration_status_message'


def registration_status(session=None):
    """What a prospective member may do right now. UNAUTHENTICATED.

    ⚠️ This must never be able to BLOCK a signup. The Flutter client degrades a
    404/500/timeout here to "unknown" and then behaves exactly as it does with
    no status endpoint at all — so the honest failure mode for this function is
    to raise, not to invent a "closed".

    There is no per-lane capacity model in this system: registration is
    infinite-capacity (``is_registration_open``) and the waitlist is ONE global
    population governed by the Pub League phase (see
    ``season_phase_service.get_program_phase``'s docstring). Every lane
    therefore reports the same open/waitlist_open today. The per-lane shape is
    still emitted because it is the client's contract and because it is where a
    real per-program capacity rule would land.
    """
    from app.models.admin_config import AdminConfig
    from app.auth.helpers import registration_enabled
    from app.services.season_phase_service import (
        is_registration_open, is_waitlist_open)

    # The master kill-switch gates BOTH paths — waitlist signup is a flavour of
    # registration, not an escape hatch around it (see auth/helpers.py).
    master_on = registration_enabled()
    reg_open = bool(master_on and is_registration_open(session))
    wl_open = bool(master_on and is_waitlist_open(session))

    message = None
    try:
        message = AdminConfig.get_setting(REGISTRATION_MESSAGE_KEY, None)
    except Exception:
        logger.debug("registration status message unavailable", exc_info=True)
    if isinstance(message, str):
        message = message.strip() or None
    elif message is not None:
        message = str(message)

    if not message and not reg_open and not wl_open:
        # Say SOMETHING when both doors are shut — "closed" with no explanation
        # is the state people email about.
        message = 'Registration is closed right now. Check back soon.'

    lanes = []
    for opt in waitlist_lane_options(session):
        lanes.append({
            'value': opt['value'],
            'label': opt['label'],
            'open': reg_open,
            'waitlist_open': wl_open,
            'note': ('Full — join the waitlist'
                     if (wl_open and not reg_open) else None),
        })

    payload = {
        'registration_open': reg_open,
        'waitlist_open': wl_open,
        'lanes': lanes,
    }
    if message:
        payload['message'] = message
    return payload


# ---------------------------------------------------------------------------
# POST /members/waitlist
# ---------------------------------------------------------------------------

def _position(db_session, user):
    """(position, total) or (None, None) — never fatal to the join itself."""
    try:
        from app.auth.waitlist import compute_waitlist_position
        return compute_waitlist_position(db_session, user)
    except Exception:
        logger.warning("waitlist position unavailable for user %s",
                       getattr(user, 'id', '?'), exc_info=True)
        return None, None


def join_waitlist(db_session, user, league_type=None):
    """Put ``user`` on the waitlist. Returns ``(payload, http_status)``.

    IDEMPOTENT by contract: a repeat join is ``success: true`` with
    ``already_on_waitlist: true``, and — critically — does NOT restamp
    ``waitlist_joined_at``, because that timestamp IS the queue position. A
    naive "just set it again" would send a member to the back of the line every
    time the app retried a request.

    ``league_type`` is optional. Omitted, it falls back to the member's
    ``preferred_league`` exactly as ``auth.waitlist_register`` does (the lane
    they already told us about during onboarding is a decision, not a guess);
    when they have none, they sit on the general waitlist with no lane, which
    the member hub surfaces as 'undecided'. The resolved lane is always echoed
    back, so nothing about that fallback is hidden from the client.

    An ALREADY-WAITLISTED member who sends a different ``league_type`` is
    switching lanes — the spec's "returning member queues for a different lane"
    case. The lane moves; the join time does not.

    ⚠️ Caller must be ``@transactional``. This flushes but never commits.
    """
    from app.models import Role, User

    if user is None:
        return {'success': False, 'message': 'User not found'}, 404

    # --- gate -------------------------------------------------------------
    from app.auth.helpers import registration_enabled
    from app.services.season_phase_service import is_waitlist_open

    if not registration_enabled():
        return {'success': False,
                'message': 'Registration is closed right now.'}, 403
    if not is_waitlist_open(db_session):
        return {'success': False,
                'message': 'The waitlist is not open right now.'}, 403

    # `user` may be a lightweight auth projection (UserAuthData) rather than the
    # mapped model — mutate the real row.
    db_user = db_session.query(User).get(user.id)
    if db_user is None:
        return {'success': False, 'message': 'User not found'}, 404

    # --- already playing --------------------------------------------------
    # Never move an in-season player into the waitlist: the waitlist path resets
    # approval_status to 'pending', which the Discord role calculator reads as
    # unverified and strips their league/team roles. Same guard as the web page.
    try:
        from app.auth.waitlist import is_actively_playing
        if is_actively_playing(db_user, db_session):
            return {'success': False,
                    'message': "You're already playing this season, so you "
                               "don't need the waitlist."}, 409
    except Exception:
        logger.warning("active-player guard skipped for user %s", db_user.id,
                       exc_info=True)

    # --- lane -------------------------------------------------------------
    requested = league_type
    if isinstance(requested, (list, dict)):
        # A JSON body can carry anything; a non-scalar is a client bug, not a lane.
        requested = None
    requested = (str(requested).strip() if requested is not None else '')

    lane = None
    if requested:
        lane = resolve_waitlist_lane(requested, db_session)
        if not lane:
            return {'success': False,
                    'message': f"Unknown league '{requested}'.",
                    'valid_league_types': [o['value']
                                           for o in waitlist_lane_options(db_session)]}, 400

    # --- roles ------------------------------------------------------------
    waitlist_role = db_session.query(Role).filter_by(name='pl-waitlist').first()
    if not waitlist_role:
        waitlist_role = Role(name='pl-waitlist',
                             description='Player on waitlist for current season')
        db_session.add(waitlist_role)
        db_session.flush()

    already = bool(db_user.waitlist_joined_at) and waitlist_role in db_user.roles

    if waitlist_role not in db_user.roles:
        db_user.roles.append(waitlist_role)

    # Only NEW-to-the-league people get pl-unverified. Adding it to an approved
    # returning player makes the role calculator treat them as unverified and
    # strip their league/team roles — the same trap auth/waitlist.py documents.
    if db_user.approval_status != 'approved' and not db_user.is_approved:
        unverified = db_session.query(Role).filter_by(name='pl-unverified').first()
        if unverified and unverified not in db_user.roles:
            db_user.roles.append(unverified)

    # --- timestamps + lane ------------------------------------------------
    if not db_user.waitlist_joined_at:
        db_user.waitlist_joined_at = datetime.utcnow()

    if lane:
        db_user.waitlist_league = lane
    elif not db_user.waitlist_league:
        db_user.waitlist_league = getattr(db_user, 'preferred_league', None) or None

    db_user.updated_at = datetime.utcnow()
    db_session.flush()

    # --- spine dual-write -------------------------------------------------
    if db_user.player:
        try:
            from app.services.league_membership_sync import resync_player_memberships
            resync_player_memberships(db_session, db_user.player.id)
        except Exception as exc:
            logger.warning("league_membership sync skipped for waitlist user %s: %s",
                           db_user.id, exc)

    # --- confirmation email (new joins only) ------------------------------
    if not already:
        try:
            from app.auth.waitlist import _enqueue_waitlist_confirmation_email
            _enqueue_waitlist_confirmation_email(db_user.id)
        except Exception as exc:
            logger.warning("waitlist confirmation email skipped for user %s: %s",
                           db_user.id, exc)

    position, total = _position(db_session, db_user)
    stored_lane = db_user.waitlist_league

    label = None
    if stored_lane:
        for opt in waitlist_lane_options(db_session):
            if opt['value'] == _hyphen(stored_lane):
                label = opt['label']
                break

    if already:
        message = (f"You're already on the {label} waitlist" if label
                   else "You're already on the waitlist")
    else:
        message = (f"You're on the {label} waitlist" if label
                   else "You're on the waitlist")

    logger.info("User %s (%s) joined waitlist lane=%s already=%s",
                db_user.id, db_user.username, stored_lane, already)

    payload = {
        'success': True,
        'message': message,
        'league_type': stored_lane,
        'already_on_waitlist': already,
    }
    # Only render "7 of 41" when both halves are real — the client hides the
    # counter unless both are present, and a half-known position is a lie.
    if position is not None and total is not None:
        payload['position'] = position
        payload['total'] = total
    return payload, 200
