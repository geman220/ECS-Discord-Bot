# app/log_config/logging_config.py

"""
Logging configuration for the application.

This configuration is used to initialize Python's logging module with a
dictionary-based setup. It defines formatters, handlers, and loggers for
various parts of the application to ensure detailed and organized logging.
"""

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,

    # Formatters define the layout of the log messages.
    'formatters': {
        'detailed': {
            'format': '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
        },
        'simple': {
            'format': '%(asctime)s [%(levelname)s] %(message)s'
        },
        'focused': {
            'format': '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
        }
    },

    # Handlers specify where log messages are sent (e.g., console, files).
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',  # Changed to simple for less verbose console output
            'level': 'INFO',        # Changed from DEBUG to INFO to reduce noise
        },
        'db_file': {
            'class': 'logging.FileHandler',
            'filename': 'db_operations.log',
            'formatter': 'detailed',
            'level': 'INFO',        # Only log important DB operations
        },
        'requests_file': {
            'class': 'logging.FileHandler',
            'filename': 'requests.log',
            'formatter': 'detailed',
            'level': 'INFO',        # Only log main request information
        },
        'auth_file': {
            'class': 'logging.FileHandler',
            'filename': 'auth.log',
            'formatter': 'detailed',
        },
        'session_tracking': {
            'class': 'logging.FileHandler',
            'filename': 'session_tracking.log',
            'formatter': 'focused',
            'level': 'INFO',
        },
        'errors_file': {
            'class': 'logging.FileHandler',
            'filename': 'errors.log',
            'formatter': 'detailed',
            'level': 'WARNING',     # Only log actual errors
        }
    },

    # Loggers define logging behavior for specific modules or components.
    'loggers': {
        'sqlalchemy.engine': {
            'handlers': ['db_file'],
            'level': 'WARNING',     # Only log SQL errors, not queries
            'propagate': False
        },
        'app.db_management': {
            'handlers': ['db_file', 'errors_file'],
            'level': 'WARNING',     # Reduced from INFO to WARNING
            'propagate': False
        },
        'app.database.pool': {
            'handlers': ['db_file', 'errors_file', 'session_tracking'],
            'level': 'WARNING',     # Reduced noise but keep important connection errors
            'propagate': False
        },
        'app.utils.task_monitor': {
            'handlers': ['console', 'session_tracking'],
            'level': 'WARNING',     # Reduced from INFO to WARNING
            'propagate': False
        },
        'app.request': {
            'handlers': ['requests_file'],
            'level': 'WARNING',     # Only log request problems
            'propagate': False
        },
        'app.main': {
            'handlers': ['console', 'requests_file'],
            'level': 'WARNING',     # Reduced debug output
            'propagate': False
        },
        'app.match_pages': {
            'handlers': ['requests_file'],
            'level': 'WARNING',     # Reduce RSVP checking noise
            'propagate': False
        },
        'app.availability_api_helpers': {
            'handlers': ['requests_file'],
            'level': 'WARNING',     # Reduce availability API noise
            'propagate': False
        },
        'app.sms_helpers': {
            'handlers': ['console', 'requests_file'],
            'level': 'INFO',        # Keep SMS at INFO for debugging message issues
            'propagate': False
        },
        'app.auth': {
            'handlers': ['console', 'auth_file'],
            'level': 'INFO',        # Keep auth at INFO for security monitoring
            'propagate': False
        },
        'app.core': {
            'handlers': ['console', 'requests_file'],
            'level': 'WARNING',     # Reduced from INFO to WARNING
            'propagate': False
        },
        'app.core.session_manager': {
            'handlers': ['session_tracking', 'errors_file'],
            'level': 'WARNING',     # Reduced session noise
            'propagate': False
        },
        'flask_login': {
            'handlers': ['auth_file'],
            'level': 'WARNING',     # Reduced login noise
            'propagate': False
        },
        'werkzeug': {
            'handlers': ['requests_file'],
            'level': 'ERROR',       # Further reduced HTTP noise - only errors
            'propagate': False
        },
        'app.tasks': {
            'handlers': ['console', 'session_tracking'],
            'level': 'WARNING',     # Reduced task noise
            'propagate': False
        },
        'app.lifecycle': {
            'handlers': ['console'],
            'level': 'WARNING',     # Reduce request performance logging
            'propagate': False
        },
        'app.redis_manager': {
            'handlers': ['console'],
            'level': 'WARNING',     # Reduce Redis connection noise 
            'propagate': False
        }
    },

    # The root logger catches all messages not handled by other loggers.
    'root': {
        'handlers': ['console', 'errors_file'],
        'level': 'WARNING',         # Changed from INFO to WARNING to reduce general noise
    }
}
