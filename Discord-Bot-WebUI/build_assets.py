# build_assets.py

"""
Script to build and minify static assets.

This script creates a Flask application using the create_app factory,
ensures the assets extension is initialized, and then builds each asset bundle.
"""

import logging
from app import create_app

logging.basicConfig(level=logging.DEBUG)

if __name__ == '__main__':
    try:
        # Initialize the Flask app
        app = create_app()
        with app.app_context():
            # Verify that the assets extension is initialized
            if 'assets' not in app.extensions:
                logging.error("Assets not initialized properly")
            else:
                assets = app.extensions['assets']
                # Build each asset bundle
                for bundle in assets:
                    bundle.build()
                logging.info("Assets built successfully")
    except Exception as e:
        logging.error(f"Error building assets: {str(e)}")