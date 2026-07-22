# app/classic_draft.py

"""
Classic Balanced Draft — JSON APIs for the balanced board served at
/draft/classic (the page itself renders from draft_enhanced.draft_league,
which branches to the balanced template when classic_balanced_draft_enabled).

READ-ONLY: rosters are written exclusively through the existing
draft_player_enhanced / remove_player_enhanced socket events so the entire
persistence + Discord/role chain stays identical to the legacy draft.
"""

import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required

from app.services import classic_draft_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

classic_draft_bp = Blueprint('classic_draft', __name__)


def balanced_draft_access_required(f):
    """These payloads carry averaged final scores, so access follows the
    score-blindness contract (SCORE_ACCESS_ROLES + current-season Classic
    player_teams coaches), NOT the wider draft-page role family."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not classic_draft_service.viewer_can_access_balanced_draft(
                g.db_session, current_user.id):
            return jsonify({'success': False,
                            'message': 'Access denied: Classic coaches and admins only'}), 403
        return f(*args, **kwargs)
    return wrapper


@classic_draft_bp.route('/state.json')
@login_required
@transactional
@balanced_draft_access_required
def state():
    """Full board state: teams + rosters + metric totals, pool, gaps, config.
    Used for bootstrap and as the authoritative resync after socket events."""
    return jsonify({'success': True, **classic_draft_service.get_board_state(g.db_session)}), 200


@classic_draft_bp.route('/suggestions')
@login_required
@transactional
@balanced_draft_access_required
def suggestions():
    """Top advisory picks for ?team_id=, with projected per-metric impact."""
    team_id = request.args.get('team_id', type=int)
    limit = request.args.get('limit', type=int)
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400
    try:
        result = classic_draft_service.suggest_for_team(g.db_session, team_id, limit=limit)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 404
    return jsonify({'success': True, 'team_id': team_id, 'suggestions': result}), 200


@classic_draft_bp.route('/check', methods=['POST'])
@login_required
@transactional
@balanced_draft_access_required
def check():
    """Preview a multi-assign: body {assignments: [{player_id, team_id}, ...]}.
    Pure projection — nothing is written."""
    data = request.get_json(silent=True) or {}
    assignments = data.get('assignments')
    if not isinstance(assignments, list) or not assignments:
        return jsonify({'success': False, 'message': 'assignments list is required'}), 400
    if len(assignments) > 30:
        return jsonify({'success': False, 'message': 'Too many assignments (max 30)'}), 400
    result = classic_draft_service.multi_check(g.db_session, assignments)
    return jsonify({'success': True, **result}), 200
