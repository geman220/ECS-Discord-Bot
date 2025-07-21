## app/config/celery_config.py

import os
from celery.schedules import crontab
import pytz


class CeleryConfig:
    """
    Celery configuration for the application.

    This class defines settings including timezone, broker/backend, task registration,
    worker settings, serialization, queue configuration, task routing, and periodic task scheduling.
    """

    # Timezone Settings
    timezone = 'America/Los_Angeles'
    enable_utc = False
    beat_tz = pytz.timezone('America/Los_Angeles')

    # Redis Configuration
    redis_socket_timeout = 5
    redis_socket_connect_timeout = 5
    redis_retry_on_timeout = True

    # Broker and Backend Settings
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
        'app.tasks.tasks_rsvp_ecs',
        'app.tasks.tasks_ecs_fc_scheduled',
        'app.tasks.tasks_discord',
        'app.tasks.monitoring_tasks',
        'app.tasks.tasks_maintenance',
        'app.tasks.player_sync',
        'app.tasks.tasks_substitute_pools',
        'app.tasks.tasks_image_optimization',
        'app.tasks.tasks_ecs_fc_subs'
    )

    # Task Settings
    task_acks_late = True
    task_reject_on_worker_lost = True
    task_acks_on_failure_or_timeout = True
    task_track_started = True
    task_time_limit = 30 * 60  # 30 minutes
    task_soft_time_limit = 15 * 60  # 15 minutes

    # Worker Settings
    worker_prefetch_multiplier = 1
    worker_max_tasks_per_child = 100  # Increased from 50 - restart worker after 100 tasks
    worker_max_memory_per_child = 150000  # 150MB memory limit per worker
    worker_concurrency = 4
    broker_connection_retry_on_startup = True

    # Serialization Settings
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
        },
        'player_sync': {
            'exchange': 'player_sync',
            'routing_key': 'player_sync',
            'queue_arguments': {'x-max-priority': 10}
        }
    }

    # Task Routes
    task_routes = {
        'app.tasks.tasks_discord.*': {'queue': 'discord'},
        'app.tasks.tasks_core.*': {'queue': 'celery'},
        'app.tasks.tasks_live_reporting.*': {'queue': 'live_reporting'},
        'app.tasks.tasks_match_updates.*': {'queue': 'discord'},
        'app.tasks.tasks_rsvp.*': {'queue': 'celery'},
        'app.tasks.tasks_rsvp_ecs.*': {'queue': 'discord'},
        'app.tasks.tasks_ecs_fc_scheduled.*': {'queue': 'discord'},
        'app.tasks.monitoring_tasks.*': {'queue': 'celery'},
        'app.tasks.tasks_maintenance.*': {'queue': 'celery'},
        'app.tasks.player_sync.*': {'queue': 'player_sync'},
        'app.tasks.tasks_substitute_pools.*': {'queue': 'celery'},
        'app.tasks.tasks_image_optimization.*': {'queue': 'celery'},
        'app.tasks.tasks_ecs_fc_subs.*': {'queue': 'celery'},
    }

    # Beat Schedule: periodic tasks and their schedules
    beat_schedule = {
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
        'collect-db-stats': {
            'task': 'app.tasks.monitoring_tasks.collect_db_stats',
            'schedule': crontab(minute='*/5'),
            'options': {
                'queue': 'celery',
                'expires': 330  # Task expires after 5.5 minutes
            }
        },
        'check-for-session-leaks': {
            'task': 'app.tasks.monitoring_tasks.check_for_session_leaks',
            'schedule': crontab(minute='*/15'),
            'options': {
                'queue': 'celery',
                'expires': 840
            }
        },
        'monitor-redis-connections': {
            'task': 'app.tasks.monitoring_tasks.monitor_redis_connections',
            'schedule': crontab(minute='*/10'),
            'options': {
                'queue': 'celery',
                'expires': 540
            }
        },
        'clean-zombie-tasks': {
            'task': 'app.utils.task_monitor.clean_zombie_tasks',
            'schedule': crontab(minute='*/15'),
            'options': {
                'queue': 'celery',
                'expires': 840
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
        'schedule-weekly-match-availability': {
            'task': 'app.tasks.tasks_rsvp.schedule_weekly_match_availability',
            'schedule': crontab(day_of_week='1', hour=8, minute=0),  # Every Monday at 8:00 AM
            'options': {
                'queue': 'discord',
                'expires': 3600
            }
        },
        'schedule-ecs-fc-reminders': {
            'task': 'app.tasks.tasks_ecs_fc_scheduled.schedule_ecs_fc_reminders',
            'schedule': crontab(hour=0, minute=0),  # Daily at midnight
            'options': {
                'queue': 'discord',
                'expires': 3600
            }
        },
        'monitor-rsvp-health': {
            'task': 'app.tasks.tasks_rsvp.monitor_rsvp_health',
            'schedule': crontab(minute='*/30'),  # Run every 30 minutes
            'options': {
                'queue': 'discord',
                'expires': 1740  # Task expires after 29 minutes
            }
        },
        'force-discord-rsvp-sync': {
            'task': 'app.tasks.tasks_rsvp.force_discord_rsvp_sync',
            'schedule': crontab(hour='*/4'),  # Run every 4 hours
            'options': {
                'queue': 'discord',
                'expires': 14340  # Task expires after 3 hours 59 minutes
            }
        }
    }