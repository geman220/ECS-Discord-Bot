# app/utils/session_utils.py

"""
Session utility functions for creating and managing user sessions.
"""

import uuid
import logging
from datetime import datetime

from flask import request

logger = logging.getLogger(__name__)


def create_user_session(session_db, user_id, device_name=None, device_type=None):
    """
    Create a new user session record.

    Args:
        session_db: Database session
        user_id: The user's ID
        device_name: Optional device name (from client or parsed from UA)
        device_type: Optional device type ('ios', 'android', 'web')

    Returns:
        The session_id (UUID string)
    """
    from app.models.sessions import UserSession

    session_id = str(uuid.uuid4())

    if not device_name:
        ua = request.headers.get('User-Agent', '')
        device_name = _parse_device_name(ua)

    if not device_type:
        ua = request.headers.get('User-Agent', '')
        device_type = _parse_device_type(ua)

    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()

    user_session = UserSession(
        id=session_id,
        user_id=user_id,
        device_name=device_name,
        device_type=device_type,
        ip_address=ip_address,
        is_active=True,
    )
    session_db.add(user_session)

    logger.info(f"Created session {session_id[:8]}... for user {user_id}")
    return session_id


def revoke_user_session(session_id):
    """
    Revoke a user session by adding it to the Redis blocklist.
    Any JWT carrying this session ID will be rejected by the blocklist loader.

    Args:
        session_id: The session ID to revoke

    Returns:
        True if successfully revoked
    """
    from flask import current_app

    try:
        redis_client = current_app.redis
        if redis_client:
            # Session revocation lasts 30 days (matching refresh token lifetime)
            redis_client.setex(
                f"session_revoked:{session_id}",
                30 * 24 * 60 * 60,
                'revoked',
            )
            return True
    except Exception as e:
        logger.error(f"Error revoking session {session_id[:8]}...: {e}")
    return False


def _parse_device_name(user_agent):
    """Parse a human-readable device name from User-Agent string."""
    if not user_agent:
        return 'Unknown Device'

    ua = user_agent.lower()

    if 'iphone' in ua:
        return 'iPhone'
    if 'ipad' in ua:
        return 'iPad'
    if 'android' in ua:
        return 'Android Device'
    if 'macintosh' in ua or 'mac os' in ua:
        return 'Mac'
    if 'windows' in ua:
        return 'Windows PC'
    if 'linux' in ua:
        return 'Linux PC'

    return 'Unknown Device'


def _parse_device_type(user_agent):
    """Parse device type from User-Agent string."""
    if not user_agent:
        return 'web'

    ua = user_agent.lower()

    # Flutter/Dart apps include these identifiers
    if 'dart' in ua or 'flutter' in ua:
        if 'ios' in ua or 'iphone' in ua or 'ipad' in ua:
            return 'ios'
        if 'android' in ua:
            return 'android'

    if 'iphone' in ua or 'ipad' in ua:
        return 'ios'
    if 'android' in ua:
        return 'android'

    return 'web'
