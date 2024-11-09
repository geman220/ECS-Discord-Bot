# wsgi.py

# Monkey patch before any other imports
import eventlet
eventlet.monkey_patch()

import logging
from app import create_app, socketio

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create the Flask application instance
flask_app = create_app()

# Initialize app context for background tasks
app_context = flask_app.app_context()
app_context.push()

# Import socket handlers to register them
import app.socket_handlers

def application(environ, start_response):
    return flask_app.wsgi_app(environ, start_response)

# For development server only
if __name__ == "__main__":
    socketio.run(flask_app, debug=True)