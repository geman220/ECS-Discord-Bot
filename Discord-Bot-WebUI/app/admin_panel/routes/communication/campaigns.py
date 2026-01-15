# app/admin_panel/routes/communication/campaigns.py

"""
Push Notification Campaign Routes

CRUD operations for managing push notification campaigns:
- List campaigns
- Create campaign
- View campaign details
- Update campaign
- Send/schedule campaign
- Cancel campaign
- Duplicate campaign
"""

import logging
from datetime import datetime
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models import (
    Team, League, Role,
    PushNotificationCampaign, NotificationGroup,
    CampaignStatus, TargetType, AdminAuditLog
)
from app.decorators import role_required
from app.services.push_campaign_service import push_campaign_service
from app.services.push_targeting_service import push_targeting_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/campaigns')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_list():
    """List all push notification campaigns."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        status_filter = request.args.get('status', None)

        query = PushNotificationCampaign.query

        if status_filter:
            query = query.filter_by(status=status_filter)

        campaigns = query.order_by(
            PushNotificationCampaign.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        # Get data for creating new campaigns
        teams = Team.query.order_by(Team.name).all()
        leagues = League.query.order_by(League.name).all()
        roles = Role.query.order_by(Role.name).all()
        groups = NotificationGroup.query.filter_by(is_active=True).order_by(NotificationGroup.name).all()

        # Status counts for filters
        status_counts = {
            'all': PushNotificationCampaign.query.count(),
            'draft': PushNotificationCampaign.query.filter_by(status='draft').count(),
            'scheduled': PushNotificationCampaign.query.filter_by(status='scheduled').count(),
            'sent': PushNotificationCampaign.query.filter_by(status='sent').count(),
            'failed': PushNotificationCampaign.query.filter_by(status='failed').count(),
        }

        return render_template(
            'admin_panel/communication/campaigns_flowbite.html',
            campaigns=campaigns,
            teams=teams,
            leagues=leagues,
            roles=roles,
            groups=groups,
            status_filter=status_filter,
            status_counts=status_counts,
            target_types=[(t.value, t.name.title()) for t in TargetType],
            page_title='Push Campaigns'
        )
    except Exception as e:
        logger.error(f"Error listing campaigns: {e}")
        flash('Error loading campaigns', 'error')
        return redirect(url_for('admin_panel.push_notifications'))


@admin_panel_bp.route('/communication/campaigns', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def campaigns_create():
    """Create a new push notification campaign."""
    try:
        data = request.get_json() or request.form.to_dict()

        # Required fields
        name = data.get('name', '').strip()
        title = data.get('title', '').strip()
        body = data.get('body', '').strip()
        target_type = data.get('target_type', 'all')

        if not name or not title or not body:
            error = 'Name, title, and body are required'
            if request.is_json:
                return jsonify({'success': False, 'error': error}), 400
            flash(error, 'error')
            return redirect(url_for('admin_panel.campaigns_list'))

        # Parse target IDs based on target type
        target_ids = None
        if target_type == 'team':
            team_ids = data.get('team_ids', [])
            if isinstance(team_ids, str):
                team_ids = [int(i) for i in team_ids.split(',') if i.strip()]
            target_ids = team_ids
        elif target_type == 'league':
            league_ids = data.get('league_ids', [])
            if isinstance(league_ids, str):
                league_ids = [int(i) for i in league_ids.split(',') if i.strip()]
            target_ids = league_ids
        elif target_type == 'role':
            role_names = data.get('role_names', [])
            if isinstance(role_names, str):
                role_names = [r.strip() for r in role_names.split(',') if r.strip()]
            target_ids = role_names
        elif target_type == 'pool':
            pool_types = data.get('pool_types', ['all'])
            if isinstance(pool_types, str):
                pool_types = [pool_types]
            target_ids = pool_types
        elif target_type == 'group':
            group_id = data.get('notification_group_id')
            target_ids = [int(group_id)] if group_id else None

        # Optional fields
        notification_group_id = data.get('notification_group_id')
        if notification_group_id:
            notification_group_id = int(notification_group_id)
        else:
            notification_group_id = None

        platform_filter = data.get('platform_filter', 'all')
        priority = data.get('priority', 'normal')
        action_url = data.get('action_url', '').strip() or None

        # Data payload
        data_payload = None
        if data.get('data_payload'):
            try:
                import json
                if isinstance(data['data_payload'], str):
                    data_payload = json.loads(data['data_payload'])
                else:
                    data_payload = data['data_payload']
            except:
                pass

        # Scheduling
        send_immediately = data.get('send_immediately', 'true')
        if isinstance(send_immediately, str):
            send_immediately = send_immediately.lower() in ('true', '1', 'yes')

        scheduled_send_time = None
        if not send_immediately:
            scheduled_str = data.get('scheduled_send_time', '')
            if scheduled_str:
                try:
                    scheduled_send_time = datetime.fromisoformat(scheduled_str.replace('Z', '+00:00'))
                except:
                    scheduled_send_time = datetime.strptime(scheduled_str, '%Y-%m-%dT%H:%M')

        campaign = push_campaign_service.create_campaign(
            name=name,
            title=title,
            body=body,
            target_type=target_type,
            target_ids=target_ids,
            notification_group_id=notification_group_id,
            platform_filter=platform_filter,
            priority=priority,
            action_url=action_url,
            data_payload=data_payload,
            send_immediately=send_immediately,
            scheduled_send_time=scheduled_send_time,
            created_by=current_user.id
        )

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='campaign_created',
            resource_type='push_notification_campaign',
            resource_id=str(campaign.id),
            new_value=f'Created campaign: {name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if request.is_json:
            return jsonify({
                'success': True,
                'message': 'Campaign created successfully',
                'campaign': campaign.to_dict()
            })

        flash(f'Campaign "{name}" created successfully', 'success')
        return redirect(url_for('admin_panel.campaigns_detail', campaign_id=campaign.id))

    except ValueError as e:
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(str(e), 'error')
        return redirect(url_for('admin_panel.campaigns_list'))

    except Exception as e:
        logger.error(f"Error creating campaign: {e}")

        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500

        flash('Error creating campaign', 'error')
        return redirect(url_for('admin_panel.campaigns_list'))


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_detail(campaign_id):
    """View campaign details."""
    try:
        campaign = PushNotificationCampaign.query.get_or_404(campaign_id)

        return render_template(
            'admin_panel/communication/campaign_detail_flowbite.html',
            campaign=campaign,
            page_title=f'Campaign: {campaign.name}'
        )
    except Exception as e:
        logger.error(f"Error viewing campaign {campaign_id}: {e}")
        flash('Error loading campaign', 'error')
        return redirect(url_for('admin_panel.campaigns_list'))


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_update(campaign_id):
    """Update a draft campaign."""
    try:
        data = request.get_json()

        campaign = push_campaign_service.update_campaign(campaign_id, **data)

        return jsonify({
            'success': True,
            'message': 'Campaign updated successfully',
            'campaign': campaign.to_dict()
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>/send', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_send(campaign_id):
    """Send a campaign immediately."""
    try:
        result = push_campaign_service.send_campaign_now(campaign_id)

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='campaign_sent',
            resource_type='push_notification_campaign',
            resource_id=str(campaign_id),
            new_value=f'Sent to {result.get("sent_count", 0)} devices',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"Error sending campaign {campaign_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>/schedule', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_schedule(campaign_id):
    """Schedule a campaign for future delivery."""
    try:
        data = request.get_json()
        send_time_str = data.get('send_time')

        if not send_time_str:
            return jsonify({'success': False, 'error': 'send_time required'}), 400

        try:
            send_time = datetime.fromisoformat(send_time_str.replace('Z', '+00:00'))
        except:
            send_time = datetime.strptime(send_time_str, '%Y-%m-%dT%H:%M')

        result = push_campaign_service.schedule_campaign(campaign_id, send_time)

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='campaign_scheduled',
            resource_type='push_notification_campaign',
            resource_id=str(campaign_id),
            new_value=f'Scheduled for {send_time.isoformat()}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"Error scheduling campaign {campaign_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>/cancel', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_cancel(campaign_id):
    """Cancel a scheduled campaign."""
    try:
        result = push_campaign_service.cancel_campaign(campaign_id, current_user.id)

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='campaign_cancelled',
            resource_type='push_notification_campaign',
            resource_id=str(campaign_id),
            new_value='Campaign cancelled',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify(result)

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"Error cancelling campaign {campaign_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>/duplicate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def campaigns_duplicate(campaign_id):
    """Duplicate a campaign."""
    try:
        data = request.get_json() or {}
        new_name = data.get('name')

        new_campaign = push_campaign_service.duplicate_campaign(
            campaign_id,
            new_name=new_name,
            created_by=current_user.id
        )

        return jsonify({
            'success': True,
            'message': 'Campaign duplicated successfully',
            'campaign': new_campaign.to_dict()
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"Error duplicating campaign {campaign_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/campaigns/<int:campaign_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def campaigns_delete(campaign_id):
    """Delete a draft campaign."""
    try:
        campaign = PushNotificationCampaign.query.get_or_404(campaign_id)

        if campaign.status != CampaignStatus.DRAFT.value:
            return jsonify({
                'success': False,
                'error': 'Only draft campaigns can be deleted'
            }), 400

        campaign_name = campaign.name
        db.session.delete(campaign)

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='campaign_deleted',
            resource_type='push_notification_campaign',
            resource_id=str(campaign_id),
            new_value=f'Deleted campaign: {campaign_name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Campaign "{campaign_name}" deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting campaign {campaign_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# API endpoints
@admin_panel_bp.route('/api/campaigns')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_campaigns_list():
    """API: List campaigns with filtering."""
    try:
        status = request.args.get('status')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        result = push_campaign_service.list_campaigns(
            status=status,
            page=page,
            per_page=per_page
        )

        return jsonify({'success': True, **result})

    except Exception as e:
        logger.error(f"Error listing campaigns API: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/campaigns/<int:campaign_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_campaigns_detail(campaign_id):
    """API: Get campaign details."""
    try:
        campaign = push_campaign_service.get_campaign_status(campaign_id)
        return jsonify({'success': True, 'campaign': campaign})

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404

    except Exception as e:
        logger.error(f"Error getting campaign API: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
