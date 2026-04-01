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

        # Check push notification configuration
        try:
            push_enabled = str(AdminConfig.get_setting('push_notifications_enabled', 'true')).lower() in ('true', '1', 'yes', 'on')
            push_service_status = 'active' if push_enabled else 'inactive'
        except Exception:
            push_service_status = 'unknown'

        # Mobile app downloads/installs (estimated from device tokens)
        total_app_installs = UserFCMToken.query.count()

        # Get mobile app version from AdminConfig
        try:
            mobile_app_version = str(AdminConfig.get_setting('mobile_app_version', 'v1.0.0'))
        except Exception:
            mobile_app_version = 'v1.0.0'
        
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
        
        return render_template('admin_panel/mobile_features_flowbite.html', stats=stats)
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


MOBILE_FEATURE_TOGGLES = [
    {'key': 'mobile_push_notifications', 'label': 'Push Notifications',
     'description': 'Enable push notifications for users', 'default': 'true', 'category': 'core'},
    {'key': 'mobile_wallet_passes', 'label': 'Wallet Passes',
     'description': 'Apple Wallet / Google Pay integration', 'default': 'true', 'category': 'core'},
    {'key': 'mobile_offline_sync', 'label': 'Offline Sync',
     'description': 'Allow offline data synchronization', 'default': 'false', 'category': 'core'},
    {'key': 'mobile_biometric_auth', 'label': 'Biometric Authentication',
     'description': 'Allow biometric login (Face ID / Fingerprint) as a user option', 'default': 'true', 'category': 'core'},
    {'key': 'mobile_location_services', 'label': 'Location Services',
     'description': 'Location-based features and notifications', 'default': 'false', 'category': 'privacy'},
    {'key': 'mobile_camera_upload', 'label': 'Camera Upload',
     'description': 'Photo upload from camera roll', 'default': 'true', 'category': 'privacy'},
    {'key': 'mobile_contact_sync', 'label': 'Contact Sync',
     'description': 'Sync contacts for team invitations', 'default': 'false', 'category': 'privacy'},
    {'key': 'mobile_analytics_tracking', 'label': 'Analytics Tracking',
     'description': 'Usage analytics collection from mobile app', 'default': 'true', 'category': 'privacy'},
    {'key': 'mobile_crash_reporting', 'label': 'Crash Reporting',
     'description': 'Enable crash report collection from mobile app', 'default': 'true', 'category': 'privacy'},
    {'key': 'mobile_ar_match_views', 'label': 'AR Match Views',
     'description': 'Augmented reality match experience', 'default': 'false', 'category': 'experimental'},
    {'key': 'mobile_voice_commands', 'label': 'Voice Commands',
     'description': 'Voice-controlled navigation', 'default': 'false', 'category': 'experimental'},
    {'key': 'mobile_smart_predictions', 'label': 'Smart Predictions',
     'description': 'AI-powered match predictions', 'default': 'false', 'category': 'experimental'},
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


@admin_panel_bp.route('/mobile-features/push-campaigns')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_campaigns():
    """Manage push notification campaigns."""
    try:
        # Log the access to push campaigns
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_push_campaigns',
            resource_type='mobile_features',
            resource_id='push_campaigns',
            new_value='Accessed push notification campaigns interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models.core import User
        
        # Get user statistics for targeting campaigns
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        
        # Sample campaign templates
        campaign_templates = [
            {
                'id': 1,
                'name': 'Match Reminder',
                'description': 'Remind players about upcoming matches',
                'target_audience': 'Active Players',
                'estimated_reach': active_users
            },
            {
                'id': 2,
                'name': 'Season Update',
                'description': 'Share season standings and updates',
                'target_audience': 'All Users',
                'estimated_reach': total_users
            },
            {
                'id': 3,
                'name': 'Event Announcement',
                'description': 'Announce special events and tournaments',
                'target_audience': 'Active Players',
                'estimated_reach': active_users
            }
        ]
        
        # Recent campaigns from PushNotificationCampaign model
        recent_campaigns = []
        try:
            from app.models.push_campaigns import PushNotificationCampaign
            campaigns = PushNotificationCampaign.query.order_by(
                PushNotificationCampaign.created_at.desc()
            ).limit(10).all()
            for c in campaigns:
                recent_campaigns.append({
                    'id': c.id,
                    'name': c.name,
                    'sent_date': c.actual_send_time.strftime('%Y-%m-%d') if c.actual_send_time else (c.created_at.strftime('%Y-%m-%d') if c.created_at else ''),
                    'recipients': c.target_count,
                    'delivery_rate': f'{c.delivery_rate:.0f}%' if c.delivery_rate else 'N/A',
                    'open_rate': f'{c.click_rate:.0f}%' if c.click_rate else 'N/A',
                    'status': c.status,
                })
        except Exception:
            pass

        # Calculate real stats from campaigns
        total_sent_today = 0
        try:
            from app.models.push_campaigns import PushNotificationCampaign
            today_campaigns = PushNotificationCampaign.query.filter(
                PushNotificationCampaign.actual_send_time >= datetime.utcnow().replace(hour=0, minute=0, second=0),
                PushNotificationCampaign.status == 'sent'
            ).all()
            total_sent_today = sum(c.sent_count for c in today_campaigns)
        except Exception:
            pass

        campaign_data = {
            'total_users': total_users,
            'active_users': active_users,
            'templates': campaign_templates,
            'recent_campaigns': recent_campaigns,
            'total_sent_today': total_sent_today,
            'delivery_rate': None,
            'avg_open_rate': None
        }
        
        return render_template('admin_panel/mobile_features/push_campaigns_flowbite.html',
                             campaign_data=campaign_data)
    except Exception as e:
        logger.error(f"Error loading push campaigns: {e}")
        flash('Push campaign management unavailable. Check notification service.', 'error')
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
            'active_patterns': [pattern.to_dict() for pattern in active_patterns]
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
        days_filter = request.args.get('days', 7, type=int)

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