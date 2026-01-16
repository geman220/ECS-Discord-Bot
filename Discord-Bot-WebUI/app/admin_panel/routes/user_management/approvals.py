# app/admin_panel/routes/user_management/approvals.py

"""
User Approvals Routes

Routes for user approval workflow:
- User approvals management page
- Approve/deny users
- User details for approval modal
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role
from app.models.ecs_fc import is_ecs_fc_team
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_management():
    """User management hub page."""
    try:
        # Get user statistics
        total_users = User.query.count()
        pending_approvals = User.query.filter_by(approval_status='pending').count()
        approved_users = User.query.filter_by(approval_status='approved').count()
        denied_users = User.query.filter_by(approval_status='denied').count()

        # Get waitlist statistics
        waitlist_users = User.query.join(User.roles).filter(Role.name == 'pl-waitlist').count()

        # Get role statistics
        total_roles = Role.query.count()
        users_with_roles = User.query.join(User.roles).distinct().count()

        # Get recent admin actions related to users
        recent_actions = AdminAuditLog.query.filter(
            AdminAuditLog.resource_type.in_(['user_approval', 'user_waitlist', 'user_roles'])
        ).order_by(AdminAuditLog.timestamp.desc()).limit(10).all()

        stats = {
            'total_users': total_users,
            'pending_approvals': pending_approvals,
            'approved_users': approved_users,
            'denied_users': denied_users,
            'waitlist_users': waitlist_users,
            'total_roles': total_roles,
            'users_with_roles': users_with_roles,
            'recent_actions': len(recent_actions)
        }

        return render_template('admin_panel/users/management_flowbite.html',
                               stats=stats,
                               recent_actions=recent_actions)
    except Exception as e:
        logger.error(f"Error loading user management: {e}")
        flash('User management dashboard unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/users/approvals')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def user_approvals():
    """User approvals management page with filtering."""
    try:
        current_user_safe = safe_current_user

        # Get filter parameters
        status_filter = request.args.get('status', '').strip()
        league_filter = request.args.get('league', '').strip()
        search_query = request.args.get('search', '').strip()

        # Build query for users
        query = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        )

        # Apply status filter (default to pending if not specified)
        if status_filter == 'approved':
            query = query.filter(User.approval_status == 'approved')
        elif status_filter == 'denied':
            query = query.filter(User.approval_status == 'denied')
        elif status_filter == 'all':
            pass  # No filter, show all
        else:
            # Default to pending
            query = query.filter(User.approval_status == 'pending')
            status_filter = 'pending'

        # Apply league filter
        if league_filter:
            # Filter by roles that match league patterns
            if league_filter == 'pl-classic':
                query = query.join(User.roles).filter(Role.name.ilike('%classic%'))
            elif league_filter == 'pl-premier':
                query = query.join(User.roles).filter(Role.name.ilike('%premier%'))
            elif league_filter == 'ecs-fc':
                query = query.join(User.roles).filter(
                    or_(Role.name.ilike('%ecs%fc%'), Role.name.ilike('%ecsfc%'))
                )

        # Apply search filter (email is encrypted, search by username only)
        if search_query:
            search_term = f'%{search_query}%'
            query = query.filter(User.username.ilike(search_term))

        # Order by creation date
        pending_users = query.order_by(User.created_at.desc()).all()

        # Get recent approval actions (always show recent activity)
        recent_actions = []
        try:
            recent_actions = db.session.query(User).options(
                joinedload(User.player),
                joinedload(User.roles)
            ).filter(
                User.approval_status.in_(['approved', 'denied']),
                User.approved_at.isnot(None)
            ).order_by(User.approved_at.desc()).limit(20).all()

            # Add approved_by_user information
            for user in recent_actions:
                if user.approved_by:
                    user.approved_by_user = db.session.query(User).filter_by(id=user.approved_by).first()
        except Exception as e:
            logger.error(f"Error loading recent actions: {str(e)}")
            recent_actions = []

        # Count statistics
        stats = {
            'pending_count': db.session.query(func.count(User.id)).filter(User.approval_status == 'pending').scalar(),
            'total_approved': db.session.query(func.count(User.id)).filter(User.approval_status == 'approved').scalar(),
            'total_denied': db.session.query(func.count(User.id)).filter(User.approval_status == 'denied').scalar()
        }

        # Get audit log entries for user approvals
        audit_logs = []
        try:
            audit_logs = db.session.query(AdminAuditLog).options(
                joinedload(AdminAuditLog.user)
            ).filter(
                AdminAuditLog.resource_type == 'user_approval'
            ).order_by(AdminAuditLog.timestamp.desc()).limit(20).all()
        except Exception as e:
            logger.error(f"Error loading audit logs: {str(e)}")
            audit_logs = []

        return render_template(
            'admin_panel/users/user_approvals_flowbite.html',
            pending_users=pending_users,
            recent_actions=recent_actions,
            audit_logs=audit_logs,
            stats=stats,
            # Pass filter values back to template for form persistence
            status_filter=status_filter,
            league_filter=league_filter,
            search_query=search_query
        )
    except Exception as e:
        logger.error(f"Error loading user approvals: {e}")
        flash('User approvals unavailable. Check database connectivity and user models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/approvals/approve/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def approve_user(user_id: int):
    """
    Approve a user for a specific league.
    Assigns appropriate roles and updates Discord.
    """
    try:
        current_user_safe = safe_current_user

        # Get the user to approve
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Check if user has pl-waitlist role (can approve directly from waitlist)
        has_waitlist_role = any(role.name == 'pl-waitlist' for role in user.roles)

        # Allow approving users who are pending OR on waitlist
        if user.approval_status != 'pending' and not has_waitlist_role:
            return jsonify({'success': False, 'message': 'User is not pending approval or on waitlist'}), 400

        # Get form data
        league_type = request.form.get('league_type')
        notes = request.form.get('notes', '')

        valid_league_types = ['classic', 'premier', 'ecs-fc', 'sub-classic', 'sub-premier', 'sub-ecs-fc']
        if not league_type or league_type not in valid_league_types:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        # Get the appropriate role
        role_mapping = {
            'classic': 'pl-classic',
            'premier': 'pl-premier',
            'ecs-fc': 'pl-ecs-fc',
            'sub-classic': 'Classic Sub',
            'sub-premier': 'Premier Sub',
            'sub-ecs-fc': 'ECS FC Sub'
        }

        new_role_name = role_mapping[league_type]
        new_role = db.session.query(Role).filter_by(name=new_role_name).first()

        if not new_role:
            return jsonify({'success': False, 'message': f'Role {new_role_name} not found'}), 404

        # Remove the pl-unverified role
        unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
        if unverified_role and unverified_role in user.roles:
            user.roles.remove(unverified_role)

        # Remove the pl-waitlist role (if user was on waitlist)
        waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
        if waitlist_role and waitlist_role in user.roles:
            user.roles.remove(waitlist_role)

        # Remove any existing league roles before adding new one (prevent role accumulation)
        existing_league_roles = ['pl-premier', 'pl-classic', 'pl-ecs-fc']
        for league_role_name in existing_league_roles:
            if league_role_name != new_role_name:  # Don't remove the one we're about to add
                existing_role = db.session.query(Role).filter_by(name=league_role_name).first()
                if existing_role and existing_role in user.roles:
                    user.roles.remove(existing_role)
                    logger.info(f"Removed old league role {league_role_name} from user {user.id}")

        # Add the new approved role
        if new_role not in user.roles:
            user.roles.append(new_role)

        # Update user approval status
        user.approval_status = 'approved'
        user.is_approved = True
        user.approval_league = league_type
        user.approved_by = current_user_safe.id
        user.approved_at = datetime.utcnow()
        user.approval_notes = notes

        # Clear waitlist timestamp - user now has a spot
        user.waitlist_joined_at = None

        db.session.add(user)
        db.session.flush()

        # Trigger Discord role sync
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for approved user {user.id}")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='approve_user',
            resource_type='user_approval',
            resource_id=str(user_id),
            old_value='pending',
            new_value=f'approved:{league_type}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"User {user.id} approved for {league_type} league by {current_user_safe.id}")

        return jsonify({
            'success': True,
            'message': f'User {user.username} approved for {league_type.title()} league',
            'user_id': user.id,
            'league_type': league_type,
            'approved_by': current_user_safe.username,
            'approved_at': user.approved_at.isoformat()
        })

    except Exception as e:
        logger.error(f"Error approving user {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error processing approval'}), 500


@admin_panel_bp.route('/users/approvals/deny/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def deny_user(user_id: int):
    """
    Deny a user's application.
    Removes Discord roles and updates status.
    """
    try:
        current_user_safe = safe_current_user

        # Get the user to deny
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if user.approval_status != 'pending':
            return jsonify({'success': False, 'message': 'User is not pending approval'}), 400

        # Get form data
        notes = request.form.get('notes', '')

        # Remove all roles except basic ones
        unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
        if unverified_role and unverified_role in user.roles:
            user.roles.remove(unverified_role)

        # Update user approval status
        user.approval_status = 'denied'
        user.approval_league = None
        user.approved_by = current_user_safe.id
        user.approved_at = datetime.utcnow()
        user.approval_notes = notes

        db.session.add(user)
        db.session.flush()

        # Remove Discord roles
        if user.player and user.player.discord_id:
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for denied user {user.id}")

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='deny_user',
            resource_type='user_approval',
            resource_id=str(user_id),
            old_value='pending',
            new_value='denied',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        logger.info(f"User {user.id} denied by {current_user_safe.id}")

        return jsonify({
            'success': True,
            'message': f'User {user.username} application denied',
            'user_id': user.id,
            'denied_by': current_user_safe.username,
            'denied_at': user.approved_at.isoformat()
        })

    except Exception as e:
        logger.error(f"Error denying user {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error processing denial'}), 500


@admin_panel_bp.route('/users/approvals/process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_user_approval():
    """Legacy route for bulk approval processing."""
    try:
        action = request.form.get('action')
        user_id = request.form.get('user_id')

        if action == 'approve_all':
            # Approve all pending users for classic league (default)
            pending_users = User.query.filter_by(approval_status='pending').all()
            approved_count = 0

            for user in pending_users:
                # Redirect to individual approval with default league
                try:
                    # This is a simplified bulk approval - in practice you might want more control
                    if user.approval_status == 'pending':
                        user.approval_status = 'approved'
                        user.is_approved = True
                        user.approved_by = current_user.id
                        user.approved_at = datetime.utcnow()
                        approved_count += 1
                except Exception as e:
                    logger.error(f"Error bulk approving user {user.id}: {e}")

            db.session.commit()

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='approve_all',
                resource_type='user_approval',
                resource_id='bulk',
                new_value=f"Approved {approved_count} users",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            flash(f'{approved_count} pending users approved successfully', 'success')

        return redirect(url_for('admin_panel.user_approvals'))
    except Exception as e:
        logger.error(f"Error processing user approval: {e}")
        flash('User approval processing failed. Check database connectivity and role assignment.', 'error')
        return redirect(url_for('admin_panel.user_approvals'))


@admin_panel_bp.route('/users/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_user_details():
    """Get detailed information about a user for the approval modal."""
    try:
        user_id = request.args.get('user_id')

        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'approval_status': user.approval_status,
            'approval_league': user.approval_league,
            'approval_notes': user.approval_notes,
            'is_approved': user.is_approved,
            'roles': [role.name for role in user.roles],
            'player': {
                'id': user.player.id,
                'name': user.player.name,
                'discord_id': user.player.discord_id,
                'is_current_player': user.player.is_current_player,
                'is_sub': user.player.is_sub,
                'is_coach': user.player.is_coach,
                'phone': user.player.phone,
                'jersey_size': user.player.jersey_size,
                'pronouns': user.player.pronouns,
                'favorite_position': user.player.favorite_position,
                'profile_picture_url': user.player.profile_picture_url
            } if user.player else None
        }

        return jsonify({'success': True, 'user': user_data})

    except Exception as e:
        logger.error(f"Error getting user details for {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error retrieving user details'}), 500


@admin_panel_bp.route('/api/users/<int:user_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_details_api(user_id):
    """Get detailed user information for modal display."""
    try:
        user = User.query.options(
            joinedload(User.player),
            joinedload(User.roles)
        ).get(user_id)

        if not user:
            logger.warning(f"User ID {user_id} not found in database - may be stale data in UI")
            return jsonify({
                'success': False,
                'error': f'User with ID {user_id} not found. Please refresh the page.',
                'user_id': user_id
            }), 404

        user_data = {
            'id': user.id,
            'first_name': getattr(user, 'first_name', None),
            'last_name': getattr(user, 'last_name', None),
            'username': user.username,
            'email': user.email,
            'real_name': user.player.name if user.player else None,
            'phone': getattr(user, 'phone', None),
            'discord_username': getattr(user, 'discord_username', None),
            'status': getattr(user, 'status', user.approval_status),
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'last_login': getattr(user, 'last_login', None),
            'role': user.roles[0].name if user.roles else None,
            'all_roles': [role.name for role in user.roles],
            'roles': [role.id for role in user.roles],  # Array of role IDs for form
            'approval_status': user.approval_status,
            'approval_league': user.approval_league,
            'approval_notes': user.approval_notes,
            'is_approved': user.is_approved,
            'is_active': user.is_active
        }

        # Add profile information if available
        if user.player:
            # Get all team IDs for players on multiple teams
            all_team_ids = [team.id for team in user.player.teams] if user.player.teams else []
            # Get secondary leagues (other_leagues relationship)
            other_league_ids = [lg.id for lg in user.player.other_leagues] if user.player.other_leagues else []

            # Find secondary team (first team that's not the primary team)
            secondary_team_id = None
            secondary_league_id = other_league_ids[0] if other_league_ids else None
            for team in user.player.teams:
                if team.id != user.player.primary_team_id:
                    secondary_team_id = team.id
                    # Also get that team's league if we don't have a secondary league yet
                    if not secondary_league_id and team.league_id:
                        secondary_league_id = team.league_id
                    break

            # Get ECS FC team IDs (for multi-team selection)
            ecs_fc_team_ids = [
                team.id for team in user.player.teams
                if is_ecs_fc_team(team.id)
            ] if user.player.teams else []

            # Get league names for direct type detection
            primary_league_name = user.player.primary_league.name if user.player.primary_league else None
            other_league_names = [lg.name for lg in user.player.other_leagues] if user.player.other_leagues else []

            user_data['has_player'] = True
            user_data['player'] = {
                'id': user.player.id,
                'name': user.player.name,
                'league_id': user.player.primary_league_id,
                'primary_league_name': primary_league_name,
                'team_id': user.player.primary_team_id,
                'secondary_league_id': secondary_league_id,
                'secondary_team_id': secondary_team_id,
                'other_league_ids': other_league_ids,
                'other_league_names': other_league_names,
                'team_ids': all_team_ids,
                'ecs_fc_team_ids': ecs_fc_team_ids,
                'is_current_player': user.player.is_current_player,
                'discord_id': user.player.discord_id,
                'jersey_size': user.player.jersey_size,
                'phone': user.player.phone,
                'pronouns': user.player.pronouns,
                'favorite_position': user.player.favorite_position,
                'profile_picture_url': user.player.profile_picture_url
            }
        else:
            user_data['has_player'] = False
            user_data['player'] = None

        return jsonify({'success': True, 'user': user_data})

    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return jsonify({'success': False, 'error': 'Failed to get user details'}), 500
