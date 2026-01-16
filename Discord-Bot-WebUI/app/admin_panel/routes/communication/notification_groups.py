# app/admin_panel/routes/communication/notification_groups.py

"""
Notification Groups Routes

CRUD operations for managing notification groups:
- List groups
- Create group (dynamic or static)
- View group details
- Update group
- Delete group
- Manage static group members
"""

import logging
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models import (
    User, Team, League, Role,
    NotificationGroup, NotificationGroupMember,
    GroupType, AdminAuditLog
)
from app.decorators import role_required
from app.services.push_targeting_service import push_targeting_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/notification-groups')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_groups_list():
    """List all notification groups."""
    try:
        # Get all active groups
        groups = NotificationGroup.query.filter_by(is_active=True).order_by(
            NotificationGroup.created_at.desc()
        ).all()

        # Calculate statistics
        dynamic_groups = sum(1 for g in groups if g.group_type == 'dynamic')
        static_groups = sum(1 for g in groups if g.group_type == 'static')
        total_members = NotificationGroupMember.query.count()

        # Get available data for creating groups
        teams = Team.query.filter_by(is_active=True).order_by(Team.name).all()
        leagues = League.query.filter_by(is_active=True).order_by(League.name).all()
        roles = Role.query.order_by(Role.name).all()

        return render_template(
            'admin_panel/communication/notification_groups_flowbite.html',
            groups=groups,
            dynamic_groups=dynamic_groups,
            static_groups=static_groups,
            total_members=total_members,
            teams=teams,
            leagues=leagues,
            roles=roles,
            page_title='Notification Groups'
        )
    except Exception as e:
        logger.error(f"Error listing notification groups: {e}")
        flash('Error loading notification groups', 'error')
        return redirect(url_for('admin_panel.push_notifications'))


@admin_panel_bp.route('/communication/notification-groups', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def notification_groups_create():
    """Create a new notification group."""
    try:
        data = request.get_json() or request.form.to_dict()

        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        group_type = data.get('group_type', 'dynamic')

        if not name:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Name is required'}), 400
            flash('Name is required', 'error')
            return redirect(url_for('admin_panel.notification_groups_list'))

        # Build criteria for dynamic groups
        criteria = None
        if group_type == 'dynamic':
            target_type = data.get('target_type', 'all')
            criteria = {'target_type': target_type}

            if target_type == 'role':
                role_names = data.get('role_names', [])
                if isinstance(role_names, str):
                    role_names = [r.strip() for r in role_names.split(',')]
                criteria['role_names'] = role_names
            elif target_type == 'team':
                team_ids = data.get('team_ids', [])
                if isinstance(team_ids, str):
                    team_ids = [int(i) for i in team_ids.split(',') if i.strip()]
                criteria['team_ids'] = team_ids
            elif target_type == 'league':
                league_ids = data.get('league_ids', [])
                if isinstance(league_ids, str):
                    league_ids = [int(i) for i in league_ids.split(',') if i.strip()]
                criteria['league_ids'] = league_ids
            elif target_type == 'pool':
                criteria['pool_type'] = data.get('pool_type', 'all')
            elif target_type == 'platform':
                criteria['platform'] = data.get('platform', 'all')

        group = NotificationGroup(
            name=name,
            description=description,
            group_type=group_type,
            criteria=criteria,
            created_by=current_user.id,
        )

        db.session.add(group)

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='notification_group_created',
            resource_type='notification_group',
            resource_id=str(group.id),
            new_value=f'Created group: {name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"Created notification group {group.id}: {name}")

        if request.is_json:
            return jsonify({
                'success': True,
                'message': 'Group created successfully',
                'group': group.to_dict()
            })

        flash(f'Notification group "{name}" created successfully', 'success')
        return redirect(url_for('admin_panel.notification_groups_list'))

    except Exception as e:
        logger.error(f"Error creating notification group: {e}")

        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500

        flash('Error creating notification group', 'error')
        return redirect(url_for('admin_panel.notification_groups_list'))


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_groups_detail(group_id):
    """View notification group details."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)

        # Get member count for static groups
        member_count = 0
        if group.is_static:
            member_count = NotificationGroupMember.query.filter_by(group_id=group_id).count()
        else:
            # For dynamic groups, try to estimate reach
            try:
                preview = push_targeting_service.preview_recipient_count(
                    group.criteria.get('target_type', 'all') if group.criteria else 'all',
                    group.criteria.get('team_ids') or group.criteria.get('league_ids') or group.criteria.get('role_names') if group.criteria else None,
                    group.criteria.get('platform') if group.criteria else None
                )
                member_count = preview.get('total_users', 0)
            except Exception:
                member_count = 0

        # Return JSON for AJAX requests
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({
                'success': True,
                'group': {
                    'id': group.id,
                    'name': group.name,
                    'description': group.description,
                    'group_type': group.group_type,
                    'criteria': group.criteria,
                    'is_active': group.is_active,
                    'member_count': member_count,
                    'created_at': group.created_at.strftime('%Y-%m-%d %H:%M') if group.created_at else None,
                    'updated_at': group.updated_at.strftime('%Y-%m-%d %H:%M') if group.updated_at else None
                }
            })

        # For non-AJAX requests, return a rendered page
        # For static groups, get members
        members = []
        if group.is_static:
            members = NotificationGroupMember.query.filter_by(group_id=group_id).join(User).order_by(User.username).all()

        # Get available data for editing
        teams = Team.query.filter_by(is_active=True).order_by(Team.name).all()
        leagues = League.query.filter_by(is_active=True).order_by(League.name).all()
        roles = Role.query.order_by(Role.name).all()

        return render_template(
            'admin_panel/communication/notification_group_detail_flowbite.html',
            group=group,
            members=members,
            member_count=member_count,
            teams=teams,
            leagues=leagues,
            roles=roles,
            page_title=f'Group: {group.name}'
        )
    except Exception as e:
        logger.error(f"Error viewing notification group {group_id}: {e}")
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash('Error loading notification group', 'error')
        return redirect(url_for('admin_panel.notification_groups_list'))


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>', methods=['PUT'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def notification_groups_update(group_id):
    """Update a notification group."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)
        data = request.get_json()

        if 'name' in data:
            group.name = data['name'].strip()
        if 'description' in data:
            group.description = data['description'].strip()
        if 'is_active' in data:
            group.is_active = bool(data['is_active'])

        # Update criteria for dynamic groups
        if group.is_dynamic and 'criteria' in data:
            group.criteria = data['criteria']

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='notification_group_updated',
            resource_type='notification_group',
            resource_id=str(group.id),
            new_value=f'Updated group: {group.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Group updated successfully',
            'group': {
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'group_type': group.group_type,
                'is_active': group.is_active
            }
        })

    except Exception as e:
        logger.error(f"Error updating notification group {group_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def notification_groups_delete(group_id):
    """Delete (deactivate) a notification group."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)
        group_name = group.name

        # Soft delete
        group.is_active = False

        # Log action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='notification_group_deleted',
            resource_type='notification_group',
            resource_id=str(group_id),
            new_value=f'Deleted group: {group_name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Group "{group_name}" deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting notification group {group_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>/members', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_groups_members(group_id):
    """Get members of a static notification group."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)

        if not group.is_static:
            return jsonify({
                'success': False,
                'error': 'Only static groups have explicit members'
            }), 400

        # Get members with user information
        members = db.session.query(NotificationGroupMember, User).join(
            User, NotificationGroupMember.user_id == User.id
        ).filter(
            NotificationGroupMember.group_id == group_id
        ).order_by(User.username).all()

        member_list = [{
            'id': user.id,
            'name': user.username or user.name or 'Unknown',
            'email': user.email or '',
            'added_at': member.added_at.strftime('%Y-%m-%d') if member.added_at else None
        } for member, user in members]

        return jsonify({
            'success': True,
            'members': member_list,
            'count': len(member_list)
        })

    except Exception as e:
        logger.error(f"Error getting group members: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>/members', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def notification_groups_add_member(group_id):
    """Add members to a static notification group."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)

        if not group.is_static:
            return jsonify({
                'success': False,
                'error': 'Can only add members to static groups'
            }), 400

        data = request.get_json()

        # Support both single user_id and user_ids array
        user_ids = data.get('user_ids', [])
        if 'user_id' in data:
            user_ids = [data['user_id']]

        if not user_ids:
            return jsonify({'success': False, 'error': 'user_id or user_ids required'}), 400

        added_count = 0
        for user_id in user_ids:
            # Check if already a member
            existing = NotificationGroupMember.query.filter_by(
                group_id=group_id,
                user_id=user_id
            ).first()

            if not existing:
                member = NotificationGroupMember(
                    group_id=group_id,
                    user_id=user_id,
                    added_by=current_user.id
                )
                db.session.add(member)
                added_count += 1

        return jsonify({
            'success': True,
            'message': f'Added {added_count} member(s)',
            'added_count': added_count
        })

    except Exception as e:
        logger.error(f"Error adding group members: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def notification_groups_remove_member(group_id, user_id):
    """Remove a member from a static notification group."""
    try:
        member = NotificationGroupMember.query.filter_by(
            group_id=group_id,
            user_id=user_id
        ).first_or_404()

        db.session.delete(member)

        return jsonify({
            'success': True,
            'message': 'Member removed successfully'
        })

    except Exception as e:
        logger.error(f"Error removing group member: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>/preview', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_groups_preview(group_id):
    """Preview how many users/tokens a group reaches."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)

        preview = push_targeting_service.preview_recipient_count(
            'group',
            [group_id],
            None
        )

        return jsonify({
            'success': True,
            'group_id': group_id,
            'preview': preview
        })

    except Exception as e:
        logger.error(f"Error previewing group: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/search-users', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_groups_search_users():
    """Search users to add to static groups."""
    try:
        query = request.args.get('q', '').strip()
        limit = request.args.get('limit', 20, type=int)

        if len(query) < 2:
            return jsonify({'success': True, 'users': []})

        # Search by username only (email is encrypted, User has no name column - that's on Player)
        users = User.query.filter(
            User.username.ilike(f'%{query}%')
        ).order_by(User.username).limit(limit).all()

        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'name': u.username or u.name or 'Unknown',
                'email': u.email or ''
            } for u in users]
        })

    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/communication/notification-groups/<int:group_id>/members/search', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def notification_groups_search_members(group_id):
    """Search users to add to a specific static group (excludes existing members)."""
    try:
        group = NotificationGroup.query.get_or_404(group_id)

        if not group.is_static:
            return jsonify({
                'success': False,
                'error': 'Only static groups have explicit members'
            }), 400

        query = request.args.get('q', '').strip()
        limit = request.args.get('limit', 20, type=int)

        if len(query) < 2:
            return jsonify({'success': True, 'users': []})

        # Get existing member IDs
        existing_member_ids = db.select(NotificationGroupMember.user_id).where(
            NotificationGroupMember.group_id == group_id
        )

        # Search users not already in the group (email is encrypted, User has no name column)
        users = User.query.filter(
            User.username.ilike(f'%{query}%'),
            User.id.not_in(existing_member_ids)
        ).order_by(User.username).limit(limit).all()

        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'name': u.username or u.name or 'Unknown',
                'email': u.email or ''
            } for u in users]
        })

    except Exception as e:
        logger.error(f"Error searching users for group: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# API endpoints for AJAX
@admin_panel_bp.route('/api/notification-groups')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_notification_groups_list():
    """API: List notification groups."""
    try:
        groups = NotificationGroup.query.filter_by(is_active=True).order_by(
            NotificationGroup.name
        ).all()

        return jsonify({
            'success': True,
            'groups': [g.to_dict() for g in groups]
        })

    except Exception as e:
        logger.error(f"Error listing groups API: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
