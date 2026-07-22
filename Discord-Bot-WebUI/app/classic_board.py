# app/classic_board.py

"""
Classic Board + coach rating screen — coach/admin facing pages (NOT part of the
admin panel; Classic coaches are not admins, so these live in the normal player
shell, NAD-board style).

Blindness contract: the /rate page and its save endpoint only ever read/write
the REQUESTING coach's own ratings (classic_rating_service.get_my_ratings /
upsert_rating). Averaged final scores appear on the board only for viewers with
score access (Classic Coach + admins); per-coach raw rows are admin-panel-only.
"""

import logging

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.decorators import role_required
from app.services import classic_rating_service as rating_service
from app.services.classic_board_service import compute_classic_board
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

classic_board_bp = Blueprint('classic_board', __name__)

# Board page: Classic coaches + Pub League coaches + admins. Averaged scores are
# rendered only for SCORE_ROLES viewers.
BOARD_ROLES = ['Global Admin', 'Pub League Admin', 'Pub League Coach', 'Classic Coach']
SCORE_ROLES = ['Global Admin', 'Pub League Admin', 'Classic Coach']
# Rating: Classic Coaches submit; admins may open the page read-only to verify.
RATE_PAGE_ROLES = ['Global Admin', 'Pub League Admin', 'Classic Coach']


def _viewer_sees_scores():
    return any(current_user.has_role(r) for r in SCORE_ROLES)


@classic_board_bp.route('/')
@login_required
@role_required(BOARD_ROLES)
@transactional
def index():
    """Classic Board — every current-season Classic player with attendance,
    career goals/assists, positions, GK willingness, and (for score viewers)
    the averaged rating metrics behind a per-card disclosure."""
    try:
        include_scores = _viewer_sees_scores()
        board = compute_classic_board(g.db_session, include_scores=include_scores)
        players = board['players']
        rated_count = sum(1 for p in players
                          if p.get('ratings', {}).get('is_rated')) if include_scores else 0
        with_attendance = [p['attendance_rate'] for p in players
                           if p['has_attendance_data'] and p['attendance_rate'] is not None]
        stats = {
            'total': len(players),
            'new': sum(1 for p in players if p['is_new']),
            'returning': sum(1 for p in players if not p['is_new'] and not p['is_coach']),
            'avg_attendance': round(sum(with_attendance) / len(with_attendance)) if with_attendance else None,
            'rated': rated_count,
        }
        return render_template(
            'classic_board/board_flowbite.html',
            players=players,
            stats=stats,
            metrics=board['metrics'],
            season_name=board['season_name'],
            show_scores=include_scores,
        )
    except Exception as e:
        logger.error(f"Error loading Classic board: {e}", exc_info=True)
        flash('Error loading the Classic board. Please try again.', 'error')
        return redirect(url_for('main.index'))


@classic_board_bp.route('/rate')
@login_required
@role_required(RATE_PAGE_ROLES)
@transactional
def rate():
    """Blind rating sheet — the requesting coach's own ratings only."""
    try:
        session = g.db_session
        config = rating_service.get_rating_config()
        board = compute_classic_board(session, include_scores=False)
        season_id = board['season_id']

        # Coaches never rate other coaches — drop them from the rating queue.
        players = [p for p in board['players'] if not p['is_coach']]

        mine = rating_service.get_my_ratings(session, season_id, current_user.id) if season_id else {}
        for p in players:
            row = mine.get(p['id'])
            p['my_rating'] = row.to_dict() if row else None

        rated = sum(1 for p in players if p['my_rating'] and p['my_rating']['is_complete'])
        can_submit = current_user.has_role('Classic Coach')
        return render_template(
            'classic_board/rate_flowbite.html',
            players=players,
            metrics=board['metrics'],
            season_name=board['season_name'],
            window_open=config['window_open'],
            can_submit=can_submit and config['window_open'],
            is_classic_coach=can_submit,
            rated_count=rated,
        )
    except Exception as e:
        logger.error(f"Error loading Classic rating screen: {e}", exc_info=True)
        flash('Error loading the rating screen. Please try again.', 'error')
        return redirect(url_for('main.index'))


# ==================== Scouting notes (NADs — shared PlayerAdminNote thread) ==
# Same thread the NAD board / mobile Waiting Room use, so review happens in one
# place. The service hides the thread once a player is no longer a NAD.

@classic_board_bp.route('/players/<int:player_id>/notes', methods=['GET'])
@login_required
@role_required(BOARD_ROLES)
@transactional
def get_notes(player_id):
    """List the shared scouting notes for a NAD on the Classic board."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    service = PlayerAdminService(g.db_session)
    result = service.get_player_admin_notes(player_id, limit=100, offset=0)
    if not result.success:
        return jsonify({'success': False, 'message': result.message}), 404
    return jsonify({'success': True, **result.data}), 200


@classic_board_bp.route('/players/<int:player_id>/notes', methods=['POST'])
@login_required
@role_required(BOARD_ROLES)
@transactional
def create_note(player_id):
    """Add a scouting note from the Classic board."""
    from app.services.mobile.player_admin_service import PlayerAdminService
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'Note content is required'}), 400
    service = PlayerAdminService(g.db_session)
    result = service.create_admin_note(player_id, current_user.id, content)
    if not result.success:
        status = 404 if result.error_code == 'PLAYER_NOT_FOUND' else 400
        return jsonify({'success': False, 'message': result.message}), status
    return jsonify({'success': True, **result.data}), 201


@classic_board_bp.route('/rate/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Classic Coach'])
@transactional
def save_rating(player_id):
    """Autosave endpoint: upsert the requesting coach's rating for one player.

    Body: {"intensity": 2.75, ...} — any subset of the four metrics, plus an
    optional "notes". Values 1.00–5.00, max 2 decimals.
    """
    session = g.db_session
    league = rating_service.current_classic_league(session)
    if league is None:
        return jsonify({'success': False, 'message': 'No current Classic season'}), 404

    data = request.get_json(silent=True) or {}
    values = {k: data[k] for k in rating_service.METRICS if k in data}
    notes = data.get('notes')
    if not values and notes is None:
        return jsonify({'success': False, 'message': 'No rating values provided'}), 400

    try:
        row = rating_service.upsert_rating(
            session, league.season_id, current_user.id, player_id, values, notes=notes)
    except rating_service.RatingWindowClosed:
        return jsonify({'success': False, 'error': 'WINDOW_CLOSED',
                        'message': 'The rating window is closed'}), 403
    except rating_service.NotRateable as e:
        return jsonify({'success': False, 'message': str(e)}), 404
    except PermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'rating': row.to_dict()}), 200
