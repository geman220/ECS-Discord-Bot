# app/services/live_reporting/config.py

"""
Live Reporting Configuration

Industry standard configuration management using Pydantic for validation,
environment variables, and type safety.
"""

import os
from typing import Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from dataclasses import dataclass


class LiveReportingConfig(BaseSettings):
    """
    Configuration for live reporting service.
    
    Uses Pydantic BaseSettings for automatic environment variable loading,
    validation, and type conversion.
    """
    
    # Database Configuration
    database_url: str = Field(..., env="DATABASE_URL")
    database_pool_size: int = Field(default=2, env="LIVE_REPORTING_DATABASE_POOL_SIZE")  # Much smaller for V2
    database_max_overflow: int = Field(default=1, env="LIVE_REPORTING_DATABASE_MAX_OVERFLOW")  # Much smaller for V2
    database_pool_timeout: int = Field(default=30, env="DATABASE_POOL_TIMEOUT")
    
    # Redis Configuration
    redis_url: str = Field(..., env="REDIS_URL")
    redis_socket_timeout: int = Field(default=5, env="REDIS_SOCKET_TIMEOUT")
    redis_socket_connect_timeout: int = Field(default=5, env="REDIS_SOCKET_CONNECT_TIMEOUT")
    
    # ESPN API Configuration
    espn_api_base: str = Field(default="https://site.api.espn.com/apis/site/v2", env="ESPN_API_BASE")
    espn_timeout: int = Field(default=15, env="ESPN_TIMEOUT")  # Faster timeout for live sports
    espn_max_retries: int = Field(default=3, env="ESPN_MAX_RETRIES")
    espn_cache_ttl: int = Field(default=300, env="ESPN_CACHE_TTL")  # 5 minutes
    
    # Discord Configuration (compatible with legacy environment variables)
    discord_token: Optional[str] = Field(default=None)  # Will be populated by model_post_init
    discord_timeout: int = Field(default=30, env="DISCORD_TIMEOUT")
    discord_max_retries: int = Field(default=3, env="DISCORD_MAX_RETRIES")
    
    # OpenAI Configuration (compatible with legacy environment variables)
    openai_api_key: Optional[str] = Field(default=None)  # Will be populated by model_post_init
    openai_model: str = Field(default="gpt-4o-mini", env="OPENAI_MODEL")
    openai_timeout: int = Field(default=15, env="OPENAI_TIMEOUT")  # Faster AI responses
    openai_max_retries: int = Field(default=2, env="OPENAI_MAX_RETRIES")
    
    # Live Reporting Settings
    update_interval: int = Field(default=10, env="LIVE_REPORTING_UPDATE_INTERVAL")  # Base polling interval
    burst_mode_interval: int = Field(default=7, env="LIVE_REPORTING_BURST_INTERVAL")  # Ultra-fast for active matches
    max_error_count: int = Field(default=10, env="LIVE_REPORTING_MAX_ERRORS")
    session_timeout: int = Field(default=3600, env="LIVE_REPORTING_SESSION_TIMEOUT")  # 1 hour
    
    # Monitoring and Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    enable_metrics: bool = Field(default=True, env="ENABLE_METRICS")
    metrics_port: int = Field(default=9090, env="METRICS_PORT")
    
    # Feature Flags
    enable_ai_commentary: bool = Field(default=True, env="ENABLE_AI_COMMENTARY")
    enable_discord_posting: bool = Field(default=True, env="ENABLE_DISCORD_POSTING")
    enable_caching: bool = Field(default=True, env="ENABLE_CACHING")
    
    @validator('log_level')
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'log_level must be one of {valid_levels}')
        return v.upper()
    
    @validator('database_url')
    def validate_database_url(cls, v):
        if not v.startswith(('postgresql://', 'postgresql+asyncpg://')):
            raise ValueError('database_url must be a PostgreSQL URL')
        
        # Convert sync postgresql:// to async postgresql+asyncpg:// for V2 compatibility
        if v.startswith('postgresql://') and not v.startswith('postgresql+asyncpg://'):
            v = v.replace('postgresql://', 'postgresql+asyncpg://', 1)
            
        return v
    
    def model_post_init(self, __context) -> None:
        """Post-initialization to handle legacy environment variables."""
        # Manually read environment variables for fields that need legacy compatibility
        if not self.discord_token:
            self.discord_token = os.getenv('BOT_TOKEN') or os.getenv('DISCORD_TOKEN')
            
        if not self.openai_api_key:
            self.openai_api_key = os.getenv('GPT_API') or os.getenv('OPENAI_API_KEY')
    
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = False


@dataclass(frozen=True)
class MatchEventContext:
    """
    Immutable context object for match events.
    
    Provides type safety and immutability for passing match context
    between services without coupling.
    """
    match_id: str
    competition: str
    thread_id: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    venue: Optional[str] = None
    current_status: Optional[str] = None
    current_score: Optional[str] = None
    last_event_keys: Optional[list] = None


# Global configuration instance
_config: Optional[LiveReportingConfig] = None


def get_config() -> LiveReportingConfig:
    """
    Get the global configuration instance.
    
    Implements singleton pattern for configuration to avoid
    repeated environment variable parsing.
    """
    global _config
    if _config is None:
        _config = LiveReportingConfig()
    return _config


def override_config(config: LiveReportingConfig) -> None:
    """
    Override the global configuration (primarily for testing).
    
    Args:
        config: New configuration to use globally
    """
    global _config
    _config = config