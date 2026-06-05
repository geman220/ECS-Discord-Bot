# app/services/live_reporting/__init__.py

"""
Live Reporting package.

IMPORTANT: The MLS/ESPN live-reporting ENGINE is
app/services/realtime_reporting_service.py (run by the realtime-live-reporting
container), NOT this package.

The modules that remain here — redis_state, live_match_queries, live_match_roles,
submit_helper — belong to the SEPARATE league/ECS-FC live socket engine
(app/sockets/live_reporting_v2.py, app/mobile_api, app/admin_panel match
operations, tasks_live_reporting_timers). They are imported directly as
submodules; this __init__ intentionally re-exports nothing to avoid import-time
coupling.

The old "industry standard async" cluster (MatchMonitoringService,
LiveReportingOrchestrator, ESPNClient, AICommentaryClient, DiscordClient,
CircuitBreaker, MetricsCollector, health_monitor, repositories, config, models)
was removed in 2026-06 as dead code — it had no callers and was superseded by
the realtime service. See reference_mls_live_reporting_active_path in memory.
"""

__version__ = '2.0.0'
