# app/admin_panel/routes/match_operations/seasons.py

"""
Season Management Routes

Routes for season management:
- View/manage seasons
- Create/update/delete seasons
- Set current season
"""

import logging
from datetime import datetime

from flask import render_template, flash, redirect, url_for, request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/seasons')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def seasons():
    """Redirect to canonical seasons management in league_management."""
    return redirect(url_for('admin_panel.league_management_seasons', **request.args), code=302)


@admin_panel_bp.route('/match-operations/seasons/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_season():
    """Create a new season."""
    from app.models import Season

    name = request.form.get('name')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    is_current = request.form.get('is_current') == 'true'

    if not name:
        return jsonify({'success': False, 'message': 'Season name is required'}), 400

    # Parse dates if provided
    parsed_start = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    parsed_end = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None

    # If setting as current, unset other current seasons
    if is_current:
        db.session.query(Season).update({'is_current': False})

    # Create new season
    season = Season(
        name=name,
        start_date=parsed_start,
        end_date=parsed_end,
        is_current=is_current,
        league_type=request.form.get('league_type', 'CLASSIC')
    )
    db.session.add(season)
    db.session.flush()

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='create_season',
        resource_type='season',
        resource_id=str(season.id),
        new_value=f'Created season: {name}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    logger.info(f"Season '{name}' created by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'Season "{name}" created successfully',
        'season_id': season.id
    })


@admin_panel_bp.route('/match-operations/seasons/<int:season_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_season(season_id):
    """Update an existing season."""
    from app.models import Season

    season = db.session.query(Season).get_or_404(season_id)
    old_name = season.name

    name = request.form.get('name')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    is_current = request.form.get('is_current') == 'true'

    if not name:
        return jsonify({'success': False, 'message': 'Season name is required'}), 400

    # If setting as current, unset other current seasons
    if is_current and not season.is_current:
        db.session.query(Season).filter(Season.id != season_id).update({'is_current': False})

    # Update season
    season.name = name
    season.start_date = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    season.end_date = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
    season.is_current = is_current

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_season',
        resource_type='season',
        resource_id=str(season_id),
        old_value=old_name,
        new_value=name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    logger.info(f"Season '{name}' updated by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'Season "{name}" updated successfully'
    })


@admin_panel_bp.route('/match-operations/seasons/<int:season_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_season(season_id):
    """Delete a season."""
    from app.models import Season, Match

    season = db.session.query(Season).get_or_404(season_id)

    # Check if season has matches
    match_count = db.session.query(Match).filter_by(season_id=season_id).count() if hasattr(Match, 'season_id') else 0
    if match_count > 0:
        return jsonify({
            'success': False,
            'message': f'Cannot delete season with {match_count} matches. Archive or reassign matches first.'
        }), 400

    season_name = season.name

    # Log the action before deletion
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='delete_season',
        resource_type='season',
        resource_id=str(season_id),
        old_value=season_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    db.session.delete(season)

    logger.info(f"Season '{season_name}' deleted by user {current_user.id}")
    return jsonify({
        'success': True,
        'message': f'Season "{season_name}" deleted successfully'
    })


@admin_panel_bp.route('/match-operations/seasons/<int:season_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_season_details(season_id):
    """Get season details for editing modal."""
    try:
        from app.models import Season

        season = db.session.query(Season).get_or_404(season_id)

        return jsonify({
            'success': True,
            'season': {
                'id': season.id,
                'name': season.name,
                'start_date': season.start_date.strftime('%Y-%m-%d') if season.start_date else '',
                'end_date': season.end_date.strftime('%Y-%m-%d') if season.end_date else '',
                'is_current': season.is_current
            }
        })

    except Exception as e:
        logger.error(f"Error getting season details: {e}")
        return jsonify({'success': False, 'message': 'Failed to get season details'}), 500
