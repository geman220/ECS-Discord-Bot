# app/admin_panel/routes/access_control.py

"""
Access Control — the unified home for Roles, Permissions and Discord role-mapping.

These three surfaces all edit the same ``Role`` (permissions via role_permissions,
Discord link via ``Role.discord_role_id``), so they live on one page with
server-side tabs (?tab=roles|permissions|discord), mirroring the Members command
center. Per-person role *assignment* stays in the Member Hub.

Roles CRUD reuses the existing ``admin_panel.*_role_comprehensive`` endpoints and
Discord mapping reuses the existing ``admin_panel.*_role_mapping`` endpoints — this
module only adds the page composition + the NEW editable-permission-matrix write
endpoint (grant/revoke a single role×permission), which nothing had before.
"""

import logging
from datetime import datetime

from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

from .. import admin_panel_bp
from app.core import db
from app.models import Role, user_roles
from app.models.core import Permission
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.utils.permission_registry import build_permission_matrix, ENFORCED_PERMISSIONS
from app.utils.role_display import role_display, role_sort_key

logger = logging.getLogger(__name__)


def _roles_with_counts(session):
    """[(Role, user_count)] ordered by our friendly kind→label ordering."""
    rows = (session.query(Role, func.count(user_roles.c.user_id).label('uc'))
            .outerjoin(user_roles).group_by(Role.id).all())
    rows.sort(key=lambda r: role_sort_key(r[0].name))
    return rows


@admin_panel_bp.route('/access-control')
@login_required
@role_required(['Global Admin'])
def access_control():
    """Unified Access Control center (Roles / Permissions / Discord mapping)."""
    tab = (request.args.get('tab') or 'roles').strip()
    if tab not in ('roles', 'permissions', 'discord'):
        tab = 'roles'

    session = db.session

    # ---- header counts (cheap; shown on every tab's tab-bar) ----
    all_roles = session.query(Role).all()
    roles_count = len(all_roles)
    mapped_count = sum(1 for r in all_roles if r.discord_role_id)
    perms_count = len(ENFORCED_PERMISSIONS)
    seeded_count = session.query(func.count(Permission.id)).scalar() or 0
    counts = {'roles': roles_count, 'permissions': perms_count, 'discord': mapped_count}

    ctx = {
        'tab': tab,
        'counts': counts,
        'seeded_count': seeded_count,
        'enforced_count': perms_count,
    }

    if tab == 'roles':
        roles_rows = _roles_with_counts(session)
        total_assignments = session.query(user_roles).count()
        max_users = max((uc for _, uc in roles_rows), default=0)
        roles_view = []
        for role, uc in roles_rows:
            d = role_display(role.name)
            roles_view.append({
                'id': role.id,
                'name': role.name,
                'label': d['label'],
                'what': d['what'],
                'kind': d['kind'],
                'discord_expected': d['discord_expected'],
                'description': role.description,
                'user_count': uc,
                'user_pct': round((uc / max_users) * 100) if max_users else 0,
                'discord_role_id': role.discord_role_id,
                'discord_role_name': role.discord_role_name,
                'sync_enabled': role.sync_enabled,
                'is_system': role.name in ('Global Admin', 'Pub League Admin', 'Discord Admin'),
            })
        ctx.update({
            'roles': roles_view,
            'stats': {
                'total_roles': roles_count,
                'assignments': total_assignments,
                'avg_per_role': round(total_assignments / roles_count, 1) if roles_count else 0,
                'mapped': mapped_count,
            },
        })

    elif tab == 'permissions':
        matrix = build_permission_matrix(session)
        # Attach friendly role labels for the column headers.
        for r in matrix['roles']:
            r['label'] = role_display(r['name'])['label']
        ctx.update({'matrix': matrix})

    elif tab == 'discord':
        from app.services.discord_role_sync_service import (
            fetch_discord_roles_sync, CANONICAL_DISCORD_ROLE_MAP,
        )
        discord_roles, bot_status, guild_name = [], 'offline', ''
        try:
            discord_roles = fetch_discord_roles_sync()
            if discord_roles:
                bot_status, guild_name = 'online', 'Connected'
        except Exception as e:  # pragma: no cover - network dependent
            logger.warning(f"Access Control: could not fetch Discord roles: {e}")
        roles_rows = _roles_with_counts(session)
        mapping_view = []
        for role, uc in roles_rows:
            d = role_display(role.name)
            mapping_view.append({
                'id': role.id, 'name': role.name, 'label': d['label'],
                'kind': d['kind'], 'discord_expected': d['discord_expected'],
                'discord_role_id': role.discord_role_id,
                'discord_role_name': role.discord_role_name,
                'sync_enabled': role.sync_enabled,
                'last_synced_at': role.last_synced_at,
                'user_count': uc,
            })
        mapped = sum(1 for m in mapping_view if m['discord_role_id'])
        needs = sum(1 for m in mapping_view if m['discord_expected'] and not m['discord_role_id'])
        app_only = sum(1 for m in mapping_view if not m['discord_expected'])
        ctx.update({
            'mappings': mapping_view,
            'discord_roles': discord_roles,
            'bot_status': bot_status,
            'guild_name': guild_name,
            'dstats': {
                'flask_roles': roles_count, 'mapped': mapped, 'needs': needs,
                'app_only': app_only, 'discord_roles': len(discord_roles),
            },
        })

    return render_template('admin_panel/access_control/index_flowbite.html', **ctx)


@admin_panel_bp.route('/access-control/permission/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def toggle_role_permission():
    """Grant or revoke ONE permission for ONE role (editable matrix cell).

    Body JSON: {role_id, permission_name, grant: bool}. Dedupes on write because
    role_permissions has no unique constraint. Never touches Global Admin (kept
    all-granted by convention — the matrix locks that column).
    """
    from flask import g
    session = g.db_session
    data = request.get_json(silent=True) or {}
    role_id = data.get('role_id')
    perm_name = (data.get('permission_name') or '').strip()
    grant = bool(data.get('grant'))

    if not role_id or not perm_name:
        return jsonify({'success': False, 'message': 'role_id and permission_name are required'}), 400

    role = session.query(Role).get(role_id)
    if role is None:
        return jsonify({'success': False, 'message': 'Role not found'}), 404
    if role.name == 'Global Admin':
        return jsonify({'success': False, 'message': 'Global Admin always has every permission and can’t be changed here.'}), 400

    perm = session.query(Permission).filter_by(name=perm_name).first()
    if perm is None:
        return jsonify({'success': False,
                        'message': f'Permission “{perm_name}” doesn’t exist yet — run the permission seed first.'}), 409

    current = list(role.permissions or [])
    has_it = any(p.id == perm.id for p in current)

    if grant and not has_it:
        role.permissions.append(perm)
    elif grant and has_it:
        pass  # already granted — idempotent
    elif not grant:
        # Remove ALL occurrences (dedupe: the join table has no unique constraint).
        role.permissions = [p for p in current if p.id != perm.id]

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='toggle_role_permission',
        resource_type='role',
        resource_id=str(role_id),
        new_value={'permission': perm_name, 'granted': grant, 'role': role.name},
    )
    return jsonify({'success': True, 'granted': grant,
                    'message': f'{"Granted" if grant else "Revoked"} “{perm_name}” {"to" if grant else "from"} {role_display(role.name)["label"]}'})
