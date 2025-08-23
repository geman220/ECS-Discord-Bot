# app/services/live_reporting/metrics.py

"""
Metrics Collection

Industry standard metrics collection using Prometheus for observability,
monitoring, and alerting.
"""

import logging
import time
from typing import Dict, Any, Optional
from contextlib import contextmanager
from prometheus_client import (
    Counter, Histogram, Gauge, Info,
    CollectorRegistry, generate_latest,
    start_http_server
)

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Centralized metrics collection for live reporting system.
    
    Provides Prometheus metrics for:
    - Request counts and rates
    - Response times and latencies
    - Error rates and types
    - System health indicators
    - Business metrics (matches, events, etc.)
    """
    
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()
        self._setup_metrics()
    
    def _setup_metrics(self):
        """Initialize all metrics."""
        
        # System Info
        self.system_info = Info(
            'live_reporting_system_info',
            'Live reporting system information',
            registry=self.registry
        )
        
        # ESPN API Metrics
        self.espn_requests_total = Counter(
            'espn_requests_total',
            'Total ESPN API requests',
            ['endpoint'],
            registry=self.registry
        )
        
        self.espn_requests_failed = Counter(
            'espn_requests_failed_total',
            'Failed ESPN API requests',
            ['endpoint', 'error_type'],
            registry=self.registry
        )
        
        self.espn_requests_timeout = Counter(
            'espn_requests_timeout_total',
            'Timed out ESPN API requests',
            ['endpoint'],
            registry=self.registry
        )
        
        self.espn_request_duration = Histogram(
            'espn_request_duration_seconds',
            'ESPN API request duration',
            ['endpoint'],
            registry=self.registry
        )
        
        self.espn_response_status = Counter(
            'espn_response_status_total',
            'ESPN API response status codes',
            ['status'],
            registry=self.registry
        )
        
        # Discord API Metrics
        self.discord_requests_total = Counter(
            'discord_requests_total',
            'Total Discord API requests',
            ['action'],
            registry=self.registry
        )
        
        self.discord_requests_failed = Counter(
            'discord_requests_failed_total',
            'Failed Discord API requests',
            ['action', 'error_type'],
            registry=self.registry
        )
        
        self.discord_request_duration = Histogram(
            'discord_request_duration_seconds',
            'Discord API request duration',
            ['action'],
            registry=self.registry
        )
        
        self.discord_rate_limit_hits = Counter(
            'discord_rate_limit_hits_total',
            'Discord API rate limit hits',
            registry=self.registry
        )
        
        # Database Metrics
        self.database_connections_active = Gauge(
            'database_connections_active',
            'Active database connections',
            registry=self.registry
        )
        
        self.database_query_duration = Histogram(
            'database_query_duration_seconds',
            'Database query duration',
            ['operation'],
            registry=self.registry
        )
        
        self.database_queries_total = Counter(
            'database_queries_total',
            'Total database queries',
            ['operation'],
            registry=self.registry
        )
        
        self.database_queries_failed = Counter(
            'database_queries_failed_total',
            'Failed database queries',
            ['operation', 'error_type'],
            registry=self.registry
        )
        
        # Cache Metrics
        self.cache_hits = Counter(
            'cache_hits_total',
            'Cache hits',
            ['type'],
            registry=self.registry
        )
        
        self.cache_misses = Counter(
            'cache_misses_total',
            'Cache misses',
            ['type'],
            registry=self.registry
        )
        
        self.cache_operations_duration = Histogram(
            'cache_operations_duration_seconds',
            'Cache operation duration',
            ['operation', 'type'],
            registry=self.registry
        )
        
        # Circuit Breaker Metrics
        self.circuit_breaker_state = Counter(
            'circuit_breaker_state_changes_total',
            'Circuit breaker state changes',
            ['service', 'state'],
            registry=self.registry
        )
        
        self.circuit_breaker_requests_blocked = Counter(
            'circuit_breaker_requests_blocked_total',
            'Requests blocked by circuit breaker',
            ['service'],
            registry=self.registry
        )
        
        # AI Commentary Metrics
        self.ai_requests_total = Counter(
            'ai_requests_total',
            'Total AI commentary requests',
            registry=self.registry
        )
        
        self.ai_requests_failed = Counter(
            'ai_requests_failed_total',
            'Failed AI commentary requests',
            ['error_type'],
            registry=self.registry
        )
        
        self.ai_request_duration = Histogram(
            'ai_request_duration_seconds',
            'AI commentary request duration',
            registry=self.registry
        )
        
        self.ai_fallback_used = Counter(
            'ai_fallback_used_total',
            'AI commentary fallback usage',
            ['reason'],
            registry=self.registry
        )
        
        # Business Metrics
        self.matches_monitored = Gauge(
            'matches_monitored_total',
            'Currently monitored matches',
            registry=self.registry
        )
        
        self.match_events_processed = Counter(
            'match_events_processed_total',
            'Match events processed',
            ['event_type'],
            registry=self.registry
        )
        
        self.match_updates_posted = Counter(
            'match_updates_posted_total',
            'Match updates posted to Discord',
            ['update_type'],
            registry=self.registry
        )
        
        self.match_sessions_active = Gauge(
            'match_sessions_active',
            'Active live reporting sessions',
            registry=self.registry
        )
        
        self.match_sessions_errors = Counter(
            'match_sessions_errors_total',
            'Match session errors',
            ['error_type'],
            registry=self.registry
        )
        
        # System Health Metrics
        self.health_check_status = Gauge(
            'health_check_status',
            'Health check status (1=healthy, 0=unhealthy)',
            ['component'],
            registry=self.registry
        )
        
        self.uptime_seconds = Gauge(
            'uptime_seconds',
            'Service uptime in seconds',
            registry=self.registry
        )
        
        # Performance Metrics
        self.memory_usage_bytes = Gauge(
            'memory_usage_bytes',
            'Memory usage in bytes',
            registry=self.registry
        )
        
        self.cpu_usage_percent = Gauge(
            'cpu_usage_percent',
            'CPU usage percentage',
            registry=self.registry
        )
    
    @contextmanager
    def time_operation(self, metric: Histogram, labels: Dict[str, str] = None):
        """
        Context manager for timing operations.
        
        Args:
            metric: Histogram metric to record timing
            labels: Optional labels for the metric
        """
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            if labels:
                metric.labels(**labels).observe(duration)
            else:
                metric.observe(duration)
    
    def set_system_info(self, **info):
        """Set system information."""
        self.system_info.info(info)
    
    def update_health_status(self, component: str, is_healthy: bool):
        """Update health status for a component."""
        self.health_check_status.labels(component=component).set(1 if is_healthy else 0)
    
    def record_match_event(self, event_type: str):
        """Record a match event being processed."""
        self.match_events_processed.labels(event_type=event_type).inc()
    
    def record_match_update_posted(self, update_type: str):
        """Record a match update being posted."""
        self.match_updates_posted.labels(update_type=update_type).inc()
    
    def set_active_sessions(self, count: int):
        """Set the number of active sessions."""
        self.match_sessions_active.set(count)
    
    def set_monitored_matches(self, count: int):
        """Set the number of monitored matches."""
        self.matches_monitored.set(count)
    
    def record_session_error(self, error_type: str):
        """Record a session error."""
        self.match_sessions_errors.labels(error_type=error_type).inc()
    
    def get_metrics_text(self) -> str:
        """Get metrics in Prometheus text format."""
        return generate_latest(self.registry).decode('utf-8')
    
    def start_metrics_server(self, port: int = 9090) -> None:
        """Start HTTP server for metrics endpoint."""
        try:
            start_http_server(port, registry=self.registry)
            logger.info(f"Metrics server started on port {port}")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"Metrics server port {port} already in use - skipping (likely another worker)")
            else:
                logger.error(f"Failed to start metrics server: {e}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")


# Global metrics instance
_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get the global metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def setup_metrics(config) -> MetricsCollector:
    """Setup and configure metrics collection."""
    global _metrics
    _metrics = MetricsCollector()
    
    # Set system info
    _metrics.set_system_info(
        version="1.0.0",
        environment=config.log_level,
        service="live-reporting"
    )
    
    # Start metrics server if enabled
    if config.enable_metrics:
        _metrics.start_metrics_server(config.metrics_port)
    
    return _metrics