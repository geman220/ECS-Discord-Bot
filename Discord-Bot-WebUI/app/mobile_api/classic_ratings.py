# app/mobile_api/classic_ratings.py

"""
Mobile API — Classic rating system + balanced-draft board data.

Blindness contract mirrors the web: /classic-ratings/players returns ONLY the
requesting coach's rows; per-coach raw data is behind admin-role endpoints.
Picks/removals are NOT here — Flutter reuses the existing
POST/DELETE /api/v1/draft/classic/pick endpoints and /draft socket events so
the persistence chain stays singular.

Contract doc: docs/flutter-classic-rating-draft-contract.md
"""

import logging

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.core.session_manager import managed_session
from app.decorators import jwt_role_required
from app.services import classic_draft_service, classic_rating_service as rating_service
from app.services.classic_board_service import compute_classic_board

from . import mobile_api_v2

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['Pub League Admin', 'Global Admin']
SCORE_ROLES = ['Classic Coach', 'Pub League Admin', 'Global Admin']


def _user_has_any_role(session, user_id, roles):
    from app.models import Role, user_roles
    from sqlalchemy import select
    hit = session.execute(
        select(user_roles.c.user_id)
        .select_from(user_roles.join(Role, Role.id == user_roles.c.role_id))
        .where(user_roles.c.user_id == user_id, Role.name.in_(roles))
    ).first()
    return hit is not None


def _metrics_payload(session):
    return rating_service.get_metrics(session)


@mobile_api_v2.route('/classic-ratings/config', methods=['GET'])
@jwt_required()
def classic_ratings_config():
    """Metric definitions (label/description/anchors/weight) + window state."""
    user_id = int(get_jwt_identity())
    with managed_session() as session:
        if not _user_has_any_role(session, user_id, SCORE_ROLES):
            return jsonify({"msg": f"Access denied: Required roles: {', '.join(SCORE_ROLES)}"}), 403
        config = rating_service.get_rating_config()
        return jsonify({
            "success": True,
            "metrics": _metrics_payload(session),
            "window_open": config['window_open'],
            "max_metric_gap": float(config['max_metric_gap']),
            "gender_balance_enabled": config['gender_balance_enabled'],
        }), 200


@mobile_api_v2.route('/classic-ratings/players', methods=['GET'])
@jwt_role_required(['Classic Coach'])
def classic_ratings_players():
    """Rateable players + the CALLER'S ratings only (blind)."""
    user_id = int(get_jwt_identity())
    with managed_session() as session:
        league = rating_service.current_classic_league(session)
        if league is None:
            return jsonify({"success": True, "window_open": False, "players": [],
                            "season_id": None}), 200
        config = rating_service.get_rating_config()
        board = compute_classic_board(session, include_scores=False)
        players = [p for p in board['players'] if not p['is_coach']]
        mine = rating_service.get_my_ratings(session, league.season_id, user_id)
        for p in players:
            row = mine.get(p['id'])
            p['my_rating'] = row.to_dict() if row else None
            p.pop('balance_gender', None)
        return jsonify({
            "success": True,
            "season_id": league.season_id,
            "season_name": board['season_name'],
            "window_open": config['window_open'],
            "metrics": board['metrics'],
            "players": players,
        }), 200


@mobile_api_v2.route('/classic-ratings/players/<int:player_id>', methods=['PUT'])
@jwt_role_required(['Classic Coach'])
def classic_ratings_upsert(player_id):
    """Upsert the caller's rating for one player. Body: any subset of the four
    metric keys (1.00–5.00, ≤2 decimals) plus optional notes."""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    values = {k: data[k] for k in rating_service.METRICS if k in data}
    notes = data.get('notes')
    if not values and notes is None:
        return jsonify({"msg": "No rating values provided"}), 400

    with managed_session() as session:
        league = rating_service.current_classic_league(session)
        if league is None:
            return jsonify({"msg": "No current Classic season"}), 404
        try:
            row = rating_service.upsert_rating(
                session, league.season_id, user_id, player_id, values, notes=notes)
        except rating_service.RatingWindowClosed:
            return jsonify({"msg": "The rating window is closed",
                            "error": "WINDOW_CLOSED"}), 403
        except rating_service.NotRateable as e:
            return jsonify({"msg": str(e)}), 404
        except PermissionError as e:
            return jsonify({"msg": str(e)}), 403
        except ValueError as e:
            return jsonify({"msg": str(e)}), 400
        result = row.to_dict()
        session.commit()
    return jsonify({"success": True, "rating": result}), 200


@mobile_api_v2.route('/classic-board', methods=['GET'])
@jwt_required()
def classic_board():
    """Classic Board payload — averaged final scores only (never per-coach raws).
    Score access: Classic Coach + admins; Pub League Coach gets the board with
    no ratings block."""
    user_id = int(get_jwt_identity())
    with managed_session() as session:
        sees_scores = _user_has_any_role(session, user_id, SCORE_ROLES)
        if not sees_scores and not _user_has_any_role(session, user_id, ['Pub League Coach']):
            return jsonify({"msg": "Access denied: coaches and admins only"}), 403
        board = compute_classic_board(session, include_scores=sees_scores)
        for p in board['players']:
            p.pop('balance_gender', None)
        return jsonify({"success": True, **board}), 200


@mobile_api_v2.route('/classic-ratings/admin/summary', methods=['GET'])
@jwt_role_required(ADMIN_ROLES)
def classic_ratings_admin_summary():
    """ADMIN: per-coach raw matrix + per-coach stats + completion progress."""
    with managed_session() as session:
        league = rating_service.current_classic_league(session)
        if league is None:
            return jsonify({"success": True, "season_id": None, "raters": {},
                            "rows": {}, "progress": []}), 200
        matrix = rating_service.get_rater_matrix(session, league.season_id)
        progress = rating_service.get_rating_progress(session, league.season_id)
        finals = rating_service.get_final_scores(session, league.season_id)
        return jsonify({
            "success": True,
            "season_id": league.season_id,
            "raters": {str(k): v for k, v in matrix['raters'].items()},
            "rows": {str(pid): {str(uid): r for uid, r in row.items()}
                     for pid, row in matrix['rows'].items()},
            "finals": {str(pid): {
                "composite": float(f['composite']) if f['composite'] is not None else None,
                "is_rated": f['is_rated'],
                "metrics": {m: {
                    "value": float(f['metrics'][m]['value']) if f['metrics'][m]['value'] is not None else None,
                    "avg": float(f['metrics'][m]['avg']) if f['metrics'][m]['avg'] is not None else None,
                    "overridden": f['metrics'][m]['overridden'],
                    "count": f['metrics'][m]['count'],
                } for m in rating_service.METRICS},
            } for pid, f in finals.items()},
            "progress": progress,
        }), 200


# ---------------------------------------------------------------------------
# Balanced-draft board data (picks/removals stay on /draft/classic/pick)
# ---------------------------------------------------------------------------

def _balanced_draft_access_required(f):
    """Score-blindness gate for the balanced-draft payloads: NOT the wide
    draft-role family (_draft_access_required admits Premier/ECS FC coaches
    and any-league team coaches). Allowed: SCORE_ACCESS_ROLES + current-season
    Classic player_teams coaches — same rule as the web board."""
    from functools import wraps

    @wraps(f)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        with managed_session() as session:
            allowed = classic_draft_service.viewer_can_access_balanced_draft(
                session, user_id)
        if not allowed:
            return jsonify({"msg": "Access denied: Classic coaches and admins only"}), 403
        return f(*args, **kwargs)
    return wrapper


@mobile_api_v2.route('/draft/classic/balance', methods=['GET'])
@_balanced_draft_access_required
def classic_draft_balance():
    """Balanced-draft board state: teams + rosters + per-metric totals, pool,
    gaps, config."""
    with managed_session() as session:
        state = classic_draft_service.get_board_state(session)
        return jsonify({"success": True, **state}), 200


@mobile_api_v2.route('/draft/classic/suggestions', methods=['GET'])
@_balanced_draft_access_required
def classic_draft_suggestions():
    """Top advisory picks for ?team_id= with projected per-metric impact."""
    team_id = request.args.get('team_id', type=int)
    limit = request.args.get('limit', type=int)
    if not team_id:
        return jsonify({"msg": "team_id is required"}), 400
    with managed_session() as session:
        try:
            suggestions = classic_draft_service.suggest_for_team(
                session, team_id, limit=limit)
        except ValueError as e:
            return jsonify({"msg": str(e)}), 404
    return jsonify({"success": True, "team_id": team_id,
                    "suggestions": suggestions}), 200


@mobile_api_v2.route('/classic-ratings/admin/override', methods=['PUT'])
@jwt_role_required(ADMIN_ROLES)
def classic_ratings_admin_override():
    """ADMIN: set (value) or clear (value=null) one final-score override."""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    metric = data.get('metric')
    value = data.get('value')
    reason = (data.get('reason') or '').strip() or None
    if not player_id or metric not in rating_service.METRICS:
        return jsonify({"msg": "player_id and a valid metric are required"}), 400

    with managed_session() as session:
        league = rating_service.current_classic_league(session)
        if league is None:
            return jsonify({"msg": "No current Classic season"}), 404
        try:
            if value is None:
                rating_service.clear_override(session, league.season_id, player_id,
                                              metric, user_id)
            else:
                rating_service.set_override(session, league.season_id, player_id,
                                            metric, value, user_id, reason=reason)
        except ValueError as e:
            return jsonify({"msg": str(e)}), 400
        session.commit()
    return jsonify({"success": True}), 200
