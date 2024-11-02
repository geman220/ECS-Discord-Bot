import logging
import sys
from gunicorn import glogging

class GunicornLogger(glogging.Logger):
    def setup(self, cfg):
        """Configure Gunicorn logging"""
        super().setup(cfg)
        
        # Add custom formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            '%Y-%m-%d %H:%M:%S %z'
        )
        
        # Update all handlers to use our formatter
        for handler in self.error_log.handlers + self.access_log.handlers:
            handler.setFormatter(formatter)
            
        # Ensure we catch everything
        self.error_log.setLevel(logging.DEBUG)
        self.access_log.setLevel(logging.INFO)