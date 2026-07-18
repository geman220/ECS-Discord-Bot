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


@mobile_api_v2.route('/admin/players/<int:player_id>/teams/<int:team_id>/coach', methods=['PUT'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def set_team_coach_status(player_id: int, team_id: int):
    """
    Set (team-scoped) coach status for a player on ONE team.

    This is the precise, per-team coach control — the mobile equivalent of the
    web edit-user modal's coach picker. Use this (not a role assignment) so the
    division-scoped Discord coach role (…-PREMIER-COACH / …-CLASSIC-COACH) is
    driven by the exact team coached, including the play-one-division /
    coach-another edge case.

    Args:
        player_id: Player ID
        team_id: The team the coach flag applies to

    Expected JSON:
        is_coach: bool — true to make coach of this team, false to remove

    Returns:
        JSON with the updated per-team + player-level coach state
    """
    data = request.get_json()
    if not data or 'is_coach' not in data:
        return jsonify({"msg": "Missing 'is_coach' boolean"}), 400

    is_coach = data.get('is_coach')
    if not isinstance(is_coach, bool):
        return jsonify({"msg": "'is_coach' must be a boolean"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        service = MobileAdminService(session)
        result = service.set_team_coach_status(
            player_id=player_id,
            team_id=team_id,
            is_coach=is_coach
        )

        if not result.success:
            status_code = 400
            if result.error_code in ("PLAYER_NOT_FOUND", "NO_USER_ACCOUNT", "PLAYER_NOT_ON_TEAM"):
                status_code = 404
            return jsonify({"msg": result.message}), status_code

        _log_role_change(
            session=session,
            admin_user_id=current_user_id,
            target_player_id=player_id,
            added=['coach:%s' % team_id] if is_coach else [],
            removed=[] if is_coach else ['coach:%s' % team_id]
        )

        return jsonify({
            "success": True,
            "message": "Coach status updated",
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


# ==================== Admin Notes Management ====================

# Roles allowed to manage admin notes (admins and coaches)
NOTES_ALLOWED_ROLES = ['Pub League Admin', 'Global Admin', 'Pub League Coach']


@mobile_api_v2.route('/admin/players/<int:player_id>/notes', methods=['GET'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def get_player_admin_notes(player_id: int):
    """
    Get admin notes for a player.

    Args:
        player_id: Player ID

    Query parameters:
        limit: Maximum notes to return (default: 50, max: 100)
        offset: Pagination offset (default: 0)

    Returns:
        JSON with list of admin notes with author attribution
    """
    limit = min(request.args.get('limit', 50, type=int), 100)
    offset = request.args.get('offset', 0, type=int)

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.get_player_admin_notes(player_id, limit=limit, offset=offset)

        if not result.success:
            return jsonify({"msg": result.message}), 404

        return jsonify(result.data), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/notes', methods=['POST'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def create_player_admin_note(player_id: int):
    """
    Create a new admin note for a player.

    Args:
        player_id: Player ID

    Expected JSON:
        content: The note content (required)

    Returns:
        JSON with the created note including author attribution
    """
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    content = data.get('content')
    if not content or not content.strip():
        return jsonify({"msg": "Note content is required"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.create_admin_note(
            player_id=player_id,
            author_id=current_user_id,
            content=content
        )

        if not result.success:
            status_code = 404 if result.error_code == "PLAYER_NOT_FOUND" else 400
            return jsonify({"msg": result.message}), status_code

        # Log audit trail
        _log_admin_note_action(
            session=session,
            admin_user_id=current_user_id,
            target_player_id=player_id,
            action='create_admin_note'
        )

        return jsonify({
            "success": True,
            "message": "Note created successfully",
            **result.data
        }), 201


@mobile_api_v2.route('/admin/players/<int:player_id>/notes/<int:note_id>', methods=['PUT'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def update_player_admin_note(player_id: int, note_id: int):
    """
    Update an existing admin note.

    Args:
        player_id: Player ID (for URL consistency)
        note_id: Note ID

    Expected JSON:
        content: The new note content (required)

    Returns:
        JSON with the updated note

    Note: Users can only edit their own notes unless they are a Global Admin.
    """
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    content = data.get('content')
    if not content or not content.strip():
        return jsonify({"msg": "Note content is required"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Check if user is a Global Admin (can edit any note)
        from app.models import User
        user = session.query(User).get(current_user_id)
        is_global_admin = any(role.name == 'Global Admin' for role in user.roles) if user else False

        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.update_admin_note(
            note_id=note_id,
            editor_id=current_user_id,
            content=content,
            allow_edit_others=is_global_admin,
            expected_player_id=player_id
        )

        if not result.success:
            status_code = 404 if result.error_code == "NOTE_NOT_FOUND" else 403
            return jsonify({"msg": result.message}), status_code

        return jsonify({
            "success": True,
            "message": "Note updated successfully",
            **result.data
        }), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/notes/<int:note_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def delete_player_admin_note(player_id: int, note_id: int):
    """
    Delete an admin note.

    Args:
        player_id: Player ID (for URL consistency)
        note_id: Note ID

    Returns:
        JSON with deletion confirmation

    Note: Users can only delete their own notes unless they are a Global Admin.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Check if user is a Global Admin (can delete any note)
        from app.models import User
        user = session.query(User).get(current_user_id)
        is_global_admin = any(role.name == 'Global Admin' for role in user.roles) if user else False

        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.delete_admin_note(
            note_id=note_id,
            deleter_id=current_user_id,
            allow_delete_others=is_global_admin,
            expected_player_id=player_id
        )

        if not result.success:
            status_code = 404 if result.error_code == "NOTE_NOT_FOUND" else 403
            return jsonify({"msg": result.message}), status_code

        # Log audit trail
        _log_admin_note_action(
            session=session,
            admin_user_id=current_user_id,
            target_player_id=player_id,
            action='delete_admin_note'
        )

        return jsonify({
            "success": True,
            "message": "Note deleted successfully",
            **result.data
        }), 200


# ==================== Waiting Room (not-yet-approved prospects) ====================
# One pool, two intakes: self-signup users pending approval, and admin-made quick
# profiles. Coaches + admins browse it and leave fit notes; they cannot approve/deny.

@mobile_api_v2.route('/admin/waiting-room', methods=['GET'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def get_waiting_room():
    """
    List every not-yet-approved prospect (self-signups pending approval + pending
    quick profiles), league-wide, with photo/info and a note count. Read-only for
    coaches — this endpoint never approves/denies.

    Query params:
        limit: max items per intake (default 100, max 200)
        search: case-insensitive name filter

    Returns:
        JSON: { success, total, prospects: [ {type, id, name, ...notes_endpoint} ] }
    """
    from datetime import datetime
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload
    from app.models import User, Player
    from app.models.players import PlayerAdminNote
    from app.models.quick_profile import QuickProfile, QuickProfileStatus

    limit = min(request.args.get('limit', 100, type=int), 200)
    search = (request.args.get('search') or '').strip()

    with managed_session() as session:
        # --- self-signup prospects: users pending approval (with a player row) ---
        players_q = session.query(Player).join(User, Player.user_id == User.id).filter(
            User.approval_status == 'pending'
        )
        if search:
            players_q = players_q.filter(Player.name.ilike(f'%{search}%'))
        players_q = players_q.options(joinedload(Player.user)).order_by(Player.id.desc()).limit(limit)
        pending_players = players_q.all()

        # --- admin-made prospects: pending, non-expired quick profiles ---
        qps_q = session.query(QuickProfile).filter(
            QuickProfile.status == QuickProfileStatus.PENDING.value,
            QuickProfile.expires_at > datetime.utcnow()
        )
        if search:
            qps_q = qps_q.filter(QuickProfile.player_name.ilike(f'%{search}%'))
        qps_q = qps_q.order_by(QuickProfile.created_at.desc()).limit(limit)
        pending_qps = qps_q.all()

        # Note counts in two grouped queries (no N+1).
        player_ids = [p.id for p in pending_players]
        qp_ids = [q.id for q in pending_qps]
        player_counts = dict(
            session.query(PlayerAdminNote.player_id, func.count(PlayerAdminNote.id))
            .filter(PlayerAdminNote.player_id.in_(player_ids))
            .group_by(PlayerAdminNote.player_id).all()
        ) if player_ids else {}
        qp_counts = dict(
            session.query(PlayerAdminNote.quick_profile_id, func.count(PlayerAdminNote.id))
            .filter(PlayerAdminNote.quick_profile_id.in_(qp_ids))
            .group_by(PlayerAdminNote.quick_profile_id).all()
        ) if qp_ids else {}

        prospects = []
        for p in pending_players:
            prospects.append({
                'type': 'player',
                'id': p.id,                     # use with /admin/players/<id>/notes
                'user_id': p.user_id,
                'name': p.name,
                'profile_picture_url': p.profile_picture_url,
                'pronouns': p.pronouns,
                'jersey_size': p.jersey_size,
                'intake': 'self_signup',
                'note_count': player_counts.get(p.id, 0),
                'created_at': p.user.created_at.isoformat() if p.user and p.user.created_at else None,
                'notes_endpoint': f'/api/v1/admin/players/{p.id}/notes',
            })
        for q in pending_qps:
            prospects.append({
                'type': 'quick_profile',
                'id': q.id,                     # use with /admin/quick-profiles/<id>/notes
                'user_id': None,
                'name': q.player_name,
                'profile_picture_url': q.profile_picture_url,
                'pronouns': q.pronouns,
                'jersey_size': q.jersey_size,
                'intake': 'admin_quick_profile',
                'note_count': qp_counts.get(q.id, 0),
                'created_at': q.created_at.isoformat() if q.created_at else None,
                'notes_endpoint': f'/api/v1/admin/quick-profiles/{q.id}/notes',
            })

        # Newest first across both intakes (None dates sort last).
        prospects.sort(key=lambda x: x['created_at'] or '', reverse=True)

        return jsonify({
            'success': True,
            'total': len(prospects),
            'prospects': prospects
        }), 200


# ==================== NAD Board (Newly Acquired Drinkers) ====================
# NADs are *approved* players in their FIRST league season. Unlike the waiting
# room (which asks "do we let them in?"), the NAD board asks "who is this new
# player and how do we place them fairly?" — so coaches + admins pool scouting
# notes to support the 3-NADs-per-team rule. NADs already have a Player row, so
# notes/photo/profile edits reuse the existing /admin/players/<id>/... endpoints.

@mobile_api_v2.route('/admin/nad-board', methods=['GET'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def get_nad_board():
    """
    List NADs (approved players in their first league season) with positions
    inline (allocation is all about positions, so we return them so the client
    doesn't fan out N /players/<id> calls) and a shared-notes count.

    Derivation + visibility scoping live in app.services.nad_board_service so the
    mobile app, the admin-panel web board, and the Discord /nads command can never
    drift. Admins see every NAD; coaches see the shared pre-draft pool (unassigned
    NADs) plus NADs assigned to a team in a league they coach.

    Query params:
        search: case-insensitive name filter
        limit: max items (default 100, max 200)
        season_id: target season (default = current Pub League season)

    Returns:
        JSON: { success, total, season_id, season_name, team_nad_counts, nads: [...] }
    """
    from app.services.nad_board_service import compute_nad_board

    limit = min(request.args.get('limit', 100, type=int), 200)
    search = (request.args.get('search') or '').strip()
    season_id_param = request.args.get('season_id', type=int)
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        result = compute_nad_board(
            session,
            season_id=season_id_param,
            search=search,
            limit=limit,
            viewer_user_id=current_user_id,
        )
        return jsonify({
            'success': True,
            'total': len(result['nads']),
            'season_id': result['season_id'],
            'season_name': result['season_name'],
            'team_nad_counts': result['team_nad_counts'],
            'nads': result['nads'],
        }), 200


# ==================== Quick Profile (waiting-room) Notes ====================
# Same note system as players; the quick profile is just the other intake. Coaches
# can add + edit/delete their OWN notes; Global Admins can edit/delete any.

@mobile_api_v2.route('/admin/quick-profiles/<int:quick_profile_id>/notes', methods=['GET'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def get_quick_profile_notes(quick_profile_id: int):
    """Get waiting-room notes for a quick profile."""
    limit = min(request.args.get('limit', 50, type=int), 100)
    offset = request.args.get('offset', 0, type=int)

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.get_quick_profile_notes(quick_profile_id, limit=limit, offset=offset)

        if not result.success:
            return jsonify({"msg": result.message}), 404

        return jsonify(result.data), 200


@mobile_api_v2.route('/admin/quick-profiles/<int:quick_profile_id>/notes', methods=['POST'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def create_quick_profile_note(quick_profile_id: int):
    """Create a waiting-room note on a quick profile."""
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    content = data.get('content')
    if not content or not content.strip():
        return jsonify({"msg": "Note content is required"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.create_quick_profile_note(
            quick_profile_id=quick_profile_id,
            author_id=current_user_id,
            content=content
        )

        if not result.success:
            status_code = 404 if result.error_code == "QUICK_PROFILE_NOT_FOUND" else 400
            return jsonify({"msg": result.message}), status_code

        return jsonify({
            "success": True,
            "message": "Note created successfully",
            **result.data
        }), 201


@mobile_api_v2.route('/admin/quick-profiles/<int:quick_profile_id>/notes/<int:note_id>', methods=['PUT'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def update_quick_profile_note(quick_profile_id: int, note_id: int):
    """Update a waiting-room note (own note, or any if Global Admin)."""
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    content = data.get('content')
    if not content or not content.strip():
        return jsonify({"msg": "Note content is required"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        from app.models import User
        user = session.query(User).get(current_user_id)
        is_global_admin = any(role.name == 'Global Admin' for role in user.roles) if user else False

        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        # Shared, target-agnostic (operates by note_id); scoped to this quick
        # profile so a note reached through the wrong URL 404s.
        result = service.update_admin_note(
            note_id=note_id,
            editor_id=current_user_id,
            content=content,
            allow_edit_others=is_global_admin,
            expected_quick_profile_id=quick_profile_id
        )

        if not result.success:
            status_code = 404 if result.error_code == "NOTE_NOT_FOUND" else 403
            return jsonify({"msg": result.message}), status_code

        return jsonify({
            "success": True,
            "message": "Note updated successfully",
            **result.data
        }), 200


@mobile_api_v2.route('/admin/quick-profiles/<int:quick_profile_id>/notes/<int:note_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def delete_quick_profile_note(quick_profile_id: int, note_id: int):
    """Delete a waiting-room note (own note, or any if Global Admin)."""
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        from app.models import User
        user = session.query(User).get(current_user_id)
        is_global_admin = any(role.name == 'Global Admin' for role in user.roles) if user else False

        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.delete_admin_note(
            note_id=note_id,
            deleter_id=current_user_id,
            allow_delete_others=is_global_admin,
            expected_quick_profile_id=quick_profile_id
        )

        if not result.success:
            status_code = 404 if result.error_code == "NOTE_NOT_FOUND" else 403
            return jsonify({"msg": result.message}), status_code

        return jsonify({
            "success": True,
            "message": "Note deleted successfully",
            **result.data
        }), 200


# ==================== Player Profile Management ====================

@mobile_api_v2.route('/admin/players/<int:player_id>/profile', methods=['GET'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def get_player_full_profile(player_id: int):
    """
    Get full player profile including admin-only fields.

    Args:
        player_id: Player ID

    Returns:
        JSON with complete player profile data including:
        - All profile fields
        - Admin-specific fields (is_coach, is_ref, discord info)
        - Recent admin notes
        - User account info
    """
    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.get_player_full_profile(player_id)

        if not result.success:
            return jsonify({"msg": result.message}), 404

        return jsonify(result.data), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/profile', methods=['PUT'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def update_player_profile_admin(player_id: int):
    """
    Update a player's profile (admin/coach operation).

    Args:
        player_id: Player ID

    Expected JSON (all fields optional):
        name: Player name
        phone: Phone number
        jersey_size: Jersey size
        jersey_number: Jersey number
        pronouns: Preferred pronouns
        date_of_birth: ISO date string (YYYY-MM-DD); used for iSpy age gate
        ispy_opt_out: Boolean - hides player from iSpy targeting when true
        favorite_position: Favorite playing position
        other_positions: Other positions (comma-separated)
        positions_not_to_play: Positions to avoid
        frequency_play_goal: Goal frequency preference
        expected_weeks_available: Expected availability
        unavailable_dates: Dates unavailable
        willing_to_referee: Referee willingness
        additional_info: Additional information
        player_notes: Player's own notes
        is_coach: Boolean - is this player a coach
        is_ref: Boolean - is this player a referee
        is_current_player: Boolean - is this a current player

    Returns:
        JSON with updated player data and list of changed fields
    """
    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.update_player_profile(
            player_id=player_id,
            editor_id=current_user_id,
            data=data
        )

        if not result.success:
            return jsonify({"msg": result.message}), 404

        # Log audit trail if fields were updated
        if result.data.get('updated_fields'):
            _log_profile_update(
                session=session,
                admin_user_id=current_user_id,
                target_player_id=player_id,
                updated_fields=result.data['updated_fields']
            )

        return jsonify({
            "success": True,
            "message": "Profile updated successfully",
            **result.data
        }), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/profile-picture', methods=['POST'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def upload_player_profile_picture_admin(player_id: int):
    """
    Upload a profile picture for a player (admin/coach operation).

    Args:
        player_id: Player ID

    Supports two formats:
    1. Base64 JSON: {"cropped_image_data": "data:image/png;base64,..."}
    2. Multipart form data with 'file' field

    Returns:
        JSON with new profile picture URL
    """
    current_user_id = int(get_jwt_identity())

    # Get image data based on content type
    content_type = request.content_type or ''

    if 'multipart/form-data' in content_type:
        if 'file' not in request.files:
            return jsonify({"msg": "No file provided"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"msg": "No file selected"}), 400

        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if file_ext not in allowed_extensions:
            return jsonify({
                "msg": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            }), 400

        # Read and convert to base64
        import base64
        file_data = file.read()

        # Check file size (5MB limit)
        max_size = 5 * 1024 * 1024
        if len(file_data) > max_size:
            return jsonify({"msg": "File too large. Maximum size: 5MB"}), 400

        mime_type = file.content_type or f'image/{file_ext}'
        base64_data = base64.b64encode(file_data).decode('utf-8')
        image_data = f"data:{mime_type};base64,{base64_data}"
    else:
        data = request.get_json()
        if not data:
            return jsonify({"msg": "Missing request data"}), 400

        image_data = data.get('cropped_image_data')
        if not image_data:
            return jsonify({"msg": "Missing cropped_image_data"}), 400

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.upload_player_profile_picture(
            player_id=player_id,
            uploader_id=current_user_id,
            image_data=image_data
        )

        if not result.success:
            status_code = 404 if result.error_code == "PLAYER_NOT_FOUND" else 400
            return jsonify({"msg": result.message}), status_code

        # Build full URL for response
        base_url = request.host_url.rstrip('/')
        profile_url = result.data.get('profile_picture_url', '')
        full_url = (
            profile_url if profile_url.startswith('http')
            else f"{base_url}{profile_url}"
        )

        return jsonify({
            "success": True,
            "message": "Profile picture updated successfully",
            "player_id": result.data['player_id'],
            "player_name": result.data['player_name'],
            "profile_picture_url": full_url
        }), 200


@mobile_api_v2.route('/admin/players/<int:player_id>/profile-picture', methods=['DELETE'])
@jwt_required()
@jwt_role_required(NOTES_ALLOWED_ROLES)
def delete_player_profile_picture_admin(player_id: int):
    """
    Delete a player's profile picture (admin/coach operation).

    Args:
        player_id: Player ID

    Returns:
        JSON with confirmation and default image URL
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        from app.services.mobile.player_admin_service import PlayerAdminService
        service = PlayerAdminService(session)
        result = service.delete_player_profile_picture(
            player_id=player_id,
            deleter_id=current_user_id
        )

        if not result.success:
            status_code = 404 if result.error_code in ["PLAYER_NOT_FOUND", "NO_PICTURE"] else 400
            return jsonify({"msg": result.message}), status_code

        base_url = request.host_url.rstrip('/')
        return jsonify({
            "success": True,
            "message": "Profile picture deleted successfully",
            "player_id": result.data['player_id'],
            "player_name": result.data['player_name'],
            "profile_picture_url": f"{base_url}/static/img/default_player.png"
        }), 200


# ==================== Additional Audit Logging Helpers ====================

def _log_admin_note_action(
    session,
    admin_user_id: int,
    target_player_id: int,
    action: str
) -> None:
    """Log admin note actions to audit log."""
    try:
        AdminAuditLog.log_action(
            user_id=admin_user_id,
            action=action,
            resource_type='player_admin_notes',
            resource_id=str(target_player_id),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
    except Exception as e:
        logger.error(f"Failed to log admin note audit: {e}")


def _log_profile_update(
    session,
    admin_user_id: int,
    target_player_id: int,
    updated_fields: list
) -> None:
    """Log profile update actions to audit log."""
    try:
        AdminAuditLog.log_action(
            user_id=admin_user_id,
            action='admin_update_profile',
            resource_type='player_management',
            resource_id=str(target_player_id),
            new_value=f"Updated fields: {', '.join(updated_fields)}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
    except Exception as e:
        logger.error(f"Failed to log profile update audit: {e}")
