from app import create_app
import logging

logging.basicConfig(level=logging.DEBUG)

if __name__ == '__main__':
    try:
        app = create_app()
        with app.app_context():
            if 'assets' not in app.extensions:
                logging.error("Assets not initialized properly")
            else:
                assets = app.extensions['assets']
                for bundle in assets:
                    bundle.build()
                logging.info("Assets built successfully")
    except Exception as e:
        logging.error(f"Error building assets: {str(e)}")