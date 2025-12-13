# app/admin_panel/routes/user_management/analytics.py

"""
User Analytics Routes

Routes for user analytics and export:
- User analytics dashboard
- Export user data
"""

import logging

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.admin_panel.routes.user_management.helpers import (
    get_user_analytics,
    generate_user_export_data,
)

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_analytics():
    """Advanced user analytics dashboard."""
    try:
        # Get comprehensive analytics data
        analytics_data = get_user_analytics()

        return render_template('admin_panel/users/analytics.html',
                               analytics_data=analytics_data)
    except Exception as e:
        logger.error(f"Error loading user analytics: {e}")
        flash('User analytics unavailable. Verify database connection and analytics data.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/analytics/export', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_user_analytics():
    """Export user analytics data."""
    try:
        data = request.get_json()
        export_type = data.get('type', 'users')  # users, roles, activity
        format_type = data.get('format', 'csv')  # csv, json, xlsx
        date_range = data.get('date_range', '30_days')

        # Generate export data
        export_data = generate_user_export_data(export_type, format_type, date_range)

        # Log the export action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='export_user_analytics',
            resource_type='user_analytics',
            resource_id=export_type,
            new_value=f'Exported {export_type} data in {format_type} format',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'User analytics export completed',
            'download_url': export_data.get('url'),
            'filename': export_data.get('filename')
        })

    except Exception as e:
        logger.error(f"Error exporting user analytics: {e}")
        return jsonify({'success': False, 'message': 'Export failed'}), 500
