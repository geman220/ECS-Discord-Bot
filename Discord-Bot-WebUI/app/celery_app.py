# app/celery_app.py

# Note: This file should not import eventlet as it's imported by other modules
from celery import Celery

def create_celery():
    celery = Celery(
        'app',
        broker='redis://redis:6379/0',
        backend='redis://redis:6379/0',
        include=[
            'app.tasks.tasks_core',
            'app.tasks.tasks_live_reporting',
            'app.tasks.tasks_match_updates',
            'app.tasks.tasks_rsvp',
            'app.tasks.tasks_discord'
        ]
    )

    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=30 * 60,
        task_soft_time_limit=15 * 60
    )

    return celery

# Create the Celery instance
celery = create_celery()