# app/admin_panel/routes/user_management/analytics.py

"""
User Analytics Routes

Routes for user analytics and export:
- User analytics dashboard
- Export user data
"""

import logging

from flask import request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.admin_panel.routes.user_management.helpers import (
    generate_user_export_data,
    get_registration_trends,
)

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_analytics():
    """Legacy user-analytics dashboard — now folded into the Members command center.

    The account-lifecycle analytics live at Members → Analytics so they sit beside
    the intake queues they summarize. The endpoint name is kept so any lingering
    bookmark or url_for('admin_panel.user_analytics') lands on the new surface; the
    old standalone template is retired. The JSON/export endpoints below are unchanged
    (the new view calls the same ones).
    """
    return redirect(url_for('admin_panel.members_worklist', tab='analytics'))


@admin_panel_bp.route('/users/analytics/registration-trends')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_analytics_registration_trends():
    """Return registration trend data for a given period as JSON.

    Used by the analytics dashboard's period toggle (30d/90d/12m) to reload
    the registration trend chart without a full page reload.
    """
    try:
        period = request.args.get('period', '30d')
        if period not in ('30d', '90d', '12m'):
            period = '30d'
        trends = get_registration_trends(period)
        return jsonify({
            'success': True,
            'period': period,
            'registration_trends': trends,
        })
    except Exception as e:
        logger.error(f"Error loading registration trends: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to load trends'}), 500


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
