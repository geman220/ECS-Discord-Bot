# app/admin_panel/routes/system_center/worklist.py

"""
System Command Center — the ops surface at /admin-panel/system (Phase 1).

Mirrors the Members command center: one shell, a KPI band, a tab bar, and a
per-tab body. Phase 1 ships the shell + two live tabs (Overview, Services) plus a
service-detail drawer endpoint. The remaining six tabs render an honest
"comes online later" empty state — nothing is fabricated.

Read model: app/services/system_center_service.py (every value traces to a real
collector). This module is READ-ONLY in Phase 1 — no @transactional, no writes.
"""

import logging

from flask import render_template, request, jsonify, abort
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.decorators import role_required

logger = logging.getLogger(__name__)


# Tabs that are not built yet — they render the honest "later in this rollout" state.
# Phase 4 wired Logs & Audit (the last tab), so this set is now EMPTY. It is kept
# (with the template's empty-state else branch) as a safety net for any future stub.
_STUB_TABS = set()
_ALL_TABS = {'overview', 'services', 'perf', 'jobs', 'data', 'security', 'logs', 'api'} | _STUB_TABS


def _is_global_admin():
    """True when the EFFECTIVE roles (impersonation-aware, same source role_required
    checks) include Global Admin. Used to UI-gate GA-only action controls — the
    endpoints still enforce roles server-side; this is defense-in-depth + honesty."""
    try:
        from app.role_impersonation import get_effective_roles
        return 'Global Admin' in (get_effective_roles() or [])
    except Exception:
        logger.debug("system center: effective-role lookup failed", exc_info=True)
        return False


def _shared_kpis(session):
    """The KPI band + tab badges, from real collectors. Guarded so a single failing
    probe leaves a neutral figure rather than 500-ing the whole page.

    Returns (kpis, counts, board, perf_metrics):
      kpis         : dict for the 6-up stat band
      counts       : dict for tab badges (services, jobs, security)
      board        : the services board (reused by the Services tab so it isn't recomputed)
      perf_metrics : the raw _get_system_performance_metrics() dict, passed through to
                     the Overview so CPU isn't sampled (a blocking ~1s call) twice.
    """
    from app.services.system_center_service import get_services_board

    kpis = {
        'health_word': 'Unknown', 'health_tone': 'neutral',
        'services_up': 0, 'services_total': 0,
        'active_jobs': 0, 'error_rate': None,
        'cpu': 0, 'memory': 0,
    }
    counts = {'services': 0, 'jobs': 0, 'security': 0}
    perf_metrics = {}

    # ---- services board (drives services_up/total + overall health roll-up) ----
    board = []
    try:
        board = get_services_board(session)
        counts['services'] = len(board)
        # 'idle' services (e.g. Twilio, deliberately not probed on load; or Docker
        # when the socket isn't visible) are EXCLUDED from the health roll-up — they
        # were never checked, so they can neither pass nor fail. Otherwise a healthy
        # system could never read "Healthy".
        probed = [s for s in board if s['status'] != 'idle']
        total = len(probed)
        up = sum(1 for s in probed if s['status'] == 'healthy')
        kpis['services_up'], kpis['services_total'] = up, total
        # Overall roll-up: a core service down = Down; any non-healthy probed = Degraded.
        core_down = any(s['status'] == 'down' for s in probed
                        if s['key'] in ('database', 'redis', 'celery'))
        if total == 0:
            word, tone = 'Unknown', 'neutral'
        elif core_down:
            word, tone = 'Down', 'danger'
        elif up == total:
            word, tone = 'Healthy', 'primary'
        else:
            word, tone = 'Degraded', 'warning'
        kpis['health_word'], kpis['health_tone'] = word, tone
    except Exception:
        logger.exception("system KPIs: services board failed")

    # ---- resource metrics (cpu / memory) — shared-cached to avoid the ~1s psutil
    #      cpu_percent block on every tab load ----
    try:
        from app.services.system_center_service import cached_perf_metrics
        perf_metrics = cached_perf_metrics() or {}
        kpis['cpu'] = perf_metrics.get('cpu_usage', 0)
        kpis['memory'] = perf_metrics.get('memory_usage', 0)
    except Exception:
        logger.exception("system KPIs: perf metrics failed")

    # ---- task stats (active jobs + 24h error rate) ----
    try:
        from app.services.system_center_service import cached_task_stats
        stats = cached_task_stats() or {}
        running = int(stats.get('running') or 0)
        total_t = int(stats.get('total') or 0)
        failed = int(stats.get('failed') or 0)
        kpis['active_jobs'] = running
        counts['jobs'] = running
        if total_t > 0:
            kpis['error_rate'] = round(failed / total_t * 100, 1)
    except Exception:
        logger.debug("system KPIs: task stats unavailable", exc_info=True)

    # ---- active IP bans (security tab badge — cheap count) ----
    # Must match the enforcement definition of "active": is_active AND not expired.
    # A lifted permanent ban (is_active=False, expires_at=NULL) must NOT be counted.
    try:
        from datetime import datetime
        from app.models import IPBan
        counts['security'] = session.query(IPBan).filter(
            IPBan.is_active.is_(True),
            (IPBan.expires_at.is_(None)) | (IPBan.expires_at > datetime.utcnow())
        ).count()
    except Exception:
        logger.debug("system KPIs: IP ban count unavailable", exc_info=True)

    return kpis, counts, board, perf_metrics


@admin_panel_bp.route('/system', endpoint='system_center')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def system_center_worklist():
    """System Command Center — the unified operations surface.

    Tabs: Overview + Services are live; the other six render an honest
    "comes online later in this rollout" state. Read-only.
    """
    from flask import g
    session = g.db_session

    tab = (request.args.get('tab') or 'overview').strip()
    if tab not in _ALL_TABS:
        tab = 'overview'

    kpis, counts, board, perf_metrics = _shared_kpis(session)
    is_global_admin = _is_global_admin()

    overview = None
    services = None
    perf = None
    jobs = None
    data = None
    security = None
    logs = None
    api = None
    if tab == 'overview':
        try:
            from app.services.system_center_service import get_system_overview
            overview = get_system_overview(session, perf_metrics=perf_metrics,
                                           board=board, is_global_admin=is_global_admin,
                                           overall_word=kpis.get('health_word'),
                                           overall_tone=kpis.get('health_tone'))
        except Exception:
            logger.exception("system center: overview assembly failed")
            overview = None
    elif tab == 'services':
        services = board  # already computed for the KPI band
    elif tab == 'perf':
        try:
            from app.services.system_center_service import get_performance_tab
            perf = get_performance_tab(session, perf_metrics=perf_metrics)
        except Exception:
            logger.exception("system center: performance assembly failed")
            perf = None
    elif tab == 'jobs':
        try:
            from app.services.system_center_service import get_jobs_tab
            jobs = get_jobs_tab(session)
        except Exception:
            logger.exception("system center: jobs assembly failed")
            jobs = None
    elif tab == 'data':
        try:
            from app.services.system_center_service import get_data_tab
            data = get_data_tab(session, is_global_admin=is_global_admin)
        except Exception:
            logger.exception("system center: data assembly failed")
            data = None
    elif tab == 'security':
        try:
            from app.services.system_center_service import get_security_tab
            security = get_security_tab(session, is_global_admin=is_global_admin)
        except Exception:
            logger.exception("system center: security assembly failed")
            security = None
    elif tab == 'logs':
        try:
            from app.services.system_center_service import get_logs_tab
            src = (request.args.get('src') or 'app').strip()
            logs = get_logs_tab(
                session, src, is_global_admin=is_global_admin,
                level=(request.args.get('level') or 'all').strip(),
                search=(request.args.get('search') or '').strip(),
                container=(request.args.get('container') or '').strip(),
                page=request.args.get('page', 1, type=int),
                logfile=(request.args.get('logfile') or '').strip() or None,
            )
        except Exception:
            logger.exception("system center: logs assembly failed")
            logs = None
    elif tab == 'api':
        try:
            from app.services.system_center_service import get_api_tab
            api = get_api_tab(session)
        except Exception:
            logger.exception("system center: api assembly failed")
            api = None

    is_stub = tab in _STUB_TABS

    return render_template('admin_panel/system_center/worklist_flowbite.html',
                           tab=tab, kpis=kpis, counts=counts,
                           overview=overview, services=services,
                           perf=perf, jobs=jobs,
                           data=data, security=security,
                           logs=logs, api=api,
                           is_stub=is_stub,
                           is_global_admin=is_global_admin)


@admin_panel_bp.route('/system/service/<key>/data')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def system_center_service_data(key):
    """JSON per-service detail for the drawer (AJAX). 404 on an unknown key."""
    from flask import g
    from app.services.system_center_service import get_service_360

    data = get_service_360(g.db_session, key, is_global_admin=_is_global_admin())
    if data is None:
        abort(404)
    return jsonify({'success': True, 'service': data})
