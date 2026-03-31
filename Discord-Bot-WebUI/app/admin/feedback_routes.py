# app/admin/feedback_routes.py

"""
Legacy Feedback Routes - DEPRECATED

These routes redirect to the admin_panel equivalents which have:
- Full audit logging
- Multi-channel notifications via orchestrator
- Proper status change tracking
"""

import logging
from flask import redirect, url_for
from flask_login import login_required

from app.decorators import role_required

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


@admin_bp.route('/admin/feedback/<int:feedback_id>', endpoint='view_feedback', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_feedback(feedback_id):
    """Redirect to admin panel feedback view."""
    return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback_id), code=301)


@admin_bp.route('/admin/feedback/<int:feedback_id>/close', endpoint='close_feedback', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def close_feedback(feedback_id):
    """Redirect to admin panel feedback close."""
    return redirect(url_for('admin_panel.close_feedback', feedback_id=feedback_id), code=307)


@admin_bp.route('/admin/feedback/<int:feedback_id>/delete', endpoint='delete_feedback', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_feedback(feedback_id):
    """Redirect to admin panel feedback delete."""
    return redirect(url_for('admin_panel.delete_feedback', feedback_id=feedback_id), code=307)
