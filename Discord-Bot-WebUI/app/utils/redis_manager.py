# app/utils/redis_manager.py
from redis import Redis
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

class RedisManager:
    _instance: Optional['RedisManager'] = None
    _client: Optional[Redis] = None
    
    def __new__(cls) -> 'RedisManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Redis client with retries"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Use environment variable or default to Docker service name
                redis_host = os.getenv('REDIS_HOST', 'redis')
                redis_port = int(os.getenv('REDIS_PORT', '6379'))
                redis_db = int(os.getenv('REDIS_DB', '0'))
                
                self._client = Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    decode_responses=True,
                    health_check_interval=30
                )
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
        if self._client is None or not self._client.ping():
            self._initialize_client()
        return self._client