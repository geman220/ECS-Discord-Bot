# app/admin_panel/routes/integrity.py

"""
Admin Panel — Data Integrity dashboard.

Surfaces the conflict/silent-breakage detectors in app/services/integrity_service.py
(the G1–G15 catalog in docs/admin-integrity-guards-audit.md) in one place: a card
per check with a live count, plus a per-check list of the affected players. Each
finding's Manage modal offers the contextual fixes the detector attached
(fix_actions), applied by POST /integrity/resolve via integrity_fix_service.
"""

import logging

from flask import render_template, jsonify, g, request
from flask_login import login_required, current_user

from .. import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/integrity')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def integrity_dashboard():
    """Data-integrity conflict dashboard."""
    from app.services.integrity_service import run_all_checks, summarize, store_counts_cache
    session = g.db_session
    try:
        results = run_all_checks(session)
        # We just paid for a full scan — refresh the main dashboard's cached counts.
        store_counts_cache(results)
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


@admin_panel_bp.route('/integrity/resolve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def integrity_resolve():
    """Apply one contextual fix from a finding's Manage modal.

    Body: {code, action, user_id?, player_id?, params?}. The (code, action) pair
    must be one a detector actually offers (integrity_fix_service.FIXERS), so this
    endpoint can't be driven to arbitrary mutations. Uses db.session (matching
    @transactional); Discord work is deferred until after commit.
    """
    from app.services.integrity_fix_service import apply_fix
    from app.services.integrity_service import invalidate_counts_cache
    from app.models.admin_config import AdminAuditLog

    data = request.get_json(silent=True) or {}
    code = data.get('code')
    action = data.get('action')
    user_id = data.get('user_id')
    player_id = data.get('player_id')
    params = data.get('params') or {}
    if not code or not action:
        return jsonify({'success': False, 'message': 'code and action are required'}), 400

    try:
        message = apply_fix(code, action, user_id, player_id, params, current_user.id)
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        logger.error(f"Integrity fix {code}/{action} failed: {e}", exc_info=True)
        # A DB error mid-fix leaves the transaction aborted; roll back so the
        # @transactional wrapper doesn't attempt to commit a poisoned session.
        from app.core import db
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Fix failed — see server logs.'}), 500

    try:
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'integrity_fix_{action}',
            resource_type='integrity',
            resource_id=f'{code}:user={user_id},player={player_id}',
            new_value=message,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
    except Exception:
        logger.warning('Integrity fix audit log failed', exc_info=True)

    invalidate_counts_cache()
    logger.info(f"Integrity fix {code}/{action} by admin {current_user.id}: {message}")
    return jsonify({'success': True, 'message': message})


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
