# app/admin_panel/routes/communication/categories.py

"""
Message Category Management Routes

CRUD operations for message categories.
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models import MessageCategory, MessageTemplate
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/messages/category/<int:category_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def message_category(category_id):
    """View templates in a specific category."""
    try:
        category = MessageCategory.query.get_or_404(category_id)
        templates = MessageTemplate.query.filter_by(category_id=category_id).order_by(MessageTemplate.name).all()

        return render_template('admin_panel/communication/category_detail_flowbite.html',
                             category=category,
                             templates=templates)
    except Exception as e:
        logger.error(f"Error loading message category: {e}")
        flash('Message category data unavailable. Check database connectivity and category models.', 'error')
        return redirect(url_for('admin_panel.message_templates'))


@admin_panel_bp.route('/communication/messages/category/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_message_category():
    """Create a new message category."""
    try:
        name = request.form.get('name')
        description = request.form.get('description')

        if not name:
            flash('Category name is required', 'error')
            return redirect(url_for('admin_panel.message_templates'))

        category = MessageCategory(name=name, description=description)
        db.session.add(category)
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create',
            resource_type='message_category',
            resource_id=str(category.id),
            new_value=f"Created category: {name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message category "{name}" created successfully', 'success')
        return redirect(url_for('admin_panel.message_templates'))
    except Exception as e:
        logger.error(f"Error creating message category: {e}")
        flash('Message category creation failed. Check database connectivity and input validation.', 'error')
        return redirect(url_for('admin_panel.message_templates'))


@admin_panel_bp.route('/communication/messages/category/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_message_category():
    """Update a message category."""
    try:
        category_id = request.form.get('category_id')
        name = request.form.get('name')
        description = request.form.get('description')

        category = MessageCategory.query.get_or_404(category_id)
        old_name = category.name

        category.name = name
        category.description = description
        category.updated_at = datetime.utcnow()
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update',
            resource_type='message_category',
            resource_id=str(category.id),
            old_value=old_name,
            new_value=name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message category updated successfully', 'success')
        return redirect(url_for('admin_panel.message_templates'))
    except Exception as e:
        logger.error(f"Error updating message category: {e}")
        flash('Message category update failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.message_templates'))


@admin_panel_bp.route('/communication/messages/category/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_message_category():
    """Delete a message category."""
    try:
        category_id = request.form.get('category_id')
        category = MessageCategory.query.get_or_404(category_id)

        if category.templates:
            flash('Cannot delete category with existing templates', 'error')
            return redirect(url_for('admin_panel.message_templates'))

        category_name = category.name
        db.session.delete(category)
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete',
            resource_type='message_category',
            resource_id=str(category_id),
            old_value=f"Deleted category: {category_name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Message category "{category_name}" deleted successfully', 'success')
        return redirect(url_for('admin_panel.message_templates'))
    except Exception as e:
        logger.error(f"Error deleting message category: {e}")
        flash('Message category deletion failed. Verify database connection and constraints.', 'error')
        return redirect(url_for('admin_panel.message_templates'))
