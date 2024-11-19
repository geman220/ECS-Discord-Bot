## app/config/celery_config.py
import os
from celery.schedules import crontab
import pytz

class CeleryConfig:
    # Timezone Settings (Add these)
    timezone = 'America/Los_Angeles'
    enable_utc = False
    beat_tz = pytz.timezone('America/Los_Angeles')

    # Redis Configuration (Add these)
    redis_socket_timeout = 5
    redis_socket_connect_timeout = 5
    redis_retry_on_timeout = True

    # Update broker and backend with more options
    broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
    broker_transport_options = {
        'visibility_timeout': 3600,  # 1 hour
        'socket_timeout': 5,
        'socket_connect_timeout': 5
    }
    result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
    result_backend_transport_options = {
        'socket_timeout': 5,
        'socket_connect_timeout': 5
    }

    # Task Registration and Imports
    imports = (
        'app.tasks.tasks_core',
        'app.tasks.tasks_live_reporting',
        'app.tasks.tasks_match_updates',
        'app.tasks.tasks_rsvp',
        'app.tasks.tasks_discord',
        'app.tasks.monitoring_tasks',
        'app.tasks.tasks_maintenance'
    )
    
    # Task Settings
    task_acks_late = True
    task_reject_on_worker_lost = True
    task_acks_on_failure_or_timeout = True
    task_track_started = True
    task_time_limit = 30 * 60
    task_soft_time_limit = 15 * 60
    
    # Worker Settings
    worker_prefetch_multiplier = 1
    worker_max_tasks_per_child = 50
    worker_concurrency = 4
    broker_connection_retry_on_startup = True
    
    # Serialization
    accept_content = ['json']
    task_serializer = 'json'
    result_serializer = 'json'
    
    # Queue Configuration
    task_queues = {
        'live_reporting': {
            'exchange': 'live_reporting',
            'routing_key': 'live_reporting',
            'queue_arguments': {'x-max-priority': 10}
        },
        'discord': {
            'exchange': 'discord',
            'routing_key': 'discord',
            'queue_arguments': {'x-max-priority': 10}
        },
        'celery': {
            'exchange': 'celery',
            'routing_key': 'celery',
            'queue_arguments': {'x-max-priority': 10}
        }
    }
    
    # Task Routes
    task_routes = {
        'app.tasks.tasks_discord.*': {'queue': 'discord'},
        'app.tasks.tasks_core.*': {'queue': 'celery'},
        'app.tasks.tasks_live_reporting.*': {'queue': 'live_reporting'},
        'app.tasks.tasks_match_updates.*': {'queue': 'celery'},
        'app.tasks.tasks_rsvp.*': {'queue': 'celery'},
        'app.tasks.monitoring_tasks.*': {'queue': 'celery'},
        'app.tasks.tasks_maintenance.*': {'queue': 'celery'}
    }
    
    # Beat Schedule
    beat_schedule = {
        # Match Management Tasks
        'check-upcoming-matches': {
            'task': 'app.tasks.tasks_live_reporting.check_upcoming_matches',
            'schedule': crontab(minute='*/5'),
            'options': {
                'queue': 'live_reporting',
                'expires': 270
            }
        },
        'check-create-match-threads': {
            'task': 'app.tasks.tasks_live_reporting.check_and_create_scheduled_threads',
            'schedule': crontab(minute='*/10'),
            'options': {
                'queue': 'live_reporting',
                'expires': 540
            }
        },
        'schedule-live-reporting': {
            'task': 'app.tasks.tasks_live_reporting.schedule_live_reporting',
            'schedule': crontab(minute='*/15'),
            'options': {
                'queue': 'live_reporting',
                'expires': 840
            }
        },
        
        # Monitoring Tasks
        'verify-scheduled-tasks': {
            'task': 'app.tasks.tasks_live_reporting.verify_scheduled_tasks',
            'schedule': crontab(minute='*/15'),
            'options': {
                'queue': 'live_reporting',
                'expires': 840
            }
        },
        'check-redis-connection': {
            'task': 'app.tasks.tasks_live_reporting.check_redis_connection',
            'schedule': crontab(minute='*/30'),
            'options': {
                'queue': 'live_reporting',
                'expires': 1740
            }
        },

        'collect-db-stats': {
            'task': 'app.tasks.monitoring_tasks.collect_db_stats',
            'schedule': crontab(minute='*/5'),  # Runs every 5 minutes
            'options': {
                'queue': 'celery',  # Specify the queue to use
                'expires': 330      # Task expires after 5.5 minutes
            }
        },
        
        # Core Tasks
        'schedule-season-availability': {
            'task': 'app.tasks.tasks_core.schedule_season_availability',
            'schedule': crontab(hour=0, minute=0),
            'options': {
                'queue': 'celery',
                'expires': 3540
            }
        },

        'process-scheduled-messages': {
            'task': 'app.tasks.tasks_rsvp.process_scheduled_messages',
            'schedule': crontab(minute='*/5'),
            'options': {
                'queue': 'celery',
                'expires': 270
            }
        },

        'monitor-scheduled-tasks': {
            'task': 'app.tasks.tasks_live_reporting.verify_scheduled_tasks',
            'schedule': crontab(minute='*/5'),  # Run every 5 minutes
            'options': {
                'queue': 'live_reporting',
                'expires': 270
            }
        },

        'monitor-all-matches': {
            'task': 'app.tasks.tasks_live_reporting.monitor_all_matches',
            'schedule': crontab(minute='*/15'),  # Run every 15 minutes
            'options': {
                'queue': 'live_reporting',
                'expires': 840
            }
        },

        'verify-redis-tasks': {
            'task': 'app.tasks.tasks_live_reporting.verify_redis_tasks',
            'schedule': crontab(minute='*/10'),  # Run every 10 minutes
            'options': {
                'queue': 'live_reporting',
                'expires': 540
            }
        }
    }
