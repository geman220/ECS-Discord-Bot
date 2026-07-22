# app/admin_panel/routes/communication/push.py

"""
Push Notifications Routes (Consolidated)

All push notification management in a single module:
- Page views: list, dashboard, send form, settings
- Send operations: basic send, broadcast, enhanced broadcast
- Admin operations: test, token cleanup, token list, status
- Target data APIs: teams, leagues, roles, pools, platform stats
- Legacy redirects: /push-notifications/* → /communication/push-notifications/*
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.communication import Notification
from app.models.notifications import UserFCMToken
from app.models.core import User
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


def _build_send_volume_series(windows):
    """Build per-day push send-volume series for the dashboard trend chart.

    Reads ONLY real columns from PushNotificationCampaign:
      - sent_count   (devices the campaign reported sending to)
      - actual_send_time / created_at (the day the volume is attributed to)
      - status       (only count campaigns that actually sent)

    Returns a dict keyed by window label ('7d', '30d', '90d') with a dense,
    zero-filled daily series plus summary figures so the template can render an
    SVG area/line chart and Sent / Daily-Avg / Peak footer without any further
    computation:

        {
          '7d': {
            'series': [{'date': '2026-05-27', 'label': 'May 27', 'count': 12}, ...],
            'total': 84, 'daily_avg': 12, 'peak': 30, 'days': 7
          },
          ...
        }

    Fully defensive: any failure (missing table, empty data) yields zero-filled
    series so the dashboard never 500s.
    """
    result = {}
    try:
        from app.models.push_campaigns import PushNotificationCampaign, CampaignStatus

        # Attribute each campaign's volume to the day it sent (or was created if
        # actual_send_time is null). COALESCE keeps drafts-turned-sent honest.
        send_day = db.func.date(
            db.func.coalesce(
                PushNotificationCampaign.actual_send_time,
                PushNotificationCampaign.created_at,
            )
        )

        max_window = max(windows)
        window_start = (datetime.utcnow() - timedelta(days=max_window - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # One grouped query across the widest window; slice per-window in Python.
        rows = db.session.query(
            send_day.label('day'),
            db.func.coalesce(db.func.sum(PushNotificationCampaign.sent_count), 0).label('volume'),
        ).filter(
            PushNotificationCampaign.status == CampaignStatus.SENT.value,
            db.func.coalesce(
                PushNotificationCampaign.actual_send_time,
                PushNotificationCampaign.created_at,
            ) >= window_start,
        ).group_by(send_day).all()

        # Normalize day keys to date objects (func.date may return str or date).
        volume_by_day = {}
        for day, volume in rows:
            if day is None:
                continue
            if isinstance(day, str):
                try:
                    day = datetime.strptime(day[:10], '%Y-%m-%d').date()
                except ValueError:
                    continue
            elif isinstance(day, datetime):
                day = day.date()
            volume_by_day[day] = int(volume or 0)
    except Exception as e:
        logger.warning(f"Send volume series unavailable, defaulting to empty: {e}")
        volume_by_day = {}

    today = datetime.utcnow().date()
    for days in windows:
        series = []
        for offset in range(days - 1, -1, -1):
            d = today - timedelta(days=offset)
            count = volume_by_day.get(d, 0)
            series.append({
                'date': d.isoformat(),
                'label': d.strftime('%b %-d') if hasattr(d, 'strftime') else str(d),
                'count': count,
            })
        total = sum(pt['count'] for pt in series)
        peak = max((pt['count'] for pt in series), default=0)
        daily_avg = round(total / days) if days else 0
        result[f'{days}d'] = {
            'series': series,
            'total': total,
            'daily_avg': daily_avg,
            'peak': peak,
            'days': days,
        }
    return result


# =============================================================================
# PAGE VIEWS
# =============================================================================

@admin_panel_bp.route('/push-notifications')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notifications():
    """Push notifications management page."""
    try:
        notification_history = Notification.query.filter_by(
            notification_type='push'
        ).order_by(Notification.created_at.desc()).limit(20).all()

        total_subscribers = UserFCMToken.query.filter_by(is_active=True).count()
        active_subscribers = UserFCMToken.query.filter(
            UserFCMToken.is_active == True,
            UserFCMToken.updated_at >= datetime.utcnow() - timedelta(days=30)
        ).count()

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        notifications_sent_today = Notification.query.filter(
            Notification.notification_type == 'push',
            Notification.created_at >= today_start
        ).count()

        week_start = datetime.utcnow() - timedelta(days=7)
        new_subscribers_week = UserFCMToken.query.filter(
            UserFCMToken.created_at >= week_start,
            UserFCMToken.is_active == True
        ).count()

        unsubscribed_count = UserFCMToken.query.filter_by(is_active=False).count()
        total_notifications = Notification.query.filter_by(notification_type='push').count()
        # Real delivery/click rates aggregated from campaign analytics (no estimates).
        # delivery_rate = delivered/sent, click_rate = clicked/delivered; 'N/A' when
        # there is nothing sent yet rather than a fabricated percentage.
        # Wrapped defensively: a missing/mismatched campaigns table must degrade
        # to N/A rates, not take down the whole page.
        try:
            from app.models.push_campaigns import PushNotificationCampaign
            from sqlalchemy import func as _func
            _sent, _delivered, _clicked = db.session.query(
                _func.coalesce(_func.sum(PushNotificationCampaign.sent_count), 0),
                _func.coalesce(_func.sum(PushNotificationCampaign.delivered_count), 0),
                _func.coalesce(_func.sum(PushNotificationCampaign.click_count), 0),
            ).first() or (0, 0, 0)
        except Exception as analytics_err:
            logger.warning(f"Campaign analytics unavailable, showing N/A rates: {analytics_err}")
            db.session.rollback()
            _sent, _delivered, _clicked = 0, 0, 0
        delivery_rate = f"{round(100 * _delivered / _sent)}%" if _sent else 'N/A'
        click_rate = f"{round(100 * _clicked / _delivered)}%" if _delivered else 'N/A'

        from app.models import Team, League, Role
        teams = Team.query.filter_by(is_active=True).order_by(Team.name).all()
        leagues = League.query.filter_by(is_active=True).order_by(League.name).all()
        roles = Role.query.order_by(Role.name).all()

        try:
            from app.models import NotificationGroup
            notification_groups = NotificationGroup.query.filter_by(is_active=True).order_by(NotificationGroup.name).all()
        except Exception:
            notification_groups = []

        from app.models.admin_config import AdminConfig
        # mobile_push_notifications is the key the app actually reads via
        # /app_config; the old push_notifications_enabled flag gated nothing.
        push_notifications_enabled = AdminConfig.get_setting('mobile_push_notifications', True)

        stats = {
            'total_subscribers': total_subscribers,
            'notifications_sent_today': notifications_sent_today,
            'delivery_rate': delivery_rate,
            'click_rate': click_rate,
            'active_subscribers': active_subscribers,
            'new_subscribers_week': new_subscribers_week,
            'unsubscribed_count': unsubscribed_count,
            'push_notifications_enabled': push_notifications_enabled
        }

        return render_template('admin_panel/push_notifications_flowbite.html',
                             notification_history=notification_history,
                             teams=teams,
                             leagues=leagues,
                             roles=roles,
                             notification_groups=notification_groups,
                             **stats)
    except Exception as e:
        logger.exception(f"Error loading push notifications page: {e}")
        flash('The Push Notifications page failed to load. The error has been logged — check the server log for details.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/push-notifications/dashboard')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notifications_dashboard():
    """Push notifications dashboard with overview stats."""
    try:
        total_subscribers = UserFCMToken.query.filter_by(is_active=True).count()
        active_subscribers = UserFCMToken.query.filter(
            UserFCMToken.is_active == True,
            UserFCMToken.updated_at >= datetime.utcnow() - timedelta(days=30)
        ).count()

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        notifications_sent_today = Notification.query.filter(
            Notification.notification_type == 'push',
            Notification.created_at >= today_start
        ).count()

        week_start = datetime.utcnow() - timedelta(days=7)
        notifications_sent_week = Notification.query.filter(
            Notification.notification_type == 'push',
            Notification.created_at >= week_start
        ).count()

        recent_notifications = Notification.query.filter_by(
            notification_type='push'
        ).order_by(Notification.created_at.desc()).limit(10).all()

        platform_stats = db.session.query(
            UserFCMToken.platform,
            db.func.count(UserFCMToken.id)
        ).filter_by(is_active=True).group_by(UserFCMToken.platform).all()

        # --- Send Volume trend (real per-day campaign send counts) ---------------
        # Derived from PushNotificationCampaign: sum of sent_count grouped by the
        # day the campaign actually went out (actual_send_time), falling back to
        # created_at when a campaign has no recorded send time. Built for 7/30/90
        # day windows so the dashboard chart's period toggle has real data. Wrapped
        # defensively so an empty/missing table never 500s the dashboard.
        send_volume = _build_send_volume_series([7, 30, 90])

        # Real delivery/engagement from campaign analytics (no estimates); 'N/A'
        # until there is real sent/delivered volume rather than a fabricated %.
        try:
            from app.models.push_campaigns import PushNotificationCampaign as _PNC
            from sqlalchemy import func as _f
            _sent, _delivered, _clicked = db.session.query(
                _f.coalesce(_f.sum(_PNC.sent_count), 0),
                _f.coalesce(_f.sum(_PNC.delivered_count), 0),
                _f.coalesce(_f.sum(_PNC.click_count), 0),
            ).first() or (0, 0, 0)
        except Exception as analytics_err:
            logger.warning(f"Campaign analytics unavailable, showing N/A rates: {analytics_err}")
            db.session.rollback()
            _sent, _delivered, _clicked = 0, 0, 0

        stats = {
            'total_subscribers': total_subscribers,
            'active_subscribers': active_subscribers,
            'notifications_sent_today': notifications_sent_today,
            'notifications_sent_week': notifications_sent_week,
            'platform_stats': dict(platform_stats) if platform_stats else {},
            'delivery_rate': (f"{round(100 * _delivered / _sent)}%" if _sent else 'N/A'),
            'avg_engagement': (f"{round(100 * _clicked / _delivered)}%" if _delivered else 'N/A'),
        }

        return render_template('admin_panel/communication/push_notifications_dashboard_flowbite.html',
                             recent_notifications=recent_notifications,
                             send_volume=send_volume,
                             **stats)
    except Exception as e:
        logger.error(f"Error loading push notifications dashboard: {e}")
        flash('Dashboard unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/push-notifications/search-users')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_search_users():
    """AJAX endpoint: search users with active push tokens."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    from flask import g
    from sqlalchemy.orm import joinedload
    from app.models import Player

    # Search username OR player name. The old email clause compiled against
    # the encrypted column (User.email is a hybrid with no expression) so it
    # scanned base64 ciphertext and could never match — dropped; admins type
    # real names anyway, which the old version didn't support at all.
    search = f'%{q}%'
    users = g.db_session.query(User).outerjoin(
        Player, Player.user_id == User.id
    ).join(UserFCMToken).options(
        joinedload(User.player)
    ).filter(
        UserFCMToken.is_active == True,
        db.or_(
            User.username.ilike(search),
            Player.name.ilike(search),
        )
    ).distinct().limit(15).all()

    results = [{
        'id': u.id,
        'username': u.username,
        'name': u.player.name if u.player else u.username,
    } for u in users]
    return jsonify(results)


@admin_panel_bp.route('/communication/push-notifications/settings', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notifications_settings():
    """Push notification settings configuration."""
    from app.models.admin_config import AdminConfig

    if request.method == 'GET':
        settings = {
            # The master toggle is mobile_push_notifications — the key served
            # to the app via /app_config. (push_notifications_enabled and
            # auto_notifications_enabled were ghost flags nothing read;
            # removed 2026-07. quiet_hours_* were write-only config no send
            # path ever read — removed from the form 2026-07 rather than
            # pretending they were enforced.)
            'push_notifications_enabled': AdminConfig.get_setting('mobile_push_notifications', True),
        }
        return render_template('admin_panel/communication/push_notifications_settings_flowbite.html',
                             **settings)

    try:
        updates = []
        # Form field names must match the template's actual inputs — the old
        # loop read request.form.get('push_notifications_enabled') while the
        # template posts name="push_enabled", so the master toggle saved False
        # on every submit.
        push_on = request.form.get('push_enabled') == 'on'
        old_push = AdminConfig.get_setting('mobile_push_notifications', True)
        AdminConfig.set_setting('mobile_push_notifications', push_on,
                              description='Enable push notifications for users (served to the app via /app_config)',
                              category='mobile_features', data_type='boolean', user_id=current_user.id)
        if old_push != push_on:
            updates.append(f'mobile_push_notifications: {old_push} -> {push_on}')

        if updates:
            AdminAuditLog.log_action(
                user_id=current_user.id, action='update_push_settings',
                resource_type='push_notifications', resource_id='settings',
                new_value='; '.join(updates),
                ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
            )

        flash('Push notification settings updated successfully!', 'success')
        return redirect(url_for('admin_panel.push_notifications_settings'))

    except Exception as e:
        logger.error(f"Error updating push notification settings: {e}")
        flash('Failed to update settings. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.push_notifications_settings'))


# =============================================================================
# SEND / BROADCAST OPERATIONS
# =============================================================================

@admin_panel_bp.route('/push-notifications/send', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def send_push_notification():
    """Send a push notification to devices via FCM, honoring the compose form's audience
    targeting, and mirror it to in-app notifications so it appears in history."""
    try:
        from app.services.notification_service import notification_service
        from app.services.push_targeting_service import push_targeting_service

        title = request.form.get('title')
        body = request.form.get('body')

        if not title or not body:
            flash('Title and body are required.', 'error')
            return redirect(url_for('admin_panel.push_notifications'))

        target_type = request.form.get('target_type', 'all')
        platform = request.form.get('platform_filter', 'all')
        priority = request.form.get('priority', 'normal')
        action_url = request.form.get('action_url') or None

        # Map the compose form's audience fields to targeting IDs.
        if target_type == 'team':
            target_ids = request.form.getlist('team_ids', type=int)
        elif target_type == 'league':
            target_ids = request.form.getlist('league_ids', type=int)
        elif target_type == 'role':
            target_ids = request.form.getlist('role_names')
        elif target_type == 'pool':
            target_ids = [request.form.get('pool_type', 'all')]
        elif target_type == 'group':
            group_id = request.form.get('notification_group_id', type=int)
            target_ids = [group_id] if group_id else []
        elif target_type == 'users':
            target_ids = request.form.getlist('user_ids', type=int)
            if not target_ids:
                flash('Please pick at least one person to send to.', 'error')
                return redirect(url_for('admin_panel.push_notifications'))
        else:  # 'all' or 'platform'
            target_ids = []

        # Resolve the audience to actual device tokens. The targeting service
        # calls specific-user targeting 'custom'.
        resolved_type = 'custom' if target_type == 'users' else target_type
        tokens = push_targeting_service.resolve_targets(resolved_type, target_ids, platform)
        if not tokens:
            flash('No devices with active push tokens match the selected audience.', 'warning')
            return redirect(url_for('admin_panel.push_notifications'))

        # Deliver to devices via FCM.
        extra_data = {'priority': priority}
        if action_url:
            extra_data['action_url'] = action_url
            extra_data['deep_link'] = action_url
        result = notification_service.send_general_notification(tokens, title, body, extra_data)
        delivered = result.get('success', 0)
        failed = result.get('failure', 0)

        # Mirror to in-app notifications for the same recipients (keeps the history feed accurate).
        recipient_user_ids = [
            row[0] for row in db.session.query(UserFCMToken.user_id).filter(
                UserFCMToken.fcm_token.in_(tokens)
            ).distinct().all()
        ]
        for uid in recipient_user_ids:
            db.session.add(Notification(
                user_id=uid, content=f"{title}: {body}"[:255],  # column is String(255)
                notification_type='push', icon='ti ti-bell'
            ))
        db.session.commit()

        AdminAuditLog.log_action(
            user_id=current_user.id, action='SEND_PUSH_NOTIFICATION',
            resource_type='Notification', resource_id='bulk',
            new_value=f'Push "{title}" to {len(tokens)} device(s) ({target_type}): {delivered} delivered, {failed} failed',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )

        if delivered and not failed:
            flash(f'Push "{title}" delivered to {delivered} device(s).', 'success')
        elif delivered:
            flash(f'Push "{title}" delivered to {delivered} device(s); {failed} failed.', 'warning')
        else:
            flash(f'Push "{title}" could not be delivered ({failed} device(s) failed). Check push service connectivity.', 'error')
        return redirect(url_for('admin_panel.push_notifications'))
    except Exception as e:
        logger.error(f"Error sending push notification: {e}")
        flash('Push notification sending failed. Check push service connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.push_notifications'))


@admin_panel_bp.route('/communication/push-notifications/broadcast', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_broadcast():
    """Send broadcast notification from admin panel."""
    try:
        from app.services.notification_service import notification_service

        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = UserFCMToken

        data = request.get_json()
        title = data.get('title', 'ECS Soccer')
        message = data.get('message', '')
        target = data.get('target', 'all')

        if not message:
            return jsonify({'success': False, 'message': 'Message is required'}), 400

        query = token_model.query.filter_by(is_active=True)
        if target == 'ios':
            query = query.filter_by(platform='ios')
        elif target == 'android':
            query = query.filter_by(platform='android')
        elif target == 'coaches':
            coach_users = User.query.join(User.roles).filter(
                db.or_(db.text("roles.name = 'Pub League Coach'"), db.text("roles.name = 'ECS FC Coach'"))
            ).all()
            query = query.filter(token_model.user_id.in_([u.id for u in coach_users]))
        elif target == 'admins':
            admin_users = User.query.join(User.roles).filter(
                db.or_(db.text("roles.name = 'Global Admin'"), db.text("roles.name = 'Pub League Admin'"))
            ).all()
            query = query.filter(token_model.user_id.in_([u.id for u in admin_users]))

        tokens_objs = query.all()
        token_attr = 'fcm_token' if hasattr(token_model, 'fcm_token') else 'token'
        tokens = [getattr(token, token_attr) for token in tokens_objs]

        # Honor each user's push-notification preference.
        from app.services.push_targeting_service import push_targeting_service
        tokens = push_targeting_service.filter_by_user_preference(tokens)

        if not tokens:
            return jsonify({'success': False, 'message': 'No devices found for selected target'}), 404

        result = notification_service.send_general_notification(tokens, title, message)

        AdminAuditLog.log_action(
            user_id=current_user.id, action='push_notification_broadcast',
            resource_type='communication', resource_id='broadcast',
            new_value=f'Sent to {len(tokens)} devices: {title}',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'Broadcast sent to {len(tokens)} devices', 'result': result})

    except Exception as e:
        logger.error(f"Error sending push broadcast: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/broadcast-enhanced', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_broadcast_enhanced():
    """Send push notification with advanced targeting options."""
    try:
        from app.services.push_targeting_service import push_targeting_service
        from app.services.push_campaign_service import push_campaign_service
        from app.services.notification_service import notification_service

        data = request.get_json()
        title = data.get('title', 'ECS Soccer')
        body = data.get('message') or data.get('body', '')
        target_type = data.get('target_type', 'all')
        target_ids = data.get('target_ids')
        platform = data.get('platform', 'all')
        priority = data.get('priority', 'normal')
        action_url = data.get('action_url')

        if not body:
            return jsonify({'success': False, 'error': 'Message body is required'}), 400

        create_campaign = data.get('create_campaign', False)
        if create_campaign:
            campaign_name = data.get('campaign_name', f'Broadcast {title[:50]}')
            campaign = push_campaign_service.create_campaign(
                name=campaign_name, title=title, body=body,
                target_type=target_type, target_ids=target_ids,
                platform_filter=platform, priority=priority,
                action_url=action_url, send_immediately=True,
                created_by=current_user.id
            )
            result = push_campaign_service.send_campaign_now(campaign.id)
            return jsonify({
                'success': result.get('success', False),
                'message': f'Sent to {result.get("sent_count", 0)} devices',
                'campaign_id': campaign.id, **result
            })

        tokens = push_targeting_service.resolve_targets(target_type, target_ids, platform)
        if not tokens:
            return jsonify({'success': False, 'error': 'No recipients found for the selected targeting criteria'}), 404

        notification_data = {'type': 'broadcast', 'priority': priority}
        if action_url:
            notification_data['action_url'] = action_url
            notification_data['deep_link'] = action_url

        result = notification_service.send_push_notification(
            tokens=tokens, title=title, body=body, data=notification_data,
            android_channel_id='general',
        )
        sent_count = result.get('success', 0) + result.get('failure', 0)

        AdminAuditLog.log_action(
            user_id=current_user.id, action='push_notification_broadcast_enhanced',
            resource_type='communication', resource_id='broadcast',
            new_value=f'Sent to {sent_count} devices ({target_type}): {title}',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True, 'message': f'Broadcast sent to {sent_count} devices',
            'token_count': len(tokens), 'sent_count': sent_count,
            'delivered_count': result.get('success', 0), 'failed_count': result.get('failure', 0)
        })

    except Exception as e:
        logger.error(f"Error sending enhanced broadcast: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/communication/push-notifications/preview', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_preview():
    """Preview how many recipients would receive a notification."""
    try:
        from app.services.push_targeting_service import push_targeting_service

        data = request.get_json()
        target_type = data.get('target_type', 'all')
        target_ids = data.get('target_ids')
        platform = data.get('platform')

        preview = push_targeting_service.preview_recipient_count(target_type, target_ids, platform)
        target_details = []
        if target_type in ['team', 'league', 'role', 'group']:
            target_details = push_targeting_service.get_target_details(target_type, target_ids)

        return jsonify({'success': True, 'preview': preview, 'target_details': target_details})

    except Exception as e:
        logger.error(f"Error previewing push notification: {e}")
        return jsonify({
            'success': False, 'error': 'Internal Server Error',
            'preview': {'total_users': 0, 'total_tokens': 0, 'breakdown': {}}
        }), 500


# =============================================================================
# REMINDER TRIGGERS (manual fire of automated reminder Celery tasks)
# =============================================================================

@admin_panel_bp.route('/communication/push-notifications/trigger-match-reminders', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_trigger_match_reminders():
    """Manually trigger the daily match-reminder Celery task.

    Fires the same task celery beat runs at 6 PM Pacific
    (send_match_reminders_daily): one consolidated DM per player covering
    every match they have tomorrow, respecting per-user preferences and the
    MatchReminderLog dedup so manual triggers never double-send.
    """
    try:
        from app.tasks.tasks_notification_reminders import send_match_reminders_daily
        task = send_match_reminders_daily.delay()

        AdminAuditLog.log_action(
            user_id=current_user.id, action='trigger_match_reminders',
            resource_type='push_notifications', resource_id='match_reminders',
            new_value=f'Manually triggered daily match reminders (task {task.id})',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({
            'success': True,
            'message': 'Match reminders queued. Players with matches tomorrow will receive a reminder.',
            'task_id': task.id
        })
    except Exception as e:
        logger.error(f"Error triggering match reminders: {e}")
        return jsonify({'success': False, 'message': 'Unable to queue match reminders. Check the task queue.'}), 500


@admin_panel_bp.route('/communication/push-notifications/trigger-rsvp-reminders', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_trigger_rsvp_reminders():
    """Manually trigger the RSVP-reminder Celery task.

    Fires send_rsvp_reminders, which chases players who have not responded to
    RSVP for matches happening in 3-5 days, via the unified
    NotificationOrchestrator (in-app + push, respecting user preferences).
    """
    try:
        from app.tasks.tasks_notification_reminders import send_rsvp_reminders
        task = send_rsvp_reminders.delay()

        AdminAuditLog.log_action(
            user_id=current_user.id, action='trigger_rsvp_reminders',
            resource_type='push_notifications', resource_id='rsvp_reminders',
            new_value=f'Manually triggered RSVP reminders (task {task.id})',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({
            'success': True,
            'message': 'RSVP reminders queued. Non-responders for matches in 3-5 days will be reminded.',
            'task_id': task.id
        })
    except Exception as e:
        logger.error(f"Error triggering RSVP reminders: {e}")
        return jsonify({'success': False, 'message': 'Unable to queue RSVP reminders. Check the task queue.'}), 500


# =============================================================================
# ADMIN OPERATIONS
# =============================================================================

@admin_panel_bp.route('/communication/push-notifications/test', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_test():
    """Send test notification to admin's devices."""
    try:
        from app.services.notification_service import notification_service

        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = UserFCMToken

        user_tokens = token_model.query.filter_by(user_id=current_user.id, is_active=True).all()
        if not user_tokens:
            return jsonify({'success': False, 'message': 'No devices registered for your account.'}), 404

        token_attr = 'fcm_token' if hasattr(token_model, 'fcm_token') else 'token'
        tokens = [getattr(token, token_attr) for token in user_tokens]

        result = notification_service.send_general_notification(
            tokens, "ECS Soccer Admin Test",
            "Test notification from the admin panel - your push notifications are working!"
        )
        return jsonify({'success': True, 'message': 'Test notification sent', 'result': result})

    except Exception as e:
        logger.error(f"Error sending test notification: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/cleanup-tokens', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def push_notification_cleanup_tokens():
    """Clean up invalid/inactive FCM tokens."""
    try:
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = UserFCMToken

        cutoff_date = datetime.utcnow() - timedelta(days=90)
        old_tokens = token_model.query.filter(token_model.updated_at < cutoff_date).all()
        count = len(old_tokens)
        for token in old_tokens:
            token.is_active = False

        AdminAuditLog.log_action(
            user_id=current_user.id, action='push_notification_token_cleanup',
            resource_type='communication', resource_id='tokens',
            new_value=f'Cleaned up {count} old tokens',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': True, 'message': f'Cleaned up {count} old tokens', 'count': count})

    except Exception as e:
        logger.error(f"Error cleaning up tokens: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/tokens')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_tokens():
    """List all FCM tokens for management."""
    try:
        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = UserFCMToken

        page = request.args.get('page', 1, type=int)
        tokens = token_model.query.join(User).paginate(page=page, per_page=50, error_out=False)
        token_data = [{
            'id': t.id, 'user_id': t.user_id,
            'username': t.user.username if hasattr(t, 'user') and t.user else 'Unknown',
            'platform': getattr(t, 'platform', 'unknown'), 'is_active': t.is_active,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'updated_at': t.updated_at.isoformat() if t.updated_at else None
        } for t in tokens.items]

        return jsonify({
            'success': True, 'tokens': token_data,
            'pagination': {'page': tokens.page, 'pages': tokens.pages, 'per_page': tokens.per_page, 'total': tokens.total}
        })

    except Exception as e:
        logger.error(f"Error listing tokens: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500


@admin_panel_bp.route('/communication/push-notifications/status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_status():
    """Get notification system status and statistics."""
    try:
        try:
            from app.services.notification_service import notification_service
            firebase_configured = getattr(notification_service, '_initialized', False)
        except ImportError:
            firebase_configured = False

        try:
            from app.models import UserFCMToken
            token_model = UserFCMToken
        except ImportError:
            token_model = UserFCMToken

        total_tokens = token_model.query.filter_by(is_active=True).count()
        ios_tokens = token_model.query.filter_by(is_active=True, platform='ios').count() if hasattr(token_model, 'platform') else 0
        android_tokens = token_model.query.filter_by(is_active=True, platform='android').count() if hasattr(token_model, 'platform') else 0

        yesterday = datetime.utcnow() - timedelta(days=1)
        notifications_sent_24h = Notification.query.filter(
            Notification.notification_type == 'push', Notification.created_at >= yesterday
        ).count()

        return jsonify({
            'success': True, 'firebase_configured': firebase_configured,
            'stats': {
                'total_devices': total_tokens, 'ios_devices': ios_tokens,
                'android_devices': android_tokens, 'notifications_sent_24h': notifications_sent_24h
            }
        })

    except Exception as e:
        logger.error(f"Error getting notification status: {e}")
        return jsonify({
            'success': False, 'firebase_configured': False,
            'stats': {'total_devices': 0, 'ios_devices': 0, 'android_devices': 0, 'notifications_sent_24h': 0}
        }), 500


# =============================================================================
# LEGACY ROUTES
# =============================================================================
# duplicate_notification_legacy REMOVED 2026-07-21: it flashed "duplicated
# successfully" without duplicating anything. The real duplicate lives at
# ajax.py duplicate_notification (/push-notifications/<id>/duplicate).

@admin_panel_bp.route('/resend-notification', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def resend_notification():
    """Resend a push notification."""
    try:
        notification_id = request.form.get('notification_id', type=int)
        if not notification_id:
            flash('Notification ID is required.', 'error')
            return redirect(url_for('admin_panel.push_notifications'))

        original_notification = Notification.query.get_or_404(notification_id)
        new_notification = Notification(
            user_id=original_notification.user_id,
            content=original_notification.content,
            notification_type=original_notification.notification_type,
            icon=original_notification.icon, read=False, created_at=datetime.utcnow()
        )
        db.session.add(new_notification)
        db.session.commit()

        AdminAuditLog.log_action(
            user_id=current_user.id, action='resend_notification',
            resource_type='push_notifications', resource_id=str(notification_id),
            new_value=f'Resent notification: {original_notification.content[:50]}...',
            ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent')
        )
        flash('Notification resent successfully!', 'success')
        return redirect(url_for('admin_panel.push_notifications'))
    except Exception as e:
        logger.error(f"Error resending notification: {e}")
        flash('Notification resending failed.', 'error')
        return redirect(url_for('admin_panel.push_notifications'))


# =============================================================================
# TARGET DATA APIS (for dynamic selectors in send form)
# =============================================================================

@admin_panel_bp.route('/api/push/teams')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_teams():
    """Get teams for targeting selector."""
    try:
        from app.models import Team
        league_id = request.args.get('league_id', type=int)
        query = Team.query.order_by(Team.name)
        if league_id:
            query = query.filter_by(league_id=league_id)
        teams = query.all()
        return jsonify({
            'success': True,
            'teams': [{'id': t.id, 'name': t.name, 'league_id': t.league_id,
                       'league_name': t.league.name if t.league else None} for t in teams]
        })
    except Exception as e:
        logger.error(f"Error getting teams: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/push/leagues')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_leagues():
    """Get leagues for targeting selector."""
    try:
        from app.models import League
        leagues = League.query.order_by(League.name).all()
        return jsonify({
            'success': True,
            'leagues': [{'id': l.id, 'name': l.name, 'team_count': len(l.teams) if l.teams else 0} for l in leagues]
        })
    except Exception as e:
        logger.error(f"Error getting leagues: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/push/roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_roles():
    """Get roles for targeting selector."""
    try:
        from app.models import Role
        roles = Role.query.order_by(Role.name).all()
        return jsonify({
            'success': True,
            'roles': [{'id': r.id, 'name': r.name, 'description': r.description} for r in roles]
        })
    except Exception as e:
        logger.error(f"Error getting roles: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/push/substitute-pools')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_substitute_pools():
    """Get substitute pool options for targeting selector."""
    try:
        from app.models.substitutes import SubstitutePool, EcsFcSubPool
        pub_league_count = SubstitutePool.query.filter_by(is_active=True).count()
        ecs_fc_count = EcsFcSubPool.query.filter_by(is_active=True).count()
        return jsonify({
            'success': True,
            'pools': [
                {'id': 'all', 'name': 'All Substitute Pools', 'member_count': pub_league_count + ecs_fc_count},
                {'id': 'pub_league', 'name': 'Pub League Sub Pool', 'member_count': pub_league_count},
                {'id': 'ecs_fc', 'name': 'ECS FC Sub Pool', 'member_count': ecs_fc_count}
            ]
        })
    except Exception as e:
        logger.error(f"Error getting substitute pools: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/push/platform-stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_platform_stats():
    """Get platform statistics for targeting selector."""
    try:
        from app.models import UserFCMToken
        total = UserFCMToken.query.filter_by(is_active=True).count()
        ios = UserFCMToken.query.filter_by(is_active=True, platform='ios').count()
        android = UserFCMToken.query.filter_by(is_active=True, platform='android').count()
        web = UserFCMToken.query.filter_by(is_active=True, platform='web').count()
        return jsonify({
            'success': True,
            'platforms': {
                'all': {'name': 'All Platforms', 'count': total},
                'ios': {'name': 'iOS', 'count': ios},
                'android': {'name': 'Android', 'count': android},
                'web': {'name': 'Web', 'count': web}
            }
        })
    except Exception as e:
        logger.error(f"Error getting platform stats: {e}")
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500
