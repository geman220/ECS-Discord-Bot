# app/services/live_reporting/__init__.py

"""
Live Reporting Service

Industry standard async live reporting system with:
- Pure async architecture
- Dependency injection
- Circuit breakers and retries
- Comprehensive metrics
- Event-driven design
- Type safety
"""

from .config import LiveReportingConfig, MatchEventContext, get_config, override_config
from .repositories import MatchRepository, LiveReportingRepository, DatabaseError
from .espn_client import ESPNClient, MatchData, ESPNAPIError
from .discord_client import DiscordClient, DiscordEmbed, DiscordAPIError
from .ai_client import AICommentaryClient, AICommentaryError
from .circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerError
from .metrics import MetricsCollector, get_metrics, setup_metrics
from .match_monitor import (
    MatchEvent, MonitoringResult, MatchMonitoringService, LiveReportingOrchestrator
)

__all__ = [
    # Configuration
    'LiveReportingConfig',
    'MatchEventContext', 
    'get_config',
    'override_config',
    
    # Repositories
    'MatchRepository',
    'LiveReportingRepository',
    'DatabaseError',
    
    # Clients
    'ESPNClient',
    'MatchData',
    'ESPNAPIError',
    'DiscordClient',
    'DiscordEmbed', 
    'DiscordAPIError',
    'AICommentaryClient',
    'AICommentaryError',
    
    # Infrastructure
    'CircuitBreaker',
    'CircuitState',
    'CircuitBreakerError',
    'MetricsCollector',
    'get_metrics',
    'setup_metrics',
    
    # Core Services
    'MatchEvent',
    'MonitoringResult',
    'MatchMonitoringService',
    'LiveReportingOrchestrator',
]

# Version info
__version__ = '2.0.0'
__author__ = 'ECS Discord Bot Team'
__description__ = 'Industry standard async live reporting system'