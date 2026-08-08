# app/log_config/filters.py

"""Reusable logging filters for LOGGING_CONFIG.

Referenced from logging_config.py via dictConfig's '()' factory syntax.
"""

import logging


class DropMessagesContaining(logging.Filter):
    """Drop records whose rendered message contains any given substring.

    Used to silence a logger's known noise lines while keeping its genuinely
    actionable records at the same level — e.g. python-socketio's Redis
    manager logs both its endless reconnect loop ("... retrying in Ns") and
    the one line that records a permanently dropped broadcast ("... giving
    up") at ERROR on the same logger; only the former is noise.
    """

    def __init__(self, substrings=()):
        super().__init__()
        self.substrings = tuple(substrings)

    def filter(self, record):
        message = record.getMessage()
        return not any(s in message for s in self.substrings)
