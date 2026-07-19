# app/admin_panel/routes/integrity.py

"""
Admin Panel — Data Integrity dashboard.

Surfaces the conflict/silent-breakage detectors in app/services/integrity_service.py
(the G1–G15 catalog in docs/admin-integrity-guards-audit.md) in one place: a card
per check with a live count, plus a per-check list of the affected players linking
back to the user-management edit surface. Read-only.
"""

import logging

from flask import render_template, jsonify, g
from flask_login import login_required

from .. import admin_panel_bp
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/integrity')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def integrity_dashboard():
    """Data-integrity conflict dashboard."""
    from app.services.integrity_service import run_all_checks, summarize
    session = g.db_session
    try:
        results = run_all_checks(session)
    except Exception as e:
        logger.error(f"Integrity dashboard failed to run checks: {e}", exc_info=True)
        results = {}
    summary = summarize(session, results=results)
    # flist is None for an errored detector — coalesce so the template never iterates None.
    details = {code: [f.as_dict() for f in (flist or [])] for code, flist in results.items()}
    total = sum((r['count'] or 0) for r in summary)
    high = sum((r['count'] or 0) for r in summary if r['severity'] == 'high')
    errored = sum(1 for r in summary if r['errored'])
    return render_template(
        'admin_panel/integrity/dashboard.html',
        summary=summary, details=details, total_conflicts=total,
        high_conflicts=high, errored_checks=errored,
    )


@admin_panel_bp.route('/integrity/data')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def integrity_data():
    """JSON version of the integrity summary (for badges / polling)."""
    from app.services.integrity_service import run_all_checks, summarize
    session = g.db_session
    results = run_all_checks(session)
    return jsonify({
        'summary': summarize(session, results=results),
        'total': sum(len(v) for v in results.values() if v is not None),
    })
