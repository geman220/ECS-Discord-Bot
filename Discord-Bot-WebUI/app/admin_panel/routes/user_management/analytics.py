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

        return render_template('admin_panel/users/analytics_flowbite.html',
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
        data = request.get_json() or {}
        export_type = data.get('type', 'users')  # users, roles, activity, all
        format_type = data.get('format', 'json')  # json (csv/xlsx would need additional libs)
        date_range = data.get('date_range', 'all')  # 7_days, 30_days, 90_days, all

        # Generate export data
        export_result = generate_user_export_data(export_type, format_type, date_range)

        # Log the export action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='export_user_analytics',
            resource_type='user_analytics',
            resource_id=export_type,
            new_value=f'Exported {export_result.get("count", 0)} {export_type} records',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Exported {export_result.get("count", 0)} records successfully',
            'export_data': export_result,
            'filename': export_result.get('filename'),
            'count': export_result.get('count', 0)
        })

    except Exception as e:
        logger.error(f"Error exporting user analytics: {e}")
        return jsonify({'success': False, 'message': 'Export failed'}), 500
