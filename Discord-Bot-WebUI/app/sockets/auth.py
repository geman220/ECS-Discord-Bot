# app/sockets/auth.py

"""
Socket.IO Authentication Handlers

JWT authentication middleware and connection handlers for Socket.IO.
Includes presence tracking for real-time online status.
"""

import logging
from datetime import datetime

from flask import g, request, session
from flask_socketio import emit

from app.core import socketio
from app.core.session_manager import managed_session
from app.sockets.presence import PresenceManager

logger = logging.getLogger(__name__)


def authenticate_socket_connection(auth=None):
    """
    Comprehensive JWT authentication middleware for Socket.IO connections.

    Extracts JWT tokens from:
    1. Auth object (auth.token)
    2. Authorization header (Bearer token)
    3. Query parameters (?token=...)
    4. Custom auth header variations

    Args:
        auth: Authentication object from Socket.IO client

    Returns:
        dict: Authentication result with user_id and status
    """
    from app.models import User

    token = None
    token_source = None

    try:
        # 1. Check auth object first (Socket.IO client auth parameter)
        if auth and isinstance(auth, dict):
            # Special handling for Discord bot connections
            if auth.get('type') == 'discord-bot' and auth.get('api_key'):
                logger.info(f"🔌 [AUTH] Discord bot authentication detected")
                # For Discord bot, we can skip JWT validation
                # Return authenticated with a special system user ID
                return {
                    'authenticated': True,
                    'user_id': -1,  # Special system user ID for Discord bot
                    'username': 'Discord Bot',
                    'auth_type': 'discord-bot'
                }

            token = auth.get('token')
            if token:
                token_source = "auth_object"
                logger.info(f"🔌 [AUTH] Token found in auth object")

        # 2. Check Authorization header
        if not token:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header[7:]  # Remove 'Bearer ' prefix
                token_source = "authorization_header"
                logger.info(f"🔌 [AUTH] Token found in Authorization header")

        # 3. Check query parameters
        if not token:
            token = request.args.get('token')
            if token:
                token_source = "query_parameter"
                logger.info(f"🔌 [AUTH] Token found in query parameter")

        # 4. Check alternative auth headers (for mobile compatibility)
        if not token:
            for header_name in ['X-Auth-Token', 'Auth-Token', 'JWT-Token']:
                token = request.headers.get(header_name)
                if token:
                    token_source = f"header_{header_name.lower()}"
                    logger.info(f"🔌 [AUTH] Token found in {header_name} header")
                    break

        # 5. Fall back to Flask-Login session authentication (for web users)
        if not token:
            try:
                from flask_login import current_user
                if current_user and current_user.is_authenticated:
                    logger.info(f"🔌 [AUTH] Authenticated via Flask-Login session: {current_user.username}")
                    return {
                        'authenticated': True,
                        'user_id': current_user.id,
                        'username': current_user.username,
                        'token_source': 'flask_login_session'
                    }
            except Exception as e:
                logger.debug(f"🔌 [AUTH] Flask-Login check failed: {e}")

        if not token:
            logger.warning("🔌 [AUTH] No JWT token found in any source")
            return {
                'authenticated': False,
                'user_id': None,
                'error': 'No authentication token provided'
            }

        # Validate JWT token using existing API validation logic
        logger.info(f"🔌 [AUTH] Attempting JWT validation from {token_source}")
        logger.info(f"🔌 [AUTH] Token length: {len(token)}")

        # Use Flask-JWT-Extended for validation (same as API endpoints)
        from flask_jwt_extended import decode_token
        from flask import current_app

        try:
            # Try Flask-JWT-Extended first (matches API authentication)
            decoded_token = decode_token(token)
            user_id = decoded_token.get('sub') or decoded_token.get('identity')

        except Exception as jwt_ext_error:
            logger.warning(f"🔌 [AUTH] Flask-JWT-Extended failed: {jwt_ext_error}")

            # Fallback to manual JWT decode
            import jwt as pyjwt
            try:
                decoded_token = pyjwt.decode(
                    token,
                    current_app.config.get('JWT_SECRET_KEY'),
                    algorithms=['HS256']
                )
                user_id = decoded_token.get('sub') or decoded_token.get('identity') or decoded_token.get('id')

            except Exception as manual_error:
                logger.error(f"🔌 [AUTH] Manual JWT decode failed: {manual_error}")
                return {
                    'authenticated': False,
                    'user_id': None,
                    'error': f'Invalid JWT token: {str(manual_error)}'
                }

        if not user_id:
            logger.error("🔌 [AUTH] No user ID found in JWT token")
            return {
                'authenticated': False,
                'user_id': None,
                'error': 'JWT token missing user identifier'
            }

        # Verify user exists in database (optional but recommended)
        try:
            with managed_session() as session_db:
                user = session_db.query(User).get(user_id)
                if user:
                    logger.info(f"🔌 [AUTH] Authentication successful for user {user.username} (ID: {user_id})")
                    return {
                        'authenticated': True,
                        'user_id': user_id,
                        'username': user.username,
                        'token_source': token_source
                    }
                else:
                    logger.warning(f"🔌 [AUTH] User ID {user_id} not found in database")
                    # Still allow connection for testing, but mark as unverified
                    return {
                        'authenticated': True,
                        'user_id': user_id,
                        'username': f'User_{user_id}',
                        'token_source': token_source,
                        'unverified': True
                    }
        except Exception as db_error:
            logger.error(f"🔌 [AUTH] Database verification failed: {db_error}")
            # Still allow connection if DB check fails
            return {
                'authenticated': True,
                'user_id': user_id,
                'username': f'User_{user_id}',
                'token_source': token_source,
                'db_error': True
            }

    except Exception as e:
        logger.error(f"🔌 [AUTH] Authentication middleware error: {str(e)}", exc_info=True)
        return {
            'authenticated': False,
            'user_id': None,
            'error': f'Authentication system error: {str(e)}'
        }


@socketio.on('connect', namespace='/')
def handle_connect(auth):
    """Handle client connection to the default namespace with enhanced authentication."""
    logger.info("🔌 [CONNECT] Client connecting to Socket.IO default namespace")

    try:
        # Use enhanced authentication middleware
        auth_result = authenticate_socket_connection(auth)

        if auth_result['authenticated']:
            user_id = auth_result['user_id']
            username = auth_result.get('username', f'User_{user_id}')

            # Store user info in session for this connection
            session['user_id'] = user_id
            session['authenticated'] = True
            session['username'] = username

            # Store in Flask g for request context
            g.socket_user_id = user_id

            # Track user presence in Redis
            PresenceManager.user_connected(user_id, request.sid)

            # Join personal room for direct messaging
            from app.sockets.messaging import join_user_room
            join_user_room(user_id)

            # Emit authentication success event
            emit('authentication_success', {
                'user_id': user_id,
                'username': username,
                'message': 'Authentication successful',
                'token_source': auth_result.get('token_source'),
                'timestamp': datetime.utcnow().isoformat(),
                'namespace': '/'
            })

            logger.info(f"🔌 [CONNECT] Successfully authenticated {username} (ID: {user_id})")

        else:
            # Authentication failed - still allow connection but inform client
            logger.warning(f"🔌 [CONNECT] Authentication failed: {auth_result.get('error')}")

            emit('authentication_failed', {
                'error': auth_result.get('error'),
                'message': 'Connection established without authentication',
                'timestamp': datetime.utcnow().isoformat(),
                'namespace': '/'
            })

        # Always emit connected event for backward compatibility
        emit('connected', {
            'message': 'Connected to Socket.IO',
            'authenticated': auth_result['authenticated'],
            'timestamp': datetime.utcnow().isoformat(),
            'namespace': '/'
        })

        return True  # Allow connection regardless of auth status

    except Exception as e:
        logger.error(f"🔌 [CONNECT] Connection handler error: {str(e)}", exc_info=True)

        # Emit error but still allow connection
        emit('connection_error', {
            'error': str(e),
            'message': 'Connection established with errors',
            'timestamp': datetime.utcnow().isoformat()
        })

        return True


@socketio.on('disconnect', namespace='/')
def handle_disconnect(reason=None):
    """Handle client disconnection - clean up any tracked resources."""
    sid = request.sid
    reason_str = f" (reason: {reason})" if reason else ""
    logger.info(f"🔌 Client disconnected from Socket.IO (sid: {sid}){reason_str}")

    # Update user presence (mark as disconnected)
    try:
        PresenceManager.user_disconnected(sid)
    except Exception as e:
        logger.error(f"Error updating presence on disconnect: {e}")

    # Clean up any match room tracking for this socket
    try:
        from app.sockets.rsvp import cleanup_room_users_for_sid
        cleaned_entries = cleanup_room_users_for_sid(sid)
        if cleaned_entries:
            logger.info(f"🧹 Cleaned up {len(cleaned_entries)} room entries for disconnected socket {sid}")
    except Exception as e:
        logger.error(f"Error cleaning up room users on disconnect: {e}")
