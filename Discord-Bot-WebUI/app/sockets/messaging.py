# app/sockets/messaging.py

"""
Socket.IO Messaging Handlers

Real-time message delivery and typing indicators for direct messaging.
Uses user-specific rooms for targeted message delivery.
"""

import logging
from datetime import datetime

from flask import session, request
from flask_socketio import emit, join_room, leave_room

from app.core import socketio, db
from app.sockets.presence import PresenceManager

logger = logging.getLogger(__name__)


def get_user_room(user_id):
    """Get the room name for a user's personal messages."""
    return f'user_{user_id}'


def join_user_room(user_id):
    """Join a user to their personal messaging room."""
    room = get_user_room(user_id)
    join_room(room)
    logger.debug(f"User {user_id} joined personal room {room}")


def leave_user_room(user_id):
    """Leave a user's personal messaging room."""
    room = get_user_room(user_id)
    leave_room(room)
    logger.debug(f"User {user_id} left personal room {room}")


def emit_to_user(user_id, event, data):
    """
    Emit an event to a specific user if they're online.

    Args:
        user_id: Target user ID
        event: Event name
        data: Event data

    Returns:
        bool: True if user was online and message was sent
    """
    if PresenceManager.is_user_online(user_id):
        room = get_user_room(user_id)
        socketio.emit(event, data, room=room, namespace='/')
        return True
    return False


# ============================================================================
# SOCKET EVENT HANDLERS
# ============================================================================

@socketio.on('join_messaging', namespace='/')
def handle_join_messaging():
    """
    Join the messaging system.
    Called when user opens chat widget or messages page.
    """
    user_id = session.get('user_id')
    if not user_id:
        emit('messaging_error', {'error': 'Not authenticated'})
        return

    # Join personal room for receiving messages
    join_user_room(user_id)

    emit('messaging_joined', {
        'user_id': user_id,
        'room': get_user_room(user_id),
        'timestamp': datetime.utcnow().isoformat()
    })

    logger.info(f"User {user_id} joined messaging system")


@socketio.on('leave_messaging', namespace='/')
def handle_leave_messaging():
    """Leave the messaging system."""
    user_id = session.get('user_id')
    if user_id:
        leave_user_room(user_id)
        logger.info(f"User {user_id} left messaging system")


@socketio.on('send_dm', namespace='/')
def handle_send_dm(data):
    """
    Handle sending a direct message via WebSocket.

    Data:
        recipient_id: Target user ID
        content: Message content
    """
    from app.models import DirectMessage, MessagingPermission, MessagingSettings, User

    user_id = session.get('user_id')
    if not user_id:
        emit('dm_error', {'error': 'Not authenticated'})
        return

    recipient_id = data.get('recipient_id')
    content = data.get('content', '').strip()

    if not recipient_id or not content:
        emit('dm_error', {'error': 'Recipient and content required'})
        return

    try:
        # Get users
        sender = User.query.get(user_id)
        recipient = User.query.get(recipient_id)

        if not sender or not recipient:
            emit('dm_error', {'error': 'User not found'})
            return

        # Check settings
        settings = MessagingSettings.get_settings()
        if not settings.enabled:
            emit('dm_error', {'error': 'Messaging is currently disabled'})
            return

        if len(content) > settings.max_message_length:
            emit('dm_error', {'error': f'Message too long (max {settings.max_message_length} chars)'})
            return

        # Check permission
        sender_role_ids = [role.id for role in sender.roles]
        recipient_role_ids = [role.id for role in recipient.roles]

        if not MessagingPermission.can_message(sender_role_ids, recipient_role_ids):
            emit('dm_error', {'error': 'You cannot message this user'})
            return

        # Create message
        message = DirectMessage(
            sender_id=user_id,
            recipient_id=recipient_id,
            content=content
        )
        db.session.add(message)
        db.session.commit()

        message_data = message.to_dict()

        # Confirm to sender
        emit('dm_sent', {
            'message': message_data,
            'timestamp': datetime.utcnow().isoformat()
        })

        # Send to recipient if online
        recipient_online = emit_to_user(recipient_id, 'new_message', message_data)

        if recipient_online:
            logger.info(f"Real-time message delivered to user {recipient_id}")
        else:
            # User is offline - send notifications via all their enabled channels
            # (email, SMS, Discord DM) based on their preferences
            try:
                from app.services.notification_orchestrator import orchestrator

                sender_name = sender.player.name if sender.player else sender.username
                message_preview = content[:50] + '...' if len(content) > 50 else content

                # Send via orchestrator - this handles in-app, email, SMS, Discord
                orchestrator.send_direct_message(
                    recipient_id=recipient_id,
                    sender_id=user_id,
                    sender_name=sender_name,
                    message_preview=message_preview,
                    message_id=message.id
                )
                logger.info(f"Offline notifications triggered for user {recipient_id}")

            except Exception as e:
                logger.warning(f"Failed to send offline notifications: {e}")
                # Fallback to basic in-app notification
                try:
                    from app.routes.navbar_notifications import create_notification
                    sender_name = sender.player.name if sender.player else sender.username
                    create_notification(
                        user_id=recipient_id,
                        content=f"New message from {sender_name}",
                        notification_type='info',
                        icon='ti ti-message'
                    )
                    db.session.commit()
                except Exception as fallback_e:
                    logger.error(f"Fallback notification also failed: {fallback_e}")

        logger.info(f"Message sent from {user_id} to {recipient_id}")

    except Exception as e:
        logger.error(f"Error sending DM: {e}")
        db.session.rollback()
        emit('dm_error', {'error': 'Failed to send message'})


@socketio.on('typing_start', namespace='/')
def handle_typing_start(data):
    """
    Handle typing indicator start.

    Data:
        recipient_id: User being typed to
    """
    from app.models import MessagingSettings

    user_id = session.get('user_id')
    if not user_id:
        return

    recipient_id = data.get('recipient_id')
    if not recipient_id:
        return

    # Check if typing indicators are enabled
    settings = MessagingSettings.get_settings()
    if not settings.typing_indicators:
        return

    emit_to_user(recipient_id, 'user_typing', {
        'user_id': user_id,
        'typing': True,
        'timestamp': datetime.utcnow().isoformat()
    })


@socketio.on('typing_stop', namespace='/')
def handle_typing_stop(data):
    """Handle typing indicator stop."""
    from app.models import MessagingSettings

    user_id = session.get('user_id')
    if not user_id:
        return

    recipient_id = data.get('recipient_id')
    if not recipient_id:
        return

    settings = MessagingSettings.get_settings()
    if not settings.typing_indicators:
        return

    emit_to_user(recipient_id, 'user_typing', {
        'user_id': user_id,
        'typing': False,
        'timestamp': datetime.utcnow().isoformat()
    })


@socketio.on('mark_dm_read', namespace='/')
def handle_mark_dm_read(data):
    """
    Mark message(s) as read via WebSocket.

    Data:
        message_id: Single message ID (optional)
        sender_id: Mark all from sender as read (optional)
    """
    from app.models import DirectMessage

    user_id = session.get('user_id')
    if not user_id:
        return

    message_id = data.get('message_id')
    sender_id = data.get('sender_id')

    try:
        if message_id:
            # Mark single message
            message = DirectMessage.query.filter_by(
                id=message_id,
                recipient_id=user_id
            ).first()
            if message:
                message.mark_as_read()
        elif sender_id:
            # Mark all from sender
            DirectMessage.query.filter_by(
                sender_id=sender_id,
                recipient_id=user_id,
                is_read=False
            ).update({
                'is_read': True,
                'read_at': datetime.utcnow()
            })

        db.session.commit()

        # Notify sender that message was read (if read receipts enabled)
        from app.models import MessagingSettings
        settings = MessagingSettings.get_settings()

        if settings.read_receipts and sender_id:
            emit_to_user(sender_id, 'messages_read', {
                'reader_id': user_id,
                'timestamp': datetime.utcnow().isoformat()
            })

        # Return updated unread count
        unread_count = DirectMessage.get_unread_count(user_id)
        emit('dm_unread_update', {'count': unread_count})

    except Exception as e:
        logger.error(f"Error marking DM read: {e}")
        db.session.rollback()


# ============================================================================
# HELPER FUNCTIONS FOR OTHER MODULES
# ============================================================================

def notify_new_message(message):
    """
    Notify recipient of new message.
    Called from API route when message is sent via HTTP.

    Args:
        message: DirectMessage instance
    """
    if emit_to_user(message.recipient_id, 'new_message', message.to_dict()):
        logger.debug(f"WebSocket notification sent for message {message.id}")
    return True
