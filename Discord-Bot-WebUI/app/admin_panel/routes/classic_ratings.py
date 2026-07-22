# app/admin_panel/routes/classic_ratings.py

"""
Admin panel — Classic ratings: per-coach raw matrix, compiled averages,
final-score overrides (audited), rating-window + config management, and
historic season-trend analytics.

This is the ONLY surface that exposes per-coach raw ratings; everything
coach-facing stays blind (see app/classic_board.py).
"""

import logging
from decimal import Decimal, InvalidOperation

from flask import flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.decorators import role_required
from app.models import ClassicRatingMetric, Player
from app.models.admin_config import AdminConfig
from app.services import classic_rating_service as rating_service
from app.services.classic_board_service import compute_classic_board

from .. import admin_panel_bp

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


@admin_panel_bp.route('/classic-ratings')
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_dashboard():
    """Coach completion, per-player averages + per-coach raw matrix, overrides."""
    try:
        session = g.db_session
        board = compute_classic_board(session, include_scores=True)
        season_id = board['season_id']
        config = rating_service.get_rating_config()

        matrix = {'raters': {}, 'rows': {}}
        progress = []
        finals = {}
        if season_id:
            matrix = rating_service.get_rater_matrix(session, season_id)
            progress = rating_service.get_rating_progress(session, season_id)
            finals = rating_service.get_final_scores(session, season_id)

        players = [p for p in board['players'] if not p['is_coach']]
        for p in players:
            score = finals.get(p['id'])
            p['final'] = {
                m: {
                    'value': float(score['metrics'][m]['value']) if score and score['metrics'][m]['value'] is not None else None,
                    'avg': float(score['metrics'][m]['avg']) if score and score['metrics'][m]['avg'] is not None else None,
                    'count': score['metrics'][m]['count'] if score else 0,
                    'overridden': score['metrics'][m]['overridden'] if score else False,
                } for m in rating_service.METRICS
            }
            p['composite'] = float(score['composite']) if score and score['composite'] is not None else None
            p['is_rated'] = bool(score and score['is_rated'])
            p['has_override'] = bool(score and any(score['metrics'][m]['overridden'] for m in rating_service.METRICS))
            p['coach_ratings'] = matrix['rows'].get(p['id'], {})

        return render_template(
            'admin_panel/classic_ratings_flowbite.html',
            players=players,
            metrics=board['metrics'],
            season_name=board['season_name'],
            raters=matrix['raters'],
            progress=progress,
            config=config,
            weights={m: float(rating_service.quantize2(config['weights'][m]))
                     for m in rating_service.METRICS},
        )
    except Exception as e:
        logger.error(f"Error loading classic ratings dashboard: {e}", exc_info=True)
        flash('Unable to load the Classic ratings dashboard.', 'error')
        return redirect(url_for('admin_panel.admin_dashboard'))


@admin_panel_bp.route('/classic-ratings/override', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_override():
    """Set (value present) or clear (value null) one final-score override."""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    metric = data.get('metric')
    value = data.get('value')
    reason = (data.get('reason') or '').strip() or None

    session = g.db_session
    league = rating_service.current_classic_league(session)
    if league is None:
        return jsonify({'success': False, 'message': 'No current Classic season'}), 404
    if not player_id or metric not in rating_service.METRICS:
        return jsonify({'success': False, 'message': 'player_id and a valid metric are required'}), 400

    try:
        if value is None:
            rating_service.clear_override(session, league.season_id, player_id, metric,
                                          current_user.id)
        else:
            rating_service.set_override(session, league.season_id, player_id, metric,
                                        value, current_user.id, reason=reason)
        session.commit()
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    finals = rating_service.get_final_scores(session, league.season_id, player_ids=[player_id])
    score = finals.get(player_id)
    return jsonify({
        'success': True,
        'final': {
            m: {
                'value': float(score['metrics'][m]['value']) if score and score['metrics'][m]['value'] is not None else None,
                'avg': float(score['metrics'][m]['avg']) if score and score['metrics'][m]['avg'] is not None else None,
                'overridden': score['metrics'][m]['overridden'] if score else False,
            } for m in rating_service.METRICS
        },
        'composite': float(score['composite']) if score and score['composite'] is not None else None,
    }), 200


@admin_panel_bp.route('/classic-ratings/window', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_window():
    """Open/close the coach rating window."""
    data = request.get_json(silent=True) or {}
    open_flag = bool(data.get('open'))
    AdminConfig.set_setting(
        'classic_ratings_window_open', 'true' if open_flag else 'false',
        description='Allow Classic coaches to submit/edit player ratings',
        category='classic_ratings', data_type='boolean', user_id=current_user.id,
    )
    g.db_session.commit()
    return jsonify({'success': True, 'window_open': open_flag}), 200


@admin_panel_bp.route('/classic-ratings/config', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_config():
    """Save the Classic rating/draft knobs. Weights must sum to exactly 100.

    VALIDATE EVERYTHING BEFORE THE FIRST WRITE: request teardown commits
    g.db_session even on a 400 response, so any early write would be silently
    persisted while the UI reports failure.
    """
    data = request.get_json(silent=True) or {}
    session = g.db_session
    pending = []   # (key, value, data_type)

    def fail(message):
        return jsonify({'success': False, 'message': message}), 400

    if 'weights' in data:
        weights = data['weights'] or {}
        try:
            cleaned = {m: Decimal(str(weights.get(m))) for m in rating_service.METRICS}
        except (InvalidOperation, TypeError):
            return fail('Weights must be numbers')
        if any(w < 0 for w in cleaned.values()):
            return fail('Weights cannot be negative')
        total = sum(cleaned.values())
        if total != 100:
            return fail(f'Weights must sum to 100 (currently {total})')
        pending.append(('classic_rating_weights',
                        {m: float(cleaned[m]) for m in rating_service.METRICS}, 'json'))

    for key, field, minimum, maximum in (
        ('classic_draft_max_metric_gap', 'max_metric_gap', Decimal('0'), Decimal('100')),
        ('classic_draft_unrated_default', 'unrated_default', Decimal('1'), Decimal('5')),
    ):
        if field not in data:
            continue
        try:
            value = Decimal(str(data[field]))
        except (InvalidOperation, TypeError):
            return fail(f'{field} must be a number')
        if not (minimum <= value <= maximum):
            return fail(f'{field} must be between {minimum} and {maximum}')
        pending.append((key, str(value), 'string'))

    if 'suggestion_count' in data:
        try:
            count = int(data['suggestion_count'])
        except (ValueError, TypeError):
            return fail('suggestion_count must be an integer')
        if not (1 <= count <= 50):
            return fail('suggestion_count must be 1–50')
        pending.append(('classic_draft_suggestion_count', count, 'integer'))

    for key, field in (
        ('classic_draft_gender_balance_enabled', 'gender_balance_enabled'),
        ('classic_balanced_draft_enabled', 'balanced_draft_enabled'),
    ):
        if field in data:
            pending.append((key, 'true' if data[field] else 'false', 'boolean'))

    if 'suggestion_coefficients' in data:
        coeffs = data['suggestion_coefficients'] or {}
        cleaned = {}
        for key in ('balance', 'need', 'gender', 'position'):
            try:
                value = Decimal(str(coeffs.get(key)))
            except (InvalidOperation, TypeError):
                return fail(f'Coefficient {key} must be a number')
            if not (Decimal('0') <= value <= Decimal('10')):
                return fail(f'Coefficient {key} must be between 0 and 10')
            cleaned[key] = float(value)
        pending.append(('classic_draft_suggestion_coefficients', cleaned, 'json'))

    # All inputs valid — now write.
    for key, value, data_type in pending:
        AdminConfig.set_setting(key, value, category='classic_ratings',
                                data_type=data_type, user_id=current_user.id)
    session.commit()
    return jsonify({'success': True}), 200


@admin_panel_bp.route('/classic-ratings/metrics', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_metrics():
    """Edit a metric's guide text (label, description, 1/3/5 anchors)."""
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    if key not in rating_service.METRICS:
        return jsonify({'success': False, 'message': 'Unknown metric'}), 400
    session = g.db_session
    row = session.query(ClassicRatingMetric).filter_by(key=key).first()
    if row is None:
        return jsonify({'success': False, 'message': 'Metric table not seeded — run sql_classic_ratings.sql'}), 404
    # Validate all fields BEFORE any setattr — teardown commits g.db_session
    # even on a 400, so a half-edited row would silently persist.
    updates = {}
    for field in ('label', 'description', 'anchor_1', 'anchor_3', 'anchor_5'):
        if field in data:
            value = (data[field] or '').strip()
            if not value:
                return jsonify({'success': False, 'message': f'{field} cannot be empty'}), 400
            updates[field] = value
    for field, value in updates.items():
        setattr(row, field, value)
    session.commit()
    return jsonify({'success': True, 'metric': row.to_dict()}), 200


@admin_panel_bp.route('/classic-ratings/players/<int:player_id>/gender', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_gender(player_id):
    """Set/clear a player's draft-balance gender override (M/N or null)."""
    data = request.get_json(silent=True) or {}
    value = data.get('balance_gender')
    if value not in (None, 'M', 'N'):
        return jsonify({'success': False, 'message': 'balance_gender must be M, N, or null'}), 400
    session = g.db_session
    player = session.query(Player).get(player_id)
    if player is None:
        return jsonify({'success': False, 'message': 'Player not found'}), 404
    player.balance_gender = value
    session.commit()
    return jsonify({'success': True, 'balance_gender': value}), 200


@admin_panel_bp.route('/classic-ratings/analytics')
@login_required
@role_required(ADMIN_ROLES)
def classic_ratings_analytics():
    """Historic trend charts: per-season metric averages, distribution, leniency."""
    try:
        session = g.db_session
        trends = rating_service.get_season_trends(session)
        league = rating_service.current_classic_league(session)
        season_id = league.season_id if league else None

        distributions = {}
        raters = {}
        if season_id:
            for metric in rating_service.METRICS:
                distributions[metric] = rating_service.get_metric_distribution(
                    session, season_id, metric)
            raters = rating_service.get_rater_matrix(session, season_id)['raters']

        # Leniency = coach mean-given minus the mean across all ratings.
        all_means = [r['mean_given'] for r in raters.values() if r['mean_given'] is not None]
        league_mean = (sum(all_means) / len(all_means)) if all_means else None
        leniency = [
            {'name': r['name'], 'delta': round(r['mean_given'] - league_mean, 2),
             'mean': r['mean_given'], 'count': r['count']}
            for r in raters.values()
            if r['mean_given'] is not None and league_mean is not None
        ]
        leniency.sort(key=lambda r: r['delta'], reverse=True)

        chart_data = {
            'trends': trends['seasons'],
            'metric_labels': {m: rating_service.METRIC_LABELS[m] for m in rating_service.METRICS},
            'distributions': distributions,
            'leniency': leniency,
        }
        # Rendered with |tojson (never json.dumps + |safe): usernames/season
        # names are user-controlled and must not be able to break out of the
        # script element.
        return render_template(
            'admin_panel/classic_ratings_analytics_flowbite.html',
            chart_data=chart_data,
            has_data=bool(trends['seasons']),
        )
    except Exception as e:
        logger.error(f"Error loading classic ratings analytics: {e}", exc_info=True)
        flash('Unable to load Classic ratings analytics.', 'error')
        return redirect(url_for('admin_panel.classic_ratings_dashboard'))
