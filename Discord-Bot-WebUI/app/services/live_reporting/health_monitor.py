# app/services/live_reporting/health_monitor.py

"""
Health Monitoring Service

Comprehensive health monitoring with alerting and metrics.
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .config import LiveReportingConfig
from .metrics import MetricsCollector

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded" 
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class ComponentHealth:
    """Health status of a component."""
    name: str
    status: HealthStatus
    last_check: datetime
    response_time_ms: float
    error_message: Optional[str] = None
    error_count: int = 0
    uptime_percentage: float = 100.0


@dataclass
class SystemHealth:
    """Overall system health."""
    overall_status: HealthStatus
    timestamp: datetime
    components: Dict[str, ComponentHealth]
    active_sessions: int = 0
    total_uptime_hours: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'overall_status': self.overall_status.value,
            'timestamp': self.timestamp.isoformat(),
            'active_sessions': self.active_sessions,
            'total_uptime_hours': self.total_uptime_hours,
            'components': {
                name: {
                    'status': comp.status.value,
                    'last_check': comp.last_check.isoformat(),
                    'response_time_ms': comp.response_time_ms,
                    'error_message': comp.error_message,
                    'error_count': comp.error_count,
                    'uptime_percentage': comp.uptime_percentage
                }
                for name, comp in self.components.items()
            }
        }


class HealthMonitor:
    """
    Comprehensive health monitoring system.
    
    Features:
    - Component health tracking
    - Performance metrics
    - Alerting thresholds
    - Historical data
    - Automated recovery suggestions
    """
    
    def __init__(self, config: LiveReportingConfig, metrics: MetricsCollector):
        self.config = config
        self.metrics = metrics
        self._component_history: Dict[str, List[ComponentHealth]] = {}
        self._system_start_time = datetime.utcnow()
        
        # Health thresholds
        self._response_time_warning = 5000  # 5 seconds
        self._response_time_critical = 15000  # 15 seconds
        self._error_rate_warning = 0.1  # 10%
        self._error_rate_critical = 0.25  # 25%
    
    async def check_component_health(self, name: str, check_func) -> ComponentHealth:
        """
        Check health of a single component.
        
        Args:
            name: Component name
            check_func: Async function that returns bool for health
            
        Returns:
            ComponentHealth status
        """
        start_time = asyncio.get_event_loop().time()
        error_message = None
        
        try:
            is_healthy = await asyncio.wait_for(check_func(), timeout=30)
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            
            # Determine status based on response time and health
            if not is_healthy:
                status = HealthStatus.UNHEALTHY
                error_message = "Health check returned False"
            elif response_time > self._response_time_critical:
                status = HealthStatus.CRITICAL
                error_message = f"Response time {response_time:.1f}ms exceeds critical threshold"
            elif response_time > self._response_time_warning:
                status = HealthStatus.DEGRADED
                error_message = f"Response time {response_time:.1f}ms exceeds warning threshold"
            else:
                status = HealthStatus.HEALTHY
            
            # Calculate error rate from history
            error_count = self._get_recent_error_count(name)
            uptime_percentage = self._calculate_uptime_percentage(name)
            
            component_health = ComponentHealth(
                name=name,
                status=status,
                last_check=datetime.utcnow(),
                response_time_ms=response_time,
                error_message=error_message,
                error_count=error_count,
                uptime_percentage=uptime_percentage
            )
            
            # Update history
            self._update_component_history(name, component_health)
            
            # Update metrics
            self.metrics.update_health_status(name, status == HealthStatus.HEALTHY)
            
            return component_health
            
        except asyncio.TimeoutError:
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            component_health = ComponentHealth(
                name=name,
                status=HealthStatus.CRITICAL,
                last_check=datetime.utcnow(),
                response_time_ms=response_time,
                error_message="Health check timed out",
                error_count=self._get_recent_error_count(name) + 1,
                uptime_percentage=self._calculate_uptime_percentage(name)
            )
            
            self._update_component_history(name, component_health)
            self.metrics.update_health_status(name, False)
            
            return component_health
            
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            component_health = ComponentHealth(
                name=name,
                status=HealthStatus.CRITICAL,
                last_check=datetime.utcnow(),
                response_time_ms=response_time,
                error_message=str(e),
                error_count=self._get_recent_error_count(name) + 1,
                uptime_percentage=self._calculate_uptime_percentage(name)
            )
            
            self._update_component_history(name, component_health)
            self.metrics.update_health_status(name, False)
            
            logger.error(f"Health check failed for {name}: {e}")
            return component_health
    
    def _update_component_history(self, name: str, health: ComponentHealth):
        """Update component health history."""
        if name not in self._component_history:
            self._component_history[name] = []
        
        self._component_history[name].append(health)
        
        # Keep only last 100 entries
        if len(self._component_history[name]) > 100:
            self._component_history[name] = self._component_history[name][-100:]
    
    def _get_recent_error_count(self, name: str) -> int:
        """Get recent error count for a component."""
        if name not in self._component_history:
            return 0
        
        # Count errors in last hour
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        recent_entries = [
            entry for entry in self._component_history[name]
            if entry.last_check > cutoff_time
        ]
        
        return sum(1 for entry in recent_entries if entry.status != HealthStatus.HEALTHY)
    
    def _calculate_uptime_percentage(self, name: str) -> float:
        """Calculate uptime percentage for a component."""
        if name not in self._component_history:
            return 100.0
        
        # Calculate uptime over last 24 hours
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        recent_entries = [
            entry for entry in self._component_history[name]
            if entry.last_check > cutoff_time
        ]
        
        if not recent_entries:
            return 100.0
        
        healthy_count = sum(1 for entry in recent_entries if entry.status == HealthStatus.HEALTHY)
        return (healthy_count / len(recent_entries)) * 100.0
    
    def determine_overall_status(self, components: Dict[str, ComponentHealth]) -> HealthStatus:
        """
        Determine overall system status based on component health.
        
        Args:
            components: Dictionary of component health statuses
            
        Returns:
            Overall system health status
        """
        if not components:
            return HealthStatus.UNHEALTHY
        
        # Count components by status
        status_counts = {status: 0 for status in HealthStatus}
        for component in components.values():
            status_counts[component.status] += 1
        
        total_components = len(components)
        
        # Determine overall status
        if status_counts[HealthStatus.CRITICAL] > 0:
            # Any critical component makes system critical
            return HealthStatus.CRITICAL
        elif status_counts[HealthStatus.UNHEALTHY] > 0:
            # Any unhealthy component makes system unhealthy
            return HealthStatus.UNHEALTHY
        elif status_counts[HealthStatus.DEGRADED] > 0:
            # Any degraded component makes system degraded
            return HealthStatus.DEGRADED
        elif status_counts[HealthStatus.HEALTHY] == total_components:
            # All components healthy
            return HealthStatus.HEALTHY
        else:
            # Unknown state
            return HealthStatus.UNHEALTHY
    
    def get_system_uptime_hours(self) -> float:
        """Get system uptime in hours."""
        uptime_delta = datetime.utcnow() - self._system_start_time
        return uptime_delta.total_seconds() / 3600
    
    def get_recovery_suggestions(self, system_health: SystemHealth) -> List[str]:
        """
        Get recovery suggestions based on system health.
        
        Args:
            system_health: Current system health status
            
        Returns:
            List of recovery suggestions
        """
        suggestions = []
        
        for name, component in system_health.components.items():
            if component.status == HealthStatus.CRITICAL:
                if "timeout" in (component.error_message or "").lower():
                    suggestions.append(f"Check network connectivity for {name}")
                    suggestions.append(f"Consider increasing timeout for {name}")
                elif "rate limit" in (component.error_message or "").lower():
                    suggestions.append(f"Reduce request rate for {name}")
                    suggestions.append(f"Implement exponential backoff for {name}")
                elif component.response_time_ms > self._response_time_critical:
                    suggestions.append(f"Investigate performance issues with {name}")
                    suggestions.append(f"Check {name} service capacity")
                else:
                    suggestions.append(f"Check {name} service configuration")
                    suggestions.append(f"Review {name} service logs")
            
            elif component.status == HealthStatus.UNHEALTHY:
                if component.error_count > 5:
                    suggestions.append(f"Restart {name} service if errors persist")
                    suggestions.append(f"Check {name} dependency health")
                
                if component.uptime_percentage < 95:
                    suggestions.append(f"Investigate frequent failures in {name}")
            
            elif component.status == HealthStatus.DEGRADED:
                if component.response_time_ms > self._response_time_warning:
                    suggestions.append(f"Monitor {name} performance trends")
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(suggestions))
    
    def should_alert(self, system_health: SystemHealth) -> bool:
        """
        Determine if an alert should be sent.
        
        Args:
            system_health: Current system health
            
        Returns:
            True if alert should be sent
        """
        # Alert on critical or unhealthy status
        if system_health.overall_status in [HealthStatus.CRITICAL, HealthStatus.UNHEALTHY]:
            return True
        
        # Alert if any component has been degraded for too long
        for component in system_health.components.values():
            if component.status == HealthStatus.DEGRADED and component.uptime_percentage < 90:
                return True
        
        return False