# app/services/system_center_service.py

"""
System Command Center — read model (Phase 1: Overview + Services).

The ONE assembly point for the operations surface at /admin-panel/system. Every
value MUST trace to a REAL collector — this module imports and calls the existing
health/perf/service collectors; it never re-implements a probe and never invents a
number. If a collector is unavailable or raises, the affected panel shows an honest
degraded/down/idle state, not a fabricated 'healthy'.

Honesty tags
------------
Some real values describe only the worker/process that served this request, or are
derived rather than directly measured. Those are TAGGED so the template can render a
small honesty badge:
  * 'per-worker'  — reflects only this gunicorn worker (e.g. the in-memory query-time
                    ring buffer behind get_performance_report()), not the whole fleet.
  * 'estimated'   — derived/estimated by an `_estimate_*` helper, not measured.
  * 'stub'        — no live source wired yet (Phase 1 only tags, never fabricates).
  * 'api-only'    — covers /api/* traffic only.
Metrics are (label, value, honesty) tuples where honesty is one of the above or None.

Collector provenance (Phase 1)
------------------------------
  health components ...... system_infrastructure._check_system_health()
  cpu/mem/disk/uptime .... helpers._get_system_performance_metrics()
  query perf ............. performance.get_performance_report()      [per-worker]
  discord service ........ helpers.get_discord_bot_stats()
  discord api probe ...... helpers._check_discord_api_status()
  push service ........... helpers._check_push_service_status()
  email service .......... helpers._check_email_service_status()
  redis service .......... helpers._check_redis_service_status()
  database service ....... helpers._check_database_service_status()
  live reporting ......... realtime_bridge_service.check_realtime_health() +
                           get_coordination_status()
  docker ................. admin_helpers.get_container_data() / check_docker_health()
  failed tasks 24h ....... task_monitor.TaskMonitor().get_task_stats(86400)
  integrity conflicts .... integrity_service.cached_counts(session)
  resource thresholds .... _get_system_performance_metrics() (mem/disk/cpu)
"""

import logging
import time

logger = logging.getLogger(__name__)

# Short per-worker cache of the services board. The board fans out to ~9 probes
# (Discord HTTP, celery inspect, docker socket, redis, db, email/push auth), some
# of which are slow. Caching for a few seconds means the KPI band (rendered on
# EVERY tab), the Services tab, and a drawer open don't each re-run the full fan-out
# in quick succession — and keeps probe work off the request's DB-transaction budget
# on rapid navigation. `force=True` (the Refresh action) bypasses it.
_BOARD_TTL = 8.0
_board_cache = {'ts': 0.0, 'data': None}


# --------------------------------------------------------------------------
# tone / status normalization
# --------------------------------------------------------------------------

# Canonical service statuses: healthy | degraded | down | idle.
_STATUS_TONE = {
    'healthy': ('primary', 'Healthy'),
    'degraded': ('warning', 'Degraded'),
    'down': ('danger', 'Down'),
    'idle': ('neutral', 'Idle'),
}

# Map the many status words the underlying collectors emit onto the 4 canonical ones.
_STATUS_MAP = {
    'healthy': 'healthy',
    'ok': 'healthy',
    'running': 'healthy',
    'connected': 'healthy',
    'warning': 'degraded',
    'degraded': 'degraded',
    'unknown': 'degraded',
    'unhealthy': 'down',
    'error': 'down',
    'offline': 'down',
    'failed': 'down',
    'disabled': 'idle',
    'idle': 'idle',
    'not probed': 'idle',
}


def _canon_status(raw):
    """Normalize any collector status word to healthy|degraded|down|idle."""
    return _STATUS_MAP.get((raw or '').strip().lower(), 'degraded')


def _tone_word(status):
    tone, word = _STATUS_TONE.get(status, ('neutral', status.title() if status else 'Unknown'))
    return tone, word


def _service(key, name, icon, status, metrics, meta):
    """Build a Services-board entry with a normalized status + tone."""
    st = _canon_status(status)
    tone, word = _tone_word(st)
    return {
        'key': key, 'name': name, 'icon': icon,
        'status': st, 'status_word': word, 'tone': tone,
        'metrics': metrics or [], 'meta': meta or '',
    }


# --------------------------------------------------------------------------
# Phase 2 — action controls
# --------------------------------------------------------------------------
#
# A "control" is one actionable button/link rendered in the drawer (per-service)
# or the Overview quick-actions strip. Every control targets an EXISTING admin
# endpoint — this module never defines an action route. The dict the template/JS
# consumes:
#   label     : button text
#   endpoint  : the Flask endpoint name (for provenance/debugging)
#   url       : resolved via a SAFE url_for (None → the control is omitted)
#   method    : 'POST' | 'GET' | 'LINK' (LINK = navigate, don't fetch)
#   danger    : bool — styled red; usually paired with a confirm
#   confirm   : str | None — Swal confirmation copy shown before firing
#   body      : dict | None — JSON body for POSTs (matched to how the endpoint reads it)
#   min_role  : 'Global Admin' | None — UI gate; filtered out for non-GAs (the
#               endpoint still enforces server-side — this is defense-in-depth + honesty)
#   refresh   : bool — re-fetch + re-render the service drawer after success
#
# Body-parsing / return-shape notes (confirmed by reading each endpoint):
#   clear_cache ............ reads request.json.cache_type when is_json; returns
#                            JSON {success,message,keys_cleared}. Overview clears the
#                            safe 'reference' (ref:*) pattern — NOT 'all' (which would
#                            flushdb: wipe sessions + the Celery broker). 'all' lives
#                            only behind the GA-only redis "Flush all" (flush_redis).
#   flush_redis ............ POST, no body; returns a REDIRECT+flash (NOT JSON). The JS
#                            executor detects the non-JSON response and shows a neutral
#                            "submitted" toast. GA-only, strong confirm.
#   warm_cache ............. POST, no body; also REDIRECT+flash (non-JSON) — same handling.
#   api_restart_bot ........ POST, no body; JSON {success,message}.
#   discord_mass_sync_roles  POST, no body; JSON {success,message,task_id}.
#   discord_refresh_all_status POST, no body; JSON {success,message,...}.
#   run_db_health_check .... POST, no body; JSON {success,message,status,...}.
#   refresh_service_status . POST, no body; JSON {success,message,...}.
#   redis_test_connection .. GET, no body/CSRF; JSON {tests:{name:{status,message}}}
#                            (no top-level success — JS derives it from the checks).
#   test_twilio_config ..... GET, no body/CSRF; JSON {connection_test:{status,message}}
#                            (no top-level success — JS derives it). Does NOT send SMS.
#   mls_force_sync ......... POST, no body; JSON from force_session_sync() (has success).
# LINK-only (ambiguous/no safe whole-service action): docker_management (container_id
# is per-container, not per-service), task_monitoring_page, push_subscriptions,
# communication.

def _safe_url(endpoint, **kw):
    """url_for that returns None instead of raising when an endpoint can't resolve.
    Runs inside a request context (both callers do)."""
    from flask import url_for
    try:
        return url_for(endpoint, **kw)
    except Exception:
        logger.debug("control url unavailable: %s", endpoint, exc_info=True)
        return None


def _control(label, endpoint, method='POST', danger=False, confirm=None,
             body=None, min_role=None, refresh=False, **url_kw):
    """Build one control dict, or None if the endpoint can't resolve (→ omitted)."""
    url = _safe_url(endpoint, **url_kw)
    if url is None:
        return None
    return {
        'label': label, 'endpoint': endpoint, 'url': url, 'method': method,
        'danger': bool(danger), 'confirm': confirm, 'body': body,
        'min_role': min_role, 'refresh': bool(refresh),
    }


def _service_control_specs(key):
    """Return the raw control list for a service key (unfiltered)."""
    if key == 'discord':
        return [
            _control('Restart bot', 'admin_panel.api_restart_bot',
                     danger=True, min_role='Global Admin', refresh=True,
                     confirm='Restart the Discord bot now? It will disconnect and '
                             'reconnect, briefly interrupting slash commands and syncs.'),
            _control('Sync all roles', 'admin_panel.discord_mass_sync_roles',
                     confirm='Queue a Discord role sync for ALL players? This flags every '
                             'player for update and runs in the background.'),
            _control('Refresh all status', 'admin_panel.discord_refresh_all_status',
                     confirm='Refresh Discord status for every linked player? This makes a '
                             'bot API call per player and can take a while on a large roster.'),
        ]
    if key == 'database':
        return [
            _control('Run health check', 'admin_panel.run_db_health_check', refresh=True),
        ]
    if key == 'redis':
        return [
            _control('Test connection', 'admin_panel.redis_test_connection', method='GET'),
            _control('Warm cache', 'admin_panel.warm_cache'),
            _control('Flush all', 'admin_panel.flush_redis',
                     danger=True, min_role='Global Admin',
                     confirm='Flush the ENTIRE Redis database? This clears ALL cache, '
                             'active sessions AND queued background jobs — everyone is '
                             'logged out and pending jobs are lost. This cannot be undone.'),
        ]
    if key == 'celery':
        return [
            _control('Task monitor', 'admin_panel.task_monitoring_page', method='LINK'),
        ]
    if key == 'live_reporting':
        return [
            # mls_force_sync enforces Global Admin / Discord Admin. Of the roles that can
            # even reach this page (Global Admin, Pub League Admin), only GA qualifies —
            # so gate to GA in the UI to match enforcement (no dead 403 button for PLAs).
            _control('Force sync', 'admin_panel.mls_force_sync', min_role='Global Admin',
                     refresh=True,
                     confirm='Force a resync between the database and the realtime engine?'),
        ]
    if key == 'docker':
        # container_id is per-container, ambiguous for a whole-service card — LINK out.
        return [
            _control('Open Docker', 'admin_panel.docker_management', method='LINK'),
        ]
    if key == 'push':
        return [
            _control('Push admin', 'admin_panel.push_subscriptions', method='LINK'),
        ]
    if key == 'email':
        return [
            _control('Email & comms', 'admin_panel.communication_hub', method='LINK'),
        ]
    if key == 'twilio':
        return [
            _control('Test config', 'admin_panel.test_twilio_config',
                     method='GET', min_role='Global Admin'),
        ]
    return []


def _filter_controls(specs, is_global_admin):
    """Drop None entries and Global-Admin-only controls for non-GAs."""
    out = []
    for c in specs:
        if c is None:
            continue
        if not is_global_admin and c.get('min_role') == 'Global Admin':
            continue
        out.append(c)
    return out


def _overview_quick_actions(is_global_admin):
    """The Overview quick-actions strip — same control shape as the drawer, so ONE
    JS executor runs both. Clear cache targets the SAFE 'reference' pattern only."""
    specs = [
        _control('Clear cache', 'admin_panel.clear_cache',
                 body={'cache_type': 'reference'}),
        _control('Sync Discord roles', 'admin_panel.discord_mass_sync_roles'),
        _control('Run DB health check', 'admin_panel.run_db_health_check'),
        _control('Refresh services', 'admin_panel.refresh_service_status'),
        _control('Restart bot', 'admin_panel.api_restart_bot',
                 danger=True, min_role='Global Admin',
                 confirm='Restart the Discord bot now? It will disconnect and reconnect, '
                         'briefly interrupting slash commands and syncs.'),
    ]
    return _filter_controls(specs, is_global_admin)


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def get_system_overview(session, perf_metrics=None, is_global_admin=False):
    """Assemble the Overview tab from real collectors.

    `perf_metrics` — the already-sampled `_get_system_performance_metrics()` dict
    from the KPI band, passed through to avoid a second blocking `cpu_percent(1)`
    sample (~1s) on the same page load. If None, it is sampled here.

    `is_global_admin` — UI-gates the quick-actions strip; Global-Admin-only actions
    (e.g. Restart bot) are omitted for non-GAs. The endpoints still enforce roles
    server-side; this is defense-in-depth + honesty (don't show a button you can't use).

    Returns a dict:
      overall       : {'status','word','tone'} — the roll-up health word
      components    : [ {key,name,icon,status,status_word,tone,message} ] health-at-a-glance
      attention     : [ {severity,icon,label,detail,action_label,action_url} ]
      perf          : {'cpu','memory','disk','uptime','load','connections'}
      quick_actions : [ control ] — real, gated actions (see _control docstring)
      health_raw    : the raw _check_system_health() dict (for debugging/detail)
    """
    from app.admin_panel.routes.system_infrastructure import _check_system_health
    from app.admin_panel.routes.helpers import _get_system_performance_metrics

    # ---- overall + component health ----
    overall = {'status': 'degraded', 'word': 'Unknown', 'tone': 'neutral'}
    components = []
    try:
        health = _check_system_health()
        raw_overall = _canon_status(health.get('status'))
        # _check_system_health uses 'degraded' as its umbrella non-healthy word.
        if (health.get('status') or '').lower() == 'degraded':
            raw_overall = 'degraded'
        tone, word = _tone_word(raw_overall)
        overall = {'status': raw_overall, 'word': word, 'tone': tone}

        _comp_meta = {
            'database': ('Database', 'ti-database'),
            'redis': ('Redis', 'ti-brand-redis'),
            'celery': ('Celery Workers', 'ti-subtask'),
            'docker': ('Docker', 'ti-box'),
        }
        for ckey, cval in (health.get('components') or {}).items():
            name, icon = _comp_meta.get(ckey, (ckey.title(), 'ti-server-2'))
            st = _canon_status(cval.get('status'))
            ct, cw = _tone_word(st)
            components.append({
                'key': ckey, 'name': name, 'icon': icon,
                'status': st, 'status_word': cw, 'tone': ct,
                'message': cval.get('message') or '',
            })
    except Exception:
        logger.exception("system overview: health check failed")
        health = {}

    # ---- resource metrics ----
    perf = {'cpu': 0, 'memory': 0, 'disk': 0, 'uptime': 'Unknown',
            'load': 'Unknown', 'connections': 0}
    try:
        m = perf_metrics if perf_metrics is not None else _get_system_performance_metrics()
        perf = {
            'cpu': m.get('cpu_usage', 0),
            'memory': m.get('memory_usage', 0),
            'disk': m.get('disk_usage', 0),
            'uptime': m.get('uptime', 'Unknown'),
            'load': m.get('load_average', 'Unknown'),
            'connections': m.get('active_connections', 0),
        }
    except Exception:
        logger.exception("system overview: perf metrics failed")
        m = {}

    # ---- attention aggregation ----
    attention = _build_attention(session, perf, m)

    # ---- quick actions (Phase 2) ----
    quick_actions = []
    try:
        quick_actions = _overview_quick_actions(is_global_admin)
    except Exception:
        logger.exception("system overview: quick actions failed")

    return {
        'overall': overall,
        'components': components,
        'attention': attention,
        'perf': perf,
        'quick_actions': quick_actions,
        'health_raw': health,
    }


def _build_attention(session, perf, raw_metrics):
    """Aggregate the 'Needs your attention' feed from real signals only. Each item:
    {severity: critical|warning|notice, icon, label, detail, action_label, action_url}."""
    from flask import url_for
    items = []

    def _url(endpoint, **kw):
        try:
            return url_for(endpoint, **kw)
        except Exception:
            return None

    # 1) Failed Celery tasks in the last 24h.
    try:
        from app.utils.task_monitor import TaskMonitor
        stats = TaskMonitor().get_task_stats(time_window=86400) or {}
        failed = int(stats.get('failed') or 0)
        if failed > 0:
            items.append({
                'severity': 'warning', 'icon': 'ti-alert-triangle',
                'label': f'{failed} failed task{"s" if failed != 1 else ""} in the last 24h',
                'detail': 'Background jobs that ended in FAILURE — check the task monitor.',
                'action_label': 'Task monitor',
                'action_url': _url('admin_panel.task_monitoring_page'),
            })
    except Exception:
        logger.debug("attention: task stats unavailable", exc_info=True)

    # 2) Data-integrity conflicts. Read the CACHE ONLY (peek_counts) — never trigger
    #    the full integrity scan on this page render (it would hold a PgBouncer txn
    #    slot). On a cold cache we simply show nothing here; the integrity dashboard +
    #    its background job keep the cache primed.
    try:
        from app.services.integrity_service import peek_counts
        counts = peek_counts(session) or {}
        total = int(counts.get('total') or 0)
        high = int(counts.get('high') or 0)
        if high > 0:
            items.append({
                'severity': 'critical', 'icon': 'ti-shield-x',
                'label': f'{high} high-severity data conflict{"s" if high != 1 else ""}',
                'detail': f'{total} total open integrity conflicts across all detectors.',
                'action_label': 'Data integrity',
                'action_url': _url('admin_panel.integrity_dashboard'),
            })
        elif total > 0:
            items.append({
                'severity': 'notice', 'icon': 'ti-shield-check',
                'label': f'{total} open data conflict{"s" if total != 1 else ""}',
                'detail': 'Lower-severity integrity findings awaiting review.',
                'action_label': 'Data integrity',
                'action_url': _url('admin_panel.integrity_dashboard'),
            })
    except Exception:
        logger.debug("attention: integrity counts unavailable", exc_info=True)

    # 3) Resource threshold warnings (mem / disk / cpu). These ARE the "system alerts"
    #    — there is no separate alerts table; the retired alerts page re-derived them
    #    from these same psutil probes, so surfacing a distinct source would double-count.
    def _resource(label, pct, unit_url_endpoint):
        try:
            v = float(pct or 0)
        except (TypeError, ValueError):
            return
        if v >= 90:
            sev, verb = 'critical', 'critically high'
        elif v >= 80:
            sev, verb = 'warning', 'high'
        else:
            return
        items.append({
            'severity': sev, 'icon': 'ti-activity-heartbeat',
            'label': f'{label} usage {verb} ({v:.0f}%)',
            'detail': 'Host/container reading, sampled at page load.',
            'action_label': 'System health',
            'action_url': _url('admin_panel.system_health_consolidated'),
        })

    _resource('Memory', perf.get('memory'), None)
    _resource('Disk', perf.get('disk'), None)
    _resource('CPU', perf.get('cpu'), None)

    return items


# --------------------------------------------------------------------------
# Services board
# --------------------------------------------------------------------------

def get_services_board(session, force=False):
    """One entry per service for the Services tab. Every collector call is isolated
    so a single failing service can't 500 the page; a failed probe reads as
    down/idle with an honest message, never a fabricated 'healthy'.

    Result is cached per-worker for a few seconds (see _BOARD_TTL) so the KPI band,
    the Services tab, and drawer opens don't each re-run the full probe fan-out.
    Pass force=True to bypass the cache (the Refresh action)."""
    now = time.time()
    if not force and _board_cache['data'] is not None and (now - _board_cache['ts']) < _BOARD_TTL:
        return _board_cache['data']

    # _SERVICE_ORDER preserves the board's display order; each probe is isolated.
    board = [_SERVICE_PROBES[key]() for key in _SERVICE_ORDER]

    _board_cache['ts'] = now
    _board_cache['data'] = board
    return board


def _svc_discord():
    try:
        from app.admin_panel.routes.helpers import get_discord_bot_stats
        data = get_discord_bot_stats() or {}
        st = (data.get('stats') or {})
        # The bot API being reachable (success) means the service is up. We only
        # downgrade to Down if the API is unreachable, or to Degraded if it is
        # reachable but explicitly reports a bad status word — we do NOT require an
        # exact-word whitelist match (the bot's status vocabulary can vary).
        reachable = bool(data.get('success'))
        bot_word = str(st.get('bot_status') or '').lower()
        if not reachable:
            status = 'down'
        elif bot_word in ('offline', 'error', 'unhealthy', 'failed', 'down'):
            status = 'degraded'
        else:
            status = 'healthy'
        metrics = [
            ('Status', st.get('bot_status') or 'offline'),
            ('Guilds', st.get('guilds_connected', 0)),
            ('Commands', st.get('total_commands', 0)),
            ('Uptime', st.get('uptime') or 'Unknown'),
        ]
        meta = 'Bot API reachable' if data.get('success') else 'Bot API not reachable'
        return _service('discord', 'Discord Bot', 'ti-brand-discord', status, metrics, meta)
    except Exception:
        logger.exception("services: discord probe failed")
        return _service('discord', 'Discord Bot', 'ti-brand-discord', 'down',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_database():
    try:
        from app.admin_panel.routes.helpers import _check_database_service_status
        d = _check_database_service_status() or {}
        metrics = [
            ('Response', d.get('response_time') or 'N/A'),
            ('Detail', d.get('message') or ''),
        ]
        return _service('database', 'PostgreSQL', 'ti-database',
                        d.get('status'), metrics, d.get('message') or '')
    except Exception:
        logger.exception("services: database probe failed")
        return _service('database', 'PostgreSQL', 'ti-database', 'down',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_redis():
    try:
        from app.admin_panel.routes.helpers import _check_redis_service_status
        d = _check_redis_service_status() or {}
        metrics = [
            ('Response', d.get('response_time') or 'N/A'),
            ('Detail', d.get('message') or ''),
        ]
        return _service('redis', 'Redis', 'ti-brand-redis',
                        d.get('status'), metrics, d.get('message') or '')
    except Exception:
        logger.exception("services: redis probe failed")
        return _service('redis', 'Redis', 'ti-brand-redis', 'down',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_celery():
    """Celery worker health, via the same inspect() the health check uses."""
    try:
        from app.core import celery
        inspect = celery.control.inspect()
        stats = inspect.stats() or {}
        worker_count = len(stats)
        if worker_count > 0:
            status = 'healthy'
            meta = f'{worker_count} worker{"s" if worker_count != 1 else ""} online'
        else:
            status = 'down'
            meta = 'No workers responding'
        metrics = [
            ('Workers', worker_count),
            ('Nodes', ', '.join(list(stats.keys())[:3]) or 'none'),
        ]
        return _service('celery', 'Celery Workers', 'ti-subtask', status, metrics, meta)
    except Exception:
        logger.exception("services: celery probe failed")
        return _service('celery', 'Celery Workers', 'ti-subtask', 'down',
                        [('Status', 'probe error')], 'Could not inspect workers')


def _svc_live_reporting():
    try:
        from app.services.realtime_bridge_service import check_realtime_health, get_coordination_status
        health = check_realtime_health() or {}
        coord = get_coordination_status() or {}
        # check_realtime_health() health words: healthy|degraded|unknown|offline|error.
        status = _canon_status(health.get('health'))
        age = health.get('heartbeat_age_seconds')
        metrics = [
            ('Service', health.get('health') or 'unknown'),
            ('Running', 'yes' if health.get('is_running') else 'no'),
            ('Active sessions', coord.get('database_sessions', 0)),
            ('Heartbeat age', f'{age}s' if age is not None else 'N/A'),
        ]
        meta = 'Realtime engine ' + (health.get('health') or 'unknown')
        return _service('live_reporting', 'Live Reporting', 'ti-antenna', status, metrics, meta)
    except Exception:
        logger.exception("services: live reporting probe failed")
        return _service('live_reporting', 'Live Reporting', 'ti-antenna', 'down',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_docker():
    try:
        from app.admin_helpers import get_container_data
        containers = get_container_data()
        if containers is None:
            return _service('docker', 'Docker', 'ti-box', 'idle',
                            [('Containers', 'unavailable')],
                            'Docker not reachable from this process')
        running = sum(1 for c in containers if str(c.get('status', '')).startswith('running'))
        total = len(containers)
        # get_container_data() lists ALL containers (all=True), which includes exited
        # one-shot / migration helpers. So "running < total" does NOT mean something is
        # broken — we only flag Down when NOTHING is running. Healthy = at least one
        # running container; the running/total figure is shown for context.
        status = 'healthy' if running else ('down' if total else 'idle')
        metrics = [
            ('Running', f'{running}/{total}'),
            ('Total', total),
        ]
        return _service('docker', 'Docker', 'ti-box', status, metrics,
                        f'{running} running (of {total}, incl. stopped one-shots)')
    except Exception:
        logger.exception("services: docker probe failed")
        return _service('docker', 'Docker', 'ti-box', 'idle',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_push():
    try:
        from app.admin_panel.routes.helpers import _check_push_service_status
        d = _check_push_service_status() or {}
        metrics = [
            ('Detail', d.get('message') or ''),
            ('Response', d.get('response_time') or 'N/A'),
        ]
        return _service('push', 'Push (FCM)', 'ti-bell',
                        d.get('status'), metrics, d.get('message') or '')
    except Exception:
        logger.exception("services: push probe failed")
        return _service('push', 'Push (FCM)', 'ti-bell', 'down',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_email():
    try:
        from app.admin_panel.routes.helpers import _check_email_service_status
        d = _check_email_service_status() or {}
        metrics = [
            ('Detail', d.get('message') or ''),
            ('Response', d.get('response_time') or 'N/A'),
        ]
        return _service('email', 'Email Service', 'ti-mail',
                        d.get('status'), metrics, d.get('message') or '')
    except Exception:
        logger.exception("services: email probe failed")
        return _service('email', 'Email Service', 'ti-mail', 'down',
                        [('Status', 'probe error')], 'Probe raised an error')


def _svc_twilio():
    """Twilio is NOT probed on page load (an outbound auth call per render is wasteful
    and can hang). It reads as idle 'not probed' until an admin runs the test action."""
    return _service('twilio', 'Twilio (SMS)', 'ti-message-2', 'idle',
                    [('Status', 'not probed')],
                    'Not probed on load — run the connection test to check')


# Registry: key -> single-service probe. The board iterates in _SERVICE_ORDER;
# get_service_360() dispatches to ONE probe so opening a drawer never re-runs the
# whole fan-out.
_SERVICE_PROBES = {
    'discord': _svc_discord,
    'database': _svc_database,
    'redis': _svc_redis,
    'celery': _svc_celery,
    'live_reporting': _svc_live_reporting,
    'docker': _svc_docker,
    'push': _svc_push,
    'email': _svc_email,
    'twilio': _svc_twilio,
}
_SERVICE_ORDER = ['discord', 'database', 'redis', 'celery', 'live_reporting',
                  'docker', 'push', 'email', 'twilio']


# --------------------------------------------------------------------------
# Per-service 360 (drawer)
# --------------------------------------------------------------------------

_KNOWN_SERVICE_KEYS = set(_SERVICE_ORDER)

_RUNBOOKS = {
    'discord': ('The Discord bot runs as a separate container exposing a REST API '
                '(BOT_API_URL). If it reads as Down, the web process could not reach '
                'that API — check the bot container and BOT_TOKEN. Web→bot calls use '
                'synchronous requests; aiohttp cannot run in the gevent web worker.'),
    'database': ('PostgreSQL fronted by PgBouncer (transaction pooling, ~22 slots). '
                 'A slow response usually means transaction-budget queueing, not a raw '
                 'query problem — never hold a transaction open across HTTP/CPU work.'),
    'redis': ('Single Redis instance serving the Celery broker, result backend, Flask '
              'session store AND app cache. It is single-threaded, so avoid blocking '
              'commands (KEYS); use SCAN. OOM here degrades the whole cluster.'),
    'celery': ('Background workers (worker + beat). If no workers respond, scheduled '
               'jobs (RSVP reminders, Discord sync, MLS reporting) stop. Restart the '
               'Celery containers; concurrency is intentionally low.'),
    'live_reporting': ('The realtime engine container reports live MLS matches and '
                       'writes a heartbeat to Redis. Health is derived from that '
                       'heartbeat age; >120s degraded, >300s or absent means offline.'),
    'docker': ('Container inventory read from the Docker socket. If unavailable, this '
               'process simply cannot see the socket — it does not mean containers are '
               'down. Manage containers from the Docker page.'),
    'push': ('FCM push delivery for the mobile app. Health reflects mobile API config '
             'and registered device tokens, not a live FCM send.'),
    'email': ('Outbound email / SMS transport (Twilio, TextMagic, or SMTP). Health is a '
              'reachability/auth check of whichever transport is configured.'),
    'twilio': ('Twilio SMS. Deliberately not probed on page load to avoid an outbound '
               'auth call per render; use the connection test to verify credentials.'),
}


def get_service_360(session, key, is_global_admin=False):
    """Richer per-service detail for the drawer. Phase 2: `controls` are real actions
    that POST/GET to existing endpoints (see `_control`). `is_global_admin` UI-gates
    Global-Admin-only controls (endpoints still enforce server-side). `recent` is
    included only when cheaply available."""
    if key not in _KNOWN_SERVICE_KEYS:
        return None

    # Run ONLY the requested service's probe (not the whole board) so opening a
    # drawer can't trigger the full multi-second fan-out.
    entry = None
    try:
        entry = _SERVICE_PROBES[key]()
    except Exception:
        logger.exception("service 360: probe failed for %s", key)

    metrics = []
    honesty = []  # parallel list is awkward; instead metrics are dicts below

    def _m(label, value, tag=None):
        return {'label': label, 'value': value, 'honesty': tag}

    detail_metrics = []
    if entry:
        for lbl, val in entry.get('metrics', []):
            detail_metrics.append(_m(lbl, val))

    recent = []

    # Database: attach per-worker query performance from get_performance_report().
    if key == 'database':
        try:
            from app.admin_panel.performance import get_performance_report
            rep = get_performance_report() or {}
            dbs = rep.get('database') or {}
            detail_metrics.append(_m('Avg query',
                                     f"{(dbs.get('avg_query_time') or 0) * 1000:.1f}ms",
                                     'per-worker'))
            detail_metrics.append(_m('Max query',
                                     f"{(dbs.get('max_query_time') or 0) * 1000:.1f}ms",
                                     'per-worker'))
            detail_metrics.append(_m('Slow queries', dbs.get('slow_queries', 0), 'per-worker'))
            detail_metrics.append(_m('Sampled queries', dbs.get('total_queries', 0), 'per-worker'))
            for rec in (rep.get('recommendations') or [])[:5]:
                recent.append(rec)
        except Exception:
            logger.debug("service 360: db perf report unavailable", exc_info=True)

    # Discord: attach a few recent bot log lines if the bot API returned them.
    if key == 'discord':
        try:
            from app.admin_panel.routes.helpers import get_discord_bot_stats
            data = get_discord_bot_stats() or {}
            for line in (data.get('recent_logs') or [])[:5]:
                if isinstance(line, dict):
                    recent.append(line.get('message') or str(line))
                else:
                    recent.append(str(line))
        except Exception:
            logger.debug("service 360: discord logs unavailable", exc_info=True)

    # controls (Phase 2): real actions, GA-gated for honesty + defense-in-depth.
    try:
        controls = _filter_controls(_service_control_specs(key), is_global_admin)
    except Exception:
        logger.exception("service 360: control assembly failed for %s", key)
        controls = []

    return {
        'key': key,
        'name': entry['name'] if entry else key.title(),
        'icon': entry['icon'] if entry else 'ti-server-2',
        'status': entry['status'] if entry else 'idle',
        'status_word': entry['status_word'] if entry else 'Unknown',
        'tone': entry['tone'] if entry else 'neutral',
        'metrics': detail_metrics,
        'runbook': _RUNBOOKS.get(key, ''),
        'controls': controls,
        'recent': recent,
    }


# --------------------------------------------------------------------------
# Phase 3a — Performance tab
# --------------------------------------------------------------------------
#
# Every panel here traces to a REAL collector (imported + called, never
# reimplemented). Panels that COULD only be filled by a fabricated/estimated
# collector are OMITTED and replaced with an honest empty state in the template.
#
#   resources ...... helpers._get_system_performance_metrics()   [host, sampled at load]
#   query_perf ..... performance.get_performance_report().database  [per-worker ring buffer]
#   db_conn ........ monitoring._get_database_connection_stats()  [pg_stat_activity + pool]
#   redis .......... redis_manager.get_redis_manager().client.info()  [live INFO]
#   celery ......... celery.control.inspect() active/reserved/stats  [live broadcast]
#   requests ....... monitoring._get_request_analytics()          [APIRequestLog, api-only]
#
# OMITTED (audit-flagged as fabricated/estimated — never surfaced here):
#   _get_slow_queries, _get_database_activity, _get_query_statistics,
#   _estimate_queries_per_second, _estimate_avg_query_time.
# Slow queries render an honest "pg_stat_statements not enabled" empty state.


def _m(label, value, tag=None):
    """One display metric: label, value, optional honesty tag ('per-worker'/'api-only'/…)."""
    return {'label': label, 'value': value, 'honesty': tag}


def _fmt_ms_from_seconds(v):
    """Seconds (float) -> 'NN.Nms' string; tolerant of None/garbage."""
    try:
        return f"{float(v or 0) * 1000:.1f}ms"
    except (TypeError, ValueError):
        return '—'


def _fmt_duration_seconds(secs):
    """Whole seconds -> compact 'Xd Yh', 'Xh Ym', 'Xm Ys' or 'Xs'. None -> '—'."""
    try:
        s = int(float(secs))
    except (TypeError, ValueError):
        return '—'
    if s < 0:
        return '—'
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    mnt, sec = divmod(rem, 60)
    if d:
        return f'{d}d {h}h'
    if h:
        return f'{h}h {mnt}m'
    if mnt:
        return f'{mnt}m {sec}s'
    return f'{sec}s'


def _meter_tone(pct):
    """Threshold tone for a 0-100 gauge: >=90 danger, >=80 warning, else success."""
    try:
        v = float(pct or 0)
    except (TypeError, ValueError):
        return 'neutral'
    if v >= 90:
        return 'danger'
    if v >= 80:
        return 'warning'
    return 'success'


def get_performance_tab(session, perf_metrics=None):
    """Assemble the Performance tab from real collectors only.

    `perf_metrics` — the already-sampled `_get_system_performance_metrics()` dict from
    the KPI band, passed through to avoid a SECOND blocking `cpu_percent(interval=1)`
    (~1s) sample on the same page load. If None, it is sampled here.

    Every collector is isolated in its own try/except: a single failing source
    yields that panel's `None`/degraded value (the template shows an honest empty
    state), never a fabricated number and never a 500. Honesty tags:
      * query_perf ...... 'per-worker' (in-memory ring buffer of the serving worker)
      * db_conn pool .... 'per-worker' (this process's SQLAlchemy engine pool)
      * requests ........ 'api-only'  (APIRequestLog records only /api/* traffic)
      * resources ....... host metrics sampled at page load (no per-worker badge —
                          they describe the whole container, not one worker)
    """
    out = {
        'resources': None,     # host gauges (cpu/mem/disk) + load/uptime/connections
        'gauges': [],          # [(label, pct, tone)] for meter bars
        'query_perf': None,    # per-worker query-time metrics
        'db_conn': None,       # pg_stat_activity + engine pool
        'redis': None,         # live redis INFO
        'celery': None,        # live inspect() active/reserved/workers
        'requests': None,      # api-only request analytics
        'slow_queries': None,  # intentionally never populated — honest empty state
    }

    # ---- resource gauges (host, sampled at load) ----
    try:
        from app.admin_panel.routes.helpers import _get_system_performance_metrics
        m = perf_metrics if perf_metrics is not None else (_get_system_performance_metrics() or {})
        cpu = m.get('cpu_usage', 0)
        mem = m.get('memory_usage', 0)
        disk = m.get('disk_usage', 0)
        out['resources'] = {
            'cpu': cpu, 'memory': mem, 'disk': disk,
            'uptime': m.get('uptime', 'Unknown'),
            'load': m.get('load_average', 'Unknown'),
            'connections': m.get('active_connections', 0),
        }
        out['gauges'] = [
            ('CPU', cpu, _meter_tone(cpu), 'ti-cpu'),
            ('Memory', mem, _meter_tone(mem), 'ti-ram'),
            ('Disk', disk, _meter_tone(disk), 'ti-database'),
        ]
    except Exception:
        logger.exception("performance tab: resource metrics failed")

    # ---- query performance (per-worker in-memory ring buffer) ----
    try:
        from app.admin_panel.performance import get_performance_report
        rep = get_performance_report() or {}
        dbs = rep.get('database') or {}
        out['query_perf'] = [
            _m('Avg query time', _fmt_ms_from_seconds(dbs.get('avg_query_time')), 'per-worker'),
            _m('Max query time', _fmt_ms_from_seconds(dbs.get('max_query_time')), 'per-worker'),
            _m('Min query time', _fmt_ms_from_seconds(dbs.get('min_query_time')), 'per-worker'),
            _m('Slow queries (>1s)', dbs.get('slow_queries', 0), 'per-worker'),
            _m('Sampled queries', dbs.get('total_queries', 0), 'per-worker'),
        ]
    except Exception:
        logger.exception("performance tab: query perf report failed")

    # ---- DB connections & pool (real pg_stat_activity + engine pool) ----
    # Read the SQLAlchemy engine pool DIRECTLY (no DB query, genuinely per-worker) plus
    # ONE cheap round-trip for cluster-wide active/max connections. We deliberately do
    # NOT call monitoring._get_database_connection_stats(): it eagerly runs two discarded
    # estimate queries (incl. a COUNT(*) FROM users) that would waste the request's
    # PgBouncer transaction budget — and whose values are audit-flagged fabrications.
    try:
        from app import db as _db
        from sqlalchemy import text as _text
        db_conn = []
        # cluster-wide, one query
        try:
            row = session.execute(_text(
                "SELECT count(*) AS active, "
                "(SELECT setting::int FROM pg_settings WHERE name='max_connections') AS maxc "
                "FROM pg_stat_activity")).first()
            if row is not None:
                db_conn.append(_m('Active connections (cluster)', f'{row.active} / {row.maxc}'))
        except Exception:
            logger.debug("performance tab: pg_stat_activity count failed", exc_info=True)
        # this worker's engine pool — no query; per-worker
        try:
            pool = _db.engine.pool
            if hasattr(pool, 'checkedout'):
                db_conn.append(_m('Pool checked out', pool.checkedout(), 'per-worker'))
                db_conn.append(_m('Pool checked in', pool.checkedin(), 'per-worker'))
            if hasattr(pool, 'overflow'):
                db_conn.append(_m('Pool overflow', pool.overflow(), 'per-worker'))
            if hasattr(pool, 'size'):
                db_conn.append(_m('Pool size', pool.size(), 'per-worker'))
        except Exception:
            logger.debug("performance tab: engine pool read failed", exc_info=True)
        out['db_conn'] = db_conn or None
    except Exception:
        logger.exception("performance tab: db connection stats failed")

    # ---- Redis (live INFO — same call the Cache & Redis page uses) ----
    try:
        from app.utils.redis_manager import get_redis_manager
        info = get_redis_manager().client.info() or {}
        hits = int(info.get('keyspace_hits', 0) or 0)
        misses = int(info.get('keyspace_misses', 0) or 0)
        total_req = hits + misses
        hit_rate = f'{(hits / total_req * 100):.1f}%' if total_req > 0 else 'N/A'
        used = int(info.get('used_memory', 0) or 0)
        maxmem = int(info.get('maxmemory', 0) or 0)
        db0 = info.get('db0') if isinstance(info.get('db0'), dict) else {}
        out['redis'] = {
            'metrics': [
                _m('Memory used', f'{used / (1024 * 1024):.1f} MB'),
                _m('Max memory', (f'{maxmem / (1024 * 1024):.1f} MB' if maxmem else 'unbounded')),
                _m('Hit rate', hit_rate),
                _m('Connected clients', info.get('connected_clients', 0)),
                _m('Ops/sec', info.get('instantaneous_ops_per_sec', 0)),
                _m('Total commands', info.get('total_commands_processed', 0)),
                _m('Keys (db0)', (db0 or {}).get('keys', 0)),
                _m('Uptime', _fmt_duration_seconds(info.get('uptime_in_seconds'))),
                _m('Version', info.get('redis_version', 'Unknown')),
            ],
            # memory pressure gauge when maxmemory is configured
            'mem_pct': (round(used / maxmem * 100, 1) if maxmem else None),
        }
    except Exception:
        logger.exception("performance tab: redis info failed")

    # ---- Celery (live inspect broadcast) ----
    try:
        from app.core import celery
        inspect = celery.control.inspect()
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        stats = inspect.stats() or {}
        active_n = sum(len(v or []) for v in active.values())
        reserved_n = sum(len(v or []) for v in reserved.values())
        out['celery'] = [
            _m('Workers online', len(stats)),
            _m('Active tasks', active_n),
            _m('Reserved (prefetched)', reserved_n),
            _m('Nodes', ', '.join(list(stats.keys())[:3]) or 'none'),
        ]
    except Exception:
        logger.exception("performance tab: celery inspect failed")

    # ---- Request analytics (APIRequestLog — api-only) ----
    try:
        from app.admin_panel.routes.monitoring import _get_request_analytics
        ra = _get_request_analytics() or {}
        out['requests'] = {
            'metrics': [
                _m('Avg response time', f"{ra.get('response_time_avg', 0)}ms", 'api-only'),
                _m('P50', f"{ra.get('p50', 0)}ms", 'api-only'),
                _m('P95', f"{ra.get('p95', 0)}ms", 'api-only'),
                _m('Peak', f"{ra.get('peak', 0)}ms", 'api-only'),
                _m('Requests / min', ra.get('requests_per_minute', 0), 'api-only'),
                _m('Error rate', f"{ra.get('error_rate_percent', 0)}%", 'api-only'),
                _m('Errors (24h)', ra.get('error_count_24h', 0), 'api-only'),
                _m('Total requests (24h)', ra.get('total_requests_24h', 0), 'api-only'),
            ],
            'error_rate': ra.get('error_rate_percent', 0),
            'top_endpoints': [
                {'path': e.get('path', ''),
                 'requests': e.get('requests', 0),
                 'avg_time': e.get('avg_time', 0)}
                for e in (ra.get('top_endpoints') or [])[:8]
            ],
        }
    except Exception:
        logger.exception("performance tab: request analytics failed")

    return out


# --------------------------------------------------------------------------
# Phase 3a — Jobs & Queues tab
# --------------------------------------------------------------------------
#
#   stats ...... task_monitor.TaskMonitor().get_task_stats(86400)  [Redis-backed]
#   active ..... celery.control.inspect().active()                 [live broadcast]
#   recent ..... api_logs.TaskExecution                            [persisted history]
#
# Honesty notes:
#   * get_task_stats() returns total/running/completed/failed/pending/by_name.
#     There is NO 'zombies' and NO 'retries' in that shape, so neither is shown
#     (zombie detection is a separate expensive SCAN we do NOT trigger on render;
#     the hardcoded-0 'retries' stub is simply omitted rather than faked).
#   * TaskExecution columns are `name` (not task_name), status, started_at,
#     duration_ms, worker, result, error — humanized for display, raw kept in title.


def get_jobs_tab(session):
    """Assemble the Jobs & Queues tab from real collectors only. Each source is
    isolated; a failure yields an empty/degraded panel, never a fabricated row."""
    from app.utils.humanize import humanize_identifier

    out = {
        'stats': None,     # headline counters (running/queued/completed/failed)
        'active': [],      # live in-flight tasks (inspect().active())
        'recent': [],      # recent executions (TaskExecution)
        'recent_error': False,
    }

    # ---- headline stats (24h window) ----
    try:
        from app.utils.task_monitor import TaskMonitor
        s = TaskMonitor().get_task_stats(time_window=86400) or {}
        out['stats'] = {
            'running': int(s.get('running') or 0),
            'queued': int(s.get('pending') or 0),
            'completed': int(s.get('completed') or 0),
            'failed': int(s.get('failed') or 0),
            'total': int(s.get('total') or 0),
        }
    except Exception:
        logger.exception("jobs tab: task stats failed")

    # ---- active tasks (live) ----
    try:
        import time as _time
        from app.core import celery
        active = celery.control.inspect().active() or {}
        now = _time.time()
        rows = []
        for worker, tasks in active.items():
            for t in (tasks or []):
                raw = t.get('name') or 'unknown'
                started = t.get('time_start')
                try:
                    runtime = _fmt_duration_seconds(now - float(started)) if started else '—'
                except (TypeError, ValueError):
                    runtime = '—'
                rows.append({
                    'worker': worker,
                    'name_raw': raw,
                    'name': humanize_identifier(raw.rsplit('.', 1)[-1]),
                    'id': t.get('id') or '',
                    'runtime': runtime,
                })
        out['active'] = rows
    except Exception:
        logger.exception("jobs tab: active tasks inspect failed")

    # ---- recent executions (persisted history) ----
    try:
        from app.models.api_logs import TaskExecution
        rows = (session.query(TaskExecution)
                .order_by(TaskExecution.created_at.desc())
                .limit(30).all())
        recent = []
        for r in rows:
            status = (r.status or 'completed').lower()
            failed = status == 'failed'
            recent.append({
                'id': r.id,
                'name_raw': r.name or 'unknown',
                'name': humanize_identifier((r.name or 'unknown').rsplit('.', 1)[-1]),
                'status': status,
                'failed': failed,
                'tone': 'danger' if failed else 'success',
                'started_at': (r.started_at.strftime('%Y-%m-%d %H:%M:%S')
                               if r.started_at else '—'),
                'duration': (f'{r.duration_ms:.0f}ms' if r.duration_ms is not None else '—'),
                'worker': r.worker or '—',
                # captured error/traceback (failed) or short result summary (ok)
                'error': (r.error or '') if failed else '',
                'result': (r.result or '') if not failed else '',
            })
        out['recent'] = recent
    except Exception:
        logger.exception("jobs tab: recent executions query failed")
        out['recent_error'] = True

    return out


# --------------------------------------------------------------------------
# Phase 3b — Data & Cache tab
# --------------------------------------------------------------------------
#
# Every panel traces to a REAL collector (imported + called, never reimplemented):
#   db_info ....... monitoring._get_database_info()          [pg version/size/tables/uptime]
#   db_health ..... monitoring._perform_database_health_check()  [live connect/query/table probe]
#   redis ......... redis_manager.get_redis_manager().client.info()  [live INFO]
#   draft_cache ... draft_cache_service.DraftCacheService.get_cache_stats()  [SCAN counts]
#   integrity ..... integrity_service.peek_counts(session)   [CACHE-ONLY read; never scans]
#
# The integrity panel reads ONLY the cached {total, high} via peek_counts — it must
# NEVER trigger run_all_checks()/cached_counts() on a page render (that holds a
# PgBouncer transaction slot). On a cold cache it links to the integrity dashboard.
#
# Actions (real endpoints, gated + confirmed by reading each route):
#   clear_cache ......... POST json {"cache_type":"reference"} → clears ref:* only.
#   warm_cache .......... POST no body → redirect+flash (non-JSON; executor toasts neutral).
#   run_db_health_check . POST no body → JSON {success,...}; reloads the (server-rendered) tab.
#   flush_redis ......... POST no body → redirect+flash; GA-only, strong confirm (flushdb).


def _data_tab_actions(is_global_admin):
    """Real Data & Cache actions, same control shape as the Overview strip so the ONE
    sys-run executor runs them. Clear cache targets the SAFE 'reference' (ref:*) pattern
    only — never sessions or the broker; that (flushdb) lives behind the GA-only flush."""
    specs = [
        _control('Clear reference cache', 'admin_panel.clear_cache',
                 body={'cache_type': 'reference'}),
        _control('Warm cache', 'admin_panel.warm_cache'),
        _control('Run DB health check', 'admin_panel.run_db_health_check'),
        _control('Flush all Redis', 'admin_panel.flush_redis',
                 danger=True, min_role='Global Admin',
                 confirm='Flush the ENTIRE Redis database? This clears ALL cache, active '
                         'sessions AND queued background jobs — everyone is logged out and '
                         'pending jobs are lost. This cannot be undone.'),
    ]
    out = _filter_controls(specs, is_global_admin)
    # The health check returns JSON but the panels it feeds are server-rendered, so
    # mark it to trigger a full page reload after success (the executor honors `reload`).
    for c in out:
        if c['endpoint'] == 'admin_panel.run_db_health_check':
            c['reload'] = True
    return out


def get_data_tab(session, is_global_admin=False):
    """Assemble the Data & Cache tab from real collectors only. Each source is isolated
    in its own try/except: a failing collector yields that panel's honest empty/degraded
    state, never a fabricated number and never a 500."""
    out = {
        'db_info': None,        # pg version / size / table count / uptime
        'db_health': None,      # live connect/query/table probe (list of checks)
        'redis': None,          # live INFO metrics + memory gauge
        'draft_cache': None,    # DraftCacheService SCAN counts
        'integrity': None,      # cached {total, high} or None (cold cache)
        'integrity_url': None,  # link to the real per-conflict resolve UI
        'actions': [],
    }

    # ---- database info (real: pg version/size/tables/uptime) ----
    try:
        from app.admin_panel.routes.monitoring import _get_database_info
        info = _get_database_info() or {}
        out['db_info'] = [
            _m('Engine', info.get('type', 'Unknown')),
            _m('Version', info.get('version', 'Unknown')),
            _m('Database size', info.get('size', 'Unknown')),
            _m('Tables', info.get('table_count', 0)),
            _m('Server uptime', info.get('uptime', 'Unknown')),
        ]
    except Exception:
        logger.exception("data tab: database info failed")

    # ---- database health check (real live probe) ----
    try:
        from app.admin_panel.routes.monitoring import _perform_database_health_check
        h = _perform_database_health_check() or {}
        last = h.get('last_run')
        out['db_health'] = {
            'checks': [
                {'label': 'Connection', 'ok': bool(h.get('connection'))},
                {'label': 'Query test', 'ok': bool(h.get('query_test'))},
                {'label': 'Table check', 'ok': bool(h.get('table_check'))},
                {'label': 'Performance (<1s)', 'ok': bool(h.get('performance'))},
            ],
            'query_time': h.get('query_time') or 'N/A',
            'last_run': (last.strftime('%Y-%m-%d %H:%M:%S UTC')
                         if hasattr(last, 'strftime') else '—'),
            'healthy': bool(h.get('connection') and h.get('query_test') and h.get('table_check')),
        }
    except Exception:
        logger.exception("data tab: database health check failed")

    # ---- Redis (live INFO — same call the Cache & Redis page uses) ----
    try:
        from app.utils.redis_manager import get_redis_manager
        info = get_redis_manager().client.info() or {}
        hits = int(info.get('keyspace_hits', 0) or 0)
        misses = int(info.get('keyspace_misses', 0) or 0)
        total_req = hits + misses
        hit_rate = f'{(hits / total_req * 100):.1f}%' if total_req > 0 else 'N/A'
        used = int(info.get('used_memory', 0) or 0)
        maxmem = int(info.get('maxmemory', 0) or 0)
        # Total keys = sum of keys across every db* keyspace block (matches the
        # Cache & Redis page's db0 read, generalized to all logical dbs).
        total_keys = 0
        for k, v in info.items():
            if isinstance(k, str) and k.startswith('db') and isinstance(v, dict):
                total_keys += int(v.get('keys', 0) or 0)
        out['redis'] = {
            'metrics': [
                _m('Memory used', f'{used / (1024 * 1024):.1f} MB'),
                _m('Max memory', (f'{maxmem / (1024 * 1024):.1f} MB' if maxmem else 'unbounded')),
                _m('Total keys', total_keys),
                _m('Hit rate', hit_rate),
                _m('Connected clients', info.get('connected_clients', 0)),
                _m('Ops/sec', info.get('instantaneous_ops_per_sec', 0)),
                _m('Total commands', info.get('total_commands_processed', 0)),
                _m('Uptime', _fmt_duration_seconds(info.get('uptime_in_seconds'))),
                _m('Version', info.get('redis_version', 'Unknown')),
            ],
            'mem_pct': (round(used / maxmem * 100, 1) if maxmem else None),
        }
    except Exception:
        logger.exception("data tab: redis info failed")

    # ---- draft cache (DraftCacheService SCAN counts) ----
    try:
        from app.draft_cache_service import DraftCacheService
        stats = DraftCacheService.get_cache_stats() or {}
        keys = stats.get('draft_cache_keys') or {}
        cb = stats.get('circuit_breaker') or {}
        out['draft_cache'] = {
            'available': bool(stats.get('redis_available')),
            'active_drafts': len(stats.get('active_drafts') or []),
            'circuit_state': cb.get('state', 'unknown'),
            'circuit_failures': cb.get('failures', 0),
            'connection_error': bool(stats.get('connection_error')),
            'keys': [
                {'label': 'Player data', 'value': keys.get('players', 0)},
                {'label': 'Analytics', 'value': keys.get('analytics', 0)},
                {'label': 'Team data', 'value': keys.get('teams', 0)},
                {'label': 'Availability', 'value': keys.get('availability', 0)},
            ],
        }
    except Exception:
        logger.exception("data tab: draft cache stats failed")

    # ---- data integrity (CACHE-ONLY peek — never scans on render) ----
    try:
        from app.services.integrity_service import peek_counts
        counts = peek_counts(session)
        if counts is not None:
            out['integrity'] = {
                'total': int(counts.get('total') or 0),
                'high': int(counts.get('high') or 0),
            }
    except Exception:
        logger.debug("data tab: integrity peek failed", exc_info=True)
    out['integrity_url'] = _safe_url('admin_panel.integrity_dashboard')

    # ---- actions ----
    try:
        out['actions'] = _data_tab_actions(is_global_admin)
    except Exception:
        logger.exception("data tab: action assembly failed")

    return out


# --------------------------------------------------------------------------
# Phase 3b — Security tab
# --------------------------------------------------------------------------
#
#   bans .......... security.IPBan.get_active_bans()            [real table]
#   events ........ security.SecurityEvent.get_recent_events()  [real table]
#   rate_stats .... current_app.security_middleware.get_stats() [PER-WORKER in-memory]
#   monitored ..... current_app.security_middleware.get_monitored_ips()  [PER-WORKER]
#   features ...... DERIVED from real state (config reads + PROBED hook registration)
#
# Honesty: rate-limiter counters + monitored IPs live in this worker's process memory,
# so EVERY such value carries the per-worker badge — never presented as a fleet total.
#
# Feature flags are NOT hardcoded True (the retired security_dashboard hardcoded
# rate_limiting/security_headers — audit #11). Instead:
#   * rate_limiting  — middleware exists, has a rate_limiter, AND its security_check is
#                      actually registered as a before_request hook (probed).
#   * security_headers — the middleware's security_response is actually registered as an
#                      after_request hook (probed) — the real header-setter.
#   * csrf_protection  — WTF_CSRF_ENABLED (config read).
#   * session_security — SESSION_COOKIE_SECURE (config read).
#   * auto_ban         — SECURITY_AUTO_BAN_ENABLED (config read).
#   * attack_detection — middleware presence.
#
# Actions (confirmed by reading each route):
#   security_unban_ip ......... POST json {"ip_address": ip}  → per-row Unban (GA-only route).
#   security_clear_rate_limit . POST json {"ip_address": ip}  → per-monitored-IP clear (GA-only).
#   security_clear_all_bans ... POST no body → JSON; GA-only, danger + confirm.
# Adding a NEW ban needs a text field the sys-run executor can't supply, so we LINK to
# the full security dashboard for that rather than fake an inline form.


_SEV_TONE = {
    'critical': 'danger',
    'high': 'danger',
    'medium': 'warning',
    'low': 'neutral',
}


def get_security_tab(session, is_global_admin=False):
    """Assemble the Security tab from real collectors only. Bans/events come from real
    tables; rate-limiter counters are this worker's in-memory state (per-worker badge).
    Feature flags are derived from real config + probed hook registration, never faked."""
    from app.utils.humanize import humanize_identifier

    out = {
        'bans': [], 'bans_error': False,
        'events': [], 'events_error': False,
        'rate_stats': None,     # per-worker counters (or None if no middleware)
        'monitored': [],        # per-worker monitored IPs
        'features': [],
        'unban': None,          # per-row Unban control template (url/method)
        'clear_rl': None,       # per-row Clear-rate-limit control template
        'clear_all': None,      # GA-only Clear-all-bans control
        'dashboard_url': None,  # LINK to the full security dashboard (add-ban lives there)
    }

    # ---- active IP bans (real table) ----
    try:
        from app.models.security import IPBan
        for b in (IPBan.get_active_bans() or []):
            out['bans'].append({
                'ip': b.ip_address,
                'reason': b.reason or '—',
                'banned_by': b.banned_by or '—',
                'banned_at': (b.banned_at.strftime('%Y-%m-%d %H:%M') if b.banned_at else '—'),
                'expires': ('Permanent' if b.expires_at is None
                            else b.expires_at.strftime('%Y-%m-%d %H:%M')),
                'permanent': b.expires_at is None,
            })
    except Exception:
        logger.exception("security tab: active bans query failed")
        out['bans_error'] = True

    # ---- recent security events (real table) ----
    try:
        from app.models.security import SecurityEvent
        for e in (SecurityEvent.get_recent_events(limit=50, hours=24) or []):
            sev = (e.severity or 'medium').lower()
            out['events'].append({
                'type_raw': e.event_type or 'unknown',
                'type': humanize_identifier(e.event_type or 'unknown'),
                'ip': e.ip_address or '—',
                'severity': sev,
                'tone': _SEV_TONE.get(sev, 'neutral'),
                'description': e.description or '—',
                'created_at': (e.created_at.strftime('%Y-%m-%d %H:%M:%S') if e.created_at else '—'),
            })
    except Exception:
        logger.exception("security tab: recent events query failed")
        out['events_error'] = True

    # ---- rate-limiter counters + monitored IPs (PER-WORKER in-memory) ----
    try:
        from flask import current_app
        mw = getattr(current_app, 'security_middleware', None)
        if mw is not None and hasattr(mw, 'get_stats'):
            s = mw.get_stats() or {}
            out['rate_stats'] = {
                'monitored_ips': s.get('total_monitored_ips', 0),
                'attack_attempts': s.get('total_attack_attempts', 0),
                'unique_attackers': s.get('unique_attackers', 0),
                'blacklisted_ips': s.get('total_blacklisted_ips', 0),
            }
            try:
                for row in (mw.get_monitored_ips() or [])[:15]:
                    out['monitored'].append({
                        'ip': row.get('ip', '—'),
                        'requests_last_hour': row.get('requests_last_hour', 0),
                        'attack_attempts': row.get('attack_attempts', 0),
                        'blacklisted': bool(row.get('is_blacklisted')),
                    })
            except Exception:
                logger.debug("security tab: monitored IPs unavailable", exc_info=True)
    except Exception:
        logger.exception("security tab: rate-limiter stats failed")

    # ---- security feature flags (DERIVED — never hardcoded True) ----
    try:
        from flask import current_app
        mw = getattr(current_app, 'security_middleware', None)
        before_funcs = current_app.before_request_funcs.get(None, []) or []
        after_funcs = current_app.after_request_funcs.get(None, []) or []
        has_mw = mw is not None
        has_rl = has_mw and hasattr(mw, 'rate_limiter')
        # Probe the ACTUAL registered hooks (bound methods compare equal), so these are
        # real signals that the enforcement/header code is installed — not a fixed True.
        rl_installed = bool(has_rl and getattr(mw, 'security_check', None) in before_funcs)
        hdr_installed = bool(has_mw and getattr(mw, 'security_response', None) in after_funcs)
        cfg = current_app.config
        out['features'] = [
            {'label': 'Rate limiting', 'on': rl_installed, 'honesty': None,
             'detail': 'Attack/rate check registered as a before_request hook'},
            {'label': 'Security headers', 'on': hdr_installed, 'honesty': None,
             'detail': 'Header-setting after_request hook installed'},
            {'label': 'CSRF protection', 'on': bool(cfg.get('WTF_CSRF_ENABLED', False)),
             'honesty': None, 'detail': 'WTF_CSRF_ENABLED'},
            {'label': 'Secure session cookie', 'on': bool(cfg.get('SESSION_COOKIE_SECURE', False)),
             'honesty': None, 'detail': 'SESSION_COOKIE_SECURE'},
            {'label': 'Auto-ban', 'on': bool(cfg.get('SECURITY_AUTO_BAN_ENABLED', True)),
             'honesty': None, 'detail': 'SECURITY_AUTO_BAN_ENABLED'},
            {'label': 'Attack detection', 'on': has_mw, 'honesty': None,
             'detail': 'Security middleware installed'},
        ]
    except Exception:
        logger.exception("security tab: feature flags failed")

    # ---- action control templates (rendered per-row / once in the template) ----
    out['unban'] = _control('Unban', 'admin_panel.security_unban_ip', min_role='Global Admin')
    out['clear_rl'] = _control('Clear counters', 'admin_panel.security_clear_rate_limit',
                               min_role='Global Admin')
    out['clear_all'] = _control(
        'Clear all bans', 'admin_panel.security_clear_all_bans',
        danger=True, min_role='Global Admin',
        confirm='Lift EVERY active IP ban (database and in-memory)? Any auto-banned '
                'attackers will be able to reach the site again immediately.')
    # UI-gate the GA-only controls for honesty (routes still enforce server-side).
    if not is_global_admin:
        out['unban'] = None
        out['clear_rl'] = None
        out['clear_all'] = None
    out['dashboard_url'] = _safe_url('admin_panel.security_dashboard')

    return out


# --------------------------------------------------------------------------
# Phase 3b — API Traffic tab
# --------------------------------------------------------------------------
#
# Every figure is from APIRequestLog (api_request_logs), aggregated the same way the
# api_management collectors do. The request logger records ONLY /api/* paths — ordinary
# web page views and static assets are NOT counted — so EVERY metric carries the
# api-only badge and the explainer states this prominently. Queries run on the request's
# own `session` (one transaction), not a second Model.query session.


_HTTP_STATUS_NAMES = {
    400: '400 Bad Request', 401: '401 Unauthorized', 403: '403 Forbidden',
    404: '404 Not Found', 405: '405 Method Not Allowed', 408: '408 Request Timeout',
    409: '409 Conflict', 422: '422 Unprocessable', 429: '429 Too Many Requests',
    500: '500 Internal Server Error', 502: '502 Bad Gateway', 503: '503 Service Unavailable',
    504: '504 Gateway Timeout',
}


def get_api_tab(session, hours=24):
    """Assemble the API Traffic tab from api_request_logs only (api-only). Isolated
    try/except per query so a single failure yields an honest empty panel, not a 500."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app.core import db
    from app.models.api_logs import APIRequestLog

    out = {
        'window_hours': hours,
        'stats': None,          # headline metrics (all api-only)
        'top_endpoints': [],    # busiest endpoints
        'error_breakdown': [],  # errors grouped by status code
        'has_data': False,
        'management_url': None,  # LINK to the full API Management page
    }
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    # ---- headline (total / avg / error rate) ----
    try:
        row = session.query(
            func.count(APIRequestLog.id).label('total'),
            func.avg(APIRequestLog.response_time_ms).label('avg'),
            func.sum(db.case((APIRequestLog.status_code >= 400, 1), else_=0)).label('errors'),
        ).filter(APIRequestLog.timestamp >= cutoff).first()
        total = int(row.total or 0) if row else 0
        errors = int(row.errors or 0) if row else 0
        avg_ms = float(row.avg or 0) if row else 0.0
        error_rate = round(errors / total * 100, 2) if total else 0
        out['has_data'] = total > 0
        out['stats'] = [
            _m('Total requests', total, 'api-only'),
            _m('Avg response time', f'{avg_ms:.0f}ms', 'api-only'),
            _m('Error rate', f'{error_rate}%', 'api-only'),
            _m('Errors', errors, 'api-only'),
            _m('Successful', total - errors, 'api-only'),
        ]
        out['error_rate'] = error_rate
    except Exception:
        logger.exception("api tab: headline stats failed")

    # ---- top endpoints ----
    try:
        rows = session.query(
            APIRequestLog.endpoint_path,
            func.count(APIRequestLog.id).label('count'),
            func.avg(APIRequestLog.response_time_ms).label('avg'),
            func.sum(db.case((APIRequestLog.status_code >= 400, 1), else_=0)).label('errors'),
        ).filter(
            APIRequestLog.timestamp >= cutoff
        ).group_by(
            APIRequestLog.endpoint_path
        ).order_by(func.count(APIRequestLog.id).desc()).limit(10).all()
        for r in rows:
            count = int(r.count or 0)
            errs = int(r.errors or 0)
            success = round((count - errs) / count * 100, 1) if count else 100.0
            out['top_endpoints'].append({
                'path': r.endpoint_path or '—',
                'count': count,
                'avg_time': round(float(r.avg or 0), 1),
                'errors': errs,
                'success_rate': success,
            })
    except Exception:
        logger.exception("api tab: top endpoints failed")

    # ---- error breakdown by status ----
    try:
        rows = session.query(
            APIRequestLog.status_code,
            func.count(APIRequestLog.id).label('count'),
        ).filter(
            APIRequestLog.timestamp >= cutoff,
            APIRequestLog.status_code >= 400,
        ).group_by(
            APIRequestLog.status_code
        ).order_by(func.count(APIRequestLog.id).desc()).all()
        for r in rows:
            out['error_breakdown'].append({
                'status': r.status_code,
                'label': _HTTP_STATUS_NAMES.get(r.status_code, f'{r.status_code} Error'),
                'count': int(r.count or 0),
            })
    except Exception:
        logger.exception("api tab: error breakdown failed")

    out['management_url'] = _safe_url('admin_panel.api_management')
    return out


# --------------------------------------------------------------------------
# Phase 4 — Logs & Audit tab
# --------------------------------------------------------------------------
#
# A UNIFIED explorer over 6 genuinely DIFFERENT log sources. A `?src=` selector
# picks ONE; only the SELECTED source's collector runs (like the tab dispatch), each
# isolated in its own try/except so one failing source can't 500 the tab. Nothing is
# fabricated — an empty/error source reads as an honest blank, never a fake row.
#
# The 6 sources and their REAL collectors:
#   app ......... on-disk application log tail of THIS container's filesystem. Mirrors
#                 monitoring.system_logs: tries logs/app.log, app.log,
#                 /var/log/ecs-portal/app.log; reads the last ~500 lines and regex-parses
#                 {timestamp, level, source, message}. If NO file is found it falls back
#                 to recent AdminAuditLog rows and SAYS SO (from_audit=True) — that is DB
#                 activity, not the real on-disk tail. level + search filters supported.
#   audit ....... AdminAuditLog (admin_audit_log) — who-did-what admin actions. Paginated
#                 (100), newest first; action humanized (raw kept for title=).
#   api ......... APIRequestLog (api_request_logs) — /api/* traffic ONLY. Newest first,
#                 limit 100, errors-only filter (status >= 400). A blank list can mean the
#                 request-path writer isn't running, not zero traffic → 'api-only' badge.
#   container ... GA-ONLY. Live docker logs via admin_helpers.get_container_data() /
#                 get_container_logs() (tail ~400 lines). Docker socket may be absent →
#                 honest "not reachable" state. Non-GA: chip hidden AND collector refused.
#   task ........ TaskExecution failed rows — captured Celery error/traceback in an
#                 expandable <details> (escaped). Newest first, limit 100.
#   security .... SecurityEvent.get_recent_events(limit=100, hours=168) — attack/ban events.
#
# Actions (audit source only):
#   clear old audit rows .. api_clear_system_logs (POST, GA-only) reads json.days_to_keep
#     (default 30) and DELETEs AdminAuditLog rows older than N days — it deletes DB TABLE
#     ROWS, NOT disk log files. The confirm text says this explicitly.
# Export links (where a real endpoint exists):
#   audit → export_audit_logs (GET /audit-logs/export); app → system_logs ?export=true.

_LOG_SOURCES = [
    ('app', 'App logs', 'ti-file-text'),
    ('audit', 'Audit trail', 'ti-history'),
    ('api', 'API requests', 'ti-plug'),
    ('container', 'Container', 'ti-box'),      # GA-only
    ('task', 'Task errors', 'ti-alert-triangle'),
    ('security', 'Security', 'ti-shield-lock'),
]
_VALID_LOG_SOURCES = {k for k, _, _ in _LOG_SOURCES}

# Tone for a parsed app-log level word.
_LOG_LEVEL_TONE = {
    'ERROR': 'danger', 'CRITICAL': 'danger', 'FATAL': 'danger',
    'WARNING': 'warning', 'WARN': 'warning',
    'INFO': 'info', 'DEBUG': 'neutral', 'NOTSET': 'neutral',
}


def _log_source_chips(is_global_admin):
    """Selector chips for the source picker. The container chip is GA-only — it is
    omitted entirely for non-GAs (and the collector is also refused server-side)."""
    chips = []
    for key, label, icon in _LOG_SOURCES:
        if key == 'container' and not is_global_admin:
            continue
        chips.append({'key': key, 'label': label, 'icon': icon})
    return chips


def _logs_app(session, level='all', search=''):
    """App-log source: tail THIS container's on-disk application log. Mirrors the
    file-finding + regex-parse in monitoring.system_logs, reading the last ~500 lines.
    If no file is found, falls back to recent AdminAuditLog rows and flags from_audit."""
    import os
    import re
    from datetime import datetime

    out = {'entries': [], 'log_file': None, 'from_audit': False,
           'level': level, 'search': search}
    log_pattern = re.compile(
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+-\s+(\w+)\s+-\s+(\S+)\s+-\s+(.*)',
        re.DOTALL)

    # This module lives at app/services/ → project root is two levels up.
    here = os.path.dirname(os.path.abspath(__file__))
    log_paths = [
        os.path.join(here, '..', '..', 'logs', 'app.log'),
        os.path.join(here, '..', '..', 'app.log'),
        '/var/log/ecs-portal/app.log',
    ]
    log_file = None
    for p in log_paths:
        rp = os.path.abspath(p)
        if os.path.exists(rp):
            log_file = rp
            break

    if log_file:
        out['log_file'] = log_file
        try:
            # Tail the last 500 lines WITHOUT loading the whole file into memory
            # (an unrotated app.log can be huge, and this read holds a request slot).
            from collections import deque
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = list(deque(f, maxlen=500))
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                m = log_pattern.match(line)
                if not m:
                    continue  # unparsed lines skipped (matches monitoring.system_logs)
                ts_str, lvl, source, message = m.groups()
                try:
                    ts = datetime.strptime(ts_str.split(',')[0], '%Y-%m-%d %H:%M:%S')
                    ts_disp = ts.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    ts_disp = ts_str
                lvl_u = lvl.upper()
                msg = message.strip()
                # Normalize level aliases so selecting "warning" also catches WARN, and
                # "error" catches ERR/CRITICAL/FATAL — otherwise those slip past the filter.
                if level and level != 'all':
                    _lv = {'warn': 'warning', 'warning': 'warning', 'err': 'error',
                           'error': 'error', 'crit': 'error', 'critical': 'error',
                           'fatal': 'error', 'info': 'info', 'debug': 'debug'}
                    if _lv.get(lvl_u.lower(), lvl_u.lower()) != _lv.get(level.lower(), level.lower()):
                        continue
                if search and search.lower() not in msg.lower():
                    continue
                out['entries'].append({
                    'timestamp': ts_disp, 'level': lvl_u,
                    'tone': _LOG_LEVEL_TONE.get(lvl_u, 'neutral'),
                    'source': source, 'message': msg,
                })
                if len(out['entries']) >= 500:
                    break
        except PermissionError:
            out['entries'].append({
                'timestamp': '—', 'level': 'WARNING', 'tone': 'warning',
                'source': 'monitoring',
                'message': f'Permission denied reading log file: {log_file}',
            })
    else:
        # No on-disk log on this container's filesystem — fall back to audit rows.
        out['from_audit'] = True
        try:
            from app.models.admin_config import AdminAuditLog
            rows = (session.query(AdminAuditLog)
                    .order_by(AdminAuditLog.timestamp.desc()).limit(200).all())
            for al in rows:
                msg = (f'{al.action} on {al.resource_type} '
                       f'({al.resource_id or ""}): {al.new_value or ""}')
                if search and search.lower() not in msg.lower():
                    continue
                out['entries'].append({
                    'timestamp': (al.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                                  if al.timestamp else '—'),
                    'level': 'INFO', 'tone': 'info', 'source': 'audit_log', 'message': msg,
                })
        except Exception:
            logger.debug("logs app: audit fallback failed", exc_info=True)
    return out


def _logs_audit(session, page=1):
    """Audit source: AdminAuditLog rows, newest first, paginated (100). Humanizes the
    action (raw kept for title=). The acting user is joined where cheap (guarded)."""
    from app.models.admin_config import AdminAuditLog
    from app.utils.humanize import humanize_identifier

    per_page = 100
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1

    out = {'rows': [], 'page': page, 'per_page': per_page, 'has_next': False}
    # Fetch one extra to know if there's a next page without a COUNT. Eager-load the
    # actor to avoid up-to-100 per-row lazy lookups (N+1) on the request transaction.
    from sqlalchemy.orm import joinedload
    q = session.query(AdminAuditLog).order_by(AdminAuditLog.timestamp.desc())
    try:
        q = q.options(joinedload(AdminAuditLog.user))
    except Exception:
        pass  # relationship name differs → fall back to lazy (still correct, just N+1)
    rows = q.offset((page - 1) * per_page).limit(per_page + 1).all()
    out['has_next'] = len(rows) > per_page
    for al in rows[:per_page]:
        actor = f'User {al.user_id}'
        try:
            u = al.user
            if u is not None:
                actor = (u.name or getattr(u, 'username', None)
                         or getattr(u, 'email', None) or f'User {al.user_id}')
        except Exception:
            logger.debug("logs audit: actor lookup failed", exc_info=True)
        out['rows'].append({
            'action_raw': al.action or '',
            'action': humanize_identifier(al.action or ''),
            'resource_type': al.resource_type or '—',
            'resource_id': al.resource_id or '',
            'actor': actor,
            'ip': al.ip_address or '—',
            'old_value': al.old_value or '',
            'new_value': al.new_value or '',
            'timestamp': (al.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                          if al.timestamp else '—'),
        })
    return out


def _logs_api(session, errors_only=False):
    """API source: APIRequestLog rows (api-only), newest first, limit 100. errors_only
    restricts to status >= 400."""
    from app.models.api_logs import APIRequestLog

    out = {'rows': [], 'errors_only': bool(errors_only)}
    q = session.query(APIRequestLog).order_by(APIRequestLog.timestamp.desc())
    if errors_only:
        q = q.filter(APIRequestLog.status_code >= 400)
    for r in q.limit(100).all():
        sc = r.status_code or 0
        out['rows'].append({
            'method': r.method or '',
            'path': r.endpoint_path or '—',
            'status': sc,
            'tone': ('danger' if sc >= 500 else ('warning' if sc >= 400 else 'success')),
            'response_time': (f'{r.response_time_ms:.0f}ms'
                              if r.response_time_ms is not None else '—'),
            'user_id': r.user_id,
            'ip': r.ip_address or '—',
            'timestamp': (r.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                          if r.timestamp else '—'),
        })
    return out


def _logs_container(session, selected=''):
    """Container source (GA-only, gated by the caller): live docker logs. Container
    inventory from get_container_data(); the selected container's log tail (~400 lines)
    from get_container_logs(). Docker socket absent → docker_available=False."""
    from app.admin_helpers import get_container_data, get_container_logs

    out = {'containers': [], 'selected': None, 'log_text': None,
           'log_lines': 0, 'docker_available': True, 'logs_error': False}
    containers = get_container_data()
    if containers is None:
        out['docker_available'] = False
        return out

    out['containers'] = [{
        'id': c.get('id'), 'name': c.get('name'),
        'status': c.get('status'), 'image': c.get('image'),
    } for c in containers]

    # Validate the requested container against the real inventory (never trust the arg).
    ids = {c.get('id') for c in containers}
    if selected and selected in ids:
        out['selected'] = selected
    elif containers:
        out['selected'] = containers[0].get('id')

    if out['selected']:
        # tail=400 bounds the fetch at the Docker source (don't pull full history).
        raw = get_container_logs(out['selected'], tail=400)
        if raw is None:
            out['logs_error'] = True
        else:
            tail = raw.splitlines()[-400:]
            out['log_lines'] = len(tail)
            out['log_text'] = '\n'.join(tail)
    return out


def _logs_task(session):
    """Task-errors source: TaskExecution failed rows, newest first, limit 100. The
    captured error/traceback is kept verbatim (escaped in the template's <details>)."""
    from app.models.api_logs import TaskExecution
    from app.utils.humanize import humanize_identifier

    out = {'rows': []}
    rows = (session.query(TaskExecution)
            .filter(TaskExecution.status == 'failed')
            .order_by(TaskExecution.created_at.desc()).limit(100).all())
    for r in rows:
        raw = r.name or 'unknown'
        out['rows'].append({
            'id': r.id,
            'name_raw': raw,
            'name': humanize_identifier(raw.rsplit('.', 1)[-1]),
            'worker': r.worker or '—',
            'started_at': (r.started_at.strftime('%Y-%m-%d %H:%M:%S')
                           if r.started_at else '—'),
            'duration': (f'{r.duration_ms:.0f}ms' if r.duration_ms is not None else '—'),
            'error': r.error or '',
        })
    return out


def _logs_security(session):
    """Security source: SecurityEvent.get_recent_events(limit=100, hours=168). Event
    types humanized (raw kept for title=)."""
    from app.models.security import SecurityEvent
    from app.utils.humanize import humanize_identifier

    out = {'rows': []}
    for e in (SecurityEvent.get_recent_events(limit=100, hours=168) or []):
        sev = (e.severity or 'medium').lower()
        out['rows'].append({
            'type_raw': e.event_type or 'unknown',
            'type': humanize_identifier(e.event_type or 'unknown'),
            'ip': e.ip_address or '—',
            'severity': sev,
            'tone': _SEV_TONE.get(sev, 'neutral'),
            'description': e.description or '—',
            'created_at': (e.created_at.strftime('%Y-%m-%d %H:%M:%S')
                           if e.created_at else '—'),
        })
    return out


def get_logs_tab(session, src, is_global_admin=False, level='all', search='',
                 container='', page=1):
    """Assemble the Logs & Audit tab. A `src` selector picks ONE of 6 real sources;
    only that source's collector runs, isolated so a failure yields an honest error
    state (out['error']=True), never a 500 and never a fabricated row.

    Honesty highlights (also spelled out in the template's explainer):
      * app ....... on-disk tail of THIS container ONLY; from_audit flags the DB fallback.
      * api ....... /api/* traffic only (api-only badge); a blank list may mean no writer.
      * container . GA-only — chip hidden AND collector refused for non-GAs.
      * The Clear action deletes AUDIT-TABLE ROWS, not disk log files.
    """
    if src not in _VALID_LOG_SOURCES:
        src = 'app'

    out = {
        'src': src,
        'sources': _log_source_chips(is_global_admin),
        'is_global_admin': is_global_admin,
        'level': level or 'all',
        'search': search or '',
        'page': page,
        'app': None, 'audit': None, 'api': None,
        'container': None, 'task': None, 'security': None,
        'error': False,             # the selected source's collector raised
        'container_denied': False,  # a non-GA requested the container source
        'clear_action': None,       # audit source only, GA-only
        'export_url': None,         # audit or app only
    }

    try:
        if src == 'app':
            out['app'] = _logs_app(session, level=out['level'], search=out['search'])
            out['export_url'] = _safe_url('admin_panel.system_logs', export='true',
                                          level=out['level'], search=out['search'])
        elif src == 'audit':
            out['audit'] = _logs_audit(session, page=page)
            out['page'] = out['audit']['page']
            out['export_url'] = _safe_url('admin_panel.export_audit_logs')
            if is_global_admin:
                out['clear_action'] = _control(
                    'Clear old audit rows', 'admin_panel.api_clear_system_logs',
                    danger=True, min_role='Global Admin',
                    body={'days_to_keep': 30},
                    confirm='Delete audit-log TABLE ROWS older than 30 days? This '
                            'permanently removes who-did-what admin records from the '
                            'admin_audit_log database table. It does NOT touch the '
                            'on-disk application log files. This cannot be undone.')
        elif src == 'api':
            out['api'] = _logs_api(
                session, errors_only=((out['level'] or '').lower() == 'error'))
        elif src == 'container':
            # GA-only: refuse server-side (the chip is also hidden for non-GAs).
            if not is_global_admin:
                out['container_denied'] = True
            else:
                out['container'] = _logs_container(session, selected=container)
        elif src == 'task':
            out['task'] = _logs_task(session)
        elif src == 'security':
            out['security'] = _logs_security(session)
    except Exception:
        logger.exception("logs tab: collector failed for src=%s", src)
        out['error'] = True

    return out
