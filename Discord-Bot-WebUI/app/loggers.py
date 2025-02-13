# app/loggers.py

"""
Loggers Module

This module defines a custom Gunicorn logger by extending Gunicorn's glogging.Logger.
The custom logger configures the logging settings, including setting a uniform log
formatter and appropriate log levels for both error and access logs.
"""

import logging
from gunicorn import glogging

class GunicornLogger(glogging.Logger):
    def setup(self, cfg):
        """Configure Gunicorn logging with a custom formatter and log levels."""
        super().setup(cfg)
        
        # Add custom formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            '%Y-%m-%d %H:%M:%S %z'
        )
        
        # Update all handlers to use our formatter
        for handler in self.error_log.handlers + self.access_log.handlers:
            handler.setFormatter(formatter)
            
        # Set log levels to capture all necessary details
        self.error_log.setLevel(logging.DEBUG)
        self.access_log.setLevel(logging.INFO)