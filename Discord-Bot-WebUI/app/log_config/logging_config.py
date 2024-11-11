LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'format': '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
        },
        'simple': {
            'format': '%(asctime)s [%(levelname)s] %(message)s'
        }
    },
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
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    }
}