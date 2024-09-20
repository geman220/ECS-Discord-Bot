from celery import Celery

def make_celery(app=None):
    celery = Celery(
        app.import_name if app else __name__,
        backend='redis://redis:6379/0',
        broker='redis://redis:6379/0'
    )
    if app:
        celery.conf.update(app.config)

        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    celery.autodiscover_tasks(['app'])
    
    return celery

# Create a global Celery instance
celery = make_celery()