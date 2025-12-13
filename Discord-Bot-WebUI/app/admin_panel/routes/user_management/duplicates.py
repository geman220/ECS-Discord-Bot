# app/admin_panel/routes/user_management/duplicates.py

"""
Duplicate Registration Management Routes

Routes for duplicate detection and management:
- Duplicate registrations page
- Scan for duplicates
- Merge duplicate accounts
- Dismiss duplicate flags
"""

import logging

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role
from app.decorators import role_required
from app.tasks.tasks_discord import assign_roles_to_player_task
from app.admin_panel.routes.user_management.helpers import find_duplicate_registrations

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users/duplicates')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def duplicate_registrations():
    """Display and manage potential duplicate registrations."""
    try:
        # Find potential duplicates based on email patterns, names, and Discord IDs
        duplicate_groups = find_duplicate_registrations()

        # Get statistics
        stats = {
            'total_groups': len(duplicate_groups),
            'total_potential_duplicates': sum(len(group['users']) for group in duplicate_groups),
            'by_email': len([g for g in duplicate_groups if g['match_type'] == 'email']),
            'by_name': len([g for g in duplicate_groups if g['match_type'] == 'name']),
            'by_discord': len([g for g in duplicate_groups if g['match_type'] == 'discord'])
        }

        return render_template('admin_panel/users/duplicates.html',
                               duplicate_groups=duplicate_groups,
                               stats=stats)
    except Exception as e:
        logger.error(f"Error loading duplicate registrations: {e}")
        flash('Duplicate detection unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/duplicates/scan', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def scan_for_duplicates():
    """Manually trigger a scan for duplicate registrations."""
    try:
        duplicate_groups = find_duplicate_registrations()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='scan_duplicates',
            resource_type='duplicate_management',
            resource_id='scan',
            new_value=f'Found {len(duplicate_groups)} potential duplicate groups',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Scan complete. Found {len(duplicate_groups)} potential duplicate groups.',
            'groups': len(duplicate_groups),
            'total_duplicates': sum(len(group['users']) for group in duplicate_groups)
        })
    except Exception as e:
        logger.error(f"Error scanning for duplicates: {e}")
        return jsonify({'success': False, 'message': 'Scan failed'}), 500


@admin_panel_bp.route('/users/duplicates/merge', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def merge_duplicate_users():
    """Merge duplicate user accounts into a primary account."""
    try:
        data = request.get_json()
        primary_user_id = data.get('primary_user_id')
        duplicate_user_ids = data.get('duplicate_user_ids', [])

        if not primary_user_id or not duplicate_user_ids:
            return jsonify({'success': False, 'message': 'Primary user and duplicates must be specified'}), 400

        if primary_user_id in duplicate_user_ids:
            return jsonify({'success': False, 'message': 'Primary user cannot be in duplicates list'}), 400

        # Get the primary user
        primary_user = User.query.options(
            joinedload(User.player),
            joinedload(User.roles)
        ).get(primary_user_id)

        if not primary_user:
            return jsonify({'success': False, 'message': 'Primary user not found'}), 404

        merged_count = 0
        merge_details = []

        for dup_id in duplicate_user_ids:
            duplicate_user = User.query.options(
                joinedload(User.player),
                joinedload(User.roles)
            ).get(dup_id)

            if not duplicate_user:
                merge_details.append({'id': dup_id, 'status': 'not_found'})
                continue

            try:
                # Merge roles
                for role in duplicate_user.roles:
                    if role not in primary_user.roles:
                        primary_user.roles.append(role)

                # If duplicate has player but primary doesn't, transfer it
                if duplicate_user.player and not primary_user.player:
                    duplicate_user.player.user_id = primary_user.id
                    duplicate_user.player = None
                elif duplicate_user.player and primary_user.player:
                    # Merge player data - prefer primary but fill in gaps
                    primary_player = primary_user.player
                    dup_player = duplicate_user.player

                    if not primary_player.discord_id and dup_player.discord_id:
                        primary_player.discord_id = dup_player.discord_id
                    if not primary_player.phone and dup_player.phone:
                        primary_player.phone = dup_player.phone

                    # Mark duplicate player as merged
                    dup_player.merged_into = primary_player.id
                    dup_player.is_current_player = False

                # Mark duplicate user as merged
                duplicate_user.is_active = False
                duplicate_user.approval_status = 'merged'
                duplicate_user.approval_notes = f'Merged into user {primary_user_id}'

                merged_count += 1
                merge_details.append({'id': dup_id, 'status': 'merged', 'username': duplicate_user.username})

            except Exception as e:
                logger.error(f"Error merging user {dup_id}: {e}")
                merge_details.append({'id': dup_id, 'status': 'error', 'error': str(e)})

        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='merge_duplicates',
            resource_type='duplicate_management',
            resource_id=str(primary_user_id),
            new_value=f'Merged {merged_count} users into {primary_user.username}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Sync Discord roles for primary user
        if primary_user.player and primary_user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=primary_user.player.id, only_add=False)

        return jsonify({
            'success': True,
            'message': f'Successfully merged {merged_count} accounts into {primary_user.username}',
            'merged_count': merged_count,
            'details': merge_details
        })

    except Exception as e:
        logger.error(f"Error merging duplicate users: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Merge failed'}), 500


@admin_panel_bp.route('/users/duplicates/dismiss', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def dismiss_duplicate():
    """Dismiss a potential duplicate (mark as not a duplicate)."""
    try:
        data = request.get_json()
        user_ids = data.get('user_ids', [])

        if len(user_ids) < 2:
            return jsonify({'success': False, 'message': 'At least 2 user IDs required'}), 400

        # Store dismissal in a simple way - we'll use approval_notes for now
        # In production, you'd want a separate table for this
        for user_id in user_ids:
            user = User.query.get(user_id)
            if user:
                dismissed_ids = user_ids.copy()
                dismissed_ids.remove(user_id)
                existing_notes = user.approval_notes or ''
                user.approval_notes = f"{existing_notes}\n[NOT_DUP:{','.join(map(str, dismissed_ids))}]"

        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='dismiss_duplicate',
            resource_type='duplicate_management',
            resource_id=','.join(map(str, user_ids)),
            new_value='Dismissed as not duplicates',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': 'Duplicate group dismissed'
        })

    except Exception as e:
        logger.error(f"Error dismissing duplicate: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Dismissal failed'}), 500
