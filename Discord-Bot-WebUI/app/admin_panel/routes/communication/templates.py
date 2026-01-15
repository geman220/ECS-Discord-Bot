# app/admin_panel/routes/communication/templates.py

"""
Message Template Management Routes

CRUD operations for message templates.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models import MessageCategory, MessageTemplate, Announcement
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/messages')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def message_templates():
    """Message templates management page."""
    try:
        categories = MessageCategory.query.order_by(MessageCategory.name).all()
        recent_announcements = Announcement.query.order_by(Announcement.created_at.desc()).limit(5).all()

        total_templates = sum(len(category.templates) for category in categories)
        active_templates = sum(len([t for t in category.templates if t.is_active]) for category in categories)

        return render_template('admin_panel/communication/messages_flowbite.html',
                             categories=categories,
                             recent_announcements=recent_announcements,
                             total_templates=total_templates,
                             active_templates=active_templates)
    except Exception as e:
        logger.error(f"Error loading message templates: {e}")
        flash('Message templates unavailable. Verify database connection and template data.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/messages/template/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_message_template():
    """Create a new message template."""
    try:
        category_id = request.form.get('category_id')
        key = request.form.get('key', '').strip().lower().replace(' ', '_')
        name = request.form.get('name')
        description = request.form.get('description')
        content = request.form.get('content')
        channel_type = request.form.get('channel_type')
        usage_context = request.form.get('usage_context')
        is_active = request.form.get('is_active') == 'on'

        if not name or not content:
            flash('Template name and content are required', 'error')
            return redirect(url_for('admin_panel.message_category', category_id=category_id))

        # Auto-generate key from name if not provided
        if not key:
            key = name.lower().replace(' ', '_').replace('-', '_')
            # Remove any non-alphanumeric characters except underscore
            key = ''.join(c for c in key if c.isalnum() or c == '_')

        template = MessageTemplate(
            key=key,
            name=name,
            description=description,
            message_content=content,  # Fixed: was 'content', should be 'message_content'
            category_id=category_id,
            channel_type=channel_type or None,
            usage_context=usage_context or None,
            is_active=is_active,
            created_by=current_user.id
        )
        db.session.add(template)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create',
            resource_type='message_template',
            resource_id=str(template.id),
            new_value=f"Created template: {name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message template "{name}" created successfully', 'success')
        return redirect(url_for('admin_panel.message_category', category_id=category_id))
    except Exception as e:
        logger.error(f"Error creating message template: {e}")
        flash('Message template creation failed. Check database connectivity and validation.', 'error')
        return redirect(url_for('admin_panel.message_category', category_id=category_id))


@admin_panel_bp.route('/communication/messages/template/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_message_template():
    """Update a message template."""
    try:
        template_id = request.form.get('template_id')
        name = request.form.get('name')
        description = request.form.get('description')
        # Support both 'message_content' (form field name) and 'content' (legacy)
        message_content = request.form.get('message_content') or request.form.get('content')
        channel_type = request.form.get('channel_type')
        usage_context = request.form.get('usage_context')
        is_active = request.form.get('is_active') == 'on'

        template = MessageTemplate.query.get_or_404(template_id)
        old_name = template.name

        template.name = name
        template.description = description
        template.message_content = message_content
        template.channel_type = channel_type or None
        template.usage_context = usage_context or None
        template.is_active = is_active
        template.updated_at = datetime.utcnow()
        template.updated_by = current_user.id

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update',
            resource_type='message_template',
            resource_id=str(template.id),
            old_value=old_name,
            new_value=name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message template updated successfully', 'success')
        return redirect(url_for('admin_panel.message_category', category_id=template.category_id))
    except Exception as e:
        logger.error(f"Error updating message template: {e}")
        flash('Message template update failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.message_templates'))


@admin_panel_bp.route('/communication/messages/template/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def toggle_message_template():
    """Toggle a message template active status."""
    try:
        template_id = request.form.get('template_id')
        template = MessageTemplate.query.get_or_404(template_id)

        old_status = template.is_active
        template.is_active = not template.is_active
        template.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='toggle',
            resource_type='message_template',
            resource_id=str(template.id),
            old_value=str(old_status),
            new_value=str(template.is_active),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        status = 'activated' if template.is_active else 'deactivated'
        flash(f'Message template "{template.name}" {status} successfully', 'success')
        return redirect(url_for('admin_panel.message_category', category_id=template.category_id))
    except Exception as e:
        logger.error(f"Error toggling message template: {e}")
        flash('Message template toggle failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.message_templates'))


@admin_panel_bp.route('/communication/messages/template/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_message_template():
    """Delete a message template."""
    try:
        template_id = request.form.get('template_id')
        template = MessageTemplate.query.get_or_404(template_id)

        template_name = template.name
        category_id = template.category_id
        db.session.delete(template)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete',
            resource_type='message_template',
            resource_id=str(template_id),
            old_value=f"Deleted template: {template_name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message template "{template_name}" deleted successfully', 'success')
        return redirect(url_for('admin_panel.message_category', category_id=category_id))
    except Exception as e:
        logger.error(f"Error deleting message template: {e}")
        flash('Message template deletion failed. Verify database connection and constraints.', 'error')
        return redirect(url_for('admin_panel.message_templates'))


@admin_panel_bp.route('/communication/messages/template/<int:template_id>/duplicate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def duplicate_message_template(template_id):
    """Duplicate a message template."""
    try:
        from app.models import MessageTemplate
        original = MessageTemplate.query.get_or_404(template_id)

        duplicate = MessageTemplate(
            name=f"Copy of {original.name}",
            key=f"copy_{original.key}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            message_content=original.message_content,
            description=original.description,
            category_id=original.category_id,
            channel_type=original.channel_type,
            usage_context=original.usage_context,
            variables=original.variables,
            is_active=False,  # Start as inactive
            created_by=current_user.id,
            created_at=datetime.utcnow()
        )

        db.session.add(duplicate)

        # Log the duplication
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='duplicate_template',
            resource_type='message_templates',
            resource_id=str(template_id),
            new_value=f'Created duplicate: {duplicate.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Template duplicated successfully',
            'new_id': duplicate.id
        })

    except Exception as e:
        logger.error(f"Template duplication error: {e}")
        return jsonify({'success': False, 'message': 'Duplication failed'}), 500
