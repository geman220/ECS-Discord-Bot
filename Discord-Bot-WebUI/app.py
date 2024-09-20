from app import create_app, socketio
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app, celery = create_app()

if __name__ == '__main__':
    if celery is None:
        logger.warning("Celery is not initialized!")
    else:
        logger.info(f"Celery broker: {celery.conf.broker_url}")
        logger.info(f"Celery backend: {celery.conf.result_backend}")

    logger.info("Starting Flask application...")
    socketio.run(app, debug=True, use_reloader=True, log_output=True, host="0.0.0.0")
