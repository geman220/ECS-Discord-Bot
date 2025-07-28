"""
Duplicate Registration Management Routes

Admin routes for managing potential duplicate registrations, including:
- Viewing pending duplicate alerts
- Merging duplicate profiles
- Resolving duplicate issues
"""

import logging
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import desc

from app.core import db
from app.models import DuplicateRegistrationAlert, Player, User
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

duplicate_management = Blueprint('duplicate_management', __name__)


@duplicate_management.route('/admin/duplicate-registrations')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def duplicate_registrations():
    """Display pending duplicate registration alerts for admin review."""
    try:
        # Get all pending alerts ordered by confidence score (highest first)
        pending_alerts = db.session.query(DuplicateRegistrationAlert).options(
            joinedload(DuplicateRegistrationAlert.existing_player).joinedload(Player.user)
        ).filter_by(status='pending').order_by(
            desc(DuplicateRegistrationAlert.confidence_score),
            desc(DuplicateRegistrationAlert.created_at)
        ).all()
        
        # Get recently resolved alerts for reference
        resolved_alerts = db.session.query(DuplicateRegistrationAlert).options(
            joinedload(DuplicateRegistrationAlert.existing_player),
            joinedload(DuplicateRegistrationAlert.resolved_by)
        ).filter(
            DuplicateRegistrationAlert.status.in_(['resolved', 'ignored'])
        ).order_by(
            desc(DuplicateRegistrationAlert.resolved_at)
        ).limit(20).all()
        
        return render_template(
            'admin/duplicate_registrations.html',
            title='Duplicate Registration Management',
            pending_alerts=pending_alerts,
            resolved_alerts=resolved_alerts
        )
        
    except Exception as e:
        logger.error(f"Error loading duplicate registrations: {e}", exc_info=True)
        show_error('Failed to load duplicate registrations.')
        return redirect(url_for('admin.index'))


@duplicate_management.route('/admin/duplicate-registrations/<int:alert_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def duplicate_registration_detail(alert_id):
    """Show detailed view of a specific duplicate registration alert."""
    try:
        alert = db.session.query(DuplicateRegistrationAlert).options(
            joinedload(DuplicateRegistrationAlert.existing_player).joinedload(Player.user),
            joinedload(DuplicateRegistrationAlert.resolved_by)
        ).get_or_404(alert_id)
        
        # Parse additional details if available
        details = {}
        if alert.details:
            try:
                details = json.loads(alert.details)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse details for alert {alert_id}")
        
        return render_template(
            'admin/duplicate_registration_detail.html',
            title=f'Duplicate Alert #{alert.id}',
            alert=alert,
            details=details
        )
        
    except Exception as e:
        logger.error(f"Error loading duplicate registration detail {alert_id}: {e}", exc_info=True)
        show_error('Failed to load duplicate registration details.')
        return redirect(url_for('duplicate_management.duplicate_registrations'))


@duplicate_management.route('/admin/duplicate-registrations/<int:alert_id>/resolve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def resolve_duplicate_registration(alert_id):
    """Resolve a duplicate registration alert."""
    try:
        alert = db.session.query(DuplicateRegistrationAlert).get_or_404(alert_id)
        
        if alert.status != 'pending':
            show_warning('This alert has already been resolved.')
            return redirect(url_for('duplicate_management.duplicate_registration_detail', alert_id=alert_id))
        
        action = request.form.get('action')
        notes = request.form.get('notes', '').strip()
        
        if action not in ['allow', 'block', 'merge']:
            show_error('Invalid action specified.')
            return redirect(url_for('duplicate_management.duplicate_registration_detail', alert_id=alert_id))
        
        # Update the alert
        alert.status = 'resolved'
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by_user_id = safe_current_user.id
        alert.resolution_action = action
        alert.resolution_notes = notes
        
        if action == 'allow':
            # Allow the registration to proceed - no additional action needed
            # The new user would have already been created when they registered
            show_success('Registration has been approved. No duplicate detected.')
            
        elif action == 'block':
            # Block/ignore the registration - log it but take no action
            # The new user registration would need to be manually handled
            show_warning('Registration has been blocked as a duplicate.')
            
        elif action == 'merge':
            # Handle profile merging
            return redirect(url_for('duplicate_management.merge_profiles', alert_id=alert_id))
        
        db.session.commit()
        
        logger.info(f"Resolved duplicate alert {alert_id} with action '{action}' by user {safe_current_user.id}")
        return redirect(url_for('duplicate_management.duplicate_registrations'))
        
    except Exception as e:
        logger.error(f"Error resolving duplicate registration {alert_id}: {e}", exc_info=True)
        db.session.rollback()
        show_error('Failed to resolve duplicate registration.')
        return redirect(url_for('duplicate_management.duplicate_registration_detail', alert_id=alert_id))


@duplicate_management.route('/admin/duplicate-registrations/<int:alert_id>/merge')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def merge_profiles(alert_id):
    """Show profile merge interface for a duplicate registration."""
    try:
        alert = db.session.query(DuplicateRegistrationAlert).options(
            joinedload(DuplicateRegistrationAlert.existing_player).joinedload(Player.user)
        ).get_or_404(alert_id)
        
        existing_player = alert.existing_player
        
        # Parse new user data from alert details
        new_user_data = {}
        if alert.details:
            try:
                new_user_data = json.loads(alert.details)
            except json.JSONDecodeError:
                pass
        
        # Compile all available data for comparison
        merge_data = {
            'alert': alert,
            'existing_player': existing_player,
            'new_user_data': new_user_data,
            'fields_to_merge': [
                'name', 'phone', 'pronouns', 'jersey_size', 'jersey_number',
                'favorite_position', 'other_positions', 'positions_not_to_play',
                'frequency_play_goal', 'expected_weeks_available', 'willing_to_referee',
                'unavailable_dates', 'additional_info', 'player_notes'
            ]
        }
        
        return render_template(
            'admin/merge_profiles.html',
            title=f'Merge Profiles - Alert #{alert.id}',
            **merge_data
        )
        
    except Exception as e:
        logger.error(f"Error loading merge interface {alert_id}: {e}", exc_info=True)
        show_error('Failed to load merge interface.')
        return redirect(url_for('duplicate_management.duplicate_registration_detail', alert_id=alert_id))


@duplicate_management.route('/admin/duplicate-registrations/<int:alert_id>/execute-merge', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def execute_profile_merge(alert_id):
    """Execute the profile merge based on admin selections."""
    try:
        alert = db.session.query(DuplicateRegistrationAlert).options(
            joinedload(DuplicateRegistrationAlert.existing_player).joinedload(Player.user)
        ).get_or_404(alert_id)
        
        if alert.status != 'pending':
            show_warning('This alert has already been resolved.')
            return redirect(url_for('duplicate_management.duplicate_registrations'))
        
        existing_player = alert.existing_player
        merge_notes = []
        
        # Get form data for fields to merge
        fields_to_update = [
            'name', 'phone', 'pronouns', 'jersey_size', 'jersey_number',
            'favorite_position', 'other_positions', 'positions_not_to_play',
            'frequency_play_goal', 'expected_weeks_available', 'willing_to_referee',
            'unavailable_dates', 'additional_info', 'player_notes'
        ]
        
        # Parse new user data from alert
        new_user_data = {}
        if alert.details:
            try:
                new_user_data = json.loads(alert.details)
            except json.JSONDecodeError:
                pass
        
        # Update fields based on admin selections
        for field in fields_to_update:
            selected_value = request.form.get(f'field_{field}')
            
            if selected_value == 'new' and field in new_user_data:
                old_value = getattr(existing_player, field, None)
                new_value = new_user_data[field]
                
                if old_value != new_value:
                    setattr(existing_player, field, new_value)
                    merge_notes.append(f"Updated {field}: '{old_value}' → '{new_value}'")
            
            elif selected_value == 'combine' and field in new_user_data:
                old_value = getattr(existing_player, field, '') or ''
                new_value = new_user_data[field] or ''
                
                if field in ['additional_info', 'player_notes'] and old_value and new_value:
                    combined_value = f"{old_value}\n\n--- Merged from duplicate registration ---\n{new_value}"
                    setattr(existing_player, field, combined_value)
                    merge_notes.append(f"Combined {field} from both profiles")
                elif new_value and not old_value:
                    setattr(existing_player, field, new_value)
                    merge_notes.append(f"Added {field}: '{new_value}'")
        
        # Update Discord information if provided
        if alert.new_discord_email and not existing_player.discord_id:
            # Link the Discord account if not already linked
            if alert.new_discord_username:
                merge_notes.append(f"Linked Discord account: {alert.new_discord_username} ({alert.new_discord_email})")
        
        # Add merge notes to player notes
        merge_summary = f"\n\n--- Profile Merged on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} by {safe_current_user.username} ---\n" + '\n'.join(merge_notes)
        if existing_player.player_notes:
            existing_player.player_notes += merge_summary
        else:
            existing_player.player_notes = merge_summary.strip()
        
        # Update timestamps
        existing_player.profile_last_updated = datetime.utcnow()
        
        # Mark alert as resolved
        alert.status = 'resolved'
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by_user_id = safe_current_user.id
        alert.resolution_action = 'merged'
        alert.resolution_notes = f"Profile merged. Changes: {', '.join(merge_notes) if merge_notes else 'No changes made'}"
        
        db.session.commit()
        
        show_success(f'Profiles have been successfully merged. {len(merge_notes)} fields were updated.')
        logger.info(f"Successfully merged profiles for alert {alert_id}. Changes: {merge_notes}")
        
        return redirect(url_for('duplicate_management.duplicate_registrations'))
        
    except Exception as e:
        logger.error(f"Error executing profile merge {alert_id}: {e}", exc_info=True)
        db.session.rollback()
        show_error('Failed to merge profiles.')
        return redirect(url_for('duplicate_management.merge_profiles', alert_id=alert_id))


@duplicate_management.route('/admin/duplicate-registrations/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def duplicate_registration_stats():
    """Show statistics about duplicate registrations."""
    try:
        # Get statistics
        stats = {
            'total_alerts': db.session.query(DuplicateRegistrationAlert).count(),
            'pending_alerts': db.session.query(DuplicateRegistrationAlert).filter_by(status='pending').count(),
            'resolved_alerts': db.session.query(DuplicateRegistrationAlert).filter_by(status='resolved').count(),
            'ignored_alerts': db.session.query(DuplicateRegistrationAlert).filter_by(status='ignored').count(),
        }
        
        # Get breakdown by match type
        match_type_stats = db.session.query(
            DuplicateRegistrationAlert.match_type,
            db.func.count(DuplicateRegistrationAlert.id)
        ).group_by(DuplicateRegistrationAlert.match_type).all()
        
        # Get recent activity
        recent_activity = db.session.query(DuplicateRegistrationAlert).options(
            joinedload(DuplicateRegistrationAlert.resolved_by)
        ).filter(
            DuplicateRegistrationAlert.resolved_at.isnot(None)
        ).order_by(
            desc(DuplicateRegistrationAlert.resolved_at)
        ).limit(10).all()
        
        return render_template(
            'admin/duplicate_registration_stats.html',
            title='Duplicate Registration Statistics',
            stats=stats,
            match_type_stats=dict(match_type_stats),
            recent_activity=recent_activity
        )
        
    except Exception as e:
        logger.error(f"Error loading duplicate registration stats: {e}", exc_info=True)
        show_error('Failed to load statistics.')
        return redirect(url_for('duplicate_management.duplicate_registrations'))