# app/routes/messages.py

"""
Direct Messaging API & Pages
============================

REST API endpoints and pages for the lightweight messaging system.
Handles conversations, sending messages, and permission checks.

API Endpoints (prefix: /api/messages):
    GET    /api/messages                       - List conversations
    GET    /api/messages/unread-count          - Get unread message count
    GET    /api/messages/<user_id>             - Get conversation with user
    POST   /api/messages/<user_id>             - Send message to user
    POST   /api/messages/<msg_id>/read         - Mark message as read
    POST   /api/messages/mark-all-read         - Mark all messages as read
    DELETE /api/messages/conversation/<user_id> - Delete conversation for current user
    GET    /api/messages/can-message/<user_id> - Check if can message user

Pages:
    GET  /messages                        - Messages inbox page
"""

import logging
from datetime import datetime
from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required, current_user
from app.core import db
from app.models import DirectMessage, MessagingPermission, MessagingSettings, User, Role
from app.sockets.presence import PresenceManager
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

messages_bp = Blueprint('messages', __name__, url_prefix='/api/messages')

# Additional blueprint for pages (not API)
messages_pages_bp = Blueprint('messages_pages', __name__, url_prefix='/messages')


def _time_ago(dt):
    """Convert datetime to human-readable time ago string."""
    if not dt:
        return ''
    delta = datetime.utcnow() - dt

    if delta.days > 30:
        return dt.strftime('%b %d')
    elif delta.days > 0:
        return f'{delta.days}d ago'
    elif delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f'{hours}h ago'
    elif delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f'{minutes}m ago'
    else:
        return 'Just now'


def _get_role_ids(user):
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
            role_obj = Role.query.filter_by(name=role).first()
            if role_obj:
                role_ids.append(role_obj.id)
    return role_ids


def _can_user_message(sender_user, recipient_user):
    """
    Check if sender can message recipient based on role permissions.

    Returns (bool, str): (can_message, reason_if_blocked)
    """
    # Check if messaging is enabled
    settings = MessagingSettings.get_settings()
    if not settings.enabled:
        return False, 'Messaging is currently disabled'

    # Get role IDs for both users (handles Role objects and string names)
    sender_role_ids = _get_role_ids(sender_user)
    recipient_role_ids = _get_role_ids(recipient_user)

    if not sender_role_ids or not recipient_role_ids:
        return False, 'User roles not configured'

    # Check permission
    if MessagingPermission.can_message(sender_role_ids, recipient_role_ids):
        return True, None

    return False, 'You do not have permission to message this user'


def _user_to_dict(user, include_online=True):
    """Serialize user for API responses with role badges."""
    player = user.player if hasattr(user, 'player') else None

    # Check roles for badges
    has_role = hasattr(user, 'has_role')
    is_global_admin = user.has_role('Global Admin') if has_role else False
    is_admin = user.has_role('Pub League Admin') if has_role else False
    is_coach = (
        user.has_role('Pub League Coach') or
        user.has_role('ECS FC Coach') or
        (player and getattr(player, 'is_coach', False))
    ) if has_role else (player and getattr(player, 'is_coach', False) if player else False)
    is_ref = user.has_role('Pub League Ref') if has_role else False

    return {
        'id': user.id,
        'username': user.username,
        'name': player.name if player else user.username,
        'avatar_url': player.profile_picture_url if player else None,
        'profile_url': f'/players/profile/{player.id}' if player else None,
        'is_online': PresenceManager.is_user_online(user.id) if include_online else None,
        'is_coach': is_coach,
        'is_admin': is_admin,
        'is_global_admin': is_global_admin,
        'is_ref': is_ref,
    }


@messages_bp.route('', methods=['GET'])
@login_required
def get_conversations():
    """
    Get list of conversations for current user.

    Returns conversations grouped by user with the most recent message.
    """
    try:
        limit = min(int(request.args.get('limit', 20)), 50)

        # Get conversations
        messages = DirectMessage.get_conversations_for_user(current_user.id, limit=limit)

        conversations = []
        for msg in messages:
            # Determine the other user in the conversation
            other_user_id = msg.recipient_id if msg.sender_id == current_user.id else msg.sender_id
            other_user = User.query.get(other_user_id)

            if not other_user:
                continue

            # Count unread messages from this user
            unread_count = DirectMessage.query.filter_by(
                sender_id=other_user_id,
                recipient_id=current_user.id,
                is_read=False
            ).count()

            conversations.append({
                'user': _user_to_dict(other_user),
                'last_message': {
                    'content': msg.content[:100] + '...' if len(msg.content) > 100 else msg.content,
                    'sent_by_me': msg.sender_id == current_user.id,
                    'time_ago': _time_ago(msg.created_at),
                    'created_at': (msg.created_at.isoformat() + 'Z') if msg.created_at else None
                },
                'unread_count': unread_count
            })

        return jsonify({
            'success': True,
            'conversations': conversations
        })

    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to load conversations'
        }), 500


@messages_bp.route('/unread-count', methods=['GET'])
@login_required
def get_unread_count():
    """Get total unread message count for badge display."""
    try:
        count = DirectMessage.get_unread_count(current_user.id)
        return jsonify({
            'success': True,
            'count': count
        })
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return jsonify({
            'success': False,
            'count': 0
        }), 500


@messages_bp.route('/<int:user_id>', methods=['GET'])
@login_required
def get_conversation(user_id):
    """
    Get conversation history with a specific user.

    Query params:
        limit: Number of messages (default 50, max 100)
        offset: Pagination offset (default 0)
    """
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = int(request.args.get('offset', 0))

        # Verify the other user exists
        other_user = User.query.get(user_id)
        if not other_user:
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404

        # Get messages
        messages = DirectMessage.get_conversation(
            current_user.id,
            user_id,
            limit=limit,
            offset=offset
        )

        # Mark messages as read
        unread_messages = [m for m in messages if m.recipient_id == current_user.id and not m.is_read]
        for msg in unread_messages:
            msg.mark_as_read()
        if unread_messages:
            db.session.commit()

        # Get settings for features
        settings = MessagingSettings.get_settings()

        return jsonify({
            'success': True,
            'user': _user_to_dict(other_user),
            'messages': [msg.to_dict() for msg in reversed(messages)],  # Oldest first for display
            'has_more': len(messages) == limit,
            'settings': {
                'typing_indicators': settings.typing_indicators,
                'read_receipts': settings.read_receipts
            }
        })

    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to load conversation'
        }), 500


@messages_bp.route('/<int:user_id>', methods=['POST'])
@login_required
def send_message(user_id):
    """
    Send a message to a user.

    Request body:
        content: Message text (required)
    """
    try:
        data = request.get_json() or {}
        content = data.get('content', '').strip()

        if not content:
            return jsonify({
                'success': False,
                'error': 'Message content is required'
            }), 400

        # Get settings
        settings = MessagingSettings.get_settings()

        # Check message length
        if len(content) > settings.max_message_length:
            return jsonify({
                'success': False,
                'error': f'Message too long. Maximum {settings.max_message_length} characters.'
            }), 400

        # Verify the recipient exists
        recipient = User.query.get(user_id)
        if not recipient:
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404

        # Check messaging permission
        can_message, reason = _can_user_message(current_user, recipient)
        if not can_message:
            return jsonify({
                'success': False,
                'error': reason
            }), 403

        # Create message
        message = DirectMessage(
            sender_id=current_user.id,
            recipient_id=user_id,
            content=content
        )
        db.session.add(message)
        db.session.commit()

        # Emit WebSocket event if recipient is online
        recipient_online = PresenceManager.is_user_online(user_id)
        try:
            from flask import current_app
            socketio = current_app.extensions.get('socketio')
            if socketio and recipient_online:
                msg_data = message.to_dict()
                # Emit to default namespace (for web browser clients)
                socketio.emit('new_message', msg_data, room=f'user_{user_id}')
                # Emit to /live namespace (for Flutter mobile clients)
                socketio.emit('new_message', msg_data, room=f'user_{user_id}', namespace='/live')
        except Exception as e:
            logger.warning(f"Failed to emit WebSocket message: {e}")

        # Send push notification for offline users (in-app + FCM push)
        if not recipient_online:
            try:
                from app.services.notification_orchestrator import orchestrator
                sender_name = current_user.player.name if current_user.player else current_user.username
                orchestrator.send_direct_message(
                    recipient_id=user_id,
                    sender_id=current_user.id,
                    sender_name=sender_name,
                    message_preview=content,
                    message_id=message.id
                )
            except Exception as e:
                logger.warning(f"Failed to send message notification: {e}")

        return jsonify({
            'success': True,
            'message': message.to_dict()
        })

    except Exception as e:
        logger.error(f"Error sending message: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to send message'
        }), 500


@messages_bp.route('/<int:message_id>/read', methods=['POST'])
@login_required
def mark_message_read(message_id):
    """Mark a single message as read."""
    try:
        message = DirectMessage.query.filter_by(
            id=message_id,
            recipient_id=current_user.id
        ).first()

        if not message:
            return jsonify({
                'success': False,
                'error': 'Message not found'
            }), 404

        message.mark_as_read()
        db.session.commit()

        return jsonify({
            'success': True,
            'unread_count': DirectMessage.get_unread_count(current_user.id)
        })

    except Exception as e:
        logger.error(f"Error marking message read: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to mark message as read'
        }), 500


@messages_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_messages_read():
    """Mark all messages as read for current user."""
    try:
        DirectMessage.query.filter_by(
            recipient_id=current_user.id,
            is_read=False
        ).update({
            'is_read': True,
            'read_at': datetime.utcnow()
        })
        db.session.commit()

        return jsonify({
            'success': True,
            'unread_count': 0
        })

    except Exception as e:
        logger.error(f"Error marking all messages read: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to mark messages as read'
        }), 500


@messages_bp.route('/message/<int:message_id>', methods=['DELETE'])
@login_required
def delete_message(message_id):
    """
    Delete a message for everyone (unsend).
    Only the sender can delete their own messages.
    The message content is cleared but a placeholder remains.
    """
    try:
        # Only allow deleting own messages
        message = DirectMessage.query.filter_by(
            id=message_id,
            sender_id=current_user.id
        ).first()

        if not message:
            return jsonify({
                'success': False,
                'error': 'Message not found or not authorized'
            }), 404

        if message.is_deleted:
            return jsonify({
                'success': False,
                'error': 'Message already deleted'
            }), 400

        # Store recipient ID for WebSocket notification
        recipient_id = message.recipient_id

        # Soft delete for everyone
        message.delete_for_everyone()
        db.session.commit()

        # Emit WebSocket event to notify recipient
        try:
            from flask import current_app
            socketio = current_app.extensions.get('socketio')
            if socketio:
                deleted_data = {
                    'message_id': message_id,
                    'deleted_for': 'everyone'
                }
                # Emit to default namespace (web browser clients)
                socketio.emit('message_deleted', deleted_data, room=f'user_{recipient_id}')
                # Emit to /live namespace (Flutter mobile clients)
                socketio.emit('message_deleted', deleted_data, room=f'user_{recipient_id}', namespace='/live')
        except Exception as e:
            logger.warning(f"Failed to emit message_deleted event: {e}")

        return jsonify({
            'success': True,
            'message_id': message_id,
            'deleted_for': 'everyone'
        })

    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to delete message'
        }), 500


@messages_bp.route('/message/<int:message_id>/hide', methods=['POST'])
@login_required
def hide_message(message_id):
    """
    Hide a message for the current user only (delete for me).
    Both sender and recipient can hide messages from their view.
    """
    try:
        # Find message where current user is sender or recipient
        message = DirectMessage.query.filter(
            DirectMessage.id == message_id,
            db.or_(
                DirectMessage.sender_id == current_user.id,
                DirectMessage.recipient_id == current_user.id
            )
        ).first()

        if not message:
            return jsonify({
                'success': False,
                'error': 'Message not found'
            }), 404

        # Hide for this user
        message.hide_for_user(current_user.id)
        db.session.commit()

        return jsonify({
            'success': True,
            'message_id': message_id,
            'deleted_for': 'me'
        })

    except Exception as e:
        logger.error(f"Error hiding message: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to hide message'
        }), 500


@messages_bp.route('/conversation/<int:user_id>', methods=['DELETE'])
@login_required
def delete_conversation(user_id):
    """
    Delete (hide) a conversation for the current user only.

    This is a soft delete - messages are hidden for the current user
    but remain visible to the other participant.

    Args:
        user_id: The other user's ID in the conversation

    Returns:
        JSON with success status and count of hidden messages
    """
    try:
        other_user = User.query.get(user_id)
        if not other_user:
            return jsonify({
                'success': False,
                'error': 'Conversation partner not found'
            }), 404

        # Hide all messages in this conversation for the current user
        hidden_count = DirectMessage.hide_conversation_for_user(current_user.id, user_id)
        db.session.commit()

        logger.info(f"User {current_user.id} hid conversation with user {user_id} ({hidden_count} messages)")

        return jsonify({
            'success': True,
            'hidden_count': hidden_count
        })

    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Failed to delete conversation'
        }), 500


@messages_bp.route('/can-message/<int:user_id>', methods=['GET'])
@login_required
def check_can_message(user_id):
    """
    Check if current user can message a specific user.
    Useful for showing/hiding message buttons in UI.
    """
    try:
        recipient = User.query.get(user_id)
        if not recipient:
            return jsonify({
                'success': False,
                'can_message': False,
                'reason': 'User not found'
            }), 404

        can_message, reason = _can_user_message(current_user, recipient)

        return jsonify({
            'success': True,
            'can_message': can_message,
            'reason': reason
        })

    except Exception as e:
        logger.error(f"Error checking message permission: {e}")
        return jsonify({
            'success': False,
            'can_message': False,
            'reason': 'Failed to check permission'
        }), 500


@messages_bp.route('/settings', methods=['GET'])
@login_required
def get_messaging_settings():
    """Get current messaging settings."""
    try:
        settings = MessagingSettings.get_settings()
        return jsonify({
            'success': True,
            'settings': settings.to_dict()
        })
    except Exception as e:
        logger.error(f"Error getting messaging settings: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get settings'
        }), 500


# ============================================================================
# USER SEARCH FOR MESSAGING
# ============================================================================

@messages_bp.route('/users/search', methods=['GET'])
@login_required
def search_users():
    """
    Search for users to start a conversation with.

    Query params:
        q: Search query (name/username)
        limit: Max results (default 10)
    """
    try:
        query = request.args.get('q', '').strip()
        limit = min(int(request.args.get('limit', 10)), 25)

        if len(query) < 2:
            return jsonify({
                'success': True,
                'users': []
            })

        # Search users by name or username
        from app.models import Player

        users = User.query.outerjoin(Player).filter(
            User.id != current_user.id,
            db.or_(
                Player.name.ilike(f'%{query}%'),
                User.username.ilike(f'%{query}%')
            )
        ).limit(limit).all()

        # Filter to users we can message
        results = []
        for user in users:
            can_msg, _ = _can_user_message(current_user, user)
            if can_msg:
                results.append(_user_to_dict(user))

        return jsonify({
            'success': True,
            'users': results
        })

    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return jsonify({
            'success': False,
            'users': [],
            'error': 'Search failed'
        }), 500


# ============================================================================
# MESSAGES INBOX PAGE
# ============================================================================

@messages_pages_bp.route('', methods=['GET'])
@messages_pages_bp.route('/', methods=['GET'])
@login_required
def messages_inbox():
    """
    Full messages inbox page.

    Query params:
        user: Optional user_id to open conversation with
    """
    # Get initial conversation to open (if specified)
    initial_user_id = request.args.get('user', type=int)
    initial_user = None

    if initial_user_id:
        initial_user = User.query.get(initial_user_id)
        if initial_user:
            # Check if we can message this user
            can_msg, _ = _can_user_message(current_user, initial_user)
            if not can_msg:
                initial_user = None

    # Get messaging settings
    settings = MessagingSettings.get_settings()

    return render_template(
        'messages/inbox_flowbite.html',
        title='Messages',
        initial_user=_user_to_dict(initial_user) if initial_user else None,
        settings={
            'enabled': settings.enabled,
            'max_message_length': settings.max_message_length,
            'typing_indicators': settings.typing_indicators,
            'read_receipts': settings.read_receipts
        }
    )
