# app/mobile_api/members.py

"""
Mobile Member Lifecycle API

Implements the two endpoints promised by docs/flutter/member_lifecycle_api.md
(§2.2 and §2.3) that were documented but never built — a Flutter client coded
against that doc got 404s.

Both are read-only projections over the LeagueMembership spine plus the
User.waitlist_* columns. Nothing here writes; joining a waitlist is still
web-only (see the handoff doc).
"""

import logging

from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, LeagueMembership

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
