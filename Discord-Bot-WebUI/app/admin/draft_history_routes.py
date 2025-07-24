# app/admin/draft_history_routes.py

"""
Draft History Admin Routes

Provides administrative interface for viewing and managing draft order history.
Allows administrators to view historical draft picks, edit them, and clear data.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

from flask import render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload

from app.admin.blueprint import admin_bp
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.models import (
    DraftOrderHistory, Season, League, Player, Team, User
)
from app.core import db
from app.draft_enhanced import DraftService

logger = logging.getLogger(__name__)


@admin_bp.route('/admin/draft-history')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_history():
    """
    Display the draft history admin page with all draft orders.
    """
    try:
        # Get available seasons and leagues for filtering
        seasons = db.session.query(Season).order_by(desc(Season.id)).all()
        leagues = db.session.query(League).distinct(League.name).order_by(League.name).all()
        
        # Get current season and league filters from query params
        season_filter = request.args.get('season', type=int)
        league_filter = request.args.get('league')
        
        # Build query for draft history
        query = db.session.query(DraftOrderHistory).options(
            joinedload(DraftOrderHistory.player),
            joinedload(DraftOrderHistory.team),
            joinedload(DraftOrderHistory.season),
            joinedload(DraftOrderHistory.league),
            joinedload(DraftOrderHistory.drafter)
        )
        
        # Apply filters
        if season_filter:
            query = query.filter(DraftOrderHistory.season_id == season_filter)
        if league_filter:
            query = query.filter(DraftOrderHistory.league_id == league_filter)
        
        # Order by season (desc), league (asc), then draft position (asc)
        draft_history = query.order_by(
            desc(DraftOrderHistory.season_id),
            DraftOrderHistory.league_id,
            DraftOrderHistory.draft_position
        ).all()
        
        # Group by season and league for easier display
        grouped_history = {}
        for pick in draft_history:
            season_key = f"{pick.season.name} (ID: {pick.season.id})"
            league_key = f"{pick.league.name} (ID: {pick.league.id})"
            
            if season_key not in grouped_history:
                grouped_history[season_key] = {}
            if league_key not in grouped_history[season_key]:
                grouped_history[season_key][league_key] = []
            
            grouped_history[season_key][league_key].append(pick)
        
        return render_template(
            'admin/draft_history.html',
            draft_history=grouped_history,
            seasons=seasons,
            leagues=leagues,
            current_season_filter=season_filter,
            current_league_filter=league_filter,
            total_picks=len(draft_history)
        )
        
    except Exception as e:
        logger.error(f"Error loading draft history: {str(e)}", exc_info=True)
        show_error("Failed to load draft history")
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/draft-history/edit/<int:pick_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def edit_draft_pick(pick_id: int):
    """
    Edit a specific draft pick.
    """
    try:
        pick = db.session.query(DraftOrderHistory).filter_by(id=pick_id).first()
        if not pick:
            return jsonify({'success': False, 'message': 'Draft pick not found'}), 404
        
        data = request.get_json()
        new_position = data.get('position')
        if new_position is not None:
            new_position = int(new_position)
        new_notes = data.get('notes', '').strip()
        position_mode = data.get('mode', 'cascading')  # New parameter for positioning mode
        
        position_changed = False
        swap_result = None
        if new_position and new_position != pick.draft_position:
            # Choose between the positioning modes
            if position_mode == 'absolute':
                swap_result = DraftService.set_absolute_draft_position(db.session, pick_id, new_position)
            elif position_mode == 'smart':
                swap_result = DraftService.insert_draft_position_smart(db.session, pick_id, new_position)
            elif position_mode == 'insert':
                swap_result = DraftService.insert_draft_position(db.session, pick_id, new_position)
            else:
                # Default: cascading swap functionality
                swap_result = DraftService.swap_draft_positions(db.session, pick_id, new_position)
            
            if not swap_result['success']:
                return jsonify(swap_result), 400
            
            position_changed = True
            logger.info(
                f"Swapped draft pick {pick_id} from position #{swap_result['old_position']} "
                f"to #{swap_result['new_position']}, affected {swap_result['affected_picks']} other picks"
            )
        
        # Update notes
        notes_changed = False
        if new_notes != pick.notes:
            old_notes = pick.notes or "No notes"
            pick.notes = new_notes if new_notes else None
            pick.updated_at = datetime.utcnow()
            notes_changed = True
            logger.info(f"Updated draft pick {pick_id} notes from '{old_notes}' to '{new_notes}'")
        
        # Only commit if we made changes
        if position_changed or notes_changed:
            db.session.commit()
        
        # Build response message
        message_parts = []
        if position_changed:
            message_parts.append(f"Moved from #{swap_result['old_position']} to #{swap_result['new_position']}")
            if swap_result['affected_picks'] > 0:
                message_parts.append(f"adjusted {swap_result['affected_picks']} other picks")
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
                'updated_at': pick.updated_at.isoformat()
            },
            'affected_picks': swap_result['affected_picks'] if swap_result else 0
        })
        
    except Exception as e:
        logger.error(f"Error editing draft pick {pick_id}: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to update draft pick'}), 500


@admin_bp.route('/admin/draft-history/delete/<int:pick_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_draft_pick(pick_id: int):
    """
    Delete a specific draft pick and adjust subsequent picks.
    """
    try:
        pick = db.session.query(DraftOrderHistory).filter_by(id=pick_id).first()
        if not pick:
            return jsonify({'success': False, 'message': 'Draft pick not found'}), 404
        
        player_name = pick.player.name
        team_name = pick.team.name
        position = pick.draft_position
        season_id = pick.season_id
        league_id = pick.league_id
        
        # Delete the pick
        db.session.delete(pick)
        
        # Adjust subsequent picks in the same season/league
        subsequent_picks = db.session.query(DraftOrderHistory).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == league_id,
            DraftOrderHistory.draft_position > position
        ).all()
        
        for subsequent_pick in subsequent_picks:
            subsequent_pick.draft_position -= 1
            subsequent_pick.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"Deleted draft pick #{position} ({player_name} to {team_name}) and adjusted {len(subsequent_picks)} subsequent picks")
        
        return jsonify({
            'success': True,
            'message': f'Deleted draft pick #{position} ({player_name} to {team_name}) and adjusted {len(subsequent_picks)} subsequent picks'
        })
        
    except Exception as e:
        logger.error(f"Error deleting draft pick {pick_id}: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to delete draft pick'}), 500


@admin_bp.route('/admin/draft-history/clear', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def clear_draft_history():
    """
    Clear draft history for a specific season and league.
    """
    try:
        data = request.get_json()
        season_id = data.get('season_id', type=int)
        league_id = data.get('league_id', type=int)
        
        if not season_id or not league_id:
            return jsonify({'success': False, 'message': 'Season ID and League ID are required'}), 400
        
        # Get season and league names for logging
        season = db.session.query(Season).filter_by(id=season_id).first()
        league = db.session.query(League).filter_by(id=league_id).first()
        
        if not season or not league:
            return jsonify({'success': False, 'message': 'Season or League not found'}), 404
        
        # Count picks to be deleted
        picks_count = db.session.query(DraftOrderHistory).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == league_id
        ).count()
        
        if picks_count == 0:
            return jsonify({'success': False, 'message': 'No draft picks found for this season/league'}), 404
        
        # Delete all picks for the season/league
        deleted_count = db.session.query(DraftOrderHistory).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == league_id
        ).delete()
        
        db.session.commit()
        
        logger.warning(f"Cleared {deleted_count} draft picks for {season.name} - {league.name} by user {current_user.username}")
        
        return jsonify({
            'success': True,
            'message': f'Cleared {deleted_count} draft picks for {season.name} - {league.name}'
        })
        
    except Exception as e:
        logger.error(f"Error clearing draft history: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to clear draft history'}), 500


@admin_bp.route('/admin/draft-history/normalize', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def normalize_draft_positions():
    """
    Normalize draft positions to remove gaps and ensure sequential numbering (1, 2, 3, ...).
    """
    try:
        data = request.get_json()
        season_id = data.get('season_id')
        league_id = data.get('league_id')
        
        # Convert to int if they exist
        if season_id:
            season_id = int(season_id)
        if league_id:
            league_id = int(league_id)
        
        if not season_id or not league_id:
            return jsonify({'success': False, 'message': 'Season ID and League ID are required'}), 400
        
        # Get season and league names for logging
        season = db.session.query(Season).filter_by(id=season_id).first()
        league = db.session.query(League).filter_by(id=league_id).first()
        
        if not season or not league:
            return jsonify({'success': False, 'message': 'Season or League not found'}), 404
        
        # Normalize the draft positions using the DraftService
        result = DraftService.normalize_draft_positions(db.session, season_id, league_id)
        
        if result['success']:
            db.session.commit()
            logger.info(f"Normalized draft positions for {season.name} - {league.name}: {result['changes_made']} changes made by user {current_user.username}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error normalizing draft positions: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to normalize draft positions'}), 500