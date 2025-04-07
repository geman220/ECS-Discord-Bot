# app/sockets/__init__.py

"""
Socket Modules Package

This package contains modules related to WebSocket functionality,
particularly for real-time communication features like live match
reporting and Discord role updates.
"""

# Utility for Socket.IO session data management
class SocketSessionManager:
    """Manages Socket.IO session data across events."""
    
    _session_storage = {}  # Simple in-memory storage
    
    @staticmethod
    def get_session_data(sid):
        """Get session data for a given Socket.IO session ID."""
        # Use simple in-memory dictionary storage
        try:
            return SocketSessionManager._session_storage.get(sid, {})
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting Socket.IO session data: {e}")
            return {}
    
    @staticmethod
    def save_session_data(sid, data):
        """Save session data for a given Socket.IO session ID."""
        try:
            # Use simple in-memory dictionary storage
            SocketSessionManager._session_storage[sid] = data
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error saving Socket.IO session data: {e}")
            return False
            
    @staticmethod
    def clear_session_data(sid):
        """Clear session data for a given Socket.IO session ID."""
        try:
            if sid in SocketSessionManager._session_storage:
                del SocketSessionManager._session_storage[sid]
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error clearing Socket.IO session data: {e}")
            return False