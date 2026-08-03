# app/mobile_api/admin_members.py

"""
Mobile Admin — Member Lifecycle

The 13 member-hub actions the portal had and mobile did not, so an admin no
longer has to open the website to clear a pending signup, place someone on a
team, or manage a sub pool.

Every handler is a thin shell: parse the body, resolve the JWT actor, call
``app/services/member_lifecycle_service.py``, jsonify. That service holds the
ONLY copy of each mutation — the web handlers in
``app/admin_panel/routes/user_management/`` call the same functions — so the two
surfaces cannot drift.

Gate: ``@jwt_required()`` + ``@jwt_role_required(ADMIN_ROLES)`` where ADMIN_ROLES
is exactly the web's ``['Global Admin', 'Pub League Admin']``. Deliberately NOT
the broader admin sets (Discord Admin / ECS FC Admin) — an app that offers an
action the server then rejects is worse than one that hides it.

⚠️ ``@transactional`` + ``db.session``, NOT ``managed_session()``. The shared
mutations run on ``db.session`` (see the service docstring); doing the work on
``g.db_session`` — which is what ``managed_session()`` yields inside a request —
would split the mutation across two transactions and silently drop half of it.
``@transactional`` commits both, which is exactly what the web routes rely on.

Bodies are read as JSON, falling back to form encoding, so the same handler
serves a Flutter client and a plain form post.
"""

import logging

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core import db
from app.core.session_manager import managed_session
from app.decorators import jwt_role_required
from app.utils.db_utils import transactional
from app.services import member_lifecycle_service as lifecycle

logger = logging.getLogger(__name__)

# Same set the web member hub enforces. jwt_role_required additionally lets
# Global Admin through unconditionally, matching role_required.
ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


def _body():
    """Request body as a dict, JSON or form.

    ``get_json()`` without ``silent=True`` raises 400/415 in Flask 3 BEFORE the
    ``or {}`` can run, which turns a bodyless confirm-button POST into an
    unexplained error.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


# Everything a form encoder can produce for "false". A form body carries only
# strings, and bare bool('false') is True -- so `active: false` would have WOKEN
# a resting sub and `is_coach: false` would have made someone a coach. JSON
# clients are unaffected; this makes both encodings mean the same thing.
_FALSY = {'false', '0', 'no', 'off', 'none', 'null', ''}


def _as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in _FALSY


def _actor():
    """(user_id, username) for the JWT caller — the service audits both."""
    from app.models import User
    actor_id = int(get_jwt_identity())
    user = db.session.query(User).get(actor_id)
    return actor_id, (user.username if user else str(actor_id))


# ==================== 1.1 Approval lifecycle ====================

@mobile_api_v2.route('/admin/members/<int:user_id>/approve', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_approve(user_id: int):
    """Approve a member into a league / sub pool, or park them on a waitlist lane.

    Body: {"league_type": "premier", "notes": ""} — league_type REQUIRED.
    Valid values come from GET /admin/members/options; do not hardcode them.
    """
    data = _body()
    actor_id, actor_username = _actor()
    # Raw values: the service coerces and validates them, so a JSON list/dict
    # where a string belongs comes back as a 400 rather than a 500 here.
    payload, status = lifecycle.approve_member(
        user_id=user_id,
        league_type=data.get('league_type'),
        actor_id=actor_id,
        actor_username=actor_username,
        notes=data.get('notes'),
    )
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/deny', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_deny(user_id: int):
    """Deny a pending application. Body: {"notes": ""}."""
    data = _body()
    actor_id, actor_username = _actor()
    payload, status = lifecycle.deny_member(
        user_id=user_id, actor_id=actor_id, actor_username=actor_username,
        notes=data.get('notes'),
    )
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/undeny', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_undeny(user_id: int):
    """Reverse a denial — back to the pending queue, not an approval.

    Body: {"notes": ""} (appended to the preserved denial reason).
    """
    data = _body()
    actor_id, actor_username = _actor()
    payload, status = lifecycle.undeny_member(
        user_id=user_id, actor_id=actor_id, actor_username=actor_username,
        notes=data.get('notes'),
    )
    return jsonify(payload), status


# ==================== 1.2 Account activation ====================

@mobile_api_v2.route('/admin/members/<int:user_id>/activate', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_activate(user_id: int):
    """Enable the account and mark the player active this season."""
    actor_id, _ = _actor()
    payload, status = lifecycle.set_member_activation(
        user_id=user_id, active=True, actor_id=actor_id,
        reason=(_body().get('reason') or None))
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/deactivate', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_deactivate(user_id: int):
    """Disable the account. Body: {"reason": ""} (recorded in the audit log)."""
    actor_id, _ = _actor()
    payload, status = lifecycle.set_member_activation(
        user_id=user_id, active=False, actor_id=actor_id,
        reason=(_body().get('reason') or None))
    return jsonify(payload), status


# ==================== 1.3 Team placement ====================

@mobile_api_v2.route('/admin/members/<int:user_id>/place', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_place(user_id: int):
    """Roster write: add to a team, remove from one, or set the primary team.

    Body: {"action": "add"|"remove"|"primary", "team_id": 42, "is_coach": false}

    This is the only way to move someone between teams outside a draft pick.
    """
    data = _body()
    actor_id, _ = _actor()
    payload, status = lifecycle.place_member(
        user_id=user_id,
        action=data.get('action'),
        team_id=data.get('team_id'),
        actor_id=actor_id,
        is_coach=_as_bool(data.get('is_coach'), False),
    )
    return jsonify(payload), status


# ==================== 1.4 Substitute pool admin ====================

# league_type accepts EITHER the League display name ('ECS FC') or the
# membership lane ('ecs_fc' / 'ecs-fc') — the web modal posts one, the program
# registry publishes the other. GET /admin/members/options lists both per lane.

@mobile_api_v2.route('/admin/members/<int:user_id>/sub-assign', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_sub_assign(user_id: int):
    """Add to a substitute pool. Body: {"league_type": "classic", "active": true}."""
    data = _body()
    actor_id, _ = _actor()
    payload, status = lifecycle.sub_assign(
        user_id=user_id, league_type=data.get('league_type'),
        actor_id=actor_id, active=_as_bool(data.get('active'), True))
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/sub-active', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_sub_active(user_id: int):
    """Rest or wake a sub. Body: {"league_type": "classic", "active": false}."""
    data = _body()
    actor_id, _ = _actor()
    payload, status = lifecycle.sub_set_active(
        user_id=user_id, league_type=data.get('league_type'),
        actor_id=actor_id, active=_as_bool(data.get('active'), True))
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/sub-remove', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_sub_remove(user_id: int):
    """Remove from a substitute pool. Body: {"league_type": "classic"}."""
    data = _body()
    actor_id, _ = _actor()
    payload, status = lifecycle.sub_remove(
        user_id=user_id, league_type=data.get('league_type'), actor_id=actor_id)
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/sub-reject', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_sub_reject(user_id: int):
    """Reject a PENDING sub-pool self-signup (approved_at IS NULL).

    Body: {"league_type": "classic"} — omit it to reject every pending signup.
    """
    data = _body()
    actor_id, _ = _actor()
    payload, status = lifecycle.sub_reject(
        user_id=user_id, league_type=data.get('league_type'), actor_id=actor_id)
    return jsonify(payload), status


# ==================== 1.5 Waitlist ====================

@mobile_api_v2.route('/admin/members/<int:user_id>/waitlist/priority', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_waitlist_priority(user_id: int):
    """Set manual waitlist priority.

    Body: {"priority": "high"|"medium"|"normal"|"auto"} — a VOCABULARY, not a
    rank number; 'auto' clears it and lets join time order the queue. The list
    is in GET /admin/members/options.
    """
    data = _body()
    actor_id, actor_username = _actor()
    # An ABSENT key means "no manual priority"; an explicitly empty/null one is
    # a client bug and gets a 400 naming the vocabulary.
    payload, status = lifecycle.set_waitlist_priority(
        user_id=user_id, priority=data.get('priority', 'auto'),
        actor_id=actor_id, actor_username=actor_username)
    return jsonify(payload), status


@mobile_api_v2.route('/admin/members/<int:user_id>/waitlist', methods=['DELETE'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_member_waitlist_remove(user_id: int):
    """Take someone off the waitlist. Body: {"reason": ""}.

    ``reason`` is also accepted as a query parameter, because some HTTP clients
    drop the body on DELETE.
    """
    reason = _body().get('reason') or request.args.get('reason') or 'No reason provided'
    actor_id, actor_username = _actor()
    payload, status = lifecycle.remove_member_from_waitlist(
        user_id=user_id, actor_id=actor_id, actor_username=actor_username,
        reason=reason)
    return jsonify(payload), status


# ==================== 1.6 Quick-profile pre-approval ====================

@mobile_api_v2.route('/admin/quick-profiles/<int:profile_id>/preapprove', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_quick_profile_preapprove(profile_id: int):
    """Pre-approve a quick profile so claiming the code auto-approves them.

    Body: {"league_type": "premier"} — "" clears the pre-approval.
    """
    data = _body()
    actor_id, _ = _actor()
    payload, status = lifecycle.preapprove_quick_profile(
        profile_id=profile_id, league_type=data.get('league_type'), actor_id=actor_id)
    return jsonify(payload), status


# ==================== 1.7 Worklist + vocabularies ====================

@mobile_api_v2.route('/admin/members', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_members_worklist():
    """The Members worklist, same criteria as the web page.

    Query: tab=all|pending|waitlist|subs|quick_profiles, search, role, league,
    team, approval, active, season, lane, sub_status, qp_status, page, per_page.

    Denied users are HIDDEN by default (opt in with approval=denied|all); the
    response reports ``hidden_denied`` so that default is never silent.
    ``per_page`` is capped server-side and the cap is stated in every response.
    """
    try:
        with managed_session() as session:
            payload, status = lifecycle.build_member_worklist(
                session, request.args,
                page=request.args.get('page', 1, type=int),
                per_page=request.args.get('per_page',
                                          lifecycle.WORKLIST_PER_PAGE_DEFAULT,
                                          type=int),
            )
        return jsonify(payload), status
    except Exception as exc:
        logger.error(f"[MOBILE_API] member worklist failed: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': 'Could not load members'}), 500


@mobile_api_v2.route('/admin/members/options', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_members_options():
    """Every vocabulary these endpoints validate against — so the app hardcodes none.

    Returns the approve/sub/waitlist league values (which genuinely differ from
    each other and from ``membership_lane`` in GET /programs), the waitlist
    priority words, the placement actions, and the worklist tabs + page cap.
    """
    try:
        with managed_session() as session:
            return jsonify({'success': True,
                            **lifecycle.describe_member_options(session)}), 200
    except Exception as exc:
        logger.error(f"[MOBILE_API] member options failed: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': 'Could not load options'}), 500
