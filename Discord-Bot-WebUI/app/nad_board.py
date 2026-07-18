# app/nad_board.py

"""
NAD Board — coach + admin facing page (NOT part of the admin panel).

The NAD board surfaces *approved* players in their first league season ("Newly
Acquired Drinkers") so coaches can pool scouting notes and place them fairly (the
3-NADs-per-team rule). Pub League coaches rotate often and are NOT admins, so this
lives in the normal player shell with no admin chrome or "admin" wording — it's
just a sidebar link. Admins get the same page.

It's the web front-end onto the same data the mobile app reads via
GET /api/v1/admin/nad-board and the Discord /nads command — all three derive the
list from app.services.nad_board_service.compute_nad_board so they can't drift.

Notes reuse the shared PlayerAdminNote thread (the same notes the mobile Waiting
Room / player admin screens use), keyed by Player.id.
"""

import logging

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, g
from flask_login import login_required, current_user

from app.decorators import role_required
from app.utils.db_utils import transactional
from app.services.nad_board_service import compute_nad_board

logger = logging.getLogger(__name__)

nad_board_bp = Blueprint('nad_board', __name__)

# Pub League coaches + admins. Coaches are scoped to their division in the service.
NAD_ROLES = ['Global Admin', 'Pub League Admin', 'Pub League Coach']
# Photo edits are admin-only (coaches scout + take notes, they don't edit photos).
NAD_ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


def _labels_to_list(value):
    """Turn a '{Label,Label}' Postgres-array display string into a clean list."""
    if not value:
        return []
    s = str(value).strip()
    if s.startswith('{') and s.endswith('}'):
        s = s[1:-1]
    return [part.strip().strip('"') for part in s.split(',') if part.strip()]


# ==================== Main Board ====================

@nad_board_bp.route('/')
@login_required
@role_required(NAD_ROLES)
@transactional
def index():
    """NAD board — new players with photos, positions, and shared notes."""
    try:
        search = (request.args.get('search') or '').strip()
        season_id = request.args.get('season_id', type=int)

        result = compute_nad_board(
            g.db_session,
            season_id=season_id,
            search=search,
            limit=200,
            viewer_user_id=current_user.id,
        )

        for nad in result['nads']:
            nad['other_positions_list'] = _labels_to_list(nad.get('other_positions'))
            nad['positions_not_to_play_list'] = _labels_to_list(nad.get('positions_not_to_play'))

        nads = result['nads']
        assigned = sum(1 for n in nads if n.get('team_id'))
        stats = {
            'total': len(nads),
            'assigned': assigned,
            'unassigned': len(nads) - assigned,
        }

        return render_template(
            'nad_board/board_flowbite.html',
            nads=nads,
            stats=stats,
            season_name=result['season_name'],
            search=search,
            is_global_admin=current_user.has_role('Global Admin'),
            can_edit_photo=(current_user.has_role('Global Admin') or current_user.has_role('Pub League Admin')),
        )

    except Exception as e:
        logger.error(f"Error loading NAD board: {e}", exc_info=True)
        flash('Error loading the NAD board. Please try again.', 'error')
        return redirect(url_for('main.index'))


# ==================== Photo (admin only) ====================

@nad_board_bp.route('/players/<int:player_id>/photo', methods=['POST'])
@login_required
@role_required(NAD_ADMIN_ROLES)
@transactional
def update_photo(player_id: int):
    """Admin: set / change / update a NAD's profile photo.

    Accepts multipart form-data with a 'file' field, or JSON with
    'cropped_image_data'/'photo_base64' (data URL). Reuses the shared player
    photo service so the picture is the player's real profile picture everywhere.
    """
    from app.services.mobile.player_admin_service import PlayerAdminService

    content_type = request.content_type or ''
    if 'multipart/form-data' in content_type:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        allowed = {'png', 'jpg', 'jpeg', 'webp'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed:
            return jsonify({'success': False, 'message': 'Invalid file type. Allowed: png, jpg, jpeg, webp'}), 400
        import base64
        data = file.read()
        if len(data) > 5 * 1024 * 1024:
            return jsonify({'success': False, 'message': 'File too large. Maximum size: 5MB'}), 400
        mime = file.content_type or f'image/{ext}'
        image_data = f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"
    else:
        body = request.get_json() or {}
        image_data = body.get('cropped_image_data') or body.get('photo_base64')
        if not image_data:
            return jsonify({'success': False, 'message': 'Missing image data'}), 400

    service = PlayerAdminService(g.db_session)
    result = service.upload_player_profile_picture(
        player_id=player_id, uploader_id=current_user.id, image_data=image_data
    )
    if not result.success:
        status = 404 if result.error_code == 'PLAYER_NOT_FOUND' else 400
        return jsonify({'success': False, 'message': result.message}), status
    return jsonify({'success': True, 'profile_picture_url': result.data.get('profile_picture_url')}), 200


# ==================== Shared Notes (reuse PlayerAdminNote) ====================
# Delegate to the same PlayerAdminService the mobile API uses, so the scouting
# thread is one and the same across web, mobile, and the player admin screens.

@nad_board_bp.route('/players/<int:player_id>/notes', methods=['GET'])
@login_required
@role_required(NAD_ROLES)
@transactional
def get_notes(player_id: int):
    """List the shared scouting notes for a NAD."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    service = PlayerAdminService(g.db_session)
    result = service.get_player_admin_notes(player_id, limit=100, offset=0)
    if not result.success:
        return jsonify({'success': False, 'message': result.message}), 404
    return jsonify({'success': True, **result.data}), 200


@nad_board_bp.route('/players/<int:player_id>/notes', methods=['POST'])
@login_required
@role_required(NAD_ROLES)
@transactional
def create_note(player_id: int):
    """Add a shared scouting note to a NAD."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'Note content is required'}), 400

    service = PlayerAdminService(g.db_session)
    result = service.create_admin_note(player_id, current_user.id, content)
    if not result.success:
        status = 404 if result.error_code == 'PLAYER_NOT_FOUND' else 400
        return jsonify({'success': False, 'message': result.message}), status
    return jsonify({'success': True, **result.data}), 201


@nad_board_bp.route('/players/<int:player_id>/notes/<int:note_id>', methods=['PUT'])
@login_required
@role_required(NAD_ROLES)
@transactional
def update_note(player_id: int, note_id: int):
    """Edit a scouting note (own note, or any note for Global Admins)."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'Note content is required'}), 400

    service = PlayerAdminService(g.db_session)
    result = service.update_admin_note(
        note_id,
        current_user.id,
        content,
        allow_edit_others=current_user.has_role('Global Admin'),
        expected_player_id=player_id,
    )
    if not result.success:
        status = 404 if result.error_code == 'NOTE_NOT_FOUND' else 403
        return jsonify({'success': False, 'message': result.message}), status
    return jsonify({'success': True, **result.data}), 200


@nad_board_bp.route('/players/<int:player_id>/notes/<int:note_id>', methods=['DELETE'])
@login_required
@role_required(NAD_ROLES)
@transactional
def delete_note(player_id: int, note_id: int):
    """Delete a scouting note (own note, or any note for Global Admins)."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    service = PlayerAdminService(g.db_session)
    result = service.delete_admin_note(
        note_id,
        current_user.id,
        allow_delete_others=current_user.has_role('Global Admin'),
        expected_player_id=player_id,
    )
    if not result.success:
        status = 404 if result.error_code == 'NOTE_NOT_FOUND' else 403
        return jsonify({'success': False, 'message': result.message}), status
    return jsonify({'success': True, **result.data}), 200
