# build_assets.py

"""
Script to build and minify static assets.

This script creates a Flask application using the create_app factory,
ensures the assets extension is initialized, and then builds each asset bundle.
"""

import logging
import os
from app import create_app

logging.basicConfig(level=logging.INFO)

if __name__ == '__main__':
    try:
        app = create_app()
        with app.app_context():
            if 'assets' not in app.extensions:
                logging.error("Assets not initialized properly")
            else:
                assets = app.extensions['assets']
                
                dist_path = os.path.join(app.static_folder, "dist")
                if not os.path.exists(dist_path):
                    os.makedirs(dist_path)
                    logging.debug(f"Created output directory: {dist_path}")
                else:
                    logging.debug(f"Output directory exists: {dist_path}")
                
                for name, bundle in assets._named_bundles.items():
                    logging.info(f"Building bundle: {name}")
                    bundle.build()
                    logging.debug(f"Finished building bundle: {name}")
                logging.debug("Assets built successfully")
    except Exception as e:
        logging.error(f"Error building assets: {str(e)}")