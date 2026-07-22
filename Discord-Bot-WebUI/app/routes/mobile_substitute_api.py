# app/routes/mobile_substitute_api.py

"""
Mobile Substitute Management API Routes

Slash-style canonical mobile endpoints for substitute management. The dash-style
legacy endpoints (`/substitute-pools/...`, `/substitute-requests/...`,
`/substitute-assignments`) were removed on 2026-04-30 — Flutter has been on the
slash-style paths exclusively for some time, and a codebase grep confirmed zero
internal callers.

The canonical create/respond/list endpoints for the mobile API live in
`app/mobile_api/substitutes.py` and `app/mobile_api/ecs_fc_matches.py`. This
module retains the assignment and pool-management endpoints below.
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.core import db
from app.decorators import jwt_role_required
from app.models import User
from app.models.substitutes import (
    SubstitutePool, SubstituteAssignment, EcsFcSubAssignment, log_pool_action
)
from app.utils.mobile_auth import api_key_required

logger = logging.getLogger(__name__)

mobile_substitute_api = Blueprint('mobile_substitute_api', __name__)


# =============================================================================
# ASSIGNMENT MANAGEMENT
# =============================================================================

# remove_substitute_assignment() REMOVED — dead route. It registered
# DELETE /api/v1/substitutes/assignments/<id>, but mobile_api_v2
# (app/mobile_api/substitutes.py:814::remove_assignment) registers first
# (blueprints.py:215 vs :219), so this never ran.


# =============================================================================
# POOL MANAGEMENT (Admin Only)
# =============================================================================

@mobile_substitute_api.route('/substitutes/pool/<league_type>/approve/<int:player_id>', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def approve_pool_member(league_type, player_id):
    """
    Approve a player for the substitute pool (Admin only).

    Path Parameters:
        league_type (str): League type
        player_id (int): Player ID

    Request Body:
        notes (str): Approval notes (optional)

    Returns:
        200: Player approved successfully
        400: Invalid data
        404: Player or pool entry not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}
        notes = data.get('notes', f'Approved for {league_type} substitute pool')

        with db.session() as session:
            pool_entry = session.query(SubstitutePool).filter_by(
                player_id=player_id,
                league_type=league_type,
                approved_at=None
            ).first()

            if not pool_entry:
                return jsonify({
                    'error': 'Pending pool entry not found for this player'
                }), 404

            pool_entry.approved_by = current_user_id
            pool_entry.approved_at = datetime.utcnow()
            pool_entry.is_active = True

            log_pool_action(
                player_id=player_id,
                league_id=pool_entry.league_id,
                action='APPROVED',
                notes=notes,
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session
            )

            # Phase-0 dual-write: mirror pool approval into the league_membership spine.
            try:
                from app.services.league_membership_sync import resync_player_memberships
                resync_player_memberships(session, player_id)
            except Exception as _lm_err:
                logger.warning(f"league_membership sync skipped for player {player_id}: {_lm_err}")

            session.commit()

            return jsonify({
                'success': True,
                'message': f'Player approved for {league_type} substitute pool'
            }), 200

    except Exception as e:
        logger.exception(f"Error approving pool member {player_id} for {league_type}: {e}")
        return jsonify({
            'error': 'Failed to approve pool member',
            'message': str(e)
        }), 500


@mobile_substitute_api.route('/substitutes/pool/<league_type>/remove/<int:player_id>', methods=['POST'])
@jwt_required()
@api_key_required
@jwt_role_required(['Global Admin', 'Pub League Admin'])
def remove_pool_member(league_type, player_id):
    """
    Remove a player from the substitute pool (Admin only).

    Path Parameters:
        league_type (str): League type
        player_id (int): Player ID

    Request Body:
        reason (str): Reason for removal

    Returns:
        200: Player removed successfully
        400: Invalid data
        404: Pool entry not found
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json() or {}
        reason = data.get('reason', 'Removed by admin')

        with db.session() as session:
            pool_entry = session.query(SubstitutePool).filter_by(
                player_id=player_id,
                league_type=league_type,
                is_active=True
            ).first()

            if not pool_entry:
                return jsonify({
                    'error': 'Active pool entry not found for this player'
                }), 404

            pool_entry.is_active = False
            pool_entry.last_active_at = datetime.utcnow()

            log_pool_action(
                player_id=player_id,
                league_id=pool_entry.league_id,
                action='REMOVED_BY_ADMIN',
                notes=reason,
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session
            )

            # Phase-0 dual-write: mirror pool removal into the league_membership spine.
            try:
                from app.services.league_membership_sync import resync_player_memberships
                resync_player_memberships(session, player_id)
            except Exception as _lm_err:
                logger.warning(f"league_membership sync skipped for player {player_id}: {_lm_err}")

            session.commit()

            return jsonify({
                'success': True,
                'message': f'Player removed from {league_type} substitute pool'
            }), 200

    except Exception as e:
        logger.exception(f"Error removing pool member {player_id} from {league_type}: {e}")
        return jsonify({
            'error': 'Failed to remove pool member',
            'message': str(e)
        }), 500


# Toggle a pool member's active state (active in pool <-> approved on break).
# Distinct from approve/remove: leaves is_approved/approved_at untouched and
# only flips is_active, so the player remains visible in the pool listing
# either way. Mirrors the Flutter "Mark on-break" / "Activate" buttons.
@mobile_substitute_api.route('/substitutes/pool/<league_type>/<int:player_id>', methods=['PATCH'])
@jwt_required()
@api_key_required
def toggle_pool_member_active(league_type, player_id):
    """
    Toggle the is_active flag on a SubstitutePool entry.

    Auth: admin only (Global Admin / Pub League Admin) for any league_type;
    ECS FC Coaches are additionally allowed when league_type == 'ECS FC'.

    Body:
        is_active (bool, required): new value for SubstitutePool.is_active

    Response: {success: true, msg: "...", member: {is_active, is_approved, approved_at}}
    """
    try:
        current_user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        if 'is_active' not in data or not isinstance(data['is_active'], bool):
            return jsonify({"msg": "is_active (boolean) is required"}), 400
        new_active = bool(data['is_active'])

        with db.session() as session:
            user = session.query(User).options(
                joinedload(User.roles)
            ).filter(User.id == current_user_id).first()
            if not user:
                return jsonify({"msg": "User not found"}), 404
            user_roles = {r.name for r in user.roles}
            is_admin = bool({'Global Admin', 'Pub League Admin', 'Admin'} & user_roles)
            is_ecs_fc_coach = 'ECS FC Coach' in user_roles
            if not (is_admin or (is_ecs_fc_coach and league_type == 'ECS FC')):
                return jsonify({
                    "msg": "Access denied: admin role required (or ECS FC Coach for the ECS FC pool)"
                }), 403

            pool_entry = session.query(SubstitutePool).filter_by(
                player_id=player_id,
                league_type=league_type,
            ).first()
            if not pool_entry:
                return jsonify({"msg": "Pool entry not found for this player and league_type"}), 404

            if pool_entry.is_active == new_active:
                return jsonify({
                    "success": True,
                    "msg": "No change",
                    "member": {
                        "is_active": pool_entry.is_active,
                        "is_approved": pool_entry.approved_at is not None,
                        "approved_at": pool_entry.approved_at.isoformat() if pool_entry.approved_at else None,
                    },
                }), 200

            pool_entry.is_active = new_active
            if new_active:
                pool_entry.last_active_at = datetime.utcnow()

            log_pool_action(
                player_id=player_id,
                league_id=pool_entry.league_id,
                action='ACTIVATED' if new_active else 'MARKED_ON_BREAK',
                notes=f"is_active toggled to {new_active} via mobile",
                performed_by=current_user_id,
                pool_id=pool_entry.id,
                session=session,
            )

            # Phase-0 dual-write: mirror the active/rest toggle into the league_membership spine.
            try:
                from app.services.league_membership_sync import resync_player_memberships
                resync_player_memberships(session, player_id)
            except Exception as _lm_err:
                logger.warning(f"league_membership sync skipped for player {player_id}: {_lm_err}")

            session.commit()

            return jsonify({
                "success": True,
                "msg": "Pool member activated" if new_active else "Pool member marked on break",
                "member": {
                    "is_active": pool_entry.is_active,
                    "is_approved": pool_entry.approved_at is not None,
                    "approved_at": pool_entry.approved_at.isoformat() if pool_entry.approved_at else None,
                },
            }), 200

    except Exception as e:
        logger.exception(
            "Error toggling pool member %s for %s: %s", player_id, league_type, e
        )
        return jsonify({
            "msg": "Failed to toggle pool member active state"
        }), 500
