# app/admin_panel/routes/communication/composer.py

"""
Multi-channel Composer — write once, send anywhere.

The Phase-4 "north star" of the comms overhaul: ONE compose surface that
delivers through the NotificationOrchestrator with an explicit channel
allow-list, so every member's channel preferences are honored automatically.

Pages
  GET  /admin-panel/communication/compose

JSON API
  POST /admin-panel/api/communication/compose/preview   {audience_type, audience_ids}
  POST /admin-panel/api/communication/compose/send      {title, message, channels,
                                                         audience_type, audience_ids,
                                                         action_url?, priority?,
                                                         scheduled_send_time?  (PST)}
  POST /admin-panel/api/communication/compose/<id>/cancel
  GET  /admin-panel/api/communication/compose/search-users?q=
"""

import logging
from datetime import datetime

import pytz
from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.decorators import role_required
from app.models import Team, League, Season, Role, User, Player, ComposedMessage
from app.models.admin_config import AdminAuditLog
from app.services import audience_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

_ROLES = ['Global Admin', 'Pub League Admin']
VALID_CHANNELS = ('in_app', 'push', 'email', 'sms', 'discord')
MAX_TITLE = 100
MAX_MESSAGE = 1000


def _pst_to_utc(value):
    """'YYYY-MM-DDTHH:MM' entered as PST -> naive UTC datetime."""
    local_dt = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    pst = pytz.timezone('America/Los_Angeles')
    return pst.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)


@admin_panel_bp.route('/communication/compose')
@login_required
@role_required(_ROLES)
def message_composer():
    """The compose page: write once, pick channels + audience, send/schedule."""
    teams = Team.query.join(League, Team.league_id == League.id).join(
        Season, League.season_id == Season.id
    ).filter(Season.is_current == True, Team.is_active == True).order_by(Team.name).all()  # noqa: E712
    leagues = League.query.join(Season, League.season_id == Season.id).filter(
        Season.is_current == True  # noqa: E712
    ).order_by(League.name).all()
    roles = Role.query.order_by(Role.name).all()

    history = ComposedMessage.query.options(
        joinedload(ComposedMessage.created_by)
    ).order_by(ComposedMessage.created_at.desc()).limit(15).all()

    return render_template(
        'admin_panel/communication/compose_flowbite.html',
        teams=teams, leagues=leagues, roles=roles, history=history,
    )


@admin_panel_bp.route('/api/communication/compose/preview', methods=['POST'])
@login_required
@role_required(_ROLES)
def composer_preview():
    """Per-channel reachability preview for the chosen audience."""
    try:
        data = request.get_json(force=True) or {}
        audience_type = data.get('audience_type', 'all_active')
        audience_ids = data.get('audience_ids') or []
        if audience_type not in audience_service.AUDIENCE_TYPES:
            return jsonify({'success': False, 'error': 'Unknown audience type'}), 400

        user_ids = audience_service.resolve_user_ids(db.session, audience_type, audience_ids)
        reach = audience_service.channel_reach(db.session, user_ids)
        description = audience_service.describe(db.session, audience_type, audience_ids)
        return jsonify({'success': True, 'reach': reach, 'description': description})
    except Exception as e:
        logger.error(f"Composer preview failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/communication/compose/send', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def composer_send():
    """Create a ComposedMessage and queue it (now or at a scheduled PST time)."""
    try:
        data = request.get_json(force=True) or {}

        title = (data.get('title') or '').strip()
        message = (data.get('message') or '').strip()
        channels = [c for c in (data.get('channels') or []) if c in VALID_CHANNELS]
        audience_type = data.get('audience_type', 'all_active')
        audience_ids = data.get('audience_ids') or []
        action_url = (data.get('action_url') or '').strip() or None
        priority = 'high' if data.get('priority') == 'high' else 'normal'
        schedule_raw = (data.get('scheduled_send_time') or '').strip()

        if not title or not message:
            return jsonify({'success': False, 'error': 'Title and message are required.'}), 400
        if len(title) > MAX_TITLE or len(message) > MAX_MESSAGE:
            return jsonify({'success': False, 'error': 'Title or message is too long.'}), 400
        if not channels:
            return jsonify({'success': False, 'error': 'Pick at least one channel.'}), 400
        if audience_type not in audience_service.AUDIENCE_TYPES:
            return jsonify({'success': False, 'error': 'Unknown audience type'}), 400
        if audience_type != 'all_active' and not audience_ids:
            return jsonify({'success': False, 'error': 'Pick at least one audience target.'}), 400

        # The audience is re-resolved at send time; this count is a sanity check
        # so an empty audience fails loudly now instead of at 9 AM tomorrow.
        user_ids = audience_service.resolve_user_ids(db.session, audience_type, audience_ids)
        if not user_ids:
            return jsonify({'success': False, 'error': 'No members match that audience.'}), 400

        scheduled_utc = None
        if schedule_raw:
            try:
                scheduled_utc = _pst_to_utc(schedule_raw)
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid schedule time format.'}), 400
            if scheduled_utc <= datetime.utcnow():
                return jsonify({'success': False, 'error': 'The scheduled time must be in the future.'}), 400
            # Broker eta tasks are only reliable inside Redis's visibility
            # timeout (7 days) — beyond it the task gets redelivered and would
            # double-send. Cap the window rather than risk duplicates.
            if (scheduled_utc - datetime.utcnow()).days >= 6:
                return jsonify({'success': False,
                                'error': 'Schedules can be at most 6 days out. For anything later, come back closer to the date.'}), 400

        # Idempotency: an identical message from the same admin inside 60s is a
        # double-click or client retry, not a second blast.
        from datetime import timedelta
        duplicate = ComposedMessage.query.filter(
            ComposedMessage.created_by_id == current_user.id,
            ComposedMessage.title == title,
            ComposedMessage.message == message,
            ComposedMessage.created_at >= datetime.utcnow() - timedelta(seconds=60),
        ).first()
        if duplicate:
            return jsonify({'success': False,
                            'error': 'An identical message was just submitted — check Recent messages below.'}), 409

        msg = ComposedMessage(
            title=title,
            message=message,
            channels=channels,
            audience_type=audience_type,
            audience_ids=audience_ids or None,
            audience_description=audience_service.describe(db.session, audience_type, audience_ids),
            action_url=action_url,
            priority=priority,
            status='scheduled',
            scheduled_send_time=scheduled_utc,
            total_recipients=len(user_ids),
            created_by_id=current_user.id,
        )
        db.session.add(msg)
        # COMMIT BEFORE ENQUEUE. @transactional only commits after this view
        # returns, but a worker can dequeue the task and look the row up before
        # that commit lands — the task then dies with "Message not found"
        # (max_retries=0) and the row is stuck "scheduled" forever.
        db.session.commit()

        from app.tasks.tasks_composed_messages import send_composed_message
        try:
            if scheduled_utc:
                eta = pytz.utc.localize(scheduled_utc)
                result = send_composed_message.apply_async(args=[msg.id], eta=eta)
            else:
                result = send_composed_message.delay(msg.id)
        except Exception as enqueue_err:
            logger.error(f"Could not enqueue composed message {msg.id}: {enqueue_err}")
            msg.status = 'failed'
            msg.error_message = 'Could not queue the delivery task — check the task broker.'
            db.session.commit()
            return jsonify({'success': False,
                            'error': 'The message was saved but could not be queued for delivery. Check the task queue and retry.'}), 502

        # The identity guard tolerates celery_task_id being NULL when the task
        # fires first, so committing the id after enqueue is safe.
        msg.celery_task_id = getattr(result, 'id', None)
        db.session.commit()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='COMPOSE_MESSAGE',
            resource_type='ComposedMessage',
            resource_id=str(msg.id),
            new_value=(f'"{title}" via {"/".join(channels)} to {msg.audience_description} '
                       f'({len(user_ids)} members)'
                       + (f', scheduled {schedule_raw} PST' if schedule_raw else ', immediate')),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

        return jsonify({
            'success': True,
            'message_id': msg.id,
            'scheduled': bool(scheduled_utc),
            'recipients': len(user_ids),
            'status_message': (f'Scheduled for {schedule_raw.replace("T", " ")} PST'
                               if scheduled_utc else 'Sending now'),
        })
    except Exception as e:
        logger.error(f"Composer send failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/communication/compose/<int:message_id>/cancel', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def composer_cancel(message_id):
    """Cancel a scheduled composed message before it fires."""
    try:
        msg = ComposedMessage.query.get(message_id)
        if not msg:
            return jsonify({'success': False, 'error': 'Message not found'}), 404
        if msg.status != 'scheduled':
            return jsonify({'success': False, 'error': f'Message is {msg.status}, not scheduled'}), 400

        # Best-effort revoke; the task's identity/status guards are the backstop.
        if msg.celery_task_id:
            try:
                from app.core import celery
                celery.control.revoke(msg.celery_task_id)
            except Exception as revoke_err:
                logger.warning(f"Could not revoke composed-message task {msg.celery_task_id}: {revoke_err}")

        msg.status = 'cancelled'
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Composer cancel failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


@admin_panel_bp.route('/api/communication/compose/search-users')
@login_required
@role_required(_ROLES)
def composer_search_users():
    """Typeahead for the 'Specific people' audience — ALL active users
    (unlike the push search, which only returns users with device tokens)."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify({'success': True, 'users': []})

    search = f'%{q}%'
    users = db.session.query(User).outerjoin(
        Player, Player.user_id == User.id
    ).options(joinedload(User.player)).filter(
        User.is_active == True,  # noqa: E712
        or_(User.username.ilike(search), Player.name.ilike(search)),
    ).distinct().limit(15).all()

    return jsonify({'success': True, 'users': [{
        'id': u.id,
        'username': u.username,
        'name': u.player.name if u.player else u.username,
    } for u in users]})
