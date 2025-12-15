# app/middleware/__init__.py

"""
Middleware Package

This package contains middleware components for the Flask application:
- api_logger: Logs API requests for analytics
"""

from .api_logger import init_api_logger

__all__ = ['init_api_logger']
