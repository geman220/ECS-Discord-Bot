# celery_worker_base_prefork.py

import logging
from app import create_app
from app.core import celery as celery_app
from app.config.celery_config import CeleryConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

flask_app = create_app()
celery_app.conf.update(flask_app.config)
celery_app.flask_app = flask_app

__all__ = ['flask_app', 'celery_app', 'logger']
