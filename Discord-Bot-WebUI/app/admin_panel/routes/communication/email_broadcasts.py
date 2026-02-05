# app/admin_panel/routes/communication/email_broadcasts.py

"""
Email Broadcast Routes

CRUD + send operations for bulk email campaigns.
"""

import logging
from datetime import datetime
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models import (
    Team, League, Season, Role,
    EmailCampaign, EmailCampaignRecipient, EmailTemplate, User, PlayerTeamSeason,
)
from app.decorators import role_required
from app.services.email_broadcast_service import email_broadcast_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/communication/email-broadcasts')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcasts_list():
    """Campaign list page."""
    try:
        status_filter = request.args.get('status', None)
        query = EmailCampaign.query

        if status_filter:
            query = query.filter_by(status=status_filter)

        campaigns = query.order_by(EmailCampaign.created_at.desc()).all()

        status_counts = {
            'all': EmailCampaign.query.count(),
            'draft': EmailCampaign.query.filter_by(status='draft').count(),
            'sending': EmailCampaign.query.filter_by(status='sending').count(),
            'sent': EmailCampaign.query.filter_by(status='sent').count(),
            'failed': EmailCampaign.query.filter_by(status='failed').count(),
        }

        total_emails_sent = db.session.query(
            db.func.coalesce(db.func.sum(EmailCampaign.sent_count), 0)
        ).scalar()

        return render_template(
            'admin_panel/communication/email_broadcasts_flowbite.html',
            campaigns=campaigns,
            status_filter=status_filter,
            status_counts=status_counts,
            total_emails_sent=total_emails_sent,
            page_title='Email Broadcasts',
        )
    except Exception as e:
        logger.error(f"Error listing email broadcasts: {e}", exc_info=True)
        flash('Error loading email broadcasts', 'error')
        return redirect(url_for('admin_panel.communication_hub'))


@admin_panel_bp.route('/communication/email-broadcasts/compose')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_compose():
    """Compose a new email broadcast."""
    try:
        # Only show current-season teams and leagues
        teams = Team.query.join(League, Team.league_id == League.id).join(
            Season, League.season_id == Season.id
        ).filter(
            Season.is_current == True,
            Team.is_active == True,
        ).order_by(Team.name).all()

        leagues = League.query.join(
            Season, League.season_id == Season.id
        ).filter(Season.is_current == True).order_by(League.name).all()

        roles = Role.query.order_by(Role.name).all()

        return render_template(
            'admin_panel/communication/email_broadcast_compose_flowbite.html',
            teams=teams,
            leagues=leagues,
            roles=roles,
            page_title='Compose Email Broadcast',
        )
    except Exception as e:
        logger.error(f"Error loading compose page: {e}", exc_info=True)
        flash('Error loading compose page', 'error')
        return redirect(url_for('admin_panel.email_broadcasts_list'))


@admin_panel_bp.route('/communication/email-broadcasts/<int:campaign_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_detail(campaign_id):
    """Campaign detail / progress page."""
    try:
        campaign = EmailCampaign.query.get_or_404(campaign_id)
        recipients = EmailCampaignRecipient.query.filter_by(
            campaign_id=campaign_id
        ).order_by(EmailCampaignRecipient.status, EmailCampaignRecipient.recipient_name).all()

        return render_template(
            'admin_panel/communication/email_broadcast_detail_flowbite.html',
            campaign=campaign,
            recipients=recipients,
            page_title=f'Campaign: {campaign.name}',
        )
    except Exception as e:
        logger.error(f"Error loading campaign detail: {e}", exc_info=True)
        flash('Error loading campaign', 'error')
        return redirect(url_for('admin_panel.email_broadcasts_list'))


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/communication/email-broadcasts', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_broadcast_create():
    """Create a new email campaign (JSON API)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        name = (data.get('name') or '').strip()
        subject = (data.get('subject') or '').strip()
        body_html = (data.get('body_html') or '').strip()
        filter_criteria = data.get('filter_criteria')

        if not name or not subject or not body_html:
            return jsonify({'success': False, 'error': 'Name, subject, and body are required'}), 400

        if not filter_criteria or not filter_criteria.get('type'):
            return jsonify({'success': False, 'error': 'Filter criteria is required'}), 400

        session = db.session
        filter_desc = email_broadcast_service.build_filter_description(session, filter_criteria)

        # Validate template_id if provided
        template_id = data.get('template_id')
        if template_id:
            template = EmailTemplate.query.get(int(template_id))
            if not template or template.is_deleted:
                return jsonify({'success': False, 'error': 'Selected template not found'}), 400
            template_id = template.id
        else:
            template_id = None

        campaign_data = {
            'name': name,
            'subject': subject,
            'body_html': body_html,
            'template_id': template_id,
            'send_mode': data.get('send_mode', 'bcc_batch'),
            'force_send': bool(data.get('force_send', False)),
            'bcc_batch_size': int(data.get('bcc_batch_size', 100)),
            'filter_criteria': filter_criteria,
            'filter_description': filter_desc,
        }

        campaign = email_broadcast_service.create_campaign(
            session, campaign_data, current_user.id
        )

        if campaign.total_recipients == 0:
            return jsonify({
                'success': False,
                'error': 'No recipients matched the filter criteria',
            }), 400

        return jsonify({
            'success': True,
            'campaign': campaign.to_dict(),
            'message': f'Campaign created with {campaign.total_recipients} recipients',
        })

    except Exception as e:
        logger.error(f"Error creating email campaign: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/email-broadcasts/<int:campaign_id>/send', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_broadcast_send(campaign_id):
    """Trigger sending a campaign (JSON API)."""
    try:
        campaign = EmailCampaign.query.get(campaign_id)
        if not campaign:
            return jsonify({'success': False, 'error': 'Campaign not found'}), 404

        if campaign.status != 'draft':
            return jsonify({'success': False, 'error': f'Campaign is {campaign.status}, not draft'}), 400

        if campaign.total_recipients == 0:
            return jsonify({'success': False, 'error': 'Campaign has no recipients'}), 400

        # Launch Celery task
        from app.tasks.tasks_email_broadcast import send_email_broadcast
        result = send_email_broadcast.delay(campaign_id)

        campaign.celery_task_id = result.id
        campaign.status = 'sending'
        campaign.sent_at = datetime.utcnow()

        return jsonify({
            'success': True,
            'message': 'Campaign sending started',
            'task_id': result.id,
        })

    except Exception as e:
        logger.error(f"Error sending campaign {campaign_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/email-broadcasts/<int:campaign_id>/cancel', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_broadcast_cancel(campaign_id):
    """Cancel a sending campaign (JSON API)."""
    try:
        campaign = EmailCampaign.query.get(campaign_id)
        if not campaign:
            return jsonify({'success': False, 'error': 'Campaign not found'}), 404

        if campaign.status != 'sending':
            return jsonify({'success': False, 'error': 'Campaign is not currently sending'}), 400

        campaign.status = 'cancelled'
        campaign.completed_at = datetime.utcnow()

        # Mark remaining pending recipients as skipped
        EmailCampaignRecipient.query.filter_by(
            campaign_id=campaign_id, status='pending'
        ).update({'status': 'skipped', 'error_message': 'Campaign cancelled'})

        return jsonify({'success': True, 'message': 'Campaign cancelled'})

    except Exception as e:
        logger.error(f"Error cancelling campaign {campaign_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/email-broadcasts/<int:campaign_id>/duplicate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_broadcast_duplicate(campaign_id):
    """Duplicate a campaign as a new draft (JSON API)."""
    try:
        original = EmailCampaign.query.get(campaign_id)
        if not original:
            return jsonify({'success': False, 'error': 'Campaign not found'}), 404

        session = db.session
        campaign_data = {
            'name': f'{original.name} (Copy)',
            'subject': original.subject,
            'body_html': original.body_html,
            'template_id': original.template_id,
            'send_mode': original.send_mode,
            'force_send': original.force_send,
            'bcc_batch_size': original.bcc_batch_size,
            'filter_criteria': original.filter_criteria,
            'filter_description': original.filter_description,
        }

        new_campaign = email_broadcast_service.create_campaign(
            session, campaign_data, current_user.id
        )

        return jsonify({
            'success': True,
            'campaign': new_campaign.to_dict(),
            'message': f'Campaign duplicated with {new_campaign.total_recipients} recipients',
        })

    except Exception as e:
        logger.error(f"Error duplicating campaign {campaign_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/email-broadcasts/<int:campaign_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def email_broadcast_delete(campaign_id):
    """Delete a draft campaign (JSON API)."""
    try:
        campaign = EmailCampaign.query.get(campaign_id)
        if not campaign:
            return jsonify({'success': False, 'error': 'Campaign not found'}), 404

        if campaign.status not in ('draft', 'cancelled', 'failed'):
            return jsonify({'success': False, 'error': 'Can only delete draft, cancelled, or failed campaigns'}), 400

        db.session.delete(campaign)
        return jsonify({'success': True, 'message': 'Campaign deleted'})

    except Exception as e:
        logger.error(f"Error deleting campaign {campaign_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# AJAX API endpoints
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/email-broadcasts/preview-recipients')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_preview_recipients():
    """Preview filtered recipients (AJAX)."""
    try:
        filter_type = request.args.get('type', 'all_active')
        filter_criteria = {'type': filter_type}

        # Multi-select arrays (comma-separated)
        for key in ('team_ids', 'league_ids', 'role_names'):
            val = request.args.get(key, '')
            if val:
                filter_criteria[key] = [v.strip() for v in val.split(',') if v.strip()]

        # Single-value params
        for key in ('discord_role',):
            val = request.args.get(key)
            if val:
                filter_criteria[key] = val

        # Handle specific_users filter - user_ids passed as comma-separated string
        if filter_type == 'specific_users':
            user_ids_str = request.args.get('user_ids', '')
            if user_ids_str:
                filter_criteria['user_ids'] = [int(uid) for uid in user_ids_str.split(',') if uid.strip()]

        force_send = request.args.get('force_send', 'false').lower() == 'true'

        session = db.session
        recipients = email_broadcast_service.resolve_recipients(session, filter_criteria, force_send)

        return jsonify({
            'success': True,
            'count': len(recipients),
            'recipients': recipients[:100],  # Limit preview to 100
            'truncated': len(recipients) > 100,
        })

    except Exception as e:
        logger.error(f"Error previewing recipients: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-broadcasts/<int:campaign_id>/status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_status(campaign_id):
    """Poll send progress (AJAX)."""
    try:
        session = db.session
        progress = email_broadcast_service.get_campaign_progress(session, campaign_id)
        if not progress:
            return jsonify({'success': False, 'error': 'Campaign not found'}), 404

        return jsonify({'success': True, **progress})

    except Exception as e:
        logger.error(f"Error getting campaign status: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-broadcasts/search-users')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_search_users():
    """Search users by name for specific_users filter (AJAX)."""
    try:
        q = (request.args.get('q') or '').strip()
        if len(q) < 2:
            return jsonify({'success': True, 'users': []})

        users = User.query.filter(
            User.is_active == True,
            User.username.ilike(f'%{q}%'),
            User.encrypted_email.isnot(None),
        ).order_by(User.username).limit(20).all()

        return jsonify({
            'success': True,
            'users': [{'id': u.id, 'name': u.username} for u in users],
        })

    except Exception as e:
        logger.error(f"Error searching users: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-broadcasts/send-test', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_send_test():
    """Send a test email to the current user (AJAX)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        subject = (data.get('subject') or '').strip()
        body_html = (data.get('body_html') or '').strip()

        if not subject or not body_html:
            return jsonify({'success': False, 'error': 'Subject and body are required'}), 400

        user = User.query.get(current_user.id)
        if not user or not user.email:
            return jsonify({'success': False, 'error': 'Your account has no email address'}), 400

        # Personalize for current user
        session = db.session
        p_subject, p_body = email_broadcast_service.personalize_content(
            session, f'[TEST] {subject}', body_html, current_user.id
        )

        # Wrap with template if provided
        template_id = data.get('template_id')
        if template_id:
            template = EmailTemplate.query.get(int(template_id))
            if template and not template.is_deleted:
                wrapped = template.render(p_body, p_subject)
            else:
                wrapped = p_body
        else:
            wrapped = p_body

        from app.email import send_email
        result = send_email(user.email, p_subject, wrapped)

        if result:
            return jsonify({'success': True, 'message': 'Test email sent'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send test email'}), 500

    except Exception as e:
        logger.error(f"Error sending test email: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/email-broadcasts/preview-with-template', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def email_broadcast_preview_with_template():
    """Preview email body rendered inside a template wrapper (AJAX)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        body_html = (data.get('body_html') or '').strip()
        subject = (data.get('subject') or '').strip() or 'Sample Subject'
        template_id = data.get('template_id')

        if not body_html:
            return jsonify({'success': False, 'error': 'Email body is required'}), 400

        if not template_id:
            # No template - return raw body
            return jsonify({'success': True, 'html': body_html})

        template = EmailTemplate.query.get(int(template_id))
        if not template or template.is_deleted:
            return jsonify({'success': False, 'error': 'Template not found'}), 404

        rendered = template.render(body_html, subject)
        return jsonify({'success': True, 'html': rendered})

    except Exception as e:
        logger.error(f"Error previewing with template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
