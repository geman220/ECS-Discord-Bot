# app/mobile_api/members.py

"""
Mobile Member Lifecycle API

Implements the endpoints promised by docs/flutter/member_lifecycle_api.md
(§2.2 and §2.3) that were documented but never built — a Flutter client coded
against that doc got 404s — plus the signup/waitlist pair that closes the real
inconsistency behind them:

Mobile Discord OAuth already CREATES accounts, so during a full season an app
signup landed in the approvals queue that ``User.pending_approval_criteria()``
deliberately excludes waitlisted people from, and waited on a decision nobody
was going to make. The web had a waitlist for exactly that; mobile had no way
in. ``GET /registration/status`` says which door is open and
``POST /members/waitlist`` walks through it.

my-status / my-waitlist are read-only projections over the LeagueMembership
spine plus the ``User.waitlist_*`` columns. The waitlist WRITE lives in
``app/services/registration_service.py`` so the web route can be moved onto the
same copy.
"""

import logging

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.limiter import limiter, get_client_ip
from app.core.session_manager import managed_session
from app.models import User, Player, LeagueMembership
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


# Terminal rows are people who LEFT — they are history, not a current
# membership, and surfacing them would make "My Memberships" read as though a
# retired sub were still on the hook. Mirrors the same exclusion list used by
# `flask sync-program-discord-roles` in app/cli.py.
_TERMINAL_STATUSES = ('inactive', 'retired', 'removed')


def _season_phase():
    """Per-league_type season phase. Same source as GET /user_profile."""
    try:
        from app.services.season_phase_service import season_phase_map
        return season_phase_map()
    except Exception as exc:
        logger.warning(f"[MOBILE_API] season_phase lookup skipped: {exc}")
        return {"pub_league": None, "ecs_fc": None}


def _waitlist_payload(db_session, user):
    """`{on_waitlist, league_type, position, joined_at}` for one user.

    Position comes from the SAME helper the web waitlist page uses
    (app/auth/waitlist.py:compute_waitlist_position) so the number a member
    sees in the app can never disagree with the one on the website. That
    helper ranks the GLOBAL waitlist by join time; `league_type` reports the
    lane they picked but does not currently re-rank within it.
    """
    if not getattr(user, 'waitlist_joined_at', None):
        return {'on_waitlist': False}

    try:
        from app.auth.waitlist import compute_waitlist_position
        position, total = compute_waitlist_position(db_session, user)
    except Exception as exc:
        logger.warning(f"[MOBILE_API] waitlist position unavailable: {exc}")
        position, total = None, None

    return {
        'on_waitlist': True,
        'league_type': user.waitlist_league,
        'position': position,
        'total': total,
        'joined_at': user.waitlist_joined_at.isoformat() if user.waitlist_joined_at else None,
    }


@mobile_api_v2.route('/registration/status', methods=['GET'])
@limiter.limit("60 per minute", key_func=lambda: f"reg_status:{get_client_ip()}")
def registration_status():
    """Which sign-up door is open. UNAUTHENTICATED — the caller has no account.

    No ``@jwt_required``: a prospective member holds no token, which is the
    entire population this answers for. It is also on the pending-user
    allowlist in ``approval_gate.py`` so a signed-in-but-unapproved user on the
    hold screen can read it.

    ⚠️ This must NEVER block signup. The client degrades any failure — 404, 500,
    timeout — to "unknown" and then behaves exactly as it did before this
    endpoint existed. So a 500 here is strictly better than inventing a
    "registration closed" the app would show to someone who could have signed
    up; that is why the except returns 500 rather than a closed-looking payload.

    Nothing here reads the caller's identity, so there is nothing to leak: the
    response is the same for everyone.
    """
    try:
        from app.services.registration_service import registration_status as _status
        return jsonify(_status()), 200
    except Exception as exc:
        logger.error(f"[MOBILE_API] registration_status failed: {exc}", exc_info=True)
        return jsonify({'success': False,
                        'msg': 'Could not load registration status'}), 500


@mobile_api_v2.route('/members/waitlist', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute", key_func=lambda: f"waitlist_join:{get_client_ip()}")
@transactional(max_retries=3)
def join_waitlist():
    """Put the calling member on the waitlist. Idempotent.

    Body: ``{"league_type": "classic"}`` — OPTIONAL; omitted means no lane
    chosen (the service falls back to their onboarding ``preferred_league`` when
    they have one, and echoes whatever it settled on back in ``league_type``).

    Reachable by a PENDING user — that is the entire population using it, so
    ``/api/v1/members`` is on the approval-gate allowlist. Also works for an
    already-approved returning member queueing for a different lane: sending a
    new ``league_type`` moves the lane and leaves ``waitlist_joined_at`` alone,
    because that timestamp is the queue position.

    ⚠️ ``@transactional``, not ``managed_session()``: this WRITES, and the web
    waitlist route it mirrors commits on the request session.
    """
    from flask import g
    from app.services.registration_service import join_waitlist as _join

    user_id = get_jwt_identity()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        # A bodyless POST is legitimate here — "put me on the general waitlist".
        # get_json() without silent=True would 400/415 it in Flask 3.
        data = request.form.to_dict() if request.form else {}

    user = g.db_session.query(User).get(user_id)
    payload, status = _join(g.db_session, user, league_type=data.get('league_type'))
    return jsonify(payload), status


@mobile_api_v2.route('/members/my-waitlist', methods=['GET'])
@jwt_required()
def my_waitlist():
    """Waitlist lane + position for the calling member. Doc §2.3."""
    user_id = get_jwt_identity()
    try:
        with managed_session() as db_session:
            user = db_session.query(User).get(user_id)
            if not user:
                return jsonify({'success': False, 'msg': 'User not found'}), 404
            return jsonify(_waitlist_payload(db_session, user)), 200
    except Exception as exc:
        logger.error(f"[MOBILE_API] my_waitlist failed for user {user_id}: {exc}", exc_info=True)
        return jsonify({'success': False, 'msg': 'Could not load waitlist status'}), 500


@mobile_api_v2.route('/members/my-status', methods=['GET'])
@jwt_required()
def my_status():
    """The member's own 360 across every axis. Doc §2.2."""
    user_id = get_jwt_identity()
    try:
        with managed_session() as db_session:
            user = db_session.query(User).get(user_id)
            if not user:
                return jsonify({'success': False, 'msg': 'User not found'}), 404

            player = db_session.query(Player).filter_by(user_id=user_id).first()

            memberships, payment = [], []
            if player:
                rows = (db_session.query(LeagueMembership)
                        .filter(LeagueMembership.player_id == player.id,
                                ~LeagueMembership.status.in_(_TERMINAL_STATUSES))
                        .all())
                for m in rows:
                    team = None
                    if m.team_id and m.team:
                        team = {'id': m.team.id, 'name': m.team.name}
                    memberships.append({
                        'league_type': m.league_type,
                        'role': m.role,
                        'status': m.status,
                        'team': team,
                        # Subs never pay — the doc pins `paid: false` for them
                        # rather than leaking a NULL paid_at as "unpaid player".
                        'paid': False if m.role == 'sub' else bool(m.paid_at),
                        'last_engaged_at': (m.last_engaged_at.isoformat()
                                            if m.last_engaged_at else None),
                        'needs_reconfirm': bool(m.needs_reconfirm),
                    })
                    if m.role != 'sub':
                        payment.append({
                            'league_type': m.league_type,
                            'pass': 'linked' if m.paid_at else 'none',
                        })

            waitlist = _waitlist_payload(db_session, user)

            return jsonify({
                'approval_status': (user.approval_status
                                    or ('approved' if user.is_approved else 'pending')),
                'season_phase': _season_phase(),
                'memberships': memberships,
                # Doc shape: null when not waiting, object when waiting.
                'waitlist': None if not waitlist.get('on_waitlist') else waitlist,
                'payment': payment,
            }), 200
    except Exception as exc:
        logger.error(f"[MOBILE_API] my_status failed for user {user_id}: {exc}", exc_info=True)
        return jsonify({'success': False, 'msg': 'Could not load member status'}), 500
