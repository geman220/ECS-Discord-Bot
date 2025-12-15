# app/mobile_api/admin.py

"""
Mobile API Admin Endpoints

Provides admin management functionality for mobile clients:
- View and manage user roles
- View and manage league memberships
- Discord role synchronization

All endpoints require Pub League Admin or Global Admin role.
All endpoints use player_id (not user_id) for easier mobile app integration.
"""

import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models.admin_config import AdminAuditLog
from app.services.mobile.admin_service import MobileAdminService

logger = logging.getLogger(__name__)

# Admin roles allowed to access these endpoints
ADMIN_ROLES = ['Pub League Admin', 'Global Admin']


# ==================== Role Management ====================

@mobile_api_v2.route('/admin/players/<int:player_id>/roles', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def get_player_roles(player_id: int):
    """
    Get a player's current roles and list of assignable roles.

    Args:
        player_id: Player ID

    Returns:
        JSON with player's roles and assignable roles
    """
    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.get_player_roles(player_id)

        if not result.success:
            return jsonify({"msg": result.message}), 404

        return jsonify(result.data), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/roles', methods=['PUT'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def update_player_roles(player_id: int):
    """
    Add or remove roles from a player.

    Args:
        player_id: Player ID

    Expected JSON:
        add: List of role IDs to add (optional)
        remove: List of role IDs to remove (optional)

    Returns:
        JSON with updated roles and Discord sync status
    """
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    add_role_ids = data.get('add', [])
    remove_role_ids = data.get('remove', [])

    if not isinstance(add_role_ids, list) or not isinstance(remove_role_ids, list):
        return jsonify({"msg": "add and remove must be arrays"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.update_player_roles(
            player_id=player_id,
            add_role_ids=add_role_ids,
            remove_role_ids=remove_role_ids
        )

        if not result.success:
            status_code = 400
            if result.error_code == "PLAYER_NOT_FOUND":
                status_code = 404
            elif result.error_code == "NO_USER_ACCOUNT":
                status_code = 404
            elif result.error_code == "ROLE_NOT_FOUND":
                status_code = 404
            elif result.error_code == "PROTECTED_ROLE":
                status_code = 403
            return jsonify({"msg": result.message}), status_code

        # Log audit trail
        _log_role_change(
            session=session,
            admin_user_id=current_user_id,
            target_player_id=player_id,
            added=result.data.get('added', []),
            removed=result.data.get('removed', [])
        )

        return jsonify({
            "success": True,
            "message": f"Roles updated for {result.data['player_name']}",
            **result.data
        }), 200


@mobile_api_v2.route('/admin/roles', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def get_assignable_roles():
    """
    Get list of all roles that can be assigned via mobile API.

    Returns:
        JSON with list of assignable roles
    """
    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.get_assignable_roles()

        return jsonify({
            "roles": result.data
        }), 200


# ==================== League Management ====================

@mobile_api_v2.route('/admin/players/<int:player_id>/leagues', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def get_player_leagues(player_id: int):
    """
    Get a player's current league memberships.

    Args:
        player_id: Player ID

    Returns:
        JSON with player's league memberships
    """
    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.get_player_leagues(player_id)

        if not result.success:
            status_code = 404 if result.error_code == "PLAYER_NOT_FOUND" else 400
            return jsonify({"msg": result.message}), status_code

        return jsonify(result.data), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/leagues', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def add_player_to_league(player_id: int):
    """
    Add a player to a league.

    Args:
        player_id: Player ID

    Expected JSON:
        league_id: ID of the league to add player to

    Returns:
        JSON with result and any auto-assigned role
    """
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    league_id = data.get('league_id')
    if not league_id:
        return jsonify({"msg": "league_id is required"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.add_player_to_league(
            player_id=player_id,
            league_id=league_id
        )

        if not result.success:
            status_code = 400
            if result.error_code in ["PLAYER_NOT_FOUND", "LEAGUE_NOT_FOUND", "NO_USER_ACCOUNT"]:
                status_code = 404
            elif result.error_code == "ALREADY_IN_LEAGUE":
                status_code = 409
            return jsonify({"msg": result.message}), status_code

        # Log audit trail
        _log_league_change(
            session=session,
            admin_user_id=current_user_id,
            target_player_id=player_id,
            action='add_to_league',
            league_name=result.data['league_name']
        )

        return jsonify({
            "success": True,
            "message": f"Added to {result.data['league_name']}",
            **result.data
        }), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/leagues/<int:league_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def remove_player_from_league(player_id: int, league_id: int):
    """
    Remove a player from a league.

    Args:
        player_id: Player ID
        league_id: League ID

    Returns:
        JSON with result and any removed role
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.remove_player_from_league(
            player_id=player_id,
            league_id=league_id
        )

        if not result.success:
            status_code = 400
            if result.error_code in ["PLAYER_NOT_FOUND", "LEAGUE_NOT_FOUND", "NO_USER_ACCOUNT"]:
                status_code = 404
            elif result.error_code == "NOT_IN_LEAGUE":
                status_code = 404
            return jsonify({"msg": result.message}), status_code

        # Log audit trail
        _log_league_change(
            session=session,
            admin_user_id=current_user_id,
            target_player_id=player_id,
            action='remove_from_league',
            league_name=result.data['league_name']
        )

        return jsonify({
            "success": True,
            "message": f"Removed from {result.data['league_name']}",
            **result.data
        }), 200


@mobile_api_v2.route('/admin/leagues', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def get_available_leagues():
    """
    Get list of current season leagues available for assignment.

    Returns:
        JSON with list of available leagues
    """
    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.get_available_leagues()

        return jsonify({
            "leagues": result.data
        }), 200


# ==================== Audit Logging Helpers ====================

def _log_role_change(
    session,
    admin_user_id: int,
    target_player_id: int,
    added: list,
    removed: list
) -> None:
    """Log role changes to audit log."""
    try:
        changes = []
        if added:
            changes.append(f"added: {', '.join(added)}")
        if removed:
            changes.append(f"removed: {', '.join(removed)}")

        if changes:
            AdminAuditLog.log_action(
                user_id=admin_user_id,
                action='update_roles',
                resource_type='player_management',
                resource_id=str(target_player_id),
                new_value='; '.join(changes),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
    except Exception as e:
        logger.error(f"Failed to log role change audit: {e}")


def _log_league_change(
    session,
    admin_user_id: int,
    target_player_id: int,
    action: str,
    league_name: str
) -> None:
    """Log league membership changes to audit log."""
    try:
        AdminAuditLog.log_action(
            user_id=admin_user_id,
            action=action,
            resource_type='player_management',
            resource_id=str(target_player_id),
            new_value=league_name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
    except Exception as e:
        logger.error(f"Failed to log league change audit: {e}")
