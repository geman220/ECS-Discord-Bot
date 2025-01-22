import os
import sys

# Only use eventlet and full app setup when not running migrations
if 'flask db' not in ' '.join(sys.argv):
    import eventlet
    eventlet.monkey_patch()
    
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
        
        # Run diagnostics before starting the server
        logger.info("Running pre-start diagnostics...")
        run_diagnostics(flask_app)
        
        # Import socket handlers to register them
        import app.socket_handlers
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}", exc_info=True)
        raise

else:
    # Minimal setup for migrations
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from flask_migrate import Migrate
    import migrations_config
    
    flask_app = Flask(__name__)
    flask_app.config.from_object('migrations_config.Config')
    
    db = SQLAlchemy(flask_app)
    migrate = Migrate(flask_app, db)
    
    # Import models to ensure they're known to Flask-Migrate
    from app.models import *

# Expose the Flask application as the WSGI application
application = flask_app

# For development server only
if __name__ == "__main__":
    if 'flask db' not in ' '.join(sys.argv):
        socketio.run(flask_app, debug=True)
    else:
        flask_app.run(debug=True)