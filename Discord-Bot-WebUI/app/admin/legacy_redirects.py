# app/admin/legacy_redirects.py

"""
Legacy Redirect Routes for Backward Compatibility

This module provides redirect routes from old /admin/* endpoints to the new
/admin-panel/* endpoints. This allows for a smooth migration while maintaining
backward compatibility with bookmarks, external links, etc.

These routes will show a deprecation warning and redirect users to the new location.
After a migration period, these routes should be removed.
"""

import logging
from flask import redirect, url_for, flash
from flask_login import login_required

from app.admin.blueprint import admin_bp
from app.decorators import role_required

logger = logging.getLogger(__name__)


def log_legacy_access(old_route, new_route):
    """Log access to legacy route for migration tracking."""
    logger.info(f"Legacy route accessed: {old_route} -> redirecting to {new_route}")


# -----------------------------------------------------------------------------
# Match Operations Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/match_verification_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def legacy_match_verification_redirect():
    """Redirect old match verification route to new admin panel."""
    log_legacy_access('/admin/match_verification', '/admin-panel/match-verification')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.match_verification'))


# -----------------------------------------------------------------------------
# User Management Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/user_approvals_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_user_approvals_redirect():
    """Redirect old user approvals route to new admin panel."""
    log_legacy_access('/admin/user_approvals', '/admin-panel/users/approvals')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.user_approvals'))


@admin_bp.route('/user_waitlist_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_user_waitlist_redirect():
    """Redirect old user waitlist route to new admin panel."""
    log_legacy_access('/admin/user_waitlist', '/admin-panel/users/waitlist')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.user_waitlist'))


# -----------------------------------------------------------------------------
# Discord Management Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/discord_management_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_discord_management_redirect():
    """Redirect old discord management route to new admin panel."""
    log_legacy_access('/admin/discord_management', '/admin-panel/discord')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.discord_overview'))


# -----------------------------------------------------------------------------
# Feedback/Reports Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/feedback_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_feedback_redirect():
    """Redirect old feedback route to new admin panel."""
    log_legacy_access('/admin/feedback', '/admin-panel/feedback')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.feedback_list'))


@admin_bp.route('/reports_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_reports_redirect():
    """Redirect old admin reports route to new admin panel."""
    log_legacy_access('/admin/reports', '/admin-panel/reports')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.reports_dashboard'))


# -----------------------------------------------------------------------------
# Substitute Management Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/manage_sub_requests_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_sub_requests_redirect():
    """Redirect old sub requests route to new admin panel."""
    log_legacy_access('/admin/manage_sub_requests', '/admin-panel/substitute-management')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.substitute_management'))


# -----------------------------------------------------------------------------
# Push Notifications Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/notifications_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_notifications_redirect():
    """Redirect old notifications route to new admin panel."""
    log_legacy_access('/admin/notifications/', '/admin-panel/push-notifications')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.push_notifications'))


# -----------------------------------------------------------------------------
# Health/System Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/health_redirect')
@login_required
@role_required(['Global Admin'])
def legacy_health_redirect():
    """Redirect old health check route to new admin panel."""
    log_legacy_access('/admin/health', '/admin-panel/system/health')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.health_dashboard'))


@admin_bp.route('/redis_stats_redirect')
@login_required
@role_required(['Global Admin'])
def legacy_redis_redirect():
    """Redirect old redis stats route to new admin panel."""
    log_legacy_access('/admin/redis_stats', '/admin-panel/system/redis')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.redis_management'))


# -----------------------------------------------------------------------------
# Draft Management Redirects
# -----------------------------------------------------------------------------

@admin_bp.route('/draft_history_redirect')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def legacy_draft_history_redirect():
    """Redirect old draft history route to new admin panel."""
    log_legacy_access('/admin/draft_history', '/admin-panel/draft/history')
    flash('This page has moved. You have been redirected to the new Admin Panel.', 'info')
    return redirect(url_for('admin_panel.draft_history'))


# -----------------------------------------------------------------------------
# Helper function to add deprecation warning to all old admin templates
# -----------------------------------------------------------------------------

def get_deprecation_warning():
    """Return a deprecation warning message for templates."""
    return (
        "This page is part of the legacy admin system. "
        "Please use the new Admin Panel for the improved experience. "
        "This page will be removed in a future update."
    )
