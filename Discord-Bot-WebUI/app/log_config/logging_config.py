# app/log_config/logging_config.py

"""
Logging configuration for the application.

This configuration is used to initialize Python's logging module with a
dictionary-based setup. It defines formatters, handlers, and loggers for
various parts of the application to ensure detailed and organized logging.

Uses RotatingFileHandler to automatically manage log file sizes and prevent
unlimited growth.
"""

import logging.handlers

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
            'formatter': 'simple',
            'level': 'INFO',
        },
        'db_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/db_operations.log',
            'formatter': 'detailed',
            'level': 'ERROR',       # Only log serious DB errors
            'maxBytes': 50485760,   # 50MB
            'backupCount': 3,
            'encoding': 'utf-8'
        },
        'requests_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/requests.log',
            'formatter': 'detailed',
            'level': 'ERROR',       # Only log request errors
            'maxBytes': 26214400,   # 25MB
            'backupCount': 2,
            'encoding': 'utf-8'
        },
        'auth_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/auth.log',
            'formatter': 'detailed',
            'level': 'INFO',
            'maxBytes': 10485760,   # 10MB
            'backupCount': 3,
            'encoding': 'utf-8'
        },
        'session_tracking': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/session_tracking.log',
            'formatter': 'focused',
            'level': 'ERROR',       # Only log session errors
            'maxBytes': 26214400,   # 25MB
            'backupCount': 2,
            'encoding': 'utf-8'
        },
        'errors_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/errors.log',
            'formatter': 'detailed',
            'level': 'WARNING',
            'maxBytes': 26214400,   # 25MB
            'backupCount': 3,
            'encoding': 'utf-8'
        }
    },

    # Loggers define logging behavior for specific modules or components.
    'loggers': {
        'sqlalchemy.engine': {
            'handlers': ['db_file'],
            'level': 'ERROR',       # Only log serious SQL errors
            'propagate': False
        },
        'app.db_management': {
            'handlers': ['db_file', 'errors_file'],
            'level': 'ERROR',       # Only log serious DB errors
            'propagate': False
        },
        'app.database.pool': {
            'handlers': ['db_file', 'errors_file'],
            'level': 'ERROR',       # Only log serious connection errors
            'propagate': False
        },
        'app.utils.task_monitor': {
            'handlers': ['console'],
            'level': 'ERROR',       # Only log serious task errors
            'propagate': False
        },
        'app.request': {
            'handlers': ['requests_file'],
            'level': 'ERROR',       # Only log request errors
            'propagate': False
        },
        'app.main': {
            'handlers': ['console'],
            'level': 'ERROR',       # Minimal logging
            'propagate': False
        },
        'app.match_pages': {
            'handlers': ['requests_file'],
            'level': 'ERROR',       # Only log serious errors
            'propagate': False
        },
        'app.availability_api_helpers': {
            'handlers': ['requests_file'],
            'level': 'ERROR',       # Only log serious errors
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
            'handlers': ['console'],
            'level': 'ERROR',       # Minimal logging
            'propagate': False
        },
        'app.core.session_manager': {
            'handlers': ['session_tracking', 'errors_file'],
            'level': 'ERROR',       # Only log serious session errors
            'propagate': False
        },
        'flask_login': {
            'handlers': ['auth_file'],
            'level': 'WARNING',     # Keep some login tracking
            'propagate': False
        },
        'werkzeug': {
            'handlers': ['requests_file'],
            'level': 'ERROR',       # Only HTTP errors
            'propagate': False
        },
        'app.tasks': {
            'handlers': ['console'],
            'level': 'ERROR',       # Only serious task errors
            'propagate': False
        },
        'app.lifecycle': {
            'handlers': ['console'],
            'level': 'ERROR',       # Only serious lifecycle errors
            'propagate': False
        },
        'app.redis_manager': {
            'handlers': ['console'],
            'level': 'ERROR',       # Only serious Redis errors
            'propagate': False
        }
    },

    # The root logger catches all messages not handled by other loggers.
    'root': {
        'handlers': ['console', 'errors_file'],
        'level': 'WARNING',         # Changed from INFO to WARNING to reduce general noise
    }
}
