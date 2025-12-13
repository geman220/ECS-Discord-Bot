# app/init/socketio.py

"""
SocketIO Initialization

Initialize Flask-SocketIO with Redis message queue and register socket handlers.
"""

import logging

logger = logging.getLogger(__name__)


def init_socketio(app):
    """
    Initialize SocketIO for the Flask application.

    Args:
        app: The Flask application instance.
    """
    from app.core import socketio

    # Initialize SocketIO with Redis as the message queue
    socketio.init_app(
        app,
        message_queue=app.config.get('REDIS_URL', 'redis://redis:6379/0'),
        manage_session=False,
        async_mode='eventlet',
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*'),
        path='/socket.io/',  # Explicitly set SocketIO path to avoid conflicts
        allow_upgrades=True,  # Allow HTTP to WebSocket upgrades
        transports=['websocket', 'polling']  # Support both transport methods
    )

    # CRITICAL: Import handlers AFTER socketio.init_app() so they register on the correct instance
    from app.sockets import register_socket_handlers
    register_socket_handlers()

    # Import live reporting handlers to register /live namespace
    from app.sockets import live_reporting

    # Debug: Check if /live namespace handlers are registered
    try:
        if hasattr(socketio.server, 'handlers'):
            live_handlers = socketio.server.handlers.get('/live', {})
            logger.info(f"🔥 Handlers in /live namespace: {list(live_handlers.keys())}")
        else:
            logger.warning("🚫 No server.handlers attribute found for /live namespace")
    except Exception as e:
        logger.error(f"🚫 Error checking /live handlers: {e}")

    logger.info("🎯 Socket.IO system initialized successfully")
