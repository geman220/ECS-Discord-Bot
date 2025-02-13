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
        }
    },

    # Handlers specify where log messages are sent (e.g., console, files).
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'detailed',
            'level': 'DEBUG',
        },
        'db_file': {
            'class': 'logging.FileHandler',
            'filename': 'db_operations.log',
            'formatter': 'detailed',
        },
        'requests_file': {
            'class': 'logging.FileHandler',
            'filename': 'requests.log',
            'formatter': 'detailed',
        },
        'auth_file': {
            'class': 'logging.FileHandler',
            'filename': 'auth.log',
            'formatter': 'detailed',
        }
    },

    # Loggers define logging behavior for specific modules or components.
    'loggers': {
        'sqlalchemy.engine': {
            'handlers': ['db_file', 'console'],
            'level': 'INFO',
            'propagate': False
        },
        'app.db_management': {
            'handlers': ['db_file', 'console'],
            'level': 'DEBUG',
            'propagate': False
        },
        'app.request': {
            'handlers': ['requests_file', 'console'],
            'level': 'DEBUG',
            'propagate': False
        },
        'app.main': {
            'handlers': ['console', 'requests_file'],
            'level': 'DEBUG',
            'propagate': False
        },
        'app.auth': {
            'handlers': ['console', 'auth_file'],
            'level': 'DEBUG',
            'propagate': False
        },
        'app.core': {
            'handlers': ['console', 'requests_file'],
            'level': 'DEBUG',
            'propagate': False
        },
        'flask_login': {
            'handlers': ['console', 'auth_file'],
            'level': 'DEBUG',
            'propagate': False
        },
        'werkzeug': {
            'handlers': ['console', 'requests_file'],
            'level': 'INFO',
            'propagate': False
        }
    },

    # The root logger catches all messages not handled by other loggers.
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    }
}
