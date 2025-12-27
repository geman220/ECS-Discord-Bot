# app/mobile_api/messages.py

"""
Mobile API - Direct Messaging Endpoints

Provides mobile app access to the in-app messaging system.
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Role
from app.models.messages import DirectMessage, MessagingPermission, MessagingSettings

logger = logging.getLogger(__name__)


def _build_avatar_url(profile_picture_url):
    """Build full avatar URL from profile picture path."""
    base_url = request.host_url.rstrip('/')
    if profile_picture_url:
        if profile_picture_url.startswith('http'):
            return profile_picture_url
        else:
            return f"{base_url}{profile_picture_url}"
    else:
        return f"{base_url}/static/img/default_player.png"


def _user_to_dict(user, session_db):
    """Serialize user for API responses with full avatar URLs and role badges."""
    player = session_db.query(Player).filter_by(user_id=user.id).first()
    avatar_url = _build_avatar_url(player.profile_picture_url if player else None)

    # Check roles for badges
    is_global_admin = user.has_role('Global Admin') if hasattr(user, 'has_role') else False
    is_admin = user.has_role('Pub League Admin') if hasattr(user, 'has_role') else False
    is_coach = (
        user.has_role('Pub League Coach') or
        user.has_role('ECS FC Coach') or
        (player and player.is_coach)
    ) if hasattr(user, 'has_role') else (player and player.is_coach if player else False)
    is_ref = user.has_role('Pub League Ref') if hasattr(user, 'has_role') else False

    return {
        'id': user.id,
        'username': user.username,
        'name': player.name if player else user.username,
        'avatar_url': avatar_url,
        'is_coach': is_coach,
        'is_admin': is_admin,
        'is_global_admin': is_global_admin,
        'is_ref': is_ref,
    }


def _message_to_dict(msg, for_user_id=None):
    """Serialize a DirectMessage with full avatar URLs and sender badges for mobile API.

    Args:
        msg: DirectMessage object
        for_user_id: If provided, adds is_from_me field based on this user's perspective
    """
    msg_dict = msg.to_dict()

    # Add is_from_me if we know who's viewing
    if for_user_id is not None:
        msg_dict['is_from_me'] = (msg.sender_id == for_user_id)

    # Fix sender_avatar to be a full URL
    if msg.sender and msg.sender.player:
        msg_dict['sender_avatar'] = _build_avatar_url(msg.sender.player.profile_picture_url)
    else:
        msg_dict['sender_avatar'] = _build_avatar_url(None)

    # Add sender role badges
    if msg.sender:
        sender = msg.sender
        player = sender.player if hasattr(sender, 'player') else None
        msg_dict['sender_is_global_admin'] = sender.has_role('Global Admin') if hasattr(sender, 'has_role') else False
        msg_dict['sender_is_admin'] = sender.has_role('Pub League Admin') if hasattr(sender, 'has_role') else False
        msg_dict['sender_is_coach'] = (
            sender.has_role('Pub League Coach') or
            sender.has_role('ECS FC Coach') or
            (player and player.is_coach)
        ) if hasattr(sender, 'has_role') else (player and player.is_coach if player else False)
        msg_dict['sender_is_ref'] = sender.has_role('Pub League Ref') if hasattr(sender, 'has_role') else False
    else:
        msg_dict['sender_is_global_admin'] = False
        msg_dict['sender_is_admin'] = False
        msg_dict['sender_is_coach'] = False
        msg_dict['sender_is_ref'] = False

    return msg_dict


def _get_role_ids(user, session_db):
    """
    Get role IDs for a user, handling both Role objects and string role names.

    When role impersonation is active, user.roles may return strings (role names)
    instead of Role objects. This function handles both cases.

    Returns list of role IDs.
    """
    role_ids = []
    for role in user.roles:
        if hasattr(role, 'id'):
            # It's a Role object
            role_ids.append(role.id)
        elif isinstance(role, str):
            # It's a role name string (from role impersonation)
            role_obj = session_db.query(Role).filter_by(name=role).first()
            if role_obj:
                role_ids.append(role_obj.id)
    return role_ids


def _can_user_message(sender_user, recipient_user, session_db):
    """Check if sender can message recipient based on permissions."""
    settings = session_db.query(MessagingSettings).first()
    if settings and not settings.enabled:
        return False, 'Messaging is currently disabled'

    # Get role IDs for both users (handles Role objects and string names)
    sender_role_ids = _get_role_ids(sender_user, session_db)
    recipient_role_ids = _get_role_ids(recipient_user, session_db)

    if not sender_role_ids or not recipient_role_ids:
        return False, 'User roles not configured'

    # Check if any permissions exist
    any_permissions = session_db.query(MessagingPermission).first()
    if not any_permissions:
        # No permissions configured = allow all
        return True, None

    # Check for explicit permission
    permission = session_db.query(MessagingPermission).filter(
        MessagingPermission.sender_role_id.in_(sender_role_ids),
        MessagingPermission.recipient_role_id.in_(recipient_role_ids),
        MessagingPermission.is_allowed == True
    ).first()

    if permission:
        return True, None

    return False, 'You do not have permission to message this user'


@mobile_api_v2.route('/messages', methods=['GET'])
@jwt_required()
def get_conversations():
    """
    Get list of conversations for current user.

    Returns:
        JSON with conversations list
    """
    current_user_id = int(get_jwt_identity())
    limit = min(int(request.args.get('limit', 20)), 50)

    with managed_session() as session_db:
        user = session_db.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Get conversations
        messages = DirectMessage.get_conversations_for_user(current_user_id, limit=limit)

        conversations = []
        for msg in messages:
            other_user_id = msg.recipient_id if msg.sender_id == current_user_id else msg.sender_id
            other_user = session_db.query(User).get(other_user_id)

            if not other_user:
                continue

            # Count unread messages from this user
            unread_count = session_db.query(DirectMessage).filter_by(
                sender_id=other_user_id,
                recipient_id=current_user_id,
                is_read=False
            ).count()

            conversations.append({
                'user': _user_to_dict(other_user, session_db),
                'last_message': {
                    'content': msg.content[:100] + '...' if len(msg.content) > 100 else msg.content,
                    'sent_by_me': msg.sender_id == current_user_id,
                    'created_at': (msg.created_at.isoformat() + 'Z') if msg.created_at else None
                },
                'unread_count': unread_count
            })

        return jsonify({
            'conversations': conversations,
            'total': len(conversations)
        }), 200


@mobile_api_v2.route('/messages/unread-count', methods=['GET'])
@jwt_required()
def get_unread_count():
    """Get total unread message count."""
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        count = session_db.query(DirectMessage).filter_by(
            recipient_id=current_user_id,
            is_read=False
        ).count()

        return jsonify({'count': count}), 200


@mobile_api_v2.route('/messages/<int:user_id>', methods=['GET'])
@jwt_required()
def get_conversation(user_id):
    """
    Get conversation history with a specific user.

    Args:
        user_id: The other user's ID

    Query params:
        limit: Number of messages (default 50, max 100)
        offset: Pagination offset (default 0)

    Returns:
        JSON with messages
    """
    current_user_id = int(get_jwt_identity())
    limit = min(int(request.args.get('limit', 50)), 100)
    offset = int(request.args.get('offset', 0))

    with managed_session() as session_db:
        current_user = session_db.query(User).get(current_user_id)
        other_user = session_db.query(User).get(user_id)

        if not current_user or not other_user:
            return jsonify({"msg": "User not found"}), 404

        # Get messages
        messages = DirectMessage.get_conversation(
            current_user_id,
            user_id,
            limit=limit,
            offset=offset
        )

        # Mark messages as read
        unread_messages = [m for m in messages if m.recipient_id == current_user_id and not m.is_read]
        for msg in unread_messages:
            msg.mark_as_read()
        if unread_messages:
            session_db.commit()

        # Get settings
        settings = session_db.query(MessagingSettings).first()

        return jsonify({
            'user': _user_to_dict(other_user, session_db),
            'messages': [_message_to_dict(msg, for_user_id=current_user_id) for msg in reversed(messages)],
            'has_more': len(messages) == limit,
            'settings': {
                'typing_indicators': settings.typing_indicators if settings else True,
                'read_receipts': settings.read_receipts if settings else True,
                'max_message_length': settings.max_message_length if settings else 2000
            }
        }), 200


@mobile_api_v2.route('/messages/<int:user_id>', methods=['POST'])
@jwt_required()
def send_message(user_id):
    """
    Send a message to a user.

    Args:
        user_id: The recipient's user ID

    Request body:
        content: Message text (required)

    Returns:
        JSON with the sent message
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json() or {}
    content = data.get('content', '').strip()

    if not content:
        return jsonify({"msg": "Message content is required"}), 400

    with managed_session() as session_db:
        current_user = session_db.query(User).get(current_user_id)
        recipient = session_db.query(User).get(user_id)

        if not current_user or not recipient:
            return jsonify({"msg": "User not found"}), 404

        # Get settings and check length
        settings = session_db.query(MessagingSettings).first()
        max_length = settings.max_message_length if settings else 2000

        if len(content) > max_length:
            return jsonify({"msg": f"Message too long. Maximum {max_length} characters."}), 400

        # Check permission
        can_message, reason = _can_user_message(current_user, recipient, session_db)
        if not can_message:
            return jsonify({"msg": reason}), 403

        # Create message
        message = DirectMessage(
            sender_id=current_user_id,
            recipient_id=user_id,
            content=content
        )
        session_db.add(message)
        session_db.commit()

        # Send notification via orchestrator
        try:
            from app.services.notification_orchestrator import orchestrator
            from app.sockets.presence import PresenceManager

            if not PresenceManager.is_user_online(user_id):
                sender_name = None
                player = session_db.query(Player).filter_by(user_id=current_user_id).first()
                sender_name = player.name if player else current_user.username

                orchestrator.send_direct_message(
                    recipient_id=user_id,
                    sender_id=current_user_id,
                    sender_name=sender_name,
                    message_preview=content,
                    message_id=message.id
                )
        except Exception as e:
            logger.warning(f"Failed to send push notification: {e}")

        # Emit WebSocket event to recipient (from their perspective, is_from_me=False)
        try:
            from flask import current_app
            from app.sockets.presence import PresenceManager

            socketio = current_app.extensions.get('socketio')
            if socketio and PresenceManager.is_user_online(user_id):
                msg_data = _message_to_dict(message, for_user_id=user_id)  # Recipient's perspective
                # Emit to default namespace (web browser clients)
                socketio.emit('new_message', msg_data, room=f'user_{user_id}')
                # Emit to /live namespace (Flutter mobile clients)
                socketio.emit('new_message', msg_data, room=f'user_{user_id}', namespace='/live')
        except Exception as e:
            logger.warning(f"Failed to emit WebSocket: {e}")

        # Return to sender with is_from_me=True
        return jsonify({
            'message': _message_to_dict(message, for_user_id=current_user_id)
        }), 201


@mobile_api_v2.route('/messages/<int:message_id>/read', methods=['POST'])
@jwt_required()
def mark_message_read(message_id):
    """Mark a single message as read."""
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        message = session_db.query(DirectMessage).filter_by(
            id=message_id,
            recipient_id=current_user_id
        ).first()

        if not message:
            return jsonify({"msg": "Message not found"}), 404

        message.mark_as_read()
        session_db.commit()

        unread_count = session_db.query(DirectMessage).filter_by(
            recipient_id=current_user_id,
            is_read=False
        ).count()

        return jsonify({
            'msg': 'Message marked as read',
            'unread_count': unread_count
        }), 200


@mobile_api_v2.route('/messages/mark-all-read', methods=['POST'])
@jwt_required()
def mark_all_messages_read():
    """Mark all messages as read for current user."""
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        session_db.query(DirectMessage).filter_by(
            recipient_id=current_user_id,
            is_read=False
        ).update({
            'is_read': True,
            'read_at': datetime.utcnow()
        })
        session_db.commit()

        return jsonify({
            'msg': 'All messages marked as read',
            'unread_count': 0
        }), 200


@mobile_api_v2.route('/messages/users/search', methods=['GET'])
@jwt_required()
def search_users():
    """
    Search for users to start a conversation with.

    Query params:
        q: Search query (name/username)
        limit: Max results (default 10)

    Returns:
        JSON with matching users
    """
    current_user_id = int(get_jwt_identity())
    query = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 10)), 25)

    if len(query) < 2:
        return jsonify({'users': []}), 200

    with managed_session() as session_db:
        current_user = session_db.query(User).get(current_user_id)
        if not current_user:
            return jsonify({"msg": "User not found"}), 404

        # Search users by name or username
        from sqlalchemy import or_

        users = session_db.query(User).outerjoin(Player).filter(
            User.id != current_user_id,
            or_(
                Player.name.ilike(f'%{query}%'),
                User.username.ilike(f'%{query}%')
            )
        ).limit(limit).all()

        # Filter to users we can message
        results = []
        for user in users:
            can_msg, _ = _can_user_message(current_user, user, session_db)
            if can_msg:
                results.append(_user_to_dict(user, session_db))

        return jsonify({'users': results}), 200


@mobile_api_v2.route('/messages/can-message/<int:user_id>', methods=['GET'])
@jwt_required()
def check_can_message(user_id):
    """Check if current user can message a specific user."""
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        current_user = session_db.query(User).get(current_user_id)
        recipient = session_db.query(User).get(user_id)

        if not current_user or not recipient:
            return jsonify({
                'can_message': False,
                'reason': 'User not found'
            }), 404

        can_message, reason = _can_user_message(current_user, recipient, session_db)

        return jsonify({
            'can_message': can_message,
            'reason': reason
        }), 200


@mobile_api_v2.route('/messages/conversation/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_conversation(user_id):
    """
    Delete (hide) a conversation for the current user only.

    This is a soft delete - messages are hidden for the current user
    but remain visible to the other participant.

    Args:
        user_id: The other user's ID in the conversation

    Returns:
        JSON with success message and count of hidden messages
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session_db:
        current_user = session_db.query(User).get(current_user_id)
        other_user = session_db.query(User).get(user_id)

        if not current_user:
            return jsonify({"msg": "User not found"}), 404

        if not other_user:
            return jsonify({"msg": "Conversation partner not found"}), 404

        # Hide all messages in this conversation for the current user
        hidden_count = DirectMessage.hide_conversation_for_user(current_user_id, user_id)
        session_db.commit()

        logger.info(f"User {current_user_id} hid conversation with user {user_id} ({hidden_count} messages)")

        return jsonify({
            'msg': 'Conversation deleted',
            'hidden_count': hidden_count
        }), 200
