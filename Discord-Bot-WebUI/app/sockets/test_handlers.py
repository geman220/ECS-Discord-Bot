# app/sockets/test_handlers.py

"""
Socket.IO Test Handlers

Simple test handlers for debugging and development.
"""

import logging

from flask_socketio import emit

from app.core import socketio

logger = logging.getLogger(__name__)


@socketio.on('simple_test', namespace='/')
def handle_simple_test(data):
    """Simple test handler for debugging."""
    print(f"🔧 Simple test: {data}")
    logger.info(f"🔧 Simple test: {data}")
    emit('simple_response', {'message': 'Test successful!', 'data': data})
