# app/admin_panel/routes/draft_management.py

"""
Admin Panel Draft Management Routes

This module contains routes for:
- Draft history viewing and editing
- Draft position management
- Draft statistics and normalization
"""

import logging
from datetime import datetime
from flask import render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required, current_user
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import DraftOrderHistory, Season, League, Player, Team
from app.models.admin_config import AdminAuditLog
from app.core import db
from app.draft_enhanced import DraftService

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Draft History Dashboard
# -----------------------------------------------------------

@admin_panel_bp.route('/draft')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_overview():
    """Redirect to unified draft history page."""
    # Redirect to draft history which has all the filtering and data
    return redirect(url_for('admin_panel.draft_history'))


@admin_panel_bp.route('/draft/history')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_history():
    """Display draft history with filtering - unified draft management page."""
    try:
        seasons = db.session.query(Season).order_by(desc(Season.id)).all()
        leagues = db.session.query(League).distinct(League.name).order_by(League.name).all()
        current_season = db.session.query(Season).filter_by(is_current=True).first()

        season_filter = request.args.get('season', type=int)
        league_filter = request.args.get('league')

        # Default to current season if no filter specified
        if season_filter is None and current_season:
            season_filter = current_season.id

        query = db.session.query(DraftOrderHistory).options(
            joinedload(DraftOrderHistory.player),
            joinedload(DraftOrderHistory.team),
            joinedload(DraftOrderHistory.season),
            joinedload(DraftOrderHistory.league),
            joinedload(DraftOrderHistory.drafter)
        )

        if season_filter:
            query = query.filter(DraftOrderHistory.season_id == season_filter)
        if league_filter:
            query = query.filter(DraftOrderHistory.league_id == league_filter)

        draft_history_list = query.order_by(
            desc(DraftOrderHistory.season_id),
            DraftOrderHistory.league_id,
            DraftOrderHistory.draft_position
        ).all()

        # Group by season and league
        grouped_history = {}
        for pick in draft_history_list:
            season_key = f"{pick.season.name} (ID: {pick.season.id})"
            league_key = f"{pick.league.name} (ID: {pick.league.id})"

            if season_key not in grouped_history:
                grouped_history[season_key] = {}
            if league_key not in grouped_history[season_key]:
                grouped_history[season_key][league_key] = []

            grouped_history[season_key][league_key].append(pick)

        # Get statistics for the header
        total_all_picks = db.session.query(DraftOrderHistory).count()
        current_season_picks = 0
        if current_season:
            current_season_picks = db.session.query(DraftOrderHistory).filter_by(
                season_id=current_season.id
            ).count()

        stats = {
            'total_picks': total_all_picks,
            'current_season_picks': current_season_picks,
            'seasons_count': len(seasons),
            'filtered_picks': len(draft_history_list)
        }

        return render_template('admin_panel/draft/history.html',
                             draft_history=grouped_history,
                             seasons=seasons,
                             leagues=leagues,
                             current_season=current_season,
                             current_season_filter=season_filter,
                             current_league_filter=league_filter,
                             total_picks=len(draft_history_list),
                             stats=stats)

    except Exception as e:
        logger.error(f"Error loading draft history: {e}", exc_info=True)
        return render_template('admin_panel/draft/history.html',
                             draft_history={},
                             seasons=[],
                             leagues=[],
                             total_picks=0,
                             error=str(e))


# -----------------------------------------------------------
# Draft Pick Management
# -----------------------------------------------------------

@admin_panel_bp.route('/draft/edit/<int:pick_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def edit_draft_pick(pick_id):
    """Edit a specific draft pick."""
    try:
        pick = db.session.query(DraftOrderHistory).filter_by(id=pick_id).first()
        if not pick:
            return jsonify({'success': False, 'message': 'Draft pick not found'}), 404

        data = request.get_json()
        new_position = data.get('position')
        if new_position is not None:
            new_position = int(new_position)
        new_notes = data.get('notes', '').strip()
        position_mode = data.get('mode', 'cascading')

        position_changed = False
        swap_result = None

        if new_position and new_position != pick.draft_position:
            if position_mode == 'absolute':
                swap_result = DraftService.set_absolute_draft_position(db.session, pick_id, new_position)
            elif position_mode == 'smart':
                swap_result = DraftService.insert_draft_position_smart(db.session, pick_id, new_position)
            elif position_mode == 'insert':
                swap_result = DraftService.insert_draft_position(db.session, pick_id, new_position)
            else:
                swap_result = DraftService.swap_draft_positions(db.session, pick_id, new_position)

            if not swap_result['success']:
                return jsonify(swap_result), 400

            position_changed = True
            logger.info(f"Swapped draft pick {pick_id} from #{swap_result['old_position']} to #{swap_result['new_position']}")

        notes_changed = False
        if new_notes != pick.notes:
            pick.notes = new_notes if new_notes else None
            pick.updated_at = datetime.utcnow()
            notes_changed = True

        if position_changed or notes_changed:
            db.session.commit()

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='draft_pick_edit',
                resource_type='draft_pick',
                resource_id=str(pick_id),
                new_value=f'Position: {new_position}, Notes: {new_notes[:50] if new_notes else ""}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

        message_parts = []
        if position_changed:
            message_parts.append(f"Moved from #{swap_result['old_position']} to #{swap_result['new_position']}")
        if notes_changed:
            message_parts.append("updated notes")

        message = f"Updated draft pick for {pick.player.name}"
        if message_parts:
            message += f" ({', '.join(message_parts)})"

        return jsonify({
            'success': True,
            'message': message,
            'pick': {
                'id': pick.id,
                'position': pick.draft_position,
                'notes': pick.notes,
                'updated_at': pick.updated_at.isoformat() if pick.updated_at else None
            },
            'affected_picks': swap_result['affected_picks'] if swap_result else 0
        })

    except Exception as e:
        logger.error(f"Error editing draft pick {pick_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to update draft pick'}), 500


@admin_panel_bp.route('/draft/delete/<int:pick_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_draft_pick(pick_id):
    """Delete a specific draft pick."""
    try:
        pick = db.session.query(DraftOrderHistory).filter_by(id=pick_id).first()
        if not pick:
            return jsonify({'success': False, 'message': 'Draft pick not found'}), 404

        player_name = pick.player.name
        team_name = pick.team.name
        position = pick.draft_position
        season_id = pick.season_id
        league_id = pick.league_id

        db.session.delete(pick)

        # Adjust subsequent picks
        subsequent_picks = db.session.query(DraftOrderHistory).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == league_id,
            DraftOrderHistory.draft_position > position
        ).all()

        for subsequent_pick in subsequent_picks:
            subsequent_pick.draft_position -= 1
            subsequent_pick.updated_at = datetime.utcnow()

        db.session.commit()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='draft_pick_delete',
            resource_type='draft_pick',
            resource_id=str(pick_id),
            new_value=f'Deleted pick #{position} ({player_name} to {team_name})',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Deleted draft pick #{position} ({player_name} to {team_name})'
        })

    except Exception as e:
        logger.error(f"Error deleting draft pick {pick_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to delete draft pick'}), 500


@admin_panel_bp.route('/draft/clear', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def clear_draft_history():
    """Clear draft history for a specific season and league."""
    try:
        data = request.get_json()
        season_id = data.get('season_id')
        league_id = data.get('league_id')

        if season_id:
            season_id = int(season_id)
        if league_id:
            league_id = int(league_id)

        if not season_id or not league_id:
            return jsonify({'success': False, 'message': 'Season ID and League ID are required'}), 400

        season = db.session.query(Season).filter_by(id=season_id).first()
        league = db.session.query(League).filter_by(id=league_id).first()

        if not season or not league:
            return jsonify({'success': False, 'message': 'Season or League not found'}), 404

        picks_count = db.session.query(DraftOrderHistory).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == league_id
        ).count()

        if picks_count == 0:
            return jsonify({'success': False, 'message': 'No draft picks found'}), 404

        deleted_count = db.session.query(DraftOrderHistory).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == league_id
        ).delete()

        db.session.commit()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='draft_history_clear',
            resource_type='draft_history',
            resource_id=f'{season_id}_{league_id}',
            new_value=f'Cleared {deleted_count} picks for {season.name} - {league.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Cleared {deleted_count} draft picks for {season.name} - {league.name}'
        })

    except Exception as e:
        logger.error(f"Error clearing draft history: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to clear draft history'}), 500


@admin_panel_bp.route('/draft/normalize', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def normalize_draft_positions():
    """Normalize draft positions to ensure sequential numbering."""
    try:
        data = request.get_json()
        season_id = data.get('season_id')
        league_id = data.get('league_id')

        if season_id:
            season_id = int(season_id)
        if league_id:
            league_id = int(league_id)

        if not season_id or not league_id:
            return jsonify({'success': False, 'message': 'Season ID and League ID are required'}), 400

        season = db.session.query(Season).filter_by(id=season_id).first()
        league = db.session.query(League).filter_by(id=league_id).first()

        if not season or not league:
            return jsonify({'success': False, 'message': 'Season or League not found'}), 404

        result = DraftService.normalize_draft_positions(db.session, season_id, league_id)

        if result['success']:
            db.session.commit()

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='draft_positions_normalize',
                resource_type='draft_history',
                resource_id=f'{season_id}_{league_id}',
                new_value=f'Normalized {result["changes_made"]} positions',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error normalizing draft positions: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to normalize positions'}), 500


# -----------------------------------------------------------
# Draft API Endpoints
# -----------------------------------------------------------

@admin_panel_bp.route('/draft/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_stats_api():
    """API endpoint for draft statistics."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)

        query = db.session.query(DraftOrderHistory)

        if season_id:
            query = query.filter(DraftOrderHistory.season_id == season_id)
        if league_id:
            query = query.filter(DraftOrderHistory.league_id == league_id)

        total_picks = query.count()

        # Get picks per team
        from sqlalchemy import func
        team_picks = query.with_entities(
            DraftOrderHistory.team_id,
            func.count(DraftOrderHistory.id)
        ).group_by(DraftOrderHistory.team_id).all()

        return jsonify({
            'total_picks': total_picks,
            'team_picks': {str(team_id): count for team_id, count in team_picks},
            'filters': {
                'season_id': season_id,
                'league_id': league_id
            }
        })

    except Exception as e:
        logger.error(f"Error getting draft stats: {e}")
        return jsonify({'error': str(e)}), 500
