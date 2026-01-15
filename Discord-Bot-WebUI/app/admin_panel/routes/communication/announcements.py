# app/admin_panel/routes/communication/announcements.py

"""
Announcement Management Routes

CRUD operations for announcements.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models import Announcement
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/announcements')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def announcements():
    """Announcements management page."""
    import traceback
    try:
        announcements_list = Announcement.query.order_by(Announcement.created_at.desc()).all()

        # Get statistics
        active_announcements = len(announcements_list)
        recent_announcements = 0
        for a in announcements_list:
            try:
                if a.created_at and (datetime.utcnow() - a.created_at).days <= 7:
                    recent_announcements += 1
            except Exception:
                pass
        announcement_types = []

        return render_template('admin_panel/communication/announcements_flowbite.html',
                             announcements=announcements_list,
                             active_announcements=active_announcements,
                             recent_announcements=recent_announcements,
                             announcement_types=announcement_types)
    except Exception as e:
        logger.error(f"Error loading announcements: {e}")
        logger.error(traceback.format_exc())
        flash('Announcements data unavailable. Check database connectivity and announcement models.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/announcements/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_announcement():
    """Create new announcement."""
    if request.method == 'POST':
        try:
            title = request.form.get('title')
            content = request.form.get('content')
            announcement_type = request.form.get('announcement_type', 'general')
            priority = request.form.get('priority', 'normal')

            if not title or not content:
                flash('Title and content are required.', 'error')
                return redirect(url_for('admin_panel.create_announcement'))

            announcement = Announcement(
                title=title,
                content=content,
                created_by=current_user.id,
                created_at=datetime.utcnow(),
                announcement_type=announcement_type,
                priority=priority
            )

            db.session.add(announcement)

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='CREATE_ANNOUNCEMENT',
                resource_type='Announcement',
                resource_id=str(announcement.id),
                new_value=f'Created announcement: {title}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            flash('Announcement created successfully!', 'success')
            return redirect(url_for('admin_panel.announcements'))
        except Exception as e:
            logger.error(f"Error creating announcement: {e}")
            flash('Announcement creation failed. Check database connectivity and input validation.', 'error')
            return redirect(url_for('admin_panel.announcements'))

    return render_template('admin_panel/communication/announcement_form_flowbite.html',
                         title='Create Announcement',
                         announcement=None)


@admin_panel_bp.route('/communication/announcements/edit/<int:announcement_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_announcement(announcement_id):
    """Edit existing announcement."""
    announcement = Announcement.query.get_or_404(announcement_id)

    if request.method == 'POST':
        try:
            announcement.title = request.form.get('title')
            announcement.content = request.form.get('content')
            announcement.announcement_type = request.form.get('announcement_type', 'general')
            announcement.priority = request.form.get('priority', 'normal')

            if not announcement.title or not announcement.content:
                flash('Title and content are required.', 'error')
                return redirect(url_for('admin_panel.edit_announcement', announcement_id=announcement_id))

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='UPDATE_ANNOUNCEMENT',
                resource_type='Announcement',
                resource_id=str(announcement.id),
                new_value=f'Updated announcement: {announcement.title}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            flash('Announcement updated successfully!', 'success')
            return redirect(url_for('admin_panel.announcements'))
        except Exception as e:
            logger.error(f"Error updating announcement: {e}")
            flash('Announcement update failed. Check database connectivity and permissions.', 'error')
            return redirect(url_for('admin_panel.announcements'))

    return render_template('admin_panel/communication/announcement_form_flowbite.html',
                         title='Edit Announcement',
                         announcement=announcement)


@admin_panel_bp.route('/communication/announcements/delete/<int:announcement_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_announcement(announcement_id):
    """Delete announcement."""
    try:
        announcement = Announcement.query.get_or_404(announcement_id)
        title = announcement.title

        db.session.delete(announcement)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='DELETE_ANNOUNCEMENT',
            resource_type='Announcement',
            resource_id=str(announcement_id),
            old_value=f'Deleted announcement: {title}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash('Announcement deleted successfully!', 'success')
        return redirect(url_for('admin_panel.announcements'))
    except Exception as e:
        logger.error(f"Error deleting announcement: {e}")
        flash('Announcement deletion failed. Check database connectivity and constraints.', 'error')
        return redirect(url_for('admin_panel.announcements'))


@admin_panel_bp.route('/communication/announcements/manage', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def manage_announcements():
    """Bulk manage announcements."""
    try:
        action = request.form.get('action')
        announcement_ids = request.form.getlist('announcement_ids')

        if not announcement_ids:
            flash('Please select announcements to manage.', 'warning')
            return redirect(url_for('admin_panel.announcements'))

        processed_count = 0

        if action == 'delete':
            for announcement_id in announcement_ids:
                announcement = Announcement.query.get(announcement_id)
                if announcement:
                    db.session.delete(announcement)
                    processed_count += 1

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'BULK_{action.upper()}_ANNOUNCEMENTS',
            resource_type='Announcement',
            resource_id='bulk',
            new_value=f'Bulk {action} {processed_count} announcements',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Successfully {action}d {processed_count} announcements!', 'success')
        return redirect(url_for('admin_panel.announcements'))
    except Exception as e:
        logger.error(f"Error with bulk announcement action: {e}")
        flash('Announcement processing failed. Verify database connection and batch operations.', 'error')
        return redirect(url_for('admin_panel.announcements'))
