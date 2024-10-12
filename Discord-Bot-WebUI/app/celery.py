from celery import Celery
from celery.schedules import crontab
from web_config import Config
import logging

logger = logging.getLogger(__name__)

def make_celery(app=None):
    celery = Celery(
        app.import_name if app else __name__,
    )
    celery.conf.update(
        broker_url=Config.CELERY_BROKER_URL,
        result_backend=Config.RESULTS_BACKEND,
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
    )
    if app:
        celery.conf.update(app.config)
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)
        celery.Task = ContextTask
    celery.autodiscover_tasks(['app'])

    # Configure the beat schedule
    celery.conf.beat_schedule = {
        'schedule_live_reporting_every_hour': {
            'task': 'app.tasks.schedule_live_reporting',
            'schedule': crontab(minute=0),  # Run every hour
        },
    }

    @celery.on_after_configure.connect
    def setup_periodic_tasks(sender, **kwargs):
        sender.add_periodic_task(
            crontab(minute='*/5'),
            send_scheduled_messages.s(),
            name='send availability messages'
        )
        sender.add_periodic_task(
            crontab(hour=0, minute=0, day_of_week=1),
            schedule_season_availability.s(),
            name='schedule next week availability'
        )

    return celery

celery = make_celery()

@celery.task(bind=True, max_retries=3)
def send_scheduled_messages(self):
    try:
        from app.tasks import send_scheduled_messages
        return send_scheduled_messages()
    except Exception as exc:
        logger.error(f"Error in send_scheduled_messages task: {exc}")
        raise self.retry(exc=exc, countdown=60)

@celery.task(bind=True, max_retries=3)
def schedule_season_availability(self):
    try:
        from app.tasks import schedule_season_availability
        return schedule_season_availability()
    except Exception as exc:
        logger.error(f"Error in schedule_season_availability task: {exc}")
        raise self.retry(exc=exc, countdown=300)