# app/sockets/presence.py

"""
User Presence Manager
=====================

Real-time user presence tracking using Redis.
Tracks which users are currently online/connected via WebSocket.
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class PresenceManager:
    """
    Manages user online presence using Redis.

    Features:
    - Tracks online users with automatic TTL expiration
    - Supports multiple connections per user (tabs/devices)
    - Provides presence check for individual users
    - Works across multiple server workers
    - O(1) online user count and listing via Redis SET

    Redis Keys:
    - presence:user:{user_id} -> JSON with connection count and last_seen
    - presence:sid:{sid} -> user_id (for reverse lookup on disconnect)
    - presence:online_set -> SET of currently online user IDs (O(1) lookups)
    """

    # Presence TTL in seconds (5 minutes - refreshed on activity)
    PRESENCE_TTL = 300

    # Redis key prefixes
    USER_KEY_PREFIX = "presence:user:"
    SID_KEY_PREFIX = "presence:sid:"
    ONLINE_SET_KEY = "presence:online_set"

    @classmethod
    def _get_redis(cls):
        """Get Redis connection lazily."""
        from app.utils.redis_manager import get_redis_connection
        return get_redis_connection()

    @classmethod
    def _user_key(cls, user_id):
        """Create Redis key for a user's presence."""
        return f"{cls.USER_KEY_PREFIX}{user_id}"

    @classmethod
    def _sid_key(cls, sid):
        """Create Redis key for socket ID to user mapping."""
        return f"{cls.SID_KEY_PREFIX}{sid}"

    @classmethod
    def user_connected(cls, user_id, sid):
        """
        Mark a user as connected.

        Args:
            user_id: The user's ID
            sid: The Socket.IO session ID
        """
        if not user_id or user_id < 0:  # Skip system users (e.g., Discord bot)
            return

        try:
            redis = cls._get_redis()
            user_key = cls._user_key(user_id)
            sid_key = cls._sid_key(sid)

            # Get current presence data
            current = redis.get(user_key)
            if current:
                data = json.loads(current)
                data['connection_count'] = data.get('connection_count', 0) + 1
                data['last_seen'] = datetime.utcnow().isoformat()
                data['sids'] = list(set(data.get('sids', []) + [sid]))
            else:
                data = {
                    'user_id': user_id,
                    'connection_count': 1,
                    'first_seen': datetime.utcnow().isoformat(),
                    'last_seen': datetime.utcnow().isoformat(),
                    'sids': [sid]
                }

            # Save presence with TTL
            redis.setex(user_key, cls.PRESENCE_TTL, json.dumps(data))

            # Save reverse lookup (sid -> user_id)
            redis.setex(sid_key, cls.PRESENCE_TTL, str(user_id))

            # Add to online users SET (O(1) operation)
            redis.sadd(cls.ONLINE_SET_KEY, user_id)

            logger.debug(f"👤 User {user_id} connected (sid: {sid}, connections: {data['connection_count']})")

        except Exception as e:
            logger.error(f"Error tracking user connection: {e}")

    @classmethod
    def user_disconnected(cls, sid):
        """
        Mark a user connection as disconnected.

        Args:
            sid: The Socket.IO session ID
        """
        try:
            redis = cls._get_redis()
            sid_key = cls._sid_key(sid)

            # Get user_id from sid
            user_id_str = redis.get(sid_key)
            if not user_id_str:
                return

            user_id = int(user_id_str)
            user_key = cls._user_key(user_id)

            # Get current presence data
            current = redis.get(user_key)
            if current:
                data = json.loads(current)
                data['connection_count'] = max(0, data.get('connection_count', 1) - 1)
                data['last_seen'] = datetime.utcnow().isoformat()

                # Remove this sid from the list
                if 'sids' in data:
                    data['sids'] = [s for s in data['sids'] if s != sid]

                if data['connection_count'] > 0:
                    # Still has other connections - update presence
                    redis.setex(user_key, cls.PRESENCE_TTL, json.dumps(data))
                else:
                    # No more connections - remove presence
                    redis.delete(user_key)
                    # Remove from online users SET (O(1) operation)
                    redis.srem(cls.ONLINE_SET_KEY, user_id)
                    logger.debug(f"👤 User {user_id} fully disconnected")

            # Clean up sid mapping
            redis.delete(sid_key)

        except Exception as e:
            logger.error(f"Error tracking user disconnection: {e}")

    @classmethod
    def is_user_online(cls, user_id):
        """
        Check if a user is currently online.

        Args:
            user_id: The user's ID

        Returns:
            bool: True if user is online
        """
        if not user_id or user_id < 0:
            return False

        try:
            redis = cls._get_redis()
            user_key = cls._user_key(user_id)
            return redis.exists(user_key) > 0
        except Exception as e:
            logger.error(f"Error checking user presence: {e}")
            return False

    @classmethod
    def get_user_presence(cls, user_id):
        """
        Get detailed presence info for a user.

        Args:
            user_id: The user's ID

        Returns:
            dict: Presence data or None if offline
        """
        if not user_id or user_id < 0:
            return None

        try:
            redis = cls._get_redis()
            user_key = cls._user_key(user_id)
            data = redis.get(user_key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error getting user presence: {e}")
            return None

    @classmethod
    def refresh_presence(cls, user_id):
        """
        Refresh presence TTL for a user (call on activity).

        Args:
            user_id: The user's ID
        """
        if not user_id or user_id < 0:
            return

        try:
            redis = cls._get_redis()
            user_key = cls._user_key(user_id)

            if redis.exists(user_key):
                redis.expire(user_key, cls.PRESENCE_TTL)

                # Update last_seen
                current = redis.get(user_key)
                if current:
                    data = json.loads(current)
                    data['last_seen'] = datetime.utcnow().isoformat()
                    redis.setex(user_key, cls.PRESENCE_TTL, json.dumps(data))

        except Exception as e:
            logger.error(f"Error refreshing user presence: {e}")

    @classmethod
    def get_online_count(cls):
        """
        Get count of currently online users.

        Uses Redis SCARD for O(1) performance.

        Returns:
            int: Number of online users
        """
        try:
            redis = cls._get_redis()
            return redis.scard(cls.ONLINE_SET_KEY) or 0
        except Exception as e:
            logger.error(f"Error counting online users: {e}")
            return 0

    @classmethod
    def get_online_users(cls, limit=100):
        """
        Get list of currently online user IDs.

        Uses Redis SMEMBERS for O(n) on SET size only (not all keys).

        Args:
            limit: Maximum users to return

        Returns:
            list: List of online user IDs
        """
        try:
            redis = cls._get_redis()
            members = redis.smembers(cls.ONLINE_SET_KEY)
            if not members:
                return []

            user_ids = []
            for member in members:
                if len(user_ids) >= limit:
                    break
                # Handle bytes or string
                member_str = member.decode('utf-8') if isinstance(member, bytes) else str(member)
                try:
                    user_ids.append(int(member_str))
                except ValueError:
                    pass

            return user_ids
        except Exception as e:
            logger.error(f"Error getting online users: {e}")
            return []

    @classmethod
    def cleanup_stale_set_members(cls):
        """
        Remove stale entries from the online SET.

        This handles edge cases where the SET gets out of sync with actual
        presence keys (e.g., after server crash). Safe to call periodically.

        Returns:
            int: Number of stale entries removed
        """
        try:
            redis = cls._get_redis()
            members = redis.smembers(cls.ONLINE_SET_KEY)
            if not members:
                return 0

            removed = 0
            for member in members:
                member_str = member.decode('utf-8') if isinstance(member, bytes) else str(member)
                try:
                    user_id = int(member_str)
                    user_key = cls._user_key(user_id)
                    # If the user's presence key doesn't exist, remove from SET
                    if not redis.exists(user_key):
                        redis.srem(cls.ONLINE_SET_KEY, user_id)
                        removed += 1
                except ValueError:
                    # Invalid member, remove it
                    redis.srem(cls.ONLINE_SET_KEY, member)
                    removed += 1

            if removed > 0:
                logger.info(f"🧹 Cleaned up {removed} stale presence SET entries")

            return removed
        except Exception as e:
            logger.error(f"Error cleaning up presence SET: {e}")
            return 0
