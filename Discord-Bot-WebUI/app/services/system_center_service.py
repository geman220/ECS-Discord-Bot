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
# Overview
# --------------------------------------------------------------------------

def get_system_overview(session, perf_metrics=None):
    """Assemble the Overview tab from real collectors.

    `perf_metrics` — the already-sampled `_get_system_performance_metrics()` dict
    from the KPI band, passed through to avoid a second blocking `cpu_percent(1)`
    sample (~1s) on the same page load. If None, it is sampled here.

    Returns a dict:
      overall      : {'status','word','tone'} — the roll-up health word
      components   : [ {key,name,icon,status,status_word,tone,message} ] health-at-a-glance
      attention    : [ {severity,icon,label,detail,action_label,action_url} ]
      perf         : {'cpu','memory','disk','uptime','load','connections'}
      health_raw   : the raw _check_system_health() dict (for debugging/detail)
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

    return {
        'overall': overall,
        'components': components,
        'attention': attention,
        'perf': perf,
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
            'detail': 'Sampled from the worker that served this page.',
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


def get_service_360(session, key):
    """Richer per-service detail for the drawer. Phase 1: read-only. `controls` is
    empty (actions land in Phase 2). `recent` is included only when cheaply available."""
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

    return {
        'key': key,
        'name': entry['name'] if entry else key.title(),
        'icon': entry['icon'] if entry else 'ti-server-2',
        'status': entry['status'] if entry else 'idle',
        'status_word': entry['status_word'] if entry else 'Unknown',
        'tone': entry['tone'] if entry else 'neutral',
        'metrics': detail_metrics,
        'runbook': _RUNBOOKS.get(key, ''),
        'controls': [],   # Phase 2 — no destructive actions yet
        'recent': recent,
    }
