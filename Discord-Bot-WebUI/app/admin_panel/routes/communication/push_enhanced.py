# app/admin_panel/routes/communication/push_enhanced.py

"""
Enhanced Push Notification Routes

Advanced targeting and preview capabilities:
- Preview recipient count before sending
- Enhanced broadcast with advanced targeting
- Target data APIs (teams, leagues, roles, pools)
"""

import logging
from flask import request, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models import Team, League, Role, AdminAuditLog
from app.models.substitutes import SubstitutePool, EcsFcSubPool
from app.decorators import role_required
from app.services.push_targeting_service import push_targeting_service
from app.services.push_campaign_service import push_campaign_service
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/push-notifications/preview', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_preview():
    """
    Preview how many recipients would receive a notification.

    Request JSON:
        {
            "target_type": "team",
            "target_ids": [1, 2, 3],
            "platform": "ios"  // optional
        }

    Response:
        {
            "success": true,
            "preview": {
                "total_users": 45,
                "total_tokens": 52,
                "breakdown": {
                    "ios": 30,
                    "android": 20,
                    "web": 2
                }
            }
        }
    """
    try:
        data = request.get_json()
        target_type = data.get('target_type', 'all')
        target_ids = data.get('target_ids')
        platform = data.get('platform')

        preview = push_targeting_service.preview_recipient_count(
            target_type,
            target_ids,
            platform
        )

        # Get target details if applicable
        target_details = []
        if target_type in ['team', 'league', 'role', 'group']:
            target_details = push_targeting_service.get_target_details(
                target_type,
                target_ids
            )

        return jsonify({
            'success': True,
            'preview': preview,
            'target_details': target_details
        })

    except Exception as e:
        logger.error(f"Error previewing push notification: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'preview': {
                'total_users': 0,
                'total_tokens': 0,
                'breakdown': {}
            }
        }), 500


@admin_panel_bp.route('/communication/push-notifications/broadcast-enhanced', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def push_notification_broadcast_enhanced():
    """
    Send push notification with advanced targeting options.

    Request JSON:
        {
            "title": "Match Reminder",
            "body": "Your match starts in 1 hour",
            "target_type": "team",
            "target_ids": [1, 2],
            "platform": "all",
            "priority": "high",
            "action_url": "ecs-fc-scheme://match/123",
            "create_campaign": true,  // optional: save as campaign
            "campaign_name": "Match Reminder Campaign"  // optional
        }

    Response:
        {
            "success": true,
            "sent_count": 45,
            "delivered_count": 42,
            "failed_count": 3
        }
    """
    try:
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

        # Check if should create a campaign record
        create_campaign = data.get('create_campaign', False)

        if create_campaign:
            campaign_name = data.get('campaign_name', f'Broadcast {title[:50]}')

            # Create and send via campaign service
            campaign = push_campaign_service.create_campaign(
                name=campaign_name,
                title=title,
                body=body,
                target_type=target_type,
                target_ids=target_ids,
                platform_filter=platform,
                priority=priority,
                action_url=action_url,
                send_immediately=True,
                created_by=current_user.id
            )

            result = push_campaign_service.send_campaign_now(campaign.id)

            return jsonify({
                'success': result.get('success', False),
                'message': f'Sent to {result.get("sent_count", 0)} devices',
                'campaign_id': campaign.id,
                **result
            })

        # Direct send without campaign record
        tokens = push_targeting_service.resolve_targets(
            target_type,
            target_ids,
            platform
        )

        if not tokens:
            return jsonify({
                'success': False,
                'error': 'No recipients found for the selected targeting criteria'
            }), 404

        # Build data payload
        notification_data = {
            'type': 'broadcast',
            'priority': priority,
        }
        if action_url:
            notification_data['action_url'] = action_url
            notification_data['deep_link'] = action_url

        result = notification_service.send_push_notification(
            tokens=tokens,
            title=title,
            body=body,
            data=notification_data
        )

        sent_count = result.get('success', 0) + result.get('failure', 0)
        delivered_count = result.get('success', 0)
        failed_count = result.get('failure', 0)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='push_notification_broadcast_enhanced',
            resource_type='communication',
            resource_id='broadcast',
            new_value=f'Sent to {sent_count} devices ({target_type}): {title}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Broadcast sent to {sent_count} devices',
            'token_count': len(tokens),
            'sent_count': sent_count,
            'delivered_count': delivered_count,
            'failed_count': failed_count
        })

    except Exception as e:
        logger.error(f"Error sending enhanced broadcast: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# API endpoints for dynamic target selectors

@admin_panel_bp.route('/api/push/teams')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_teams():
    """Get teams for targeting selector."""
    try:
        league_id = request.args.get('league_id', type=int)

        query = Team.query.order_by(Team.name)
        if league_id:
            query = query.filter_by(league_id=league_id)

        teams = query.all()

        return jsonify({
            'success': True,
            'teams': [{
                'id': t.id,
                'name': t.name,
                'league_id': t.league_id,
                'league_name': t.league.name if t.league else None
            } for t in teams]
        })

    except Exception as e:
        logger.error(f"Error getting teams: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/push/leagues')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_leagues():
    """Get leagues for targeting selector."""
    try:
        leagues = League.query.order_by(League.name).all()

        return jsonify({
            'success': True,
            'leagues': [{
                'id': l.id,
                'name': l.name,
                'team_count': len(l.teams) if l.teams else 0
            } for l in leagues]
        })

    except Exception as e:
        logger.error(f"Error getting leagues: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/push/roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_roles():
    """Get roles for targeting selector."""
    try:
        roles = Role.query.order_by(Role.name).all()

        return jsonify({
            'success': True,
            'roles': [{
                'id': r.id,
                'name': r.name,
                'description': r.description
            } for r in roles]
        })

    except Exception as e:
        logger.error(f"Error getting roles: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/push/substitute-pools')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_push_substitute_pools():
    """Get substitute pool options for targeting selector."""
    try:
        # Count members in each pool
        pub_league_count = SubstitutePool.query.filter_by(is_active=True).count()
        ecs_fc_count = EcsFcSubPool.query.filter_by(is_active=True).count()

        return jsonify({
            'success': True,
            'pools': [
                {
                    'id': 'all',
                    'name': 'All Substitute Pools',
                    'member_count': pub_league_count + ecs_fc_count
                },
                {
                    'id': 'pub_league',
                    'name': 'Pub League Sub Pool',
                    'member_count': pub_league_count
                },
                {
                    'id': 'ecs_fc',
                    'name': 'ECS FC Sub Pool',
                    'member_count': ecs_fc_count
                }
            ]
        })

    except Exception as e:
        logger.error(f"Error getting substitute pools: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        return jsonify({'success': False, 'error': str(e)}), 500
