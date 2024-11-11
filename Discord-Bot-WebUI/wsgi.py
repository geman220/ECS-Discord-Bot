# wsgi.py

# Monkey patch before any other imports
import eventlet
eventlet.monkey_patch(os=True, select=True, socket=True, thread=True, time=True)

import logging
from app import create_app, socketio
from app.debug.diagnostic import run_diagnostics

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

try:
    # Create the Flask application instance
    flask_app = create_app()
    
    # Initialize app context for background tasks
    app_context = flask_app.app_context()
    app_context.push()
    
    # Run diagnostics before starting the server
    logger.info("Running pre-start diagnostics...")
    run_diagnostics(flask_app)
    
    # Import socket handlers to register them
    import app.socket_handlers
    
except Exception as e:
    logger.error(f"Failed to initialize application: {e}", exc_info=True)
    raise

def application(environ, start_response):
    try:
        return flask_app.wsgi_app(environ, start_response)
    except Exception as e:
        logger.error(f"Error handling request: {e}", exc_info=True)
        # Return a 500 Internal Server Error response
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [b'Internal Server Error']

# For development server only
if __name__ == "__main__":
    socketio.run(flask_app, debug=True)