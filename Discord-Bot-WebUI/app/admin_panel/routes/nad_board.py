# app/admin_panel/routes/nad_board.py

"""
Admin Panel NAD Board Routes

The NAD board surfaces *approved* players in their first league season ("Newly
Acquired Drinkers") so coaches + admins can pool scouting notes and place them
fairly (the 3-NADs-per-team rule). It is the web front-end onto the same data
the mobile app reads via GET /api/v1/admin/nad-board — both derive the list from
app.services.nad_board_service.compute_nad_board so they can't drift.

Notes here reuse the shared PlayerAdminNote thread (the very same notes shown in
the mobile Waiting Room / player admin screens), keyed by Player.id.
"""

import logging

from flask import render_template, request, jsonify, flash, redirect, url_for, g
from flask_login import login_required, current_user

from .. import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.services.nad_board_service import compute_nad_board

logger = logging.getLogger(__name__)

# Admins + coaches: coaches scope to their division inside compute_nad_board().
NAD_ROLES = ['Pub League Admin', 'Global Admin', 'Pub League Coach']


def _labels_to_list(value):
    """Turn a '{Label,Label}' Postgres-array display string into a clean list."""
    if not value:
        return []
    s = str(value).strip()
    if s.startswith('{') and s.endswith('}'):
        s = s[1:-1]
    return [part.strip().strip('"') for part in s.split(',') if part.strip()]


# ==================== Main Board ====================

@admin_panel_bp.route('/nad-board')
@login_required
@role_required(NAD_ROLES)
@transactional
def nad_board():
    """NAD board dashboard — new players with photos, positions, and shared notes."""
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

        # Normalize the {Label,Label} position strings into lists for the template.
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
            'admin_panel/nad_board/board_flowbite.html',
            nads=nads,
            stats=stats,
            season_name=result['season_name'],
            season_id=result['season_id'],
            team_nad_counts=result['team_nad_counts'],
            search=search,
            is_global_admin=current_user.has_role('Global Admin'),
        )

    except Exception as e:
        logger.error(f"Error loading NAD board: {e}", exc_info=True)
        flash('Error loading the NAD board. Please try again.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


# ==================== Shared Notes (reuse PlayerAdminNote) ====================
# Web-session counterparts of the mobile /admin/players/<id>/notes endpoints,
# delegating to the same PlayerAdminService so the thread is one and the same.

@admin_panel_bp.route('/nad-board/players/<int:player_id>/notes', methods=['GET'])
@login_required
@role_required(NAD_ROLES)
@transactional
def nad_board_get_notes(player_id: int):
    """List the shared scouting notes for a NAD."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    service = PlayerAdminService(g.db_session)
    result = service.get_player_admin_notes(player_id, limit=100, offset=0)
    if not result.success:
        return jsonify({'success': False, 'message': result.message}), 404
    return jsonify({'success': True, **result.data}), 200


@admin_panel_bp.route('/nad-board/players/<int:player_id>/notes', methods=['POST'])
@login_required
@role_required(NAD_ROLES)
@transactional
def nad_board_create_note(player_id: int):
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


@admin_panel_bp.route('/nad-board/players/<int:player_id>/notes/<int:note_id>', methods=['PUT'])
@login_required
@role_required(NAD_ROLES)
@transactional
def nad_board_update_note(player_id: int, note_id: int):
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


@admin_panel_bp.route('/nad-board/players/<int:player_id>/notes/<int:note_id>', methods=['DELETE'])
@login_required
@role_required(NAD_ROLES)
@transactional
def nad_board_delete_note(player_id: int, note_id: int):
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
