# app/mobile_api/admin_feedback.py

"""
Mobile API Admin Feedback Endpoints

Global-Admin-only mobile management of user feedback tickets:
    GET    /api/v1/admin/feedback                List with filters + stats
    GET    /api/v1/admin/feedback/<id>           Detail (with replies + notes)
    POST   /api/v1/admin/feedback/<id>/reply     Admin reply (visible to user)
    POST   /api/v1/admin/feedback/<id>/note      Internal note (hidden from user)
    PATCH  /api/v1/admin/feedback/<id>           Update status and/or priority
    POST   /api/v1/admin/feedback/<id>/close     Sugar over PATCH status=Closed
    POST   /api/v1/admin/feedback/bulk           Bulk close / set_status / set_priority

Mirrors the admin web routes in app/admin_panel/routes/reports_feedback.py.
Spec: docs/BACKEND_SPEC_FEEDBACK_ADMIN.md
"""

import logging
from datetime import datetime

from flask import jsonify, request, render_template, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import User, Feedback, FeedbackReply, Note
from app.models.admin_config import AdminAuditLog
from app.services.notification_orchestrator import orchestrator, NotificationPayload, NotificationType
from app.utils.pii_encryption import create_hash

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['Global Admin']
VALID_STATUSES = ['Open', 'In Progress', 'Closed']
VALID_PRIORITIES = ['Low', 'Medium', 'High']
VALID_BULK_ACTIONS = ['close', 'set_status', 'set_priority']


# ==================== Serializers ====================

def _player_picture_url(user):
    """Return absolute profile picture URL or None.

    Mirrors Player.to_dict (players.py:299) — prepends request host to the
    stored relative path. Returns None when the user has no Player row or no
    picture set so the client can render a default avatar.
    """
    if not user or not user.player or not user.player.profile_picture_url:
        return None
    base = request.host_url.rstrip('/')
    return f"{base}{user.player.profile_picture_url}"


def _user_lite(user):
    if not user:
        return None
    return {
        'id': user.id,
        'username': user.username,
        'profile_picture_url': _player_picture_url(user),
    }


def _submitter_dict(feedback):
    if not feedback.user:
        return None
    return {
        'id': feedback.user.id,
        'username': feedback.user.username,
        'email': feedback.user.email,
        'profile_picture_url': _player_picture_url(feedback.user),
    }


def _reply_dict(reply):
    return {
        'id': reply.id,
        'content': reply.content,
        'is_admin_reply': reply.is_admin_reply,
        'user': _user_lite(reply.user),
        'created_at': reply.created_at.isoformat() + 'Z' if reply.created_at else None,
    }


def _note_dict(note):
    return {
        'id': note.id,
        'content': note.content,
        'author': _user_lite(note.author),
        'created_at': note.created_at.isoformat() + 'Z' if note.created_at else None,
    }


def _feedback_summary(feedback):
    """List-row shape: feedback fields + submitter + counts + last_admin_reply_at + metadata."""
    replies = feedback.replies or []
    last_admin = max(
        (r.created_at for r in replies if r.is_admin_reply and r.created_at),
        default=None,
    )
    return {
        'id': feedback.id,
        'category': feedback.category,
        'title': feedback.title,
        'description': feedback.description,
        'priority': feedback.priority,
        'status': feedback.status,
        'source': feedback.source,
        'created_at': feedback.created_at.isoformat() + 'Z' if feedback.created_at else None,
        'updated_at': feedback.updated_at.isoformat() + 'Z' if feedback.updated_at else None,
        'closed_at': feedback.closed_at.isoformat() + 'Z' if feedback.closed_at else None,
        'submitter': _submitter_dict(feedback),
        'reply_count': len(replies),
        'note_count': len(feedback.notes or []),
        'last_admin_reply_at': last_admin.isoformat() + 'Z' if last_admin else None,
        'metadata': feedback.extra_metadata,
    }


def _feedback_detail(feedback):
    """Detail shape: summary fields + ordered replies + notes (counts dropped)."""
    out = _feedback_summary(feedback)
    out.pop('reply_count', None)
    out.pop('note_count', None)
    out.pop('last_admin_reply_at', None)
    out['replies'] = [
        _reply_dict(r) for r in sorted(feedback.replies or [], key=lambda r: r.created_at)
    ]
    out['notes'] = [
        _note_dict(n) for n in sorted(feedback.notes or [], key=lambda n: n.created_at)
    ]
    return out


# ==================== Status transition helpers ====================

def _apply_status_change(feedback, new_status):
    """Mutate feedback.status / closed_at in place. No FCM, no commit.

    Returns True iff status actually changed. Caller is responsible for the
    session.commit() AND for dispatching the FCM event after that commit.
    """
    old_status = feedback.status
    if new_status == old_status:
        return False
    feedback.status = new_status
    if new_status == 'Closed':
        feedback.closed_at = datetime.utcnow()
    elif old_status == 'Closed':
        feedback.closed_at = None
    return True


def _dispatch_status_notification(feedback, new_status, actor_id):
    """Fire FEEDBACK_CLOSED or FEEDBACK_STATUS_CHANGE to the owner.

    No-op when the ticket has no owner or the actor IS the owner. Call only
    AFTER the DB commit so we never push for a change that didn't persist.
    """
    if not feedback.user_id or feedback.user_id == actor_id:
        return
    try:
        if new_status == 'Closed':
            orchestrator.send(NotificationPayload(
                notification_type=NotificationType.FEEDBACK_CLOSED,
                title=f"Feedback Closed: {feedback.title}",
                message=f"Your feedback has been closed: {feedback.title}",
                user_ids=[feedback.user_id],
                data={'feedback_id': str(feedback.id)},
                email_subject=f"Your Feedback #{feedback.id} has been closed",
                email_html_body=render_template('emails/feedback_closed.html', feedback=feedback),
                action_url=url_for('feedback.view_feedback', feedback_id=feedback.id, _external=True),
            ))
        else:
            status_messages = {
                'In Progress': f"Your feedback is now being worked on: {feedback.title}",
                'Open': f"Your feedback has been reopened: {feedback.title}",
            }
            orchestrator.send(NotificationPayload(
                notification_type=NotificationType.FEEDBACK_STATUS_CHANGE,
                title=f"Feedback Update: {feedback.title}",
                message=status_messages.get(new_status, f"Your feedback status changed to {new_status}: {feedback.title}"),
                user_ids=[feedback.user_id],
                data={'feedback_id': str(feedback.id)},
                action_url=url_for('feedback.view_feedback', feedback_id=feedback.id, _external=True),
            ))
    except Exception as e:
        logger.error(f"Failed to dispatch status change notification for feedback #{feedback.id}: {e}")


# ==================== List ====================

@mobile_api_v2.route('/admin/feedback', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_list_feedback():
    """List feedback with filters + stats. Mirrors web /admin-panel/feedback."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    status_filter = (request.args.get('status') or '').strip()
    priority_filter = (request.args.get('priority') or '').strip()
    category_filter = (request.args.get('category') or '').strip()
    source_filter = (request.args.get('source') or '').strip()
    search = (request.args.get('search') or '').strip()
    show_closed = request.args.get('show_closed', '0')

    with managed_session() as session:
        query = session.query(Feedback).options(
            joinedload(Feedback.user).joinedload(User.player),
            joinedload(Feedback.replies),
            joinedload(Feedback.notes),
        )

        if status_filter:
            query = query.filter(Feedback.status == status_filter)
        elif show_closed != '1':
            query = query.filter(Feedback.status.in_(['Open', 'In Progress']))

        if priority_filter:
            query = query.filter(Feedback.priority == priority_filter)
        if source_filter:
            query = query.filter(Feedback.source == source_filter)
        if category_filter:
            query = query.filter(Feedback.category == category_filter)

        if search:
            query = query.outerjoin(User, Feedback.user_id == User.id)
            conditions = [
                Feedback.title.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%'),
            ]
            if '@' in search:
                conditions.append(User.email_hash == create_hash(search.lower()))
            query = query.filter(or_(*conditions))

        total = query.count()
        feedbacks = (
            query.order_by(Feedback.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # Stats — mirrors reports_feedback.py:289-297.
        # Two grouped counts, not six full-table COUNT(*) scans.
        from sqlalchemy import func
        by_status = dict(
            session.query(Feedback.status, func.count(Feedback.id))
            .group_by(Feedback.status).all()
        )
        by_source = dict(
            session.query(Feedback.source, func.count(Feedback.id))
            .group_by(Feedback.source).all()
        )
        stats = {
            'total': sum(by_status.values()),
            'open': by_status.get('Open', 0),
            'in_progress': by_status.get('In Progress', 0),
            'closed': by_status.get('Closed', 0),
            'web': by_source.get('web', 0),
            'app': by_source.get('app', 0),
        }

        return jsonify({
            'feedback': [_feedback_summary(f) for f in feedbacks],
            'page': page,
            'per_page': per_page,
            'total': total,
            'stats': stats,
        }), 200


# ==================== Detail ====================

@mobile_api_v2.route('/admin/feedback/<int:feedback_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_get_feedback(feedback_id: int):
    """Full ticket detail with replies + internal notes."""
    with managed_session() as session:
        feedback = (
            session.query(Feedback)
            .options(
                joinedload(Feedback.user).joinedload(User.player),
                joinedload(Feedback.replies).joinedload(FeedbackReply.user).joinedload(User.player),
                joinedload(Feedback.notes).joinedload(Note.author).joinedload(User.player),
            )
            .get(feedback_id)
        )
        if not feedback:
            return jsonify({'msg': 'Feedback not found'}), 404
        return jsonify(_feedback_detail(feedback)), 200


# ==================== Reply (visible to owner) ====================

@mobile_api_v2.route('/admin/feedback/<int:feedback_id>/reply', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_reply_to_feedback(feedback_id: int):
    """Add an admin reply (visible to owner). Fires FEEDBACK_REPLY to the owner."""
    actor_id = int(get_jwt_identity())
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'msg': 'content is required'}), 400

    with managed_session() as session:
        feedback = (
            session.query(Feedback)
            .options(joinedload(Feedback.user))
            .get(feedback_id)
        )
        if not feedback:
            return jsonify({'msg': 'Feedback not found'}), 404
        if feedback.status == 'Closed':
            return jsonify({'msg': 'Cannot reply to closed feedback'}), 409

        reply = FeedbackReply(
            feedback_id=feedback.id,
            user_id=actor_id,
            content=content,
            is_admin_reply=True,
            created_at=datetime.utcnow(),
        )
        session.add(reply)
        feedback.updated_at = datetime.utcnow()
        session.commit()

        # Notify owner unless owner is also the actor
        if feedback.user_id and feedback.user_id != actor_id:
            try:
                orchestrator.send(NotificationPayload(
                    notification_type=NotificationType.FEEDBACK_REPLY,
                    title=f"Reply to: {feedback.title}",
                    message=f"An admin has replied to your feedback: {feedback.title}",
                    user_ids=[feedback.user_id],
                    data={'feedback_id': str(feedback.id)},
                    email_subject=f"New admin reply to your Feedback #{feedback.id}",
                    email_html_body=render_template('emails/new_reply_admin.html', feedback=feedback, reply=reply),
                    action_url=url_for('feedback.view_feedback', feedback_id=feedback.id, _external=True),
                ))
            except Exception as e:
                logger.error(f"Failed to send reply notification for feedback #{feedback.id}: {e}")

        AdminAuditLog.log_action(
            user_id=actor_id,
            action='feedback_reply',
            resource_type='feedback',
            resource_id=str(feedback_id),
            new_value=f'Admin reply added to feedback #{feedback_id}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

        actor = session.query(User).options(joinedload(User.player)).get(actor_id)
        return jsonify({
            'id': reply.id,
            'content': reply.content,
            'is_admin_reply': True,
            'user': _user_lite(actor),
            'created_at': reply.created_at.isoformat() + 'Z',
        }), 201


# ==================== Internal Note (hidden from owner) ====================

@mobile_api_v2.route('/admin/feedback/<int:feedback_id>/note', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_add_note(feedback_id: int):
    """Add an internal note (admin-only; never sent to owner endpoints, no FCM)."""
    actor_id = int(get_jwt_identity())
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'msg': 'content is required'}), 400

    with managed_session() as session:
        feedback = session.query(Feedback).get(feedback_id)
        if not feedback:
            return jsonify({'msg': 'Feedback not found'}), 404

        note = Note(
            feedback_id=feedback.id,
            author_id=actor_id,
            content=content,
        )
        session.add(note)
        session.commit()

        AdminAuditLog.log_action(
            user_id=actor_id,
            action='feedback_note',
            resource_type='feedback',
            resource_id=str(feedback_id),
            new_value=f'Internal note added to feedback #{feedback_id}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

        actor = session.query(User).options(joinedload(User.player)).get(actor_id)
        return jsonify({
            'id': note.id,
            'content': note.content,
            'author': _user_lite(actor),
            'created_at': note.created_at.isoformat() + 'Z' if note.created_at else None,
        }), 201


# ==================== Patch (status / priority) ====================

@mobile_api_v2.route('/admin/feedback/<int:feedback_id>', methods=['PATCH'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_patch_feedback(feedback_id: int):
    """Update status and/or priority. Fires FCM on status change."""
    actor_id = int(get_jwt_identity())
    data = request.get_json() or {}
    new_status = data.get('status')
    new_priority = data.get('priority')

    if new_status is None and new_priority is None:
        return jsonify({'msg': 'At least one of status or priority is required'}), 422
    if new_status is not None and new_status not in VALID_STATUSES:
        return jsonify({'msg': f'Invalid status. Must be one of: {VALID_STATUSES}'}), 422
    if new_priority is not None and new_priority not in VALID_PRIORITIES:
        return jsonify({'msg': f'Invalid priority. Must be one of: {VALID_PRIORITIES}'}), 422

    with managed_session() as session:
        feedback = (
            session.query(Feedback)
            .options(
                joinedload(Feedback.user).joinedload(User.player),
                joinedload(Feedback.replies).joinedload(FeedbackReply.user).joinedload(User.player),
                joinedload(Feedback.notes).joinedload(Note.author).joinedload(User.player),
            )
            .get(feedback_id)
        )
        if not feedback:
            return jsonify({'msg': 'Feedback not found'}), 404

        old_status = feedback.status
        old_priority = feedback.priority

        if new_priority is not None and new_priority != old_priority:
            feedback.priority = new_priority
        status_changed = False
        if new_status is not None:
            status_changed = _apply_status_change(feedback, new_status)

        session.commit()

        if status_changed:
            _dispatch_status_notification(feedback, new_status, actor_id)

        diff_parts = []
        if status_changed:
            diff_parts.append(f'status: {old_status}->{new_status}')
        if new_priority is not None and new_priority != old_priority:
            diff_parts.append(f'priority: {old_priority}->{new_priority}')
        if diff_parts:
            AdminAuditLog.log_action(
                user_id=actor_id,
                action='feedback_update',
                resource_type='feedback',
                resource_id=str(feedback_id),
                new_value='; '.join(diff_parts),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
            )

        return jsonify(_feedback_detail(feedback)), 200


# ==================== Close (sugar) ====================

@mobile_api_v2.route('/admin/feedback/<int:feedback_id>/close', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_close_feedback(feedback_id: int):
    """Close a feedback ticket (sugar over PATCH status=Closed)."""
    actor_id = int(get_jwt_identity())

    with managed_session() as session:
        feedback = (
            session.query(Feedback)
            .options(
                joinedload(Feedback.user).joinedload(User.player),
                joinedload(Feedback.replies).joinedload(FeedbackReply.user).joinedload(User.player),
                joinedload(Feedback.notes).joinedload(Note.author).joinedload(User.player),
            )
            .get(feedback_id)
        )
        if not feedback:
            return jsonify({'msg': 'Feedback not found'}), 404

        if feedback.status == 'Closed':
            return jsonify(_feedback_detail(feedback)), 200  # idempotent no-op

        _apply_status_change(feedback, 'Closed')
        session.commit()

        _dispatch_status_notification(feedback, 'Closed', actor_id)

        AdminAuditLog.log_action(
            user_id=actor_id,
            action='feedback_close',
            resource_type='feedback',
            resource_id=str(feedback_id),
            new_value='Feedback closed',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return jsonify(_feedback_detail(feedback)), 200


# ==================== Bulk ====================

@mobile_api_v2.route('/admin/feedback/bulk', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_bulk_feedback():
    """Apply an action to many feedback tickets at once.

    body: {"feedback_ids": [int, ...],
           "action": "close" | "set_status" | "set_priority",
           "value": str (required for set_status/set_priority)}
    """
    actor_id = int(get_jwt_identity())
    data = request.get_json() or {}
    feedback_ids = data.get('feedback_ids') or []
    action = (data.get('action') or '').strip()
    value = data.get('value')

    if not isinstance(feedback_ids, list) or not feedback_ids:
        return jsonify({'msg': 'feedback_ids must be a non-empty list'}), 400
    if action not in VALID_BULK_ACTIONS:
        return jsonify({'msg': f'Invalid action. Must be one of: {VALID_BULK_ACTIONS}'}), 400
    if action == 'set_status' and value not in VALID_STATUSES:
        return jsonify({'msg': f'Invalid value for set_status. Must be one of: {VALID_STATUSES}'}), 422
    if action == 'set_priority' and value not in VALID_PRIORITIES:
        return jsonify({'msg': f'Invalid value for set_priority. Must be one of: {VALID_PRIORITIES}'}), 422

    target_status = 'Closed' if action == 'close' else (value if action == 'set_status' else None)
    target_priority = value if action == 'set_priority' else None

    updated = []
    failed = []
    # (feedback, status_changed_to_or_None) — defer FCM until after commit
    pending_dispatches = []

    with managed_session() as session:
        for fid in feedback_ids:
            try:
                fid_int = int(fid)
            except (TypeError, ValueError):
                failed.append({'id': fid, 'reason': 'invalid_id'})
                continue

            feedback = (
                session.query(Feedback)
                .options(joinedload(Feedback.user))
                .get(fid_int)
            )
            if not feedback:
                failed.append({'id': fid_int, 'reason': 'not_found'})
                continue

            try:
                if target_priority is not None:
                    feedback.priority = target_priority
                status_changed = False
                if target_status is not None:
                    status_changed = _apply_status_change(feedback, target_status)
                session.flush()
                updated.append(fid_int)
                if status_changed:
                    pending_dispatches.append((feedback, target_status))
            except Exception as e:
                logger.error(f"Bulk action {action} failed for feedback #{fid_int}: {e}")
                failed.append({'id': fid_int, 'reason': 'error'})

        session.commit()

        # Dispatch FCM for each ticket whose status actually changed (post-commit).
        for feedback, new_status in pending_dispatches:
            _dispatch_status_notification(feedback, new_status, actor_id)

        for fid_int in updated:
            AdminAuditLog.log_action(
                user_id=actor_id,
                action=f'feedback_bulk_{action}',
                resource_type='feedback',
                resource_id=str(fid_int),
                new_value=f'Bulk {action}={value or "Closed"}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
            )

        AdminAuditLog.log_action(
            user_id=actor_id,
            action='feedback_bulk',
            resource_type='feedback',
            resource_id=None,
            new_value=f'{action}={value or "Closed"} on {len(updated)} tickets ({len(failed)} failed)',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

        return jsonify({'updated': updated, 'failed': failed}), 200
