# app/admin_panel/routes/communication/league_settings.py

"""
League Settings Management Routes

CRUD operations for league-specific settings that are used by the Discord bot
for welcome messages, contact information, and display names.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models import LeagueSetting
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/league-settings')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_settings():
    """League settings management page."""
    import traceback
    try:
        settings = LeagueSetting.query.order_by(LeagueSetting.sort_order).all()

        return render_template(
            'admin_panel/communication/league_settings.html',
            settings=settings
        )
    except Exception as e:
        logger.error(f"Error loading league settings: {e}")
        logger.error(traceback.format_exc())
        flash('League settings unavailable. Check database connection.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/league-settings/create', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def create_league_setting():
    """Create a new league setting."""
    try:
        league_key = request.form.get('league_key', '').strip().lower().replace(' ', '_')
        display_name = request.form.get('display_name', '').strip()
        welcome_message = request.form.get('welcome_message', '').strip()
        contact_info = request.form.get('contact_info', '').strip()
        emoji = request.form.get('emoji', '').strip()

        if not league_key or not display_name or not welcome_message or not contact_info:
            flash('All fields except emoji are required', 'error')
            return redirect(url_for('admin_panel.league_settings'))

        # Check for duplicate key
        existing = LeagueSetting.query.filter_by(league_key=league_key).first()
        if existing:
            flash(f'League key "{league_key}" already exists', 'error')
            return redirect(url_for('admin_panel.league_settings'))

        # Get next sort order
        max_order = db.session.query(db.func.max(LeagueSetting.sort_order)).scalar() or 0

        setting = LeagueSetting(
            league_key=league_key,
            display_name=display_name,
            welcome_message=welcome_message,
            contact_info=contact_info,
            emoji=emoji or None,
            sort_order=max_order + 1
        )
        db.session.add(setting)
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create',
            resource_type='league_setting',
            resource_id=str(setting.id),
            new_value=f"Created league setting: {display_name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'League setting "{display_name}" created successfully', 'success')
        return redirect(url_for('admin_panel.league_settings'))

    except Exception as e:
        logger.error(f"Error creating league setting: {e}")
        db.session.rollback()
        flash('Failed to create league setting', 'error')
        return redirect(url_for('admin_panel.league_settings'))


@admin_panel_bp.route('/communication/league-settings/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_league_setting():
    """Update an existing league setting."""
    try:
        setting_id = request.form.get('setting_id')
        display_name = request.form.get('display_name', '').strip()
        welcome_message = request.form.get('welcome_message', '').strip()
        contact_info = request.form.get('contact_info', '').strip()
        emoji = request.form.get('emoji', '').strip()

        if not display_name or not welcome_message or not contact_info:
            flash('Display name, welcome message, and contact info are required', 'error')
            return redirect(url_for('admin_panel.league_settings'))

        setting = LeagueSetting.query.get_or_404(setting_id)
        old_name = setting.display_name

        setting.display_name = display_name
        setting.welcome_message = welcome_message
        setting.contact_info = contact_info
        setting.emoji = emoji or None
        setting.updated_at = datetime.utcnow()
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update',
            resource_type='league_setting',
            resource_id=str(setting.id),
            old_value=old_name,
            new_value=display_name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'League setting "{display_name}" updated successfully', 'success')
        return redirect(url_for('admin_panel.league_settings'))

    except Exception as e:
        logger.error(f"Error updating league setting: {e}")
        db.session.rollback()
        flash('Failed to update league setting', 'error')
        return redirect(url_for('admin_panel.league_settings'))


@admin_panel_bp.route('/communication/league-settings/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def toggle_league_setting():
    """Toggle a league setting's active status."""
    try:
        setting_id = request.form.get('setting_id')
        setting = LeagueSetting.query.get_or_404(setting_id)

        old_status = setting.is_active
        setting.is_active = not setting.is_active
        setting.updated_at = datetime.utcnow()
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='toggle',
            resource_type='league_setting',
            resource_id=str(setting.id),
            old_value=str(old_status),
            new_value=str(setting.is_active),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        status = 'activated' if setting.is_active else 'deactivated'
        flash(f'League setting "{setting.display_name}" {status}', 'success')
        return redirect(url_for('admin_panel.league_settings'))

    except Exception as e:
        logger.error(f"Error toggling league setting: {e}")
        db.session.rollback()
        flash('Failed to toggle league setting', 'error')
        return redirect(url_for('admin_panel.league_settings'))


@admin_panel_bp.route('/communication/league-settings/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_league_setting():
    """Delete a league setting."""
    try:
        setting_id = request.form.get('setting_id')
        setting = LeagueSetting.query.get_or_404(setting_id)

        setting_name = setting.display_name
        db.session.delete(setting)
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete',
            resource_type='league_setting',
            resource_id=str(setting_id),
            old_value=f"Deleted league setting: {setting_name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'League setting "{setting_name}" deleted', 'success')
        return redirect(url_for('admin_panel.league_settings'))

    except Exception as e:
        logger.error(f"Error deleting league setting: {e}")
        db.session.rollback()
        flash('Failed to delete league setting', 'error')
        return redirect(url_for('admin_panel.league_settings'))


@admin_panel_bp.route('/communication/league-settings/reorder', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def reorder_league_settings():
    """Reorder league settings via AJAX."""
    try:
        order_data = request.get_json()
        if not order_data or 'order' not in order_data:
            return jsonify({'success': False, 'message': 'Invalid data'}), 400

        for index, setting_id in enumerate(order_data['order']):
            setting = LeagueSetting.query.get(setting_id)
            if setting:
                setting.sort_order = index

        db.session.commit()
        return jsonify({'success': True, 'message': 'Order updated'})

    except Exception as e:
        logger.error(f"Error reordering league settings: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Failed to update order'}), 500
