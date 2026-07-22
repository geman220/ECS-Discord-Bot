# app/admin_panel/routes/mobile_features.py

"""
Admin Panel Mobile Features Routes

This module contains routes for mobile app features management:
- Mobile features hub with statistics
- Mobile app configuration and settings
- Push notification campaigns and subscriptions
- Mobile user analytics and management
- Mobile feature toggles
- User management for mobile app users
"""

import json
import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for, Response
from flask_login import login_required, current_user

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminConfig, AdminAuditLog
from app.models.core import User
from app.models.notifications import UserFCMToken
from app.decorators import role_required
from app.utils.db_utils import transactional

# Set up the module logger
logger = logging.getLogger(__name__)


@admin_panel_bp.route('/mobile-features')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_features():
    """Mobile Features hub."""
    try:
        # Get mobile features statistics
        # Get real mobile feature statistics
        
        # Device tokens represent push subscriptions
        push_subscriptions = UserFCMToken.query.filter_by(is_active=True).count()
        
        # Count users with device tokens as mobile users
        mobile_users = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True
        ).distinct().count()
        
        # Active mobile users (those who have used the app in last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        active_mobile_users = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True,
            UserFCMToken.updated_at >= thirty_days_ago
        ).distinct().count()
        
        # Mobile app configuration status
        try:
            mobile_app_enabled = str(AdminConfig.get_setting('mobile_app_enabled', 'true')).lower() in ('true', '1', 'yes', 'on')
            mobile_config_valid = mobile_app_enabled
        except Exception:
            mobile_config_valid = False

        # Check push notification configuration — mobile_push_notifications is
        # the key the app actually reads via /app_config (the old
        # push_notifications_enabled flag gated nothing and was removed).
        try:
            push_enabled = str(AdminConfig.get_setting('mobile_push_notifications', 'true')).lower() in ('true', '1', 'yes', 'on')
            push_service_status = 'active' if push_enabled else 'inactive'
        except Exception:
            push_service_status = 'unknown'

        # Mobile app downloads/installs (estimated from device tokens)
        total_app_installs = UserFCMToken.query.count()

        # Current app version = the latest published build (set by CI via
        # PUT /api/v1/app_config/build). The old free-text mobile_app_version
        # string was display-only and never matched reality.
        try:
            latest_build = AdminConfig.get_setting('app_latest_build_number', None)
            mobile_app_version = f'build {latest_build}' if latest_build else 'unknown'
        except Exception:
            mobile_app_version = 'unknown'

        # Version / Update control — real AdminConfig values owned by
        # APP_CONFIG_FIELDS (edited on the App Config page). Surfaced read-only
        # here so the Version & Update Control section reflects live config
        # instead of em-dash placeholders.
        def _cfg(key, default=''):
            try:
                return AdminConfig.get_setting(key, default)
            except Exception:
                return default

        app_force_update = str(_cfg('app_force_update', 'false')).lower() in ('true', '1', 'yes', 'on')
        app_config = {
            'min_build': _cfg('app_min_build_number', None),
            'latest_build': _cfg('app_latest_build_number', None),
            'force_update': app_force_update,
            'ios_update_url': _cfg('app_ios_update_url', '') or '',
            'android_update_url': _cfg('app_android_update_url', '') or '',
        }

        # Push notification category defaults applied to new device
        # registrations — these are the real column defaults on the User model
        # (match_reminder_notifications / rsvp_reminder_notifications /
        # team_update_notifications all default to True at the schema level).
        # opted_in counts are live adoption across current mobile users.
        push_defaults = []
        try:
            push_defaults = [
                {
                    'key': 'match_reminders',
                    'default_on': User.match_reminder_notifications.default.arg is True,
                    'opted_in': User.query.join(UserFCMToken).filter(
                        UserFCMToken.is_active == True,
                        User.match_reminder_notifications == True
                    ).distinct().count(),
                },
                {
                    'key': 'rsvp_reminders',
                    'default_on': User.rsvp_reminder_notifications.default.arg is True,
                    'opted_in': User.query.join(UserFCMToken).filter(
                        UserFCMToken.is_active == True,
                        User.rsvp_reminder_notifications == True
                    ).distinct().count(),
                },
                {
                    'key': 'team_updates',
                    'default_on': User.team_update_notifications.default.arg is True,
                    'opted_in': User.query.join(UserFCMToken).filter(
                        UserFCMToken.is_active == True,
                        User.team_update_notifications == True
                    ).distinct().count(),
                },
            ]
        except Exception as e:
            logger.warning(f"Error loading push notification defaults: {e}")
            push_defaults = []

        stats = {
            'total_app_installs': total_app_installs,
            'mobile_users': mobile_users,
            'push_subscriptions': push_subscriptions,
            'app_downloads': push_subscriptions,  # Use device tokens as proxy for downloads
            'active_mobile_users': active_mobile_users,
            'mobile_config_valid': mobile_config_valid,
            'mobile_service_status': 'active' if mobile_config_valid else 'inactive',
            'push_service_status': push_service_status,
            'mobile_app_version': mobile_app_version,
            'last_updated': _get_mobile_features_last_updated()
        }

        return render_template(
            'admin_panel/mobile_features_flowbite.html',
            stats=stats,
            app_config=app_config,
            push_defaults=push_defaults,
        )
    except Exception as e:
        logger.error(f"Error loading mobile features: {e}")
        flash('Mobile features dashboard unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/mobile-features/user-management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_user_management():
    """Redirect to consolidated mobile users page."""
    return redirect(url_for('admin_panel.mobile_users'))


@admin_panel_bp.route('/mobile-features/app-distribution')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_app_distribution():
    """Redirect to consolidated app config page."""
    return redirect(url_for('admin_panel.mobile_app_config'))


@admin_panel_bp.route('/mobile-features/app-analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_app_analytics():
    """Redirect to main mobile analytics page."""
    return redirect(url_for('admin_panel.mobile_analytics'))


# MOBILE_CONFIG_FIELDS removed — its keys were disconnected from what the
# Flutter app reads via GET /api/v1/app_config.  Useful fields have been
# moved: mobile_app_enabled → APP_CONFIG_FIELDS, mobile_crash_reporting →
# MOBILE_FEATURE_TOGGLES.  The remaining keys (push_notifications_enabled,
# apple_wallet_enabled, mobile_app_version, etc.) duplicated feature-toggle
# keys under different names and are no longer needed.


@admin_panel_bp.route('/mobile-features/mobile-config')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_config():
    """Redirect to consolidated app config page."""
    return redirect(url_for('admin_panel.mobile_app_config'))


@admin_panel_bp.route('/mobile-features/app-config')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_app_config():
    """Consolidated mobile app configuration: feature toggles + version/update settings."""
    from sqlalchemy import func

    # --- Feature Toggles ---
    features = []
    for ft in MOBILE_FEATURE_TOGGLES:
        setting = AdminConfig.query.filter_by(key=ft['key']).first()
        val = setting.value if setting and setting.value else ft['default']
        features.append({
            'key': ft['key'],
            'label': ft['label'],
            'description': ft['description'],
            'category': ft['category'],
            'enabled': str(val).lower() in ('true', '1', 'yes', 'on'),
        })

    grouped = {}
    for f in features:
        grouped.setdefault(f['category'], []).append(f)

    # --- Version / Update Settings ---
    settings = []
    for field in APP_CONFIG_FIELDS:
        setting = AdminConfig.query.filter_by(key=field['key']).first()
        settings.append({
            'key': field['key'],
            'label': field['label'],
            'description': field['description'],
            'data_type': field['data_type'],
            'value': setting.value if setting else field['default'],
            'updated_at': setting.updated_at if setting else None,
            'updated_by_user': setting.updated_by_user if setting else None,
        })

    # Device version distribution
    version_dist = []
    try:
        rows = db.session.query(
            UserFCMToken.app_version,
            UserFCMToken.platform,
            func.count(UserFCMToken.id).label('count')
        ).filter(
            UserFCMToken.is_active == True,
            UserFCMToken.app_version.isnot(None)
        ).group_by(
            UserFCMToken.app_version, UserFCMToken.platform
        ).order_by(func.count(UserFCMToken.id).desc()).all()

        total_devices = sum(r.count for r in rows) or 1
        for r in rows:
            version_dist.append({
                'version': r.app_version or 'Unknown',
                'platform': {'ios': 'iOS', 'android': 'Android'}.get(
                    (r.platform or '').lower(), 'Unknown'),
                'count': r.count,
                'pct': round((r.count / total_devices) * 100, 1),
            })
    except Exception as e:
        logger.warning(f"Error loading version distribution: {e}")

    return render_template(
        'admin_panel/mobile_features/app_config_flowbite.html',
        features=features,
        grouped=grouped,
        settings=settings,
        version_dist=version_dist,
    )


# Only toggles the app can actually act on. The old placeholders for features
# that were never built (offline sync, location services, contact sync, AR
# views, voice commands, smart predictions) were removed from here, from the
# /app_config API payload, and from the AdminConfig seed.
MOBILE_FEATURE_TOGGLES = [
    {'key': 'mobile_push_notifications', 'label': 'Push Notifications',
     'description': 'Enable push notifications for users', 'default': 'true', 'category': 'core'},
    {'key': 'mobile_wallet_passes', 'label': 'Wallet Passes',
     'description': 'Apple Wallet / Google Pay integration (also enforced server-side on pass generation)', 'default': 'true', 'category': 'core'},
    {'key': 'mobile_biometric_auth', 'label': 'Biometric Authentication',
     'description': 'Allow biometric login (Face ID / Fingerprint) as a user option', 'default': 'true', 'category': 'core'},
    {'key': 'mobile_camera_upload', 'label': 'Camera Upload',
     'description': 'Photo upload from camera roll', 'default': 'true', 'category': 'privacy'},
    {'key': 'mobile_analytics_tracking', 'label': 'Analytics Tracking',
     'description': 'Usage analytics collection from mobile app', 'default': 'true', 'category': 'privacy'},
    {'key': 'mobile_crash_reporting', 'label': 'Crash Reporting',
     'description': 'Enable crash report collection from mobile app', 'default': 'true', 'category': 'privacy'},
    {'key': 'admin_points_events_enabled', 'label': 'Admin Points Events',
     'description': 'Enables the More→Admin "Points Events" entry in the mobile app for awarding participation points at non-match league events.',
     'default': 'false', 'category': 'experimental'},
    {'key': 'admin_feedback_inbox_enabled', 'label': 'Admin Feedback Inbox',
     'description': 'Enables the mobile admin feedback inbox (list/triage/reply/close/bulk) for Global Admins. Backend endpoints under /api/v1/admin/feedback.',
     'default': 'true', 'category': 'core'},
]


@admin_panel_bp.route('/mobile-features/feature-toggles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_features_toggle():
    """Redirect to consolidated app config page."""
    return redirect(url_for('admin_panel.mobile_app_config'))


@admin_panel_bp.route('/mobile-features/mobile-users')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_users():
    """View mobile users with detailed management options."""
    try:
        # Get users with mobile device tokens with pagination
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        mobile_users_query = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True
        ).distinct()
        
        mobile_users = mobile_users_query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get mobile user statistics
        total_mobile_users = mobile_users_query.count()
        active_last_week = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True,
            UserFCMToken.updated_at >= datetime.utcnow() - timedelta(days=7)
        ).distinct().count()
        
        active_last_month = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True,
            UserFCMToken.updated_at >= datetime.utcnow() - timedelta(days=30)
        ).distinct().count()
        
        recent_signups = 0
        if hasattr(User, 'created_at'):
            recent_signups = mobile_users_query.filter(
                User.created_at >= datetime.utcnow() - timedelta(days=7)
            ).count()

        stats = {
            'total_mobile_users': total_mobile_users,
            'active_last_week': active_last_week,
            'active_last_month': active_last_month,
            'retention_rate': f"{(active_last_month / total_mobile_users * 100):.1f}%" if total_mobile_users > 0 else "0%",
            'new_installs_week': UserFCMToken.query.filter(
                UserFCMToken.created_at >= datetime.utcnow() - timedelta(days=7)
            ).count(),
            'recent_signups': recent_signups,
        }
        
        return render_template('admin_panel/mobile_features/mobile_users_flowbite.html',
                             mobile_users=mobile_users,
                             stats=stats)
    except Exception as e:
        logger.error(f"Error loading mobile users: {e}")
        flash('Mobile users list unavailable. Check user database connectivity.', 'error')
        return redirect(url_for('admin_panel.mobile_features'))


@admin_panel_bp.route('/mobile-features/push-subscriptions')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_subscriptions():
    """Manage push subscriptions."""
    try:
        # Get device token statistics
        device_tokens = UserFCMToken.query.order_by(UserFCMToken.created_at.desc()).limit(100).all()
        
        # Calculate statistics
        active_subscriptions = UserFCMToken.query.filter_by(is_active=True).count()
        inactive_subscriptions = UserFCMToken.query.filter_by(is_active=False).count()
        
        # Get subscription trends
        week_ago = datetime.utcnow() - timedelta(days=7)
        new_subscriptions_week = UserFCMToken.query.filter(
            UserFCMToken.created_at >= week_ago,
            UserFCMToken.is_active == True
        ).count()
        
        stats = {
            'active_subscriptions': active_subscriptions,
            'inactive_subscriptions': inactive_subscriptions,
            'new_subscriptions_week': new_subscriptions_week,
            'total_subscriptions': active_subscriptions + inactive_subscriptions
        }
        
        return render_template('admin_panel/mobile_features/push_subscriptions_flowbite.html',
                             device_tokens=device_tokens,
                             stats=stats)
    except Exception as e:
        logger.error(f"Error loading push subscriptions: {e}")
        flash('Push subscriptions unavailable. Device token database may be offline.', 'error')
        return redirect(url_for('admin_panel.mobile_features'))


@admin_panel_bp.route('/mobile-features/push-history')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_history():
    """View push notification history from both individual notifications and campaigns."""
    try:
        from app.models.communication import Notification
        from app.models.push_campaigns import PushNotificationCampaign

        now = datetime.utcnow()
        push_list = []

        # Source 1: Individual push notifications
        try:
            individual = Notification.query.filter_by(
                notification_type='push'
            ).order_by(Notification.created_at.desc()).limit(50).all()
            for n in individual:
                push_list.append({
                    'id': n.id,
                    'source': 'individual',
                    'title': 'Push Notification',
                    'content': n.content or '',
                    'notification_type': 'Individual',
                    'status': 'sent',
                    'created_at': n.created_at,
                    'recipients': 1,
                    'recipient': getattr(n, 'user', None),
                })
        except Exception as e:
            logger.warning(f"Error loading individual push notifications: {e}")

        # Source 2: Push campaigns (primary source of push activity)
        try:
            campaigns = PushNotificationCampaign.query.filter(
                PushNotificationCampaign.status.in_(['sent', 'failed', 'sending', 'cancelled'])
            ).order_by(PushNotificationCampaign.created_at.desc()).limit(50).all()
            for c in campaigns:
                push_list.append({
                    'id': c.id,
                    'source': 'campaign',
                    'title': c.title or c.name or 'Campaign',
                    'content': c.body or '',
                    'notification_type': 'Campaign',
                    'status': c.status,
                    'created_at': c.actual_send_time or c.created_at,
                    'recipients': c.sent_count or c.target_count or 0,
                    'recipient': None,
                    'delivered_count': c.delivered_count or 0,
                    'failed_count': c.failed_count or 0,
                    'click_count': c.click_count or 0,
                })
        except Exception as e:
            logger.warning(f"Error loading push campaigns: {e}")

        # Sort merged list by date descending
        push_list.sort(key=lambda x: x['created_at'] or datetime.min, reverse=True)
        push_list = push_list[:100]

        # Calculate statistics from the merged list
        total_sent = len(push_list)
        sent_today = sum(1 for p in push_list
                         if p['created_at'] and p['created_at'].date() == now.date())
        week_ago = now - timedelta(days=7)
        sent_this_week = sum(1 for p in push_list
                             if p['created_at'] and p['created_at'] >= week_ago)
        total_recipients = sum(p.get('recipients', 0) for p in push_list)

        stats = {
            'total_sent': total_sent,
            'sent_today': sent_today,
            'sent_this_week': sent_this_week,
            'avg_per_day': round(sent_this_week / 7, 1) if sent_this_week > 0 else 0,
            'total_recipients': total_recipients,
            'status_counts': {
                'sent': sum(1 for p in push_list if p['status'] == 'sent'),
                'failed': sum(1 for p in push_list if p['status'] == 'failed'),
                'sending': sum(1 for p in push_list if p['status'] == 'sending'),
                'cancelled': sum(1 for p in push_list if p['status'] == 'cancelled'),
            },
        }

        return render_template('admin_panel/mobile_features/push_history_flowbite.html',
                             push_notifications=push_list,
                             stats=stats)
    except Exception as e:
        logger.error(f"Error loading push history: {e}")
        flash('Push notification history unavailable. Check notification database.', 'error')
        return redirect(url_for('admin_panel.mobile_features'))


@admin_panel_bp.route('/mobile-features/mobile-analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_analytics():
    """View mobile analytics."""
    try:
        # Get mobile analytics data
        mobile_users_count = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True
        ).distinct().count()
        
        # Device platform breakdown from platform field
        platform_stats = {'iOS': 0, 'Android': 0, 'unknown': 0}
        try:
            device_tokens = UserFCMToken.query.filter_by(is_active=True).all()
            for token in device_tokens:
                key = {'ios': 'iOS', 'android': 'Android'}.get(
                    (token.platform or '').lower(), 'unknown'
                )
                platform_stats[key] = platform_stats.get(key, 0) + 1
        except Exception:
            pass
        
        # Period filter from query param
        days = request.args.get('days', 7, type=int)
        if days not in (7, 30, 90):
            days = 7

        analytics_data = _calculate_mobile_analytics(mobile_users_count, platform_stats, days=days)
        analytics_data['period_days'] = days

        return render_template('admin_panel/mobile_features/mobile_analytics_flowbite.html',
                             analytics_data=analytics_data,
                             analytics_json=json.dumps(analytics_data, default=str))
    except Exception as e:
        logger.error(f"Error loading mobile analytics: {e}")
        flash('Mobile analytics dashboard unavailable. Analytics service may be down.', 'error')
        return redirect(url_for('admin_panel.mobile_features'))


# AJAX Routes for Mobile Features
@admin_panel_bp.route('/mobile-features/toggle-setting', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_mobile_setting():
    """Toggle a mobile feature setting (upsert — creates key if missing)."""
    try:
        data = request.get_json()
        setting_key = data.get('key')
        enabled = data.get('enabled')

        if not setting_key:
            return jsonify({'success': False, 'message': 'Setting key is required'})

        # Validate against known toggle keys
        valid_keys = {ft['key']: ft for ft in MOBILE_FEATURE_TOGGLES}
        if setting_key not in valid_keys:
            return jsonify({'success': False, 'message': 'Unknown setting key'})

        # Get current value for audit log
        current = AdminConfig.query.filter_by(key=setting_key).first()
        old_value = current.value if current else None

        # Determine new value
        if enabled is not None:
            new_value = 'true' if enabled else 'false'
        elif current and current.value:
            new_value = 'false' if str(current.value).lower() in ('true', '1', 'yes', 'on') else 'true'
        else:
            default = valid_keys[setting_key]['default']
            new_value = 'false' if default.lower() == 'true' else 'true'

        ft_info = valid_keys[setting_key]
        AdminConfig.set_setting(
            key=setting_key,
            value=new_value,
            description=ft_info['description'],
            category='mobile_features',
            data_type='boolean',
            user_id=current_user.id,
        )

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='toggle_mobile_setting',
            resource_type='mobile_features',
            resource_id=setting_key,
            old_value=old_value,
            new_value=new_value,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'new_value': new_value == 'true',
            'message': f'{ft_info["label"]} {"enabled" if new_value == "true" else "disabled"}'
        })

    except Exception as e:
        logger.error(f"Error toggling mobile setting: {e}")
        return jsonify({'success': False, 'message': 'Server error occurred'})


@admin_panel_bp.route('/mobile-features/kill-switch', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def mobile_kill_switch():
    """Emergency kill switch — disable all mobile feature toggles."""
    try:
        changes = []
        for ft in MOBILE_FEATURE_TOGGLES:
            current = AdminConfig.query.filter_by(key=ft['key']).first()
            old_value = current.value if current else ft['default']
            AdminConfig.set_setting(
                key=ft['key'], value='false',
                description=ft['description'],
                category='mobile_features', data_type='boolean',
                user_id=current_user.id,
            )
            changes.append(f'{ft["key"]}: {old_value} -> false')

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='mobile_kill_switch',
            resource_type='mobile_features',
            resource_id='kill_switch',
            new_value='All features disabled',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return jsonify({'success': True, 'message': 'All mobile features have been disabled'})
    except Exception as e:
        logger.error(f"Error executing kill switch: {e}")
        return jsonify({'success': False, 'message': 'Server error occurred'})


@admin_panel_bp.route('/mobile-features/export-feature-config')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_feature_config():
    """Export current feature toggle configuration as JSON."""
    config = {}
    for ft in MOBILE_FEATURE_TOGGLES:
        setting = AdminConfig.query.filter_by(key=ft['key']).first()
        val = setting.value if setting and setting.value else ft['default']
        config[ft['key']] = {
            'label': ft['label'],
            'enabled': str(val).lower() in ('true', '1', 'yes', 'on'),
            'category': ft['category'],
        }
    return Response(
        json.dumps(config, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=mobile_feature_config.json'}
    )


@admin_panel_bp.route('/mobile-features/device-token/deactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def deactivate_device_token():
    """Deactivate a device token."""
    try:
        token_id = request.form.get('token_id')

        if not token_id:
            return jsonify({'success': False, 'message': 'Token ID is required'})

        device_token = UserFCMToken.query.get_or_404(token_id)

        # Deactivate the token
        device_token.is_active = False
        device_token.updated_at = datetime.utcnow()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='deactivate_device_token',
            resource_type='mobile_features',
            resource_id=str(token_id),
            old_value='active',
            new_value='inactive',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Device token deactivated successfully'
        })

    except Exception as e:
        logger.error(f"Error deactivating device token: {e}")
        return jsonify({'success': False, 'message': 'Error deactivating device token'})


@admin_panel_bp.route('/mobile-features/device-token/activate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def activate_device_token():
    """Activate a device token (re-enable push notifications)."""
    try:
        token_id = request.form.get('token_id')
        if not token_id:
            return jsonify({'success': False, 'message': 'Token ID is required'})

        device_token = UserFCMToken.query.get_or_404(token_id)
        device_token.is_active = True
        device_token.updated_at = datetime.utcnow()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='activate_device_token',
            resource_type='mobile_features',
            resource_id=str(token_id),
            old_value='inactive',
            new_value='active',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'message': 'Device token activated successfully'})
    except Exception as e:
        logger.error(f"Error activating device token: {e}")
        return jsonify({'success': False, 'message': 'Error activating device token'})


@admin_panel_bp.route('/mobile-features/device-token/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_device_token():
    """Permanently delete a device token."""
    try:
        token_id = request.form.get('token_id')
        if not token_id:
            return jsonify({'success': False, 'message': 'Token ID is required'})

        device_token = UserFCMToken.query.get_or_404(token_id)
        db.session.delete(device_token)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete_device_token',
            resource_type='mobile_features',
            resource_id=str(token_id),
            old_value='exists',
            new_value='deleted',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'message': 'Device token deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting device token: {e}")
        return jsonify({'success': False, 'message': 'Error deleting device token'})


@admin_panel_bp.route('/mobile-features/device-token/test', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def test_device_token():
    """Send a real test push notification to a single device token via FCM."""
    try:
        token_id = request.form.get('token_id')
        if not token_id:
            return jsonify({'success': False, 'message': 'Token ID is required'})

        device_token = UserFCMToken.query.get_or_404(token_id)

        from app.services.notification_service import notification_service
        if not getattr(notification_service, '_initialized', False):
            return jsonify({'success': False, 'message': 'Push notification service is not configured'})

        result = notification_service.send_test_notification(device_token.fcm_token)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='test_device_token',
            resource_type='mobile_features',
            resource_id=str(token_id),
            new_value=f'Test push sent (success={result.get("success")})',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if result.get('success'):
            return jsonify({'success': True, 'message': 'Test notification sent to the device.'})
        return jsonify({'success': False, 'message': result.get('error') or 'Failed to send test notification'})
    except Exception as e:
        logger.error(f"Error sending test notification: {e}")
        return jsonify({'success': False, 'message': 'Error sending test notification'})


def _parse_token_ids(raw):
    """Parse a comma-separated or list payload of token ids into a list of ints."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = str(raw).split(',')
    out = []
    for item in items:
        try:
            out.append(int(str(item).strip()))
        except (ValueError, TypeError):
            continue
    return out


@admin_panel_bp.route('/mobile-features/device-token/bulk-activate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_activate_tokens():
    """Activate multiple device tokens at once."""
    try:
        token_ids = _parse_token_ids(request.form.get('token_ids'))
        if not token_ids:
            return jsonify({'success': False, 'message': 'No token IDs provided'})

        updated = UserFCMToken.query.filter(UserFCMToken.id.in_(token_ids)).update(
            {'is_active': True, 'updated_at': datetime.utcnow()},
            synchronize_session=False
        )
        AdminAuditLog.log_action(
            user_id=current_user.id, action='bulk_activate_device_tokens',
            resource_type='mobile_features', resource_id='bulk',
            new_value=f'Activated {updated} tokens',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'count': updated, 'message': f'{updated} device tokens activated'})
    except Exception as e:
        logger.error(f"Error bulk activating tokens: {e}")
        return jsonify({'success': False, 'message': 'Error activating tokens'})


@admin_panel_bp.route('/mobile-features/device-token/bulk-deactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_deactivate_tokens():
    """Deactivate multiple device tokens at once."""
    try:
        token_ids = _parse_token_ids(request.form.get('token_ids'))
        if not token_ids:
            return jsonify({'success': False, 'message': 'No token IDs provided'})

        updated = UserFCMToken.query.filter(UserFCMToken.id.in_(token_ids)).update(
            {'is_active': False, 'updated_at': datetime.utcnow()},
            synchronize_session=False
        )
        AdminAuditLog.log_action(
            user_id=current_user.id, action='bulk_deactivate_device_tokens',
            resource_type='mobile_features', resource_id='bulk',
            new_value=f'Deactivated {updated} tokens',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'count': updated, 'message': f'{updated} device tokens deactivated'})
    except Exception as e:
        logger.error(f"Error bulk deactivating tokens: {e}")
        return jsonify({'success': False, 'message': 'Error deactivating tokens'})


@admin_panel_bp.route('/mobile-features/device-token/cleanup-inactive', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def cleanup_inactive_tokens():
    """Delete tokens that are already inactive, plus active tokens unused for 30+ days."""
    try:
        stale_threshold = datetime.utcnow() - timedelta(days=30)

        # Already-inactive tokens
        inactive_q = UserFCMToken.query.filter(UserFCMToken.is_active == False)
        # Active but unused for 30+ days (stale)
        stale_q = UserFCMToken.query.filter(
            UserFCMToken.is_active == True,
            UserFCMToken.last_used < stale_threshold
        )
        to_delete = {t.id: t for t in inactive_q.all()}
        for t in stale_q.all():
            to_delete[t.id] = t

        count = len(to_delete)
        for t in to_delete.values():
            db.session.delete(t)

        AdminAuditLog.log_action(
            user_id=current_user.id, action='cleanup_inactive_device_tokens',
            resource_type='mobile_features', resource_id='cleanup',
            new_value=f'Removed {count} inactive/stale tokens',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'count': count,
                        'message': f'{count} inactive/stale device tokens removed'})
    except Exception as e:
        logger.error(f"Error cleaning up inactive tokens: {e}")
        return jsonify({'success': False, 'message': 'Error cleaning up tokens'})


@admin_panel_bp.route('/mobile-features/device-token/export')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_subscriptions():
    """Export device token subscriptions as CSV."""
    import csv
    import io

    token_ids = _parse_token_ids(request.args.get('token_ids'))
    query = UserFCMToken.query
    if token_ids:
        query = query.filter(UserFCMToken.id.in_(token_ids))
    tokens = query.order_by(UserFCMToken.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'user_id', 'username', 'email', 'platform', 'app_version',
                     'is_active', 'created_at', 'updated_at', 'last_used', 'fcm_token'])
    for t in tokens:
        writer.writerow([
            t.id, t.user_id,
            t.user.username if t.user else '',
            t.user.email if t.user else '',
            t.platform or '', t.app_version or '',
            t.is_active,
            t.created_at.isoformat() if t.created_at else '',
            t.updated_at.isoformat() if t.updated_at else '',
            t.last_used.isoformat() if t.last_used else '',
            t.fcm_token,
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=push_subscriptions.csv'}
    )


@admin_panel_bp.route('/mobile-features/user/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_mobile_user_details():
    """Get mobile user details via AJAX."""
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})
        
        user = User.query.get_or_404(user_id)
        
        # Get user's device tokens
        device_tokens = UserFCMToken.query.filter_by(user_id=user_id).all()
        
        # Build user details
        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'device_tokens': [
                {
                    'id': token.id,
                    'token': token.fcm_token[:20] + '...' if len(token.fcm_token) > 20 else token.fcm_token,
                    'platform': token.platform or 'unknown',
                    'is_active': token.is_active,
                    'created_at': token.created_at.isoformat() if token.created_at else None,
                    'updated_at': token.updated_at.isoformat() if token.updated_at else None
                }
                for token in device_tokens
            ]
        }
        
        return jsonify({'success': True, 'user': user_data})
        
    except Exception as e:
        logger.error(f"Error getting mobile user details: {e}")
        return jsonify({'success': False, 'message': 'Error loading user details'})


# =============================================================================
# APP VERSION / UPDATE CONFIG
# =============================================================================

APP_CONFIG_FIELDS = [
    {'key': 'mobile_app_enabled', 'label': 'Mobile App Enabled', 'data_type': 'boolean',
     'description': 'Master switch — disables mobile app access entirely when off',
     'default': 'true'},
    {'key': 'app_min_build_number', 'label': 'Minimum Build Number', 'data_type': 'integer',
     'description': 'Builds below this number cannot use the app (set when older builds have breaking issues)',
     'default': '1'},
    {'key': 'app_latest_build_number', 'label': 'Latest Build Number', 'data_type': 'integer',
     'description': 'The newest build available — update this when you upload a new build',
     'default': '1'},
    {'key': 'app_update_message', 'label': 'Update Message', 'data_type': 'string',
     'description': 'Message shown to users when an update is available',
     'default': 'A new version is available. Please update for the best experience.'},
    {'key': 'app_force_update', 'label': 'Force Update', 'data_type': 'boolean',
     'description': 'When enabled, users MUST update before they can continue using the app',
     'default': 'false'},
    {'key': 'app_ios_update_url', 'label': 'iOS Update URL (TestFlight)', 'data_type': 'string',
     'description': 'TestFlight or App Store URL for iOS updates',
     'default': ''},
    {'key': 'app_android_update_url', 'label': 'Android Update URL', 'data_type': 'string',
     'description': 'Google Play Store URL for Android updates',
     'default': ''},
]


@admin_panel_bp.route('/mobile-features/app-version-config')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def app_version_config():
    """Redirect to consolidated app config page."""
    return redirect(url_for('admin_panel.mobile_app_config'))


@admin_panel_bp.route('/mobile-features/app-version-config/save', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def save_app_version_config():
    """Save mobile app version/update configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data received'}), 400

    valid_keys = {f['key']: f for f in APP_CONFIG_FIELDS}
    changes = []

    for key, value in data.items():
        if key not in valid_keys:
            continue

        field = valid_keys[key]
        old_setting = AdminConfig.query.filter_by(key=key).first()
        old_value = old_setting.value if old_setting else None

        AdminConfig.set_setting(
            key=key,
            value=str(value),
            description=field['description'],
            category='mobile_app',
            data_type=field['data_type'],
            user_id=current_user.id,
        )
        changes.append(f'{key}: {old_value} -> {value}')

    if changes:
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_app_version_config',
            resource_type='mobile_features',
            resource_id='app_version_config',
            new_value='; '.join(changes),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

    return jsonify({'success': True, 'message': 'App version configuration saved'})


# Helper Functions

def _get_mobile_features_last_updated():
    """Get when mobile features were last updated."""
    try:
        from app.models.admin_config import AdminConfig
        
        # Check when mobile-related configs were last updated
        mobile_configs = AdminConfig.query.filter(
            AdminConfig.key.contains('mobile') | 
            AdminConfig.key.contains('push')
        ).order_by(AdminConfig.updated_at.desc()).first()
        
        if mobile_configs and mobile_configs.updated_at:
            delta = datetime.utcnow() - mobile_configs.updated_at
            if delta.days == 0:
                if delta.seconds < 3600:
                    return f'{delta.seconds // 60} minutes ago'
                else:
                    return f'{delta.seconds // 3600} hours ago'
            else:
                return f'{delta.days} days ago'
        
        return 'Recently'
        
    except Exception as e:
        logger.warning(f"Error getting mobile features last updated: {e}")
        return 'Unknown'


def _get_mobile_app_installs():
    """Get mobile app install count from device tokens"""
    try:
        # Count device tokens as proxy for app installs
        total_installs = UserFCMToken.query.count()
        active_installs = UserFCMToken.query.filter_by(is_active=True).count()
        
        return {
            'total_installs': total_installs,
            'active_installs': active_installs,
            'inactive_installs': total_installs - active_installs
        }
        
    except Exception as e:
        logger.warning(f"Error getting mobile app installs: {e}")
        return {
            'total_installs': 0,
            'active_installs': 0,
            'inactive_installs': 0
        }


def _calculate_mobile_analytics(total_users, platform_stats, days=7):
    """Calculate mobile analytics from real telemetry and device token data."""
    from sqlalchemy import func

    now = datetime.utcnow()
    one_day_ago = now - timedelta(days=1)
    one_week_ago = now - timedelta(days=7)
    one_month_ago = now - timedelta(days=30)
    period_start = now - timedelta(days=days)

    result = {
        'total_mobile_users': total_users,
        'platform_breakdown': platform_stats,
    }

    try:
        # Try telemetry-based analytics first (real session data)
        from app.models.mobile_telemetry import MobileSession, MobileScreenView, MobileFeatureUsage

        # DAU/WAU/MAU from real sessions
        dau = db.session.query(func.count(func.distinct(MobileSession.user_id))).filter(
            MobileSession.started_at >= one_day_ago
        ).scalar() or 0
        wau = db.session.query(func.count(func.distinct(MobileSession.user_id))).filter(
            MobileSession.started_at >= one_week_ago
        ).scalar() or 0
        mau = db.session.query(func.count(func.distinct(MobileSession.user_id))).filter(
            MobileSession.started_at >= one_month_ago
        ).scalar() or 0

        has_telemetry = dau > 0 or wau > 0 or mau > 0

        if has_telemetry:
            result['daily_active_users'] = dau
            result['weekly_active_users'] = wau
            result['monthly_active_users'] = mau
            result['data_source'] = 'telemetry'

            # Retention rate
            result['retention_rate'] = f'{round((wau / mau) * 100, 1)}%' if mau > 0 else '0%'

            # Average session duration
            avg_dur = db.session.query(func.avg(MobileSession.duration_seconds)).filter(
                MobileSession.started_at >= period_start,
                MobileSession.duration_seconds.isnot(None)
            ).scalar()
            if avg_dur:
                mins = int(avg_dur) // 60
                secs = int(avg_dur) % 60
                result['avg_session_duration'] = f'{mins}m {secs}s'
            else:
                result['avg_session_duration'] = None

            # Average sessions per user
            total_sessions = db.session.query(func.count(MobileSession.id)).filter(
                MobileSession.started_at >= period_start
            ).scalar() or 0
            unique_users = db.session.query(func.count(func.distinct(MobileSession.user_id))).filter(
                MobileSession.started_at >= period_start
            ).scalar() or 0
            result['avg_sessions_per_user'] = round(total_sessions / unique_users, 1) if unique_users > 0 else 0

            # Top screens
            top_screens = db.session.query(
                MobileScreenView.screen_name,
                func.count(MobileScreenView.id).label('views'),
                func.avg(MobileScreenView.duration_seconds).label('avg_time')
            ).filter(
                MobileScreenView.entered_at >= period_start
            ).group_by(MobileScreenView.screen_name).order_by(
                func.count(MobileScreenView.id).desc()
            ).limit(5).all()
            result['top_screens'] = [
                {
                    'name': s.screen_name,
                    'views': s.views,
                    'avg_time': f'{int(s.avg_time or 0) // 60}m {int(s.avg_time or 0) % 60}s'
                }
                for s in top_screens
            ]

            # Avg screen views per session
            avg_screens = db.session.query(func.avg(MobileSession.screens_viewed)).filter(
                MobileSession.started_at >= period_start,
                MobileSession.screens_viewed > 0
            ).scalar()
            result['avg_screen_views_per_session'] = round(avg_screens, 1) if avg_screens else 0

            # Feature usage
            feature_usage = db.session.query(
                MobileFeatureUsage.feature_name,
                func.count(func.distinct(MobileFeatureUsage.user_id)).label('users')
            ).filter(
                MobileFeatureUsage.used_at >= period_start
            ).group_by(MobileFeatureUsage.feature_name).order_by(
                func.count(func.distinct(MobileFeatureUsage.user_id)).desc()
            ).limit(5).all()
            result['feature_usage'] = [
                {'name': f.feature_name, 'users': f.users,
                 'pct': round((f.users / unique_users) * 100) if unique_users > 0 else 0}
                for f in feature_usage
            ]

            # Daily engagement data for chart (last N days)
            daily_data = db.session.query(
                func.date(MobileSession.started_at).label('day'),
                func.count(func.distinct(MobileSession.user_id)).label('dau'),
                func.count(MobileSession.id).label('sessions')
            ).filter(
                MobileSession.started_at >= period_start
            ).group_by(func.date(MobileSession.started_at)).order_by(
                func.date(MobileSession.started_at)
            ).all()
            result['daily_engagement'] = [
                {'date': str(d.day), 'dau': d.dau, 'sessions': d.sessions}
                for d in daily_data
            ]
        else:
            # Fall back to UserFCMToken-based estimates
            result.update(_fallback_token_analytics(one_day_ago, one_week_ago, one_month_ago))
            result['data_source'] = 'device_tokens'

    except ImportError:
        result.update(_fallback_token_analytics(one_day_ago, one_week_ago, one_month_ago))
        result['data_source'] = 'device_tokens'
    except Exception as e:
        logger.error(f"Error calculating mobile analytics: {e}")
        result.update(_fallback_token_analytics(one_day_ago, one_week_ago, one_month_ago))
        result['data_source'] = 'device_tokens'

    return result


def _fallback_token_analytics(one_day_ago, one_week_ago, one_month_ago):
    """Fallback analytics from UserFCMToken activity when no telemetry data exists."""
    from sqlalchemy import func

    dau = db.session.query(func.count(func.distinct(UserFCMToken.user_id))).filter(
        UserFCMToken.is_active == True, UserFCMToken.updated_at >= one_day_ago
    ).scalar() or 0
    wau = db.session.query(func.count(func.distinct(UserFCMToken.user_id))).filter(
        UserFCMToken.is_active == True, UserFCMToken.updated_at >= one_week_ago
    ).scalar() or 0
    mau = db.session.query(func.count(func.distinct(UserFCMToken.user_id))).filter(
        UserFCMToken.is_active == True, UserFCMToken.updated_at >= one_month_ago
    ).scalar() or 0

    retention = round((wau / mau) * 100, 1) if mau > 0 else 0

    return {
        'daily_active_users': dau,
        'weekly_active_users': wau,
        'monthly_active_users': mau,
        'retention_rate': f'{retention}%',
        'avg_session_duration': None,
        'avg_sessions_per_user': None,
        'top_screens': [],
        'avg_screen_views_per_session': None,
        'feature_usage': [],
        'daily_engagement': [],
    }


# API Endpoints for AJAX operations

@admin_panel_bp.route('/api/mobile/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def mobile_analytics_api():
    """Get mobile app analytics data."""
    try:
        from app.models.core import User

        # Build platform stats
        mobile_users_count = User.query.join(UserFCMToken).filter(
            UserFCMToken.is_active == True
        ).distinct().count()

        platform_stats = {'iOS': 0, 'Android': 0, 'unknown': 0}
        for token in UserFCMToken.query.filter_by(is_active=True).all():
            key = {'ios': 'iOS', 'android': 'Android'}.get(
                (token.platform or '').lower(), 'unknown'
            )
            platform_stats[key] = platform_stats.get(key, 0) + 1

        analytics = _calculate_mobile_analytics(mobile_users_count, platform_stats)

        analytics.update({
            'mobile_installs': UserFCMToken.query.count(),
            'push_subscribers': UserFCMToken.query.filter_by(is_active=True).count(),
        })
        
        return jsonify(analytics)
        
    except Exception as e:
        logger.error(f"Mobile analytics error: {e}")
        return jsonify({'error': 'Failed to get analytics'}), 500


# Mobile Error Analytics Routes (migrated from legacy mobile_analytics_admin)

# Supported analytics periods. Maps a UI token to (label, lookback timedelta,
# series-bucket granularity). 24h is bucketed hourly; 7d/30d are bucketed daily.
ERROR_PERIODS = {
    '24h': {'label': '24h', 'delta': timedelta(hours=24), 'bucket': 'hour'},
    '7d': {'label': '7 Days', 'delta': timedelta(days=7), 'bucket': 'day'},
    '30d': {'label': '30 Days', 'delta': timedelta(days=30), 'bucket': 'day'},
}


def _build_error_volume_payload(period):
    """Build the real error-volume payload for a given period token.

    Returns a dict with the volume series (one point per bucket, continuous so
    empty buckets render as 0), the peak, the in-period total, the recovery
    rate, a critical-trend direction (this period vs the immediately preceding
    period of equal length), the top platform (from MobileLogs), and an
    error-free rate (share of mobile log lines that are not ERROR/FATAL).

    Every query is wrapped defensively: a missing/empty table must never raise.
    """
    from sqlalchemy import func

    cfg = ERROR_PERIODS.get(period) or ERROR_PERIODS['7d']
    period = period if period in ERROR_PERIODS else '7d'
    delta = cfg['delta']
    bucket = cfg['bucket']

    now = datetime.utcnow()
    period_start = now - delta
    prev_start = now - (delta * 2)

    payload = {
        'period': period,
        'period_label': cfg['label'],
        'volume_series': [],
        'volume_peak': 0,
        'period_total': 0,
        'recovery_rate_pct': None,
        'critical_this': 0,
        'critical_prev': 0,
        'critical_trend': 'flat',      # 'up' | 'down' | 'flat'
        'critical_delta': 0,
        'top_platform': None,          # display string e.g. 'iOS' / 'Android' or None
        'error_free_pct': None,        # share of non-error/fatal log lines, or None if no logs
        'error_free_total_logs': 0,
    }

    try:
        from app.models_mobile_analytics import MobileErrorAnalytics, MobileLogs
    except ImportError:
        return payload

    # ---- Volume series (grouped on real `timestamp` column) ----
    try:
        if bucket == 'hour':
            # Group by hour for the 24h view. func.strftime/date_trunc differ by
            # backend, so we bucket in Python from raw timestamps instead — robust
            # across PostgreSQL and SQLite without dialect-specific SQL.
            rows = db.session.query(MobileErrorAnalytics.timestamp).filter(
                MobileErrorAnalytics.timestamp >= period_start
            ).all()
            counts = {}
            for (ts,) in rows:
                if ts is None:
                    continue
                key = ts.replace(minute=0, second=0, microsecond=0)
                counts[key] = counts.get(key, 0) + 1
            base = now.replace(minute=0, second=0, microsecond=0)
            for offset in range(23, -1, -1):
                h = base - timedelta(hours=offset)
                c = counts.get(h, 0)
                payload['volume_series'].append({
                    'date': h.isoformat(),
                    'label': h.strftime('%-I%p').lower() if hasattr(h, 'strftime') else str(h),
                    'count': c,
                })
        else:
            ndays = delta.days
            volume_rows = db.session.query(
                func.date(MobileErrorAnalytics.timestamp).label('day'),
                func.count(MobileErrorAnalytics.id).label('count')
            ).filter(
                MobileErrorAnalytics.timestamp >= period_start
            ).group_by(func.date(MobileErrorAnalytics.timestamp)).all()

            counts_by_day = {}
            for row in volume_rows:
                day = row.day
                key = day.isoformat()[:10] if hasattr(day, 'isoformat') else str(day)[:10]
                counts_by_day[key] = counts_by_day.get(key, 0) + (row.count or 0)

            today = now.date()
            for offset in range(ndays - 1, -1, -1):
                d = today - timedelta(days=offset)
                key = d.isoformat()
                payload['volume_series'].append({
                    'date': key,
                    'label': d.strftime('%b %d'),
                    'count': counts_by_day.get(key, 0),
                })
        payload['volume_peak'] = max((pt['count'] for pt in payload['volume_series']), default=0)
        payload['period_total'] = sum(pt['count'] for pt in payload['volume_series'])
    except Exception as trend_err:
        logger.warning(f"Error building error volume series ({period}): {trend_err}")
        payload['volume_series'] = []
        payload['volume_peak'] = 0
        payload['period_total'] = 0

    # ---- Recovery rate over the period (real `was_recovered` boolean) ----
    try:
        recoverable = db.session.query(func.count(MobileErrorAnalytics.id)).filter(
            MobileErrorAnalytics.timestamp >= period_start,
            MobileErrorAnalytics.was_recovered.isnot(None)
        ).scalar() or 0
        recovered = db.session.query(func.count(MobileErrorAnalytics.id)).filter(
            MobileErrorAnalytics.timestamp >= period_start,
            MobileErrorAnalytics.was_recovered.is_(True)
        ).scalar() or 0
        if recoverable > 0:
            payload['recovery_rate_pct'] = round((recovered / recoverable) * 100, 1)
    except Exception as rec_err:
        logger.warning(f"Error computing recovery rate ({period}): {rec_err}")

    # ---- Critical trend: this period vs immediately-preceding period ----
    try:
        crit_this = db.session.query(func.count(MobileErrorAnalytics.id)).filter(
            MobileErrorAnalytics.timestamp >= period_start,
            MobileErrorAnalytics.severity == 'critical'
        ).scalar() or 0
        crit_prev = db.session.query(func.count(MobileErrorAnalytics.id)).filter(
            MobileErrorAnalytics.timestamp >= prev_start,
            MobileErrorAnalytics.timestamp < period_start,
            MobileErrorAnalytics.severity == 'critical'
        ).scalar() or 0
        payload['critical_this'] = crit_this
        payload['critical_prev'] = crit_prev
        payload['critical_delta'] = crit_this - crit_prev
        if crit_this > crit_prev:
            payload['critical_trend'] = 'up'
        elif crit_this < crit_prev:
            payload['critical_trend'] = 'down'
        else:
            payload['critical_trend'] = 'flat'
    except Exception as ct_err:
        logger.warning(f"Error computing critical trend ({period}): {ct_err}")

    # ---- Top platform over the period (real `platform` field on MobileLogs) ----
    try:
        plat_row = db.session.query(
            MobileLogs.platform,
            func.count(MobileLogs.id).label('count')
        ).filter(
            MobileLogs.created_at >= period_start,
            MobileLogs.platform.isnot(None),
            MobileLogs.platform != ''
        ).group_by(MobileLogs.platform).order_by(
            func.count(MobileLogs.id).desc()
        ).first()
        if plat_row and plat_row.platform:
            raw = str(plat_row.platform).strip().lower()
            payload['top_platform'] = {
                'ios': 'iOS', 'android': 'Android', 'web': 'Web',
            }.get(raw, str(plat_row.platform).strip())
    except Exception as plat_err:
        logger.warning(f"Error computing top platform ({period}): {plat_err}")

    # ---- Error-free rate: share of mobile log lines NOT at ERROR/FATAL level ----
    # This is an accurate label for what we can measure from MobileLogs.level.
    # It is NOT a crash-free-sessions metric (no session-outcome data exists),
    # so the template labels it "Error-Free Logs" rather than "Crash-Free".
    try:
        total_logs = db.session.query(func.count(MobileLogs.id)).filter(
            MobileLogs.created_at >= period_start
        ).scalar() or 0
        if total_logs > 0:
            err_logs = db.session.query(func.count(MobileLogs.id)).filter(
                MobileLogs.created_at >= period_start,
                MobileLogs.level.in_(['ERROR', 'FATAL'])
            ).scalar() or 0
            payload['error_free_total_logs'] = total_logs
            payload['error_free_pct'] = round((1 - (err_logs / total_logs)) * 100, 1)
    except Exception as ef_err:
        logger.warning(f"Error computing error-free rate ({period}): {ef_err}")

    return payload


@admin_panel_bp.route('/mobile-features/error-analytics/volume')
@login_required
@role_required(['Global Admin'])
def mobile_error_volume():
    """AJAX: error-volume series + derived stats for a chosen period (24h/7d/30d).

    Returns JSON consumed by the period-toggle on the error analytics dashboard.
    Always crash-safe — returns a zeroed payload rather than 500 on empty data.
    """
    period = request.args.get('period', '7d')
    if period not in ERROR_PERIODS:
        period = '7d'
    try:
        payload = _build_error_volume_payload(period)
        return jsonify({'success': True, **payload})
    except Exception as e:
        logger.error(f"Error in mobile_error_volume ({period}): {e}", exc_info=True)
        return jsonify({
            'success': False,
            'period': period,
            'volume_series': [],
            'volume_peak': 0,
            'period_total': 0,
            'recovery_rate_pct': None,
            'critical_trend': 'flat',
            'critical_delta': 0,
            'top_platform': None,
            'error_free_pct': None,
        })


@admin_panel_bp.route('/mobile-features/error-analytics')
@login_required
@role_required(['Global Admin'])
def mobile_error_analytics():
    """Mobile error analytics dashboard."""
    try:
        from sqlalchemy import func, desc

        # Try to import mobile error models
        try:
            from app.models_mobile_analytics import MobileErrorAnalytics, MobileErrorPatterns, MobileLogs
            models_available = True
        except ImportError:
            models_available = False

        if not models_available:
            flash('Mobile error analytics models are not available.', 'warning')
            return redirect(url_for('admin_panel.mobile_features'))

        # Get basic statistics
        total_errors = db.session.query(MobileErrorAnalytics).count()
        total_logs = db.session.query(MobileLogs).count()
        total_patterns = db.session.query(MobileErrorPatterns).count()

        # Recent activity (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_errors = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at >= week_ago
        ).count()

        recent_logs = db.session.query(MobileLogs).filter(
            MobileLogs.created_at >= week_ago
        ).count()

        # Top error types this week
        top_errors = db.session.query(
            MobileErrorAnalytics.error_type,
            MobileErrorAnalytics.severity,
            func.count(MobileErrorAnalytics.id).label('count')
        ).filter(
            MobileErrorAnalytics.created_at >= week_ago
        ).group_by(
            MobileErrorAnalytics.error_type,
            MobileErrorAnalytics.severity
        ).order_by(desc('count')).limit(10).all()

        # Active patterns
        active_patterns = db.session.query(MobileErrorPatterns).filter(
            MobileErrorPatterns.last_seen >= week_ago
        ).order_by(desc(MobileErrorPatterns.occurrences)).limit(5).all()

        # Critical errors (last 24 hours)
        day_ago = datetime.utcnow() - timedelta(days=1)
        critical_errors = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at >= day_ago,
            MobileErrorAnalytics.severity == 'critical'
        ).count()

        # ---- Severity Breakdown (real structured `severity` field) ----
        # The model defines a CHECK constraint: severity IN ('low','medium','high','critical').
        # We break down the week's errors by that real field. No fabricated buckets.
        severity_order = ['critical', 'high', 'medium', 'low']
        severity_counts = {s: 0 for s in severity_order}
        try:
            severity_rows = db.session.query(
                MobileErrorAnalytics.severity,
                func.count(MobileErrorAnalytics.id).label('count')
            ).filter(
                MobileErrorAnalytics.created_at >= week_ago
            ).group_by(MobileErrorAnalytics.severity).all()
            for row in severity_rows:
                sev = (row.severity or 'low')
                severity_counts[sev] = severity_counts.get(sev, 0) + (row.count or 0)
        except Exception as sev_err:
            logger.warning(f"Error building mobile severity breakdown: {sev_err}")
            severity_counts = {s: 0 for s in severity_order}

        severity_total = sum(severity_counts.values())
        severity_breakdown = [
            {
                'level': sev,
                'count': severity_counts.get(sev, 0),
                'pct': round((severity_counts.get(sev, 0) / severity_total) * 100, 1) if severity_total else 0,
            }
            for sev in severity_order
        ]

        # ---- Period-derived payload (default 7d): drives the volume series,
        # recovery rate, critical trend, top platform, and error-free rate.
        # Reuses the same builder the AJAX toggle calls so server-render and
        # client-toggle stay byte-for-byte consistent. ----
        default_period = '7d'
        period_payload = _build_error_volume_payload(default_period)
        # Prefer the period builder's series/peak (continuous, period-aware) but
        # keep the established 7d values identical to before.
        volume_series = period_payload['volume_series']
        daily_peak = period_payload['volume_peak']
        recovery_rate_pct = period_payload['recovery_rate_pct']

        stats = {
            'total_errors': total_errors,
            'total_logs': total_logs,
            'total_patterns': total_patterns,
            'recent_errors': recent_errors,
            'recent_logs': recent_logs,
            'critical_errors_24h': critical_errors,
            'top_errors': [
                {
                    'error_type': error.error_type,
                    'severity': error.severity,
                    'count': error.count
                } for error in top_errors
            ],
            'active_patterns': [pattern.to_dict() for pattern in active_patterns],
            'volume_series': volume_series,
            'volume_peak': daily_peak,
            'severity_breakdown': severity_breakdown,
            'severity_week_total': severity_total,
            'recovery_rate_pct': recovery_rate_pct,
            # Period-aware extras (default 7d) — drive toggle, platform, trend, error-free tiles
            'current_period': default_period,
            'period_total': period_payload['period_total'],
            'top_platform': period_payload['top_platform'],
            'critical_trend': period_payload['critical_trend'],
            'critical_delta': period_payload['critical_delta'],
            'critical_this': period_payload['critical_this'],
            'critical_prev': period_payload['critical_prev'],
            'error_free_pct': period_payload['error_free_pct'],
            'error_free_total_logs': period_payload['error_free_total_logs'],
        }

        return render_template('admin_panel/mobile_features/error_analytics_flowbite.html', stats=stats)

    except Exception as e:
        logger.error(f"Error loading mobile error analytics: {str(e)}", exc_info=True)
        flash('Error loading error analytics data', 'error')
        return redirect(url_for('admin_panel.mobile_features'))


@admin_panel_bp.route('/mobile-features/error-analytics/errors')
@login_required
@role_required(['Global Admin'])
def mobile_error_list():
    """View mobile error analytics with filtering and pagination."""
    try:
        from sqlalchemy import desc

        try:
            from app.models_mobile_analytics import MobileErrorAnalytics
            models_available = True
        except ImportError:
            models_available = False

        if not models_available:
            flash('Mobile error analytics models are not available.', 'warning')
            return redirect(url_for('admin_panel.mobile_features'))

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        severity_filter = request.args.get('severity')
        error_type_filter = request.args.get('error_type')
        # 'days' may be an int or the literal 'all' (export dialog) — treat 'all' as no date filter.
        days_raw = request.args.get('days', '7')
        if str(days_raw).lower() == 'all':
            days_filter = None
        else:
            try:
                days_filter = int(days_raw)
            except (ValueError, TypeError):
                days_filter = 7

        # Build query
        query = db.session.query(MobileErrorAnalytics)

        # Date filter
        if days_filter:
            cutoff_date = datetime.utcnow() - timedelta(days=days_filter)
            query = query.filter(MobileErrorAnalytics.created_at >= cutoff_date)

        # Severity filter
        if severity_filter:
            query = query.filter(MobileErrorAnalytics.severity == severity_filter)

        # Error type filter
        if error_type_filter:
            query = query.filter(MobileErrorAnalytics.error_type == error_type_filter)

        # Order by most recent
        query = query.order_by(desc(MobileErrorAnalytics.created_at))

        # Export branch (CSV / JSON) — uses the same filtered query, no pagination.
        if request.args.get('export') == 'true':
            export_format = (request.args.get('format') or 'csv').lower()
            rows = query.all()
            if export_format == 'json':
                payload = json.dumps([r.to_dict() for r in rows], default=str, indent=2)
                return Response(
                    payload, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename=mobile_errors.json'}
                )
            # default CSV
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['id', 'error_type', 'severity', 'error_message',
                             'user_id', 'device_info', 'app_version',
                             'was_recovered', 'timestamp', 'created_at'])
            for r in rows:
                writer.writerow([
                    r.id, r.error_type, r.severity, r.error_message or '',
                    r.user_id if r.user_id is not None else '',
                    r.device_info or '', r.app_version or '',
                    r.was_recovered,
                    r.timestamp.isoformat() if r.timestamp else '',
                    r.created_at.isoformat() if r.created_at else '',
                ])
            return Response(
                output.getvalue(), mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=mobile_errors.csv'}
            )

        # Paginate
        errors = query.paginate(page=page, per_page=per_page, error_out=False)

        # Get filter options
        severity_options = db.session.query(
            MobileErrorAnalytics.severity.distinct()
        ).all()
        severity_options = [s[0] for s in severity_options]

        error_type_options = db.session.query(
            MobileErrorAnalytics.error_type.distinct()
        ).all()
        error_type_options = [e[0] for e in error_type_options]

        return render_template(
            'admin_panel/mobile_features/error_list_flowbite.html',
            errors=errors,
            severity_options=severity_options,
            error_type_options=error_type_options,
            current_filters={
                'severity': severity_filter,
                'error_type': error_type_filter,
                'days': days_filter
            }
        )

    except Exception as e:
        logger.error(f"Error loading mobile errors: {str(e)}", exc_info=True)
        flash('Error loading error data', 'error')
        return redirect(url_for('admin_panel.mobile_error_analytics'))


@admin_panel_bp.route('/mobile-features/error-analytics/cleanup', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def mobile_error_cleanup():
    """Data cleanup management page."""
    try:
        from app.tasks.mobile_analytics_cleanup import (
            cleanup_mobile_analytics,
            get_cleanup_preview,
            get_analytics_storage_stats
        )

        if request.method == 'POST':
            # Verify confirmation
            data = request.get_json()
            if not data or not data.get('confirmed'):
                return jsonify({'error': 'Cleanup must be confirmed'}), 400

            # Execute cleanup
            result = cleanup_mobile_analytics()

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='mobile_analytics_cleanup',
                resource_type='mobile_features',
                resource_id='error_cleanup',
                new_value=str(result),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            if result['status'] == 'success':
                return jsonify(result)
            else:
                return jsonify(result), 500

        # GET request - show cleanup page
        preview = get_cleanup_preview()
        storage_stats = get_analytics_storage_stats()

        return render_template(
            'admin_panel/mobile_features/error_cleanup_flowbite.html',
            preview=preview,
            storage_stats=storage_stats
        )

    except ImportError:
        flash('Mobile analytics cleanup tasks are not available.', 'warning')
        return redirect(url_for('admin_panel.mobile_error_analytics'))
    except Exception as e:
        logger.error(f"Error loading cleanup page: {str(e)}", exc_info=True)
        flash('Error loading cleanup data', 'error')
        return redirect(url_for('admin_panel.mobile_error_analytics'))


@admin_panel_bp.route('/api/mobile/error/<int:error_id>')
@login_required
@role_required(['Global Admin'])
def api_mobile_error_details(error_id):
    """API endpoint for error details."""
    try:
        from app.models_mobile_analytics import MobileErrorAnalytics

        error = db.session.query(MobileErrorAnalytics).get(error_id)
        if not error:
            return jsonify({'error': 'Error not found'}), 404

        return jsonify(error.to_dict())

    except ImportError:
        return jsonify({'error': 'Mobile error analytics models not available'}), 500
    except Exception as e:
        logger.error(f"Error getting error details: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal Server Error'}), 500




# =============================================================================
# MOBILE USER NOTIFICATION ACTIONS
# =============================================================================

def _send_push_to_user_ids(user_ids, title, body):
    """Send a push notification to all active tokens for the given user ids.

    Returns a (success_bool, message, result_dict) tuple.
    """
    from app.services.notification_service import notification_service

    if not getattr(notification_service, '_initialized', False):
        return False, 'Push notification service is not configured', {}

    tokens = [row[0] for row in db.session.query(UserFCMToken.fcm_token).filter(
        UserFCMToken.user_id.in_(user_ids),
        UserFCMToken.is_active == True
    ).all()]
    tokens = list(set(tokens))

    if not tokens:
        return False, 'No active devices found for the selected user(s)', {}

    result = notification_service.send_general_notification(tokens, title, body)
    delivered = result.get('success', 0)
    return True, f'Notification sent to {delivered} device(s)', result


@admin_panel_bp.route('/mobile-features/user/send-notification', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def send_user_notification():
    """Send a push notification to a single mobile user's devices."""
    try:
        user_id = request.form.get('user_id', type=int)
        title = (request.form.get('title') or '').strip()
        message = (request.form.get('message') or '').strip()

        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})
        if not title or not message:
            return jsonify({'success': False, 'message': 'Title and message are required'})

        ok, msg, result = _send_push_to_user_ids([user_id], title, message)
        AdminAuditLog.log_action(
            user_id=current_user.id, action='send_user_push_notification',
            resource_type='mobile_features', resource_id=str(user_id),
            new_value=f'{title} ({msg})',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': ok, 'message': msg, 'result': result})
    except Exception as e:
        logger.error(f"Error sending user notification: {e}")
        return jsonify({'success': False, 'message': 'Error sending notification'})


@admin_panel_bp.route('/mobile-features/user/send-bulk-notification', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def send_bulk_user_notification():
    """Send a push notification to multiple selected mobile users."""
    try:
        user_ids = _parse_token_ids(request.form.get('user_ids'))
        title = (request.form.get('title') or '').strip()
        message = (request.form.get('message') or '').strip()

        if not user_ids:
            return jsonify({'success': False, 'message': 'No users selected'})
        if not title or not message:
            return jsonify({'success': False, 'message': 'Title and message are required'})

        ok, msg, result = _send_push_to_user_ids(user_ids, title, message)
        AdminAuditLog.log_action(
            user_id=current_user.id, action='send_bulk_user_push_notification',
            resource_type='mobile_features', resource_id='bulk',
            new_value=f'{title} to {len(user_ids)} users ({msg})',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': ok, 'message': msg, 'result': result})
    except Exception as e:
        logger.error(f"Error sending bulk notification: {e}")
        return jsonify({'success': False, 'message': 'Error sending notification'})


@admin_panel_bp.route('/mobile-features/user/export')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_user_data():
    """Export mobile users (users with device tokens) as CSV."""
    import csv
    import io

    user_ids = _parse_token_ids(request.args.get('user_ids'))

    base = User.query.join(UserFCMToken).filter(UserFCMToken.is_active == True).distinct()
    if user_ids:
        base = base.filter(User.id.in_(user_ids))
    users = base.order_by(User.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['user_id', 'username', 'email', 'created_at',
                     'active_device_count', 'platforms'])
    for u in users:
        tokens = UserFCMToken.query.filter_by(user_id=u.id, is_active=True).all()
        platforms = ','.join(sorted({t.platform for t in tokens if t.platform}))
        writer.writerow([
            u.id, u.username, u.email or '',
            u.created_at.isoformat() if u.created_at else '',
            len(tokens), platforms,
        ])

    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=mobile_users.csv'}
    )


@admin_panel_bp.route('/mobile-features/user/bulk-device-action', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_user_device_action():
    """Activate / deactivate / cleanup device tokens for selected users."""
    try:
        user_ids = _parse_token_ids(request.form.get('user_ids'))
        action = (request.form.get('device_action') or '').strip()

        if not user_ids:
            return jsonify({'success': False, 'message': 'No users selected'})

        if action == 'deactivate':
            count = UserFCMToken.query.filter(UserFCMToken.user_id.in_(user_ids)).update(
                {'is_active': False, 'updated_at': datetime.utcnow()},
                synchronize_session=False
            )
            msg = f'Deactivated {count} devices for selected users'
        elif action == 'reactivate':
            count = UserFCMToken.query.filter(UserFCMToken.user_id.in_(user_ids)).update(
                {'is_active': True, 'updated_at': datetime.utcnow()},
                synchronize_session=False
            )
            msg = f'Reactivated {count} devices for selected users'
        elif action == 'cleanup':
            stale_threshold = datetime.utcnow() - timedelta(days=30)
            stale = UserFCMToken.query.filter(
                UserFCMToken.user_id.in_(user_ids),
                UserFCMToken.last_used < stale_threshold
            ).all()
            count = len(stale)
            for t in stale:
                db.session.delete(t)
            msg = f'Removed {count} devices unused for 30+ days'
        else:
            return jsonify({'success': False, 'message': 'Unknown device action'})

        AdminAuditLog.log_action(
            user_id=current_user.id, action=f'bulk_user_device_{action}',
            resource_type='mobile_features', resource_id='bulk',
            new_value=msg,
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'count': count, 'message': msg})
    except Exception as e:
        logger.error(f"Error in bulk device action: {e}")
        return jsonify({'success': False, 'message': 'Error performing device action'})


# =============================================================================
# PUSH HISTORY ACTIONS
# =============================================================================

@admin_panel_bp.route('/mobile-features/push-history/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_history_details():
    """Return real details for a push-history entry (individual notification or campaign)."""
    try:
        source = request.args.get('source', 'campaign')
        notif_id = request.args.get('id', type=int)
        if not notif_id:
            return jsonify({'success': False, 'message': 'Notification ID is required'})

        if source == 'individual':
            from app.models.communication import Notification
            n = Notification.query.get(notif_id)
            if not n:
                return jsonify({'success': False, 'message': 'Notification not found'}), 404
            return jsonify({'success': True, 'notification': {
                'id': n.id,
                'source': 'individual',
                'title': 'Push Notification',
                'content': n.content or '',
                'notification_type': n.notification_type,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'recipient': n.user.username if n.user else None,
                'recipient_email': n.user.email if n.user else None,
            }})

        # default: campaign
        from app.models.push_campaigns import PushNotificationCampaign
        c = PushNotificationCampaign.query.get(notif_id)
        if not c:
            return jsonify({'success': False, 'message': 'Campaign not found'}), 404
        return jsonify({'success': True, 'notification': {
            'id': c.id,
            'source': 'campaign',
            'title': c.title or c.name,
            'content': c.body or '',
            'notification_type': 'Campaign',
            'status': c.status,
            'created_at': (c.actual_send_time or c.created_at).isoformat() if (c.actual_send_time or c.created_at) else None,
            'recipients': c.sent_count or c.target_count or 0,
            'delivered_count': c.delivered_count or 0,
            'failed_count': c.failed_count or 0,
            'click_count': c.click_count or 0,
            'delivery_rate': f'{c.delivery_rate}%',
        }})
    except Exception as e:
        logger.error(f"Error loading push history details: {e}")
        return jsonify({'success': False, 'message': 'Error loading notification details'})


@admin_panel_bp.route('/mobile-features/push-history/export')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_push_history():
    """Export push history (individual notifications + campaigns) as CSV."""
    import csv
    import io
    from app.models.communication import Notification
    from app.models.push_campaigns import PushNotificationCampaign

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['source', 'id', 'title', 'content', 'type', 'status',
                     'created_at', 'recipients', 'delivered', 'failed', 'clicks'])

    try:
        individual = Notification.query.filter_by(notification_type='push').order_by(
            Notification.created_at.desc()).limit(500).all()
        for n in individual:
            writer.writerow([
                'individual', n.id, 'Push Notification', n.content or '',
                'Individual', 'sent',
                n.created_at.isoformat() if n.created_at else '',
                1, '', '', '',
            ])
    except Exception as e:
        logger.warning(f"Error exporting individual notifications: {e}")

    try:
        campaigns = PushNotificationCampaign.query.filter(
            PushNotificationCampaign.status.in_(['sent', 'failed', 'sending', 'cancelled'])
        ).order_by(PushNotificationCampaign.created_at.desc()).limit(500).all()
        for c in campaigns:
            writer.writerow([
                'campaign', c.id, c.title or c.name or 'Campaign', c.body or '',
                'Campaign', c.status,
                (c.actual_send_time or c.created_at).isoformat() if (c.actual_send_time or c.created_at) else '',
                c.sent_count or c.target_count or 0,
                c.delivered_count or 0, c.failed_count or 0, c.click_count or 0,
            ])
    except Exception as e:
        logger.warning(f"Error exporting campaigns: {e}")

    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=push_history.csv'}
    )


@admin_panel_bp.route('/mobile-features/push-history/cleanup-old', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def cleanup_old_push_history():
    """Delete individual push notifications older than 90 days."""
    try:
        from app.models.communication import Notification
        cutoff = datetime.utcnow() - timedelta(days=90)
        old = Notification.query.filter(
            Notification.notification_type == 'push',
            Notification.created_at < cutoff
        ).all()
        count = len(old)
        for n in old:
            db.session.delete(n)

        AdminAuditLog.log_action(
            user_id=current_user.id, action='cleanup_old_push_history',
            resource_type='mobile_features', resource_id='cleanup',
            new_value=f'Removed {count} push notifications older than 90 days',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'count': count,
                        'message': f'{count} old push notifications removed'})
    except Exception as e:
        logger.error(f"Error cleaning up old push history: {e}")
        return jsonify({'success': False, 'message': 'Error cleaning up notifications'})