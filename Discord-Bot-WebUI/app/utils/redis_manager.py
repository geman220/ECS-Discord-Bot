# app/utils/redis_manager.py

"""
Redis Manager Module

This module defines the RedisManager class, a singleton that manages the Redis client
connection. It initializes the client using configuration from environment variables,
with a retry mechanism for establishing the connection, and provides a property to
access the client, reinitializing it if needed.
"""

import logging
from redis import Redis
from typing import Optional
import os

logger = logging.getLogger(__name__)


class RedisManager:
    _instance: Optional['RedisManager'] = None
    _client: Optional[Redis] = None

    def __new__(cls) -> 'RedisManager':
        """
        Create a singleton instance of RedisManager.
        
        Returns:
            A RedisManager instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        Initialize the RedisManager.
        
        If the Redis client is not already initialized, initialize it.
        """
        if self._client is None:
            self._initialize_client()

    def _initialize_client(self):
        """
        Initialize the Redis client with retries.

        Attempts to create a Redis client using environment variables (or default values)
        and pings the server to verify connectivity. Retries up to 3 times on failure.
        """
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Retrieve Redis connection parameters from environment variables.
                redis_host = os.getenv('REDIS_HOST', 'redis')
                redis_port = int(os.getenv('REDIS_PORT', '6379'))
                redis_db = int(os.getenv('REDIS_DB', '0'))

                # Create the Redis client with connection and timeout settings.
                self._client = Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    decode_responses=True,
                    health_check_interval=30
                )
                # Test the connection by pinging the server.
                self._client.ping()
                logger.info(f"Redis connection established to {redis_host}:{redis_port}")
                break
            except Exception as e:
                retry_count += 1
                logger.error(f"Redis connection attempt {retry_count} failed: {str(e)}")
                if retry_count == max_retries:
                    raise

    @property
    def client(self) -> Redis:
        """
        Get the Redis client.

        If the client is uninitialized or the connection is not healthy, reinitialize it.

        Returns:
            A Redis client instance.
        """
        if self._client is None or not self._client.ping():
            self._initialize_client()
        return self._client