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
    redis_socket_timeout = 30  # Reasonable timeout for Celery operations
    redis_socket_connect_timeout = 5
    redis_retry_on_timeout = True

    # Broker and Backend Settings
    broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
    broker_transport_options = {
        'visibility_timeout': 3600,  # 1 hour
        'socket_timeout': 30,
        'socket_connect_timeout': 5,
        # Automatically expire unprocessed messages
        'fanout_prefix': True,
        'fanout_patterns': True,
        # Set default message TTL in Redis
        'master_name': None
    }
    result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
    result_backend_transport_options = {
        'socket_timeout': 30,
        'socket_connect_timeout': 5
    }

    # Task Registration and Imports
    imports = (
        'app.tasks.tasks_core',
        'app.tasks.tasks_live_reporting',  # DEPRECATED - V1 legacy (has warnings)
        # 'app.tasks.tasks_robust_live_reporting', # Removed - V2 is production version
        # 'app.tasks.tasks_live_reporting_v2',  # DEPRECATED - Replaced by enterprise system
        # 'app.tasks.live_reporting_orchestrator',  # DEPRECATED - V2 is self-scheduling
        'app.tasks.match_scheduler',  # ENTERPRISE - Match scheduling and live reporting coordination
        'app.tasks.tasks_live_reporting_recovery',
        'app.tasks.queue_health_monitor',
        'app.tasks.tasks_match_updates',
        'app.tasks.tasks_rsvp',
        'app.tasks.tasks_rsvp_ecs',
        'app.tasks.tasks_ecs_fc_scheduled',
        'app.tasks.tasks_discord',
        'app.tasks.monitoring_tasks',
        'app.tasks.tasks_maintenance',
        'app.tasks.tasks_cache_management',
        'app.tasks.player_sync',
        'app.tasks.tasks_substitute_pools',
        'app.tasks.tasks_image_optimization',
        'app.tasks.tasks_ecs_fc_subs',
        'app.tasks.mobile_analytics_cleanup',
        'app.tasks.security_cleanup'
    )

    # Task Settings - Industry Best Practices
    task_acks_late = True  # Acknowledge tasks after completion
    task_reject_on_worker_lost = True  # Reject tasks when worker is lost
    task_acks_on_failure_or_timeout = True  # Clean up failed tasks
    task_track_started = True
    task_time_limit = 30 * 60  # 30 minutes
    task_soft_time_limit = 15 * 60  # 15 minutes
    task_always_eager = False  # Never run tasks synchronously in production
    task_eager_propagates = False  # Don't propagate exceptions in eager mode
    task_ignore_result = False  # Keep results for monitoring
    task_store_eager_result = False  # Don't store results when eager
    task_default_retry_delay = 60  # Default retry delay (1 minute)
    task_max_retries = 3  # Default max retries
    task_serializer_kwargs = {
        'ensure_ascii': True,
        'sort_keys': True
    }
    
    # Task Result Settings - Industry Best Practices
    result_expires = 1800  # Results expire after 30 minutes (faster cleanup)
    result_compression = 'gzip'  # Compress results to save memory
    result_accept_content = ['json']
    result_persistent = False  # Don't persist results beyond expiry
    result_backend_always_retry = True  # Auto-retry result backend connections
    result_extended = True  # Store additional task metadata safely
    result_serializer_kwargs = {
        'ensure_ascii': True,
        'sort_keys': True,
        'separators': (',', ':')
    }
    
    # Task Execution Settings
    task_send_sent_event = True  # Send task-sent events for monitoring
    task_send_events = True  # Enable event monitoring

    # Worker Settings
    worker_prefetch_multiplier = 1
    worker_max_tasks_per_child = 100  # Restart worker after 100 tasks
    worker_max_memory_per_child = 150000  # 150MB memory limit per worker
    worker_concurrency = 4
    broker_connection_retry_on_startup = True
    
    # Production Worker Optimizations
    worker_disable_rate_limits = False  # Keep rate limiting enabled
    worker_pool_restarts = True  # Allow pool restarts for memory management
    worker_autoscaler_max_memory_per_child = 200000  # 200MB absolute max
    worker_lost_wait = 10.0  # Wait 10 seconds for lost worker cleanup
    
    # Connection Pool Settings for High Load
    broker_pool_limit = 10  # Connection pool size - sufficient for Celery workers
    broker_connection_retry = True
    broker_connection_max_retries = 3

    # Serialization Settings
    accept_content = ['json']
    task_serializer = 'json'
    result_serializer = 'json'

    # Queue Configuration
    task_queues = {
        'live_reporting': {
            'exchange': 'live_reporting',
            'routing_key': 'live_reporting',
            'queue_arguments': {
                'x-max-priority': 10,
                'x-message-ttl': 300000,  # 5 minutes TTL (real-time updates)
                'x-max-length': 100,  # Larger queue for real-time processing
                'x-overflow': 'drop-head'  # Drop old tasks if queue full (keep newest)
            }
        },
        'discord': {
            'exchange': 'discord',
            'routing_key': 'discord',
            'queue_arguments': {
                'x-max-priority': 10,
                'x-message-ttl': 3600000,  # 1 hour TTL for Discord tasks
                'x-max-length': 500
            }
        },
        'celery': {
            'exchange': 'celery',
            'routing_key': 'celery',
            'queue_arguments': {
                'x-max-priority': 10,
                'x-message-ttl': 1800000,  # 30 minutes TTL for general tasks
                'x-max-length': 1000
            }
        },
        'player_sync': {
            'exchange': 'player_sync',
            'routing_key': 'player_sync',
            'queue_arguments': {
                'x-max-priority': 10,
                'x-message-ttl': 7200000,  # 2 hours TTL for player sync
                'x-max-length': 200
            }
        }
    }

    # Task Routes
    task_routes = {
        'app.tasks.tasks_discord.*': {'queue': 'discord'},
        'app.tasks.tasks_core.*': {'queue': 'celery'},
        'app.tasks.tasks_live_reporting.*': {'queue': 'live_reporting'},
        'app.tasks.live_reporting_orchestrator.*': {'queue': 'live_reporting'},  # Event-driven orchestration
        'app.tasks.tasks_match_updates.*': {'queue': 'discord'},
        'app.tasks.tasks_rsvp.*': {'queue': 'celery'},  # Default for RSVP tasks; individual tasks override with queue parameter
        'app.tasks.tasks_rsvp_ecs.*': {'queue': 'discord'},
        'app.tasks.tasks_ecs_fc_scheduled.*': {'queue': 'discord'},
        'app.tasks.monitoring_tasks.*': {'queue': 'celery'},
        'app.tasks.tasks_maintenance.*': {'queue': 'celery'},
        'app.tasks.player_sync.*': {'queue': 'player_sync'},
        'app.tasks.tasks_substitute_pools.*': {'queue': 'celery'},
        'app.tasks.tasks_image_optimization.*': {'queue': 'celery'},
        'app.tasks.tasks_ecs_fc_subs.*': {'queue': 'celery'},
        'app.tasks.mobile_analytics_cleanup.*': {'queue': 'celery'},
        'app.tasks.security_cleanup.*': {'queue': 'celery'},
    }

    # Beat Schedule: periodic tasks and their schedules
    beat_schedule = {
        # DEPRECATED V1 - Use V2 real-time system instead
        # 'check-create-match-threads': {
        #     'task': 'app.tasks.tasks_live_reporting.check_and_create_scheduled_threads',
        #     'schedule': crontab(minute='*/10'),
        #     'options': {
        #         'queue': 'live_reporting',
        #         'expires': 540
        #     }
        # },
        # 'schedule-live-reporting': {
        #     'task': 'app.tasks.tasks_live_reporting.schedule_live_reporting',
        #     'schedule': crontab(minute='*/15'),
        #     'options': {
        #         'queue': 'live_reporting',
        #         'expires': 840
        #     }
        # },
        'collect-db-stats': {
            'task': 'app.tasks.monitoring_tasks.collect_db_stats',
            'schedule': crontab(minute='*/15'),  # Reduced from every 5 to every 15 minutes
            'options': {
                'queue': 'celery',
                'expires': 840  # Task expires after 14 minutes
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
            'schedule': crontab(minute='*/30'),  # Reduced from every 10 to every 30 minutes
            'options': {
                'queue': 'celery',
                'expires': 1740  # Task expires after 29 minutes
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
                'queue': 'discord',  # Fixed: process_scheduled_messages needs Discord access
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
        # 'force-discord-rsvp-sync': {
        #     'task': 'app.tasks.tasks_rsvp.force_discord_rsvp_sync',
        #     'schedule': crontab(hour='*/4'),  # Run every 4 hours
        #     'options': {
        #         'queue': 'discord',
        #         'expires': 14340  # Task expires after 3 hours 59 minutes
        #     }
        # }  # DISABLED: Replaced by smart sync system
        'mobile-analytics-cleanup': {
            'task': 'app.tasks.mobile_analytics_cleanup.cleanup_mobile_analytics_task',
            'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM PST
            'options': {
                'queue': 'celery',
                'expires': 3540  # Task expires after 59 minutes
            }
        },
        # ENTERPRISE LIVE REPORTING SYSTEM - Uses dedicated real-time service + match scheduler
        # Real-time service runs continuously in dedicated container
        # Match scheduler service handles 48hr thread creation and live reporting start times
        'enterprise-match-scheduler': {
            'task': 'app.tasks.match_scheduler.schedule_upcoming_matches',
            'schedule': crontab(minute='*/10'),  # Check every 10 minutes for new matches to schedule
            'options': {
                'queue': 'live_reporting',
                'expires': 540,  # 9 minutes
                'time_limit': 60,
                'soft_time_limit': 45,
                'priority': 8
            }
        },
        # Live Reporting Recovery - Check for matches that should be reporting but aren't
        'check-missing-live-reporting': {
            'task': 'app.tasks.tasks_live_reporting_recovery.check_and_start_missing_live_reporting',
            'schedule': crontab(minute='*/3'),  # Every 3 minutes
            'options': {
                'queue': 'live_reporting',
                'expires': 150  # Task expires after 2.5 minutes
            }
        },
        # Legacy Robust Live Reporting - DISABLED (V2 is now active)
        # 'process-active-live-sessions-legacy': {
        #     'task': 'REMOVED - V2 is production version',
        #     'schedule': crontab(minute='*/30'),  # Every 30 minutes (disabled)
        #     'options': {
        #         'queue': 'live_reporting',
        #         'expires': 25
        #     }
        # },
        # Clean up old live reporting sessions daily
        'cleanup-old-live-sessions': {
            # 'task': 'REMOVED - V2 handles session cleanup',
            'schedule': crontab(hour=3, minute=30),  # Daily at 3:30 AM PST
            'options': {
                'queue': 'live_reporting',
                'expires': 1740  # Task expires after 29 minutes
            }
        },
        # TEMPORARILY DISABLED - These new maintenance tasks may be causing connection issues
        # Clean expired tasks from queues - More Aggressive
        # 'cleanup-expired-queue-tasks': {
        #     'task': 'app.tasks.tasks_maintenance.cleanup_expired_queue_tasks',
        #     'schedule': crontab(minute='*/10'),  # Every 10 minutes (more frequent)
        #     'options': {
        #         'queue': 'celery',
        #         'expires': 540,  # Task expires after 9 minutes
        #         'priority': 9  # High priority cleanup
        #     }
        # },
        # # Monitor Celery system health
        # 'monitor-celery-health': {
        #     'task': 'app.tasks.tasks_maintenance.monitor_celery_health',
        #     'schedule': crontab(minute='*/3'),  # Every 3 minutes (more frequent monitoring)
        #     'options': {
        #         'queue': 'celery',
        #         'expires': 150,  # Task expires after 2.5 minutes
        #         'priority': 8  # High priority monitoring
        #     }
        # },
        # # Auto-purge stuck queues (emergency cleanup)
        # 'emergency-queue-purge': {
        #     'task': 'app.tasks.tasks_maintenance.emergency_queue_purge',
        #     'schedule': crontab(minute='*/30'),  # Every 30 minutes
        #     'options': {
        #         'queue': 'celery',
        #         'expires': 1740,  # Task expires after 29 minutes
        #         'priority': 10  # Highest priority
        #     }
        # },
        # Cache tasks (FIXED: removed double session usage)
        'update-task-status-cache': {
            'task': 'app.tasks.tasks_cache_management.update_task_status_cache',
            'schedule': crontab(minute='*/10'),  # Reduced from every 3 to every 10 minutes
            'options': {
                'queue': 'celery',
                'expires': 540  # Task expires after 9 minutes
            }
        },
        'cache-health-check': {
            'task': 'app.tasks.tasks_cache_management.cache_health_check',
            'schedule': crontab(minute='*/10'),  # Every 10 minutes
            'options': {
                'queue': 'celery',
                'expires': 540  # Task expires after 9 minutes
            }
        },
        # Queue Health Monitor - Prevent queue clogging
        'monitor-and-cleanup-queues': {
            'task': 'app.tasks.queue_health_monitor.monitor_and_cleanup_queues',
            'schedule': crontab(minute='*/5'),  # Every 5 minutes
            'options': {
                'queue': 'celery',
                'expires': 240,  # Task expires after 4 minutes
                'priority': 10  # Highest priority for queue health
            }
        },
        # Security maintenance tasks
        'cleanup-security-logs': {
            'task': 'app.tasks.security_cleanup.cleanup_security_logs',
            'schedule': crontab(hour=1, minute=30),  # Daily at 1:30 AM PST
            'kwargs': {
                'retention_days': int(os.getenv('SECURITY_LOG_RETENTION_DAYS', 90))  # Configurable retention
            },
            'options': {
                'queue': 'celery',
                'expires': 3540  # Task expires after 59 minutes
            }
        },
        'cleanup-expired-bans': {
            'task': 'app.tasks.security_cleanup.cleanup_expired_bans',
            'schedule': crontab(hour='*/12'),  # Reduced from every 6 to every 12 hours
            'options': {
                'queue': 'celery',
                'expires': 3600  # Task expires after 1 hour
            }
        },
        'security-maintenance': {
            'task': 'app.tasks.security_cleanup.security_maintenance',
            'schedule': crontab(hour=2, minute=30, day_of_week=0),  # Weekly on Sunday at 2:30 AM PST
            'options': {
                'queue': 'celery',
                'expires': 3540  # Task expires after 59 minutes
            }
        },
        'smart-ban-cleanup': {
            'task': 'app.tasks.security_cleanup.smart_ban_cleanup',
            'schedule': crontab(hour='*/2'),  # Reduced from every 30 minutes to every 2 hours
            'options': {
                'queue': 'celery',
                'expires': 3600  # Task expires after 1 hour
            }
        },
        # [DEPRECATED] Live Reporting Health Check - Replaced by Enterprise Live Reporting System
        # 'health-check-live-reporting': {
        #     'task': 'app.tasks.live_reporting_orchestrator.health_check_live_reporting',
        #     'schedule': crontab(minute='*/10'),  # Every 10 minutes
        #     'options': {
        #         'queue': 'live_reporting',
        #         'expires': 540  # Task expires after 9 minutes
        #     }
        # }
    }