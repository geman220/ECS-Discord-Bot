# app/admin_panel/routes/match_operations/unified_substitutes.py

"""
Unified Substitute Board Route (Phase 1a)

ONE additive admin board that shows BOTH leagues' substitute requests in the
ECS FC "at-a-glance" style. This is READ-UNIFY + ACTION-DISPATCH only — it reads
from both existing models via the unified adapter and its buttons dispatch to the
EXISTING per-league endpoints. The two original pages (substitute_management,
ecs_fc_sub_requests) are left untouched.
"""

import logging

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.decorators import role_required
from app.models.admin_config import AdminAuditLog
from app.services.unified_substitute_service import get_unified_requests, get_unified_pool

logger = logging.getLogger(__name__)

PER_PAGE = 25


@admin_panel_bp.route('/substitutes')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def unified_substitutes():
    """Unified substitute board across Pub League + ECS FC."""
    try:
        league = request.args.get('league', 'all')
        if league not in ('all', 'pub_league', 'ecs_fc'):
            league = 'all'

        status = request.args.get('status', 'active')
        if status not in ('active', 'all', 'open', 'filled', 'cancelled', 'expired'):
            status = 'active'

        page = request.args.get('page', 1, type=int) or 1

        items, total, page, pages = get_unified_requests(
            db.session, league=league, status=status, page=page, per_page=PER_PAGE
        )
        pool_members = get_unified_pool(db.session)

        # KPI band figures (computed off the returned/full counts in a lightweight pass).
        ready_count = sum(1 for it in items if it['ready_to_assign'])

        try:
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='access_unified_substitutes',
                resource_type='match_operations',
                resource_id='unified_substitutes',
                new_value='Accessed unified substitute board',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
            )
        except Exception:
            # Audit logging must never break the page.
            pass

        return render_template(
            'admin_panel/substitutes_unified_flowbite.html',
            items=items,
            total=total,
            page=page,
            pages=pages,
            per_page=PER_PAGE,
            pool_members=pool_members,
            league_filter=league,
            status_filter=status,
            ready_count=ready_count,
        )
    except Exception as e:
        logger.error(f"Error loading unified substitutes board: {e}", exc_info=True)
        flash('Unified substitute board unavailable. Verify database connection and substitute models.', 'error')
        return redirect(url_for('admin_panel.match_operations'))
