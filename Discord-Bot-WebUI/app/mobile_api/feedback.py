# app/mobile_api/feedback.py

"""
Mobile API Feedback Endpoints

Provides feedback functionality for mobile clients:
- Submit feedback (auto-tagged with source='app')
- List own feedback
- View feedback detail with replies
- Reply to own feedback
- Close own feedback
"""

import logging
from datetime import datetime

from flask import jsonify, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Feedback, FeedbackReply, Role
from app.email import send_email
from app.services.notification_orchestrator import orchestrator, NotificationPayload, NotificationType

logger = logging.getLogger(__name__)

VALID_CATEGORIES = ['Bug', 'Feature', 'Other']


def _feedback_to_dict(feedback):
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
    }


def _reply_to_dict(reply):
    return {
        'id': reply.id,
        'content': reply.content,
        'is_admin_reply': reply.is_admin_reply,
        'user_name': reply.user.username if reply.user else None,
        'created_at': reply.created_at.isoformat() + 'Z' if reply.created_at else None,
    }


@mobile_api_v2.route('/feedback', methods=['POST'])
@jwt_required()
def submit_feedback():
    """
    Submit new feedback from the mobile app.

    Expected JSON:
        category: One of 'Bug', 'Feature', 'Other' (required)
        title: Brief summary (required, max 255 chars)
        description: Detailed feedback (required)

    Returns:
        201: Created feedback object
        400: Validation error
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    category = (data.get('category') or '').strip()
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()

    if not category or not title or not description:
        return jsonify({"msg": "category, title, and description are required"}), 400

    if category not in VALID_CATEGORIES:
        return jsonify({"msg": f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"}), 400

    if len(title) > 255:
        return jsonify({"msg": "Title must be 255 characters or fewer"}), 400

    with managed_session() as session:
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        feedback = Feedback(
            user_id=current_user_id,
            name=user.username,
            category=category,
            title=title,
            description=description,
            source='app',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(feedback)
        session.commit()

        # Send admin notification via all channels (non-blocking)
        try:
            admin_role = session.query(Role).filter_by(name='Global Admin').first()
            if admin_role:
                admin_users = session.query(User).filter(User.roles.contains(admin_role)).all()
                admin_user_ids = [u.id for u in admin_users]
                if admin_user_ids:
                    orchestrator.send(NotificationPayload(
                        notification_type=NotificationType.FEEDBACK_NEW,
                        title=f"New App Feedback: {feedback.title}",
                        message=f"New {feedback.category} feedback from {feedback.name}: {feedback.title}",
                        user_ids=admin_user_ids,
                        data={'feedback_id': str(feedback.id)},
                        email_subject=f"New App Feedback Submitted: {feedback.title}",
                        email_html_body=render_template('emails/new_feedback_notification.html', feedback=feedback),
                    ))
        except Exception as e:
            logger.error(f"Failed to send feedback notification: {e}")

        return jsonify(_feedback_to_dict(feedback)), 201


@mobile_api_v2.route('/feedback', methods=['GET'])
@jwt_required()
def list_feedback():
    """
    List the authenticated user's feedback submissions.

    Query Parameters:
        page: Page number (default 1)
        per_page: Items per page (default 10, max 50)
        status: Filter by status ('Open', 'In Progress', 'Closed')

    Returns:
        200: Paginated list of feedback
    """
    current_user_id = int(get_jwt_identity())

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)
    status_filter = request.args.get('status', '').strip()

    with managed_session() as session:
        query = session.query(Feedback).filter(Feedback.user_id == current_user_id)

        if status_filter:
            query = query.filter(Feedback.status == status_filter)

        total = query.count()
        feedbacks = (
            query
            .order_by(Feedback.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return jsonify({
            "feedback": [_feedback_to_dict(f) for f in feedbacks],
            "page": page,
            "per_page": per_page,
            "total": total
        }), 200


@mobile_api_v2.route('/feedback/<int:feedback_id>', methods=['GET'])
@jwt_required()
def get_feedback(feedback_id):
    """
    Get a single feedback entry with its replies.

    Returns:
        200: Feedback object with replies array
        403: Not the feedback owner
        404: Feedback not found
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        feedback = (
            session.query(Feedback)
            .options(
                joinedload(Feedback.replies).joinedload(FeedbackReply.user)
            )
            .get(feedback_id)
        )

        if not feedback:
            return jsonify({"msg": "Feedback not found"}), 404

        if feedback.user_id != current_user_id:
            return jsonify({"msg": "Access denied"}), 403

        result = _feedback_to_dict(feedback)
        result['replies'] = [
            _reply_to_dict(r) for r in sorted(feedback.replies, key=lambda r: r.created_at)
        ]

        return jsonify(result), 200


@mobile_api_v2.route('/feedback/<int:feedback_id>/reply', methods=['POST'])
@jwt_required()
def reply_to_feedback(feedback_id):
    """
    Add a reply to own feedback.

    Expected JSON:
        content: Reply text (required)

    Returns:
        201: Created reply object
        400: Validation error
        403: Not the feedback owner
        404: Feedback not found
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({"msg": "content is required"}), 400

    with managed_session() as session:
        feedback = session.query(Feedback).get(feedback_id)

        if not feedback:
            return jsonify({"msg": "Feedback not found"}), 404

        if feedback.user_id != current_user_id:
            return jsonify({"msg": "Access denied"}), 403

        if feedback.status == 'Closed':
            return jsonify({"msg": "Cannot reply to closed feedback"}), 400

        reply = FeedbackReply(
            feedback_id=feedback.id,
            user_id=current_user_id,
            content=content,
            is_admin_reply=False,
            created_at=datetime.utcnow()
        )
        session.add(reply)
        feedback.updated_at = datetime.utcnow()
        session.commit()

        # Load user for serialization
        user = session.query(User).get(current_user_id)
        return jsonify({
            'id': reply.id,
            'content': reply.content,
            'is_admin_reply': False,
            'user_name': user.username if user else None,
            'created_at': reply.created_at.isoformat() + 'Z',
        }), 201


@mobile_api_v2.route('/feedback/<int:feedback_id>/close', methods=['POST'])
@jwt_required()
def close_feedback(feedback_id):
    """
    Close own feedback.

    Returns:
        200: Updated feedback object
        400: Already closed
        403: Not the feedback owner
        404: Feedback not found
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        feedback = session.query(Feedback).get(feedback_id)

        if not feedback:
            return jsonify({"msg": "Feedback not found"}), 404

        if feedback.user_id != current_user_id:
            return jsonify({"msg": "Access denied"}), 403

        if feedback.status == 'Closed':
            return jsonify({"msg": "Feedback is already closed"}), 400

        feedback.status = 'Closed'
        feedback.closed_at = datetime.utcnow()
        feedback.updated_at = datetime.utcnow()
        session.commit()

        return jsonify(_feedback_to_dict(feedback)), 200
