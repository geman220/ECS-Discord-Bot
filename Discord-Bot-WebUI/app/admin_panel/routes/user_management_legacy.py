# app/admin_panel/routes/user_management.py

"""
Admin Panel User Management Routes

This module contains routes for user management functionality:
- User management hub with statistics
- User approvals management (pending, approve, deny)
- Roles and permissions management
- User waitlist management
- Bulk user operations
- User details and role assignments
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role, League
from app.models import Player, Team
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.utils.user_helpers import safe_current_user

# Set up the module logger
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
        
        return render_template('admin_panel/users/management.html', 
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

        # Apply search filter
        if search_query:
            search_term = f'%{search_query}%'
            query = query.filter(
                or_(
                    User.username.ilike(search_term),
                    User.email.ilike(search_term)
                )
            )

        # Order by creation date
        pending_users = query.order_by(User.created_at.desc()).all()

        # Get recent approval actions (always show recent activity)
        recent_actions = []
        try:
            recent_actions = db.session.query(User).options(
                joinedload(User.player)
            ).filter(
                User.approval_status.in_(['approved', 'denied']),
                User.approved_at >= datetime.utcnow() - timedelta(days=30)
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

        return render_template(
            'admin_panel/users/approvals.html',
            pending_users=pending_users,
            recent_actions=recent_actions,
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
        
        if user.approval_status != 'pending':
            return jsonify({'success': False, 'message': 'User is not pending approval'}), 400
        
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
        db.session.rollback()
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
        db.session.rollback()
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
        ).get_or_404(user_id)

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

            user_data['has_player'] = True
            user_data['player'] = {
                'id': user.player.id,
                'name': user.player.name,
                'league_id': user.player.primary_league_id,
                'team_id': user.player.primary_team_id,
                'secondary_league_id': secondary_league_id,
                'secondary_team_id': secondary_team_id,
                'team_ids': all_team_ids,
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


@admin_panel_bp.route('/users/manage')
@admin_panel_bp.route('/users-management')  # Alias for template compatibility
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def users_comprehensive():
    """Comprehensive user management page."""
    try:
        from app.models import League, Season
        from datetime import datetime, timedelta

        # Get filter parameters
        search = request.args.get('search', '').strip()
        role_filter = request.args.get('role', '').strip()
        approved_filter = request.args.get('approved', '').strip()
        active_filter = request.args.get('active', '').strip()
        league_filter = request.args.get('league', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 50

        # Build query with eager loading
        query = User.query.options(
            joinedload(User.roles),
            joinedload(User.player)
        )

        # Apply filters
        if search:
            search_term = f'%{search}%'
            # Note: User.email is encrypted, so we can only search username with ILIKE
            # For exact email match, we check the email_hash
            # Player.name IS a real column and can be searched with ILIKE
            from app.utils.pii_encryption import create_hash
            email_hash = create_hash(search.lower()) if '@' in search else None

            if email_hash:
                # If search looks like an email, try exact match via hash
                query = query.filter(
                    or_(
                        User.username.ilike(search_term),
                        User.email_hash == email_hash
                    )
                )
            else:
                # Search username and player name (via outerjoin)
                query = query.outerjoin(Player, User.player).filter(
                    or_(
                        User.username.ilike(search_term),
                        Player.name.ilike(search_term)
                    )
                )

        if role_filter:
            query = query.join(User.roles).filter(Role.name == role_filter)

        if approved_filter:
            if approved_filter == 'true':
                query = query.filter(User.is_approved == True)
            elif approved_filter == 'false':
                query = query.filter(
                    or_(User.is_approved == False, User.is_approved == None)
                )

        if active_filter:
            if active_filter == 'true':
                query = query.filter(User.is_active == True)
            elif active_filter == 'false':
                query = query.filter(
                    or_(User.is_active == False, User.is_active == None)
                )

        # Order and paginate
        query = query.order_by(User.username)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        users = pagination.items

        # Get all roles and leagues for filter dropdowns
        all_roles = Role.query.order_by(Role.name).all()
        # Get leagues from current seasons only
        all_leagues = League.query.join(Season).filter(Season.is_current == True).order_by(League.name).all()

        # Calculate statistics (for stat cards)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        stats = {
            'total_users': User.query.count(),
            'active_users': User.query.filter(User.is_active == True).count(),
            'approved_users': User.query.filter(User.is_approved == True).count(),
            'pending_approval': User.query.filter(
                or_(User.is_approved == False, User.is_approved == None)
            ).count(),
            'recent_registrations': User.query.filter(
                User.created_at >= thirty_days_ago
            ).count(),
            'total_roles': len(all_roles)
        }

        return render_template('admin_panel/users/manage_users_comprehensive.html',
                             users=users,
                             roles=all_roles,
                             Role=Role,  # Pass Role model for template
                             stats=stats,
                             pagination=pagination,
                             leagues=all_leagues,
                             search=search,
                             role_filter=role_filter,
                             approved_filter=approved_filter,
                             active_filter=active_filter,
                             league_filter=league_filter)
    except Exception as e:
        logger.error(f"Error loading user management: {e}")
        flash('User management unavailable. Verify database connection and user models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def roles_management():
    """Roles and permissions management page."""
    try:
        roles = Role.query.order_by(Role.name).all()
        users = User.query.order_by(User.username).all()
        
        # Get statistics
        users_with_roles = User.query.join(User.roles).distinct().count()
        admin_roles = len([r for r in roles if 'Admin' in r.name])
        
        return render_template('admin_panel/users/roles.html',
                             roles=roles,
                             users=users,
                             permissions=[],  # TODO: Get from permissions if available
                             users_with_roles=users_with_roles,
                             admin_roles=admin_roles)
    except Exception as e:
        logger.error(f"Error loading roles management: {e}")
        flash('Roles management unavailable. Verify database connection and role models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/roles/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_role_details():
    """Get role details via AJAX."""
    try:
        role_id = request.args.get('role_id')
        role = Role.query.get_or_404(role_id)
        
        # Build role details HTML
        details_html = f"""
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0">Role Information</h6>
                    </div>
                    <div class="card-body">
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Name:</strong></div>
                            <div class="col-sm-8">{role.name}</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Description:</strong></div>
                            <div class="col-sm-8">{role.description or 'No description'}</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Users:</strong></div>
                            <div class="col-sm-8">{len(role.users)} users</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-sm-4"><strong>Permissions:</strong></div>
                            <div class="col-sm-8">{len(role.permissions)} permissions</div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0">Users with this Role</h6>
                    </div>
                    <div class="card-body">
                        {"<br>".join([user.username for user in role.users[:10]]) if role.users else "No users assigned"}
                        {"<br><small class='text-muted'>... and " + str(len(role.users) - 10) + " more</small>" if len(role.users) > 10 else ""}
                    </div>
                </div>
            </div>
        </div>
        """
        
        return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting role details: {e}")
        return jsonify({'success': False, 'message': 'Error loading role details'})


@admin_panel_bp.route('/users/waitlist')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def user_waitlist():
    """
    Display the user waitlist management interface.
    Shows users on the waitlist.
    """
    try:
        current_user_safe = safe_current_user
        
        # Get all users with pl-waitlist role
        waitlist_users = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).join(User.roles).filter(
            Role.name == 'pl-waitlist'
        ).order_by(User.created_at.desc()).all()
        
        # Get recently removed users for reference
        recent_actions = []
        try:
            # Get users who previously had pl-waitlist role but no longer do
            # This is a simplified approach - in production you might want to track this in a separate table
            recent_actions = []  # For now, we'll leave this empty until we implement proper tracking
            
        except Exception as e:
            logger.error(f"Error loading recent actions: {str(e)}")
            recent_actions = []
        
        # Count statistics
        stats = {
            'waitlist_count': len(waitlist_users),
            'total_registered': db.session.query(func.count(User.id)).scalar(),
            'total_approved': db.session.query(func.count(User.id)).filter(User.approval_status == 'approved').scalar(),
            'processed_count': db.session.query(func.count(User.id)).filter(
                User.approval_status == 'approved',
                User.approved_at >= datetime.utcnow() - timedelta(days=30)
            ).scalar(),
            'avg_wait_time': _calculate_avg_wait_time(),
            'processing_rate': _calculate_processing_rate(),
            'conversion_rate': _calculate_conversion_rate()
        }
        
        return render_template(
            'admin_panel/users/waitlist.html',
            waitlist_users=waitlist_users,
            recent_actions=recent_actions,
            now=datetime.utcnow(),
            **stats
        )
    except Exception as e:
        logger.error(f"Error loading user waitlist: {e}")
        flash('User waitlist unavailable. Check database connectivity and waitlist data.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/waitlist/remove/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def remove_from_waitlist(user_id: int):
    """
    Remove a user from the waitlist.
    """
    try:
        current_user_safe = safe_current_user
        
        # Get the user
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Get the pl-waitlist role
        waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
        if not waitlist_role:
            return jsonify({'success': False, 'message': 'Waitlist role not found'}), 404
        
        # Check if user is on waitlist
        if waitlist_role not in user.roles:
            return jsonify({'success': False, 'message': 'User is not on waitlist'}), 400
        
        # Get removal reason from request
        reason = request.json.get('reason', 'No reason provided')
        
        # Remove the waitlist role
        user.roles.remove(waitlist_role)
        
        # Clear waitlist joined timestamp since they're no longer on waitlist
        if hasattr(user, 'waitlist_joined_at'):
            user.waitlist_joined_at = None
        
        # Update user record
        user.updated_at = datetime.utcnow()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='remove_from_waitlist',
            resource_type='user_waitlist',
            resource_id=str(user_id),
            old_value='on_waitlist',
            new_value=f'removed: {reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        logger.info(f"User {user.id} ({user.username}) removed from waitlist by {current_user_safe.id} ({current_user_safe.username}). Reason: {reason}")
        
        # Commit the changes
        db.session.flush()
        
        # Sync Discord roles if user has Discord integration
        if user.player and user.player.discord_id:
            try:
                # Remove Discord roles (this will remove the waitlist Discord role)
                remove_player_roles_task.delay(player_id=user.player.id)
                logger.info(f"Queued Discord role removal for user {user.id}")
            except Exception as e:
                logger.error(f"Failed to queue Discord role removal for user {user.id}: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'User {user.username} removed from waitlist successfully',
            'user_id': user.id
        })
        
    except Exception as e:
        logger.error(f"Error removing user {user_id} from waitlist: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to remove user from waitlist'}), 500


@admin_panel_bp.route('/users/waitlist/contact/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def contact_waitlist_user(user_id: int):
    """
    Contact a user on the waitlist (placeholder for future implementation).
    """
    try:
        current_user_safe = safe_current_user
        
        # Get the user
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Get contact message from request
        message = request.json.get('message', '')
        contact_method = request.json.get('contact_method', 'email')
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='contact_waitlist_user',
            resource_type='user_waitlist',
            resource_id=str(user_id),
            new_value=f'contacted via {contact_method}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        logger.info(f"Contact initiated for waitlist user {user.id} ({user.username}) by {current_user_safe.id} ({current_user_safe.username}). Method: {contact_method}")
        
        # TODO: Implement actual contact functionality (email, Discord DM, etc.)
        # For now, we'll just log and return success
        
        return jsonify({
            'success': True,
            'message': f'Contact logged for user {user.username}',
            'user_id': user.id
        })
        
    except Exception as e:
        logger.error(f"Error contacting waitlist user {user_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to contact user'}), 500


@admin_panel_bp.route('/users/waitlist/user/<int:user_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_waitlist_user_details(user_id: int):
    """
    Get detailed information about a waitlist user for display in modal.
    """
    try:
        # Get the user with all necessary relationships
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Build user details dictionary
        user_details = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None,
            'approval_status': user.approval_status,
            'preferred_league': getattr(user, 'preferred_league', None),
            'roles': [role.name for role in user.roles],
            'player': {}
        }
        
        # Add player information if available
        if user.player:
            user_details['player'] = {
                'id': user.player.id,
                'name': user.player.name,
                'discord_id': user.player.discord_id,
                'phone': user.player.phone,
                'pronouns': user.player.pronouns,
                'jersey_size': user.player.jersey_size,
                'jersey_number': user.player.jersey_number,
                'profile_picture_url': user.player.profile_picture_url,
                'additional_info': user.player.additional_info,
                'player_notes': user.player.player_notes,
                'is_sub': user.player.is_sub,
                'interested_in_sub': user.player.interested_in_sub,
                'favorite_position': user.player.favorite_position,
                'other_positions': user.player.other_positions,
                'positions_not_to_play': user.player.positions_not_to_play,
                'frequency_play_goal': user.player.frequency_play_goal,
                'expected_weeks_available': user.player.expected_weeks_available,
                'willing_to_referee': user.player.willing_to_referee,
                'unavailable_dates': user.player.unavailable_dates
            }
        
        return jsonify({
            'success': True,
            'user': user_details
        })
        
    except Exception as e:
        logger.error(f"Error getting waitlist user details for user {user_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to get user details'}), 500


@admin_panel_bp.route('/users/waitlist/process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_waitlist_user():
    """Legacy route for bulk waitlist processing."""
    try:
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        
        if action == 'process_all':
            # Process all waitlist users - move them to pending approval
            waitlist_users = db.session.query(User).join(User.roles).filter(
                Role.name == 'pl-waitlist'
            ).all()
            
            processed_count = 0
            for user in waitlist_users:
                try:
                    # Remove waitlist role and add unverified role
                    waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
                    unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
                    
                    if waitlist_role in user.roles:
                        user.roles.remove(waitlist_role)
                    if unverified_role and unverified_role not in user.roles:
                        user.roles.append(unverified_role)
                    
                    user.approval_status = 'pending'
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing waitlist user {user.id}: {e}")
            
            db.session.commit()
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='process_all_waitlist',
                resource_type='user_waitlist',
                resource_id='bulk',
                new_value=f"Moved {processed_count} users from waitlist to pending approval",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'{processed_count} users moved from waitlist to pending approval', 'success')
        
        return redirect(url_for('admin_panel.user_waitlist'))
    except Exception as e:
        logger.error(f"Error processing waitlist users: {e}")
        flash('Waitlist processing failed. Check database connectivity and user operations.', 'error')
        return redirect(url_for('admin_panel.user_waitlist'))


@admin_panel_bp.route('/users/roles/assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_user_roles():
    """Assign roles to a user."""
    try:
        user_id = request.form.get('user_id')
        role_ids = request.form.getlist('role_ids')
        
        if not user_id:
            flash('User ID is required', 'error')
            return redirect(url_for('admin_panel.roles_management'))
        
        user = User.query.get_or_404(user_id)
        
        # Clear existing roles and assign new ones
        user.roles.clear()
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                user.roles.append(role)
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='assign_roles',
            resource_type='user_roles',
            resource_id=str(user_id),
            new_value=f"Assigned roles: {', '.join([Role.query.get(rid).name for rid in role_ids if Role.query.get(rid)])}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash(f'Roles assigned to "{user.name or user.username}" successfully', 'success')
        return redirect(url_for('admin_panel.roles_management'))
    except Exception as e:
        logger.error(f"Error assigning user roles: {e}")
        flash('Role assignment failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.roles_management'))


@admin_panel_bp.route('/users/roles/search', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def search_users_by_role():
    """Search users by role."""
    try:
        role_id = request.form.get('role_id')
        
        if not role_id:
            flash('Role ID is required', 'error')
            return redirect(url_for('admin_panel.roles_management'))
        
        role = Role.query.get_or_404(role_id)
        search_results = role.users
        search_role_name = role.name
        
        # Get all roles and users for the template
        roles = Role.query.order_by(Role.name).all()
        users = User.query.order_by(User.username).all()
        users_with_roles = User.query.join(User.roles).distinct().count()
        admin_roles = len([r for r in roles if 'Admin' in r.name])
        
        return render_template('admin_panel/users/roles.html',
                             roles=roles,
                             users=users,
                             permissions=[],
                             users_with_roles=users_with_roles,
                             admin_roles=admin_roles,
                             search_results=search_results,
                             search_role_name=search_role_name)
    except Exception as e:
        logger.error(f"Error searching users by role: {e}")
        flash('User role search failed. Verify database connection and role data.', 'error')
        return redirect(url_for('admin_panel.roles_management'))


# Phase 3: Bulk Operations and Advanced Analytics

@admin_panel_bp.route('/users/bulk-operations')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def bulk_operations():
    """Bulk user operations management page."""
    try:
        # Get user statistics for bulk operations
        pending_users = User.query.filter_by(approval_status='pending').count()
        waitlist_users = User.query.join(User.roles).filter(Role.name == 'pl-waitlist').count()
        
        # Get role statistics for bulk assignments
        roles = Role.query.order_by(Role.name).all()
        role_stats = {}
        for role in roles:
            role_stats[role.name] = len(role.users)
        
        # Get recent bulk operations from audit logs
        recent_bulk_ops = AdminAuditLog.query.filter(
            or_(
                AdminAuditLog.action.contains('bulk'),
                AdminAuditLog.resource_id == 'bulk'
            )
        ).order_by(AdminAuditLog.timestamp.desc()).limit(10).all()
        
        bulk_stats = {
            'pending_users': pending_users,
            'waitlist_users': waitlist_users,
            'total_roles': len(roles),
            'recent_operations': len(recent_bulk_ops)
        }
        
        return render_template('admin_panel/users/bulk_operations.html',
                             bulk_stats=bulk_stats,
                             roles=roles,
                             role_stats=role_stats,
                             recent_bulk_ops=recent_bulk_ops)
    except Exception as e:
        logger.error(f"Error loading bulk operations: {e}")
        flash('Bulk operations unavailable. Check database connectivity and user models.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/bulk-operations/approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_approve_users():
    """Bulk approve users with specified league assignments."""
    try:
        current_user_safe = safe_current_user
        data = request.get_json()
        
        user_ids = data.get('user_ids', [])
        default_league = data.get('default_league', 'classic')
        send_notifications = data.get('send_notifications', True)
        
        if not user_ids:
            return jsonify({'success': False, 'message': 'No users selected'}), 400
        
        # Validate league type
        valid_leagues = ['classic', 'premier', 'ecs-fc', 'sub-classic', 'sub-premier', 'sub-ecs-fc']
        if default_league not in valid_leagues:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        # Get role mapping
        role_mapping = {
            'classic': 'pl-classic',
            'premier': 'pl-premier',
            'ecs-fc': 'pl-ecs-fc',
            'sub-classic': 'Classic Sub',
            'sub-premier': 'Premier Sub',
            'sub-ecs-fc': 'ECS FC Sub'
        }
        
        new_role_name = role_mapping[default_league]
        new_role = Role.query.filter_by(name=new_role_name).first()
        
        if not new_role:
            return jsonify({'success': False, 'message': f'Role {new_role_name} not found'}), 404
        
        # Get unverified role to remove
        unverified_role = Role.query.filter_by(name='pl-unverified').first()
        
        approved_count = 0
        failed_users = []
        
        for user_id in user_ids:
            try:
                user = User.query.options(
                    joinedload(User.player),
                    joinedload(User.roles)
                ).get(user_id)
                
                if not user or user.approval_status != 'pending':
                    failed_users.append({'id': user_id, 'reason': 'User not found or not pending'})
                    continue
                
                # Remove unverified role
                if unverified_role and unverified_role in user.roles:
                    user.roles.remove(unverified_role)
                
                # Add new role
                if new_role not in user.roles:
                    user.roles.append(new_role)
                
                # Update approval status
                user.approval_status = 'approved'
                user.is_approved = True
                user.approval_league = default_league
                user.approved_by = current_user_safe.id
                user.approved_at = datetime.utcnow()
                user.approval_notes = f'Bulk approved for {default_league} league'
                
                # Queue Discord role sync
                if user.player and user.player.discord_id:
                    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
                
                approved_count += 1
                
            except Exception as e:
                logger.error(f"Error bulk approving user {user_id}: {e}")
                failed_users.append({'id': user_id, 'reason': str(e)})
        
        db.session.commit()
        
        # Log the bulk action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='bulk_approve_users',
            resource_type='user_approval',
            resource_id='bulk',
            new_value=f'Approved {approved_count} users for {default_league} league',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        result_message = f'Successfully approved {approved_count} users'
        if failed_users:
            result_message += f' ({len(failed_users)} failed)'
        
        return jsonify({
            'success': True,
            'message': result_message,
            'approved_count': approved_count,
            'failed_count': len(failed_users),
            'failed_users': failed_users
        })
        
    except Exception as e:
        logger.error(f"Error in bulk approve users: {e}")
        return jsonify({'success': False, 'message': 'Bulk approval failed'}), 500


@admin_panel_bp.route('/users/bulk-operations/role-assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_assign_roles():
    """Bulk assign roles to multiple users."""
    try:
        current_user_safe = safe_current_user
        data = request.get_json()
        
        user_ids = data.get('user_ids', [])
        role_ids = data.get('role_ids', [])
        operation = data.get('operation', 'add')  # add, remove, replace
        
        if not user_ids or not role_ids:
            return jsonify({'success': False, 'message': 'Users and roles must be selected'}), 400
        
        # Get roles to assign
        roles = Role.query.filter(Role.id.in_(role_ids)).all()
        if len(roles) != len(role_ids):
            return jsonify({'success': False, 'message': 'One or more roles not found'}), 404
        
        processed_count = 0
        failed_users = []
        
        for user_id in user_ids:
            try:
                user = User.query.options(joinedload(User.roles)).get(user_id)
                if not user:
                    failed_users.append({'id': user_id, 'reason': 'User not found'})
                    continue
                
                if operation == 'replace':
                    # Clear all existing roles and assign new ones
                    user.roles.clear()
                    for role in roles:
                        user.roles.append(role)
                elif operation == 'add':
                    # Add roles if not already present
                    for role in roles:
                        if role not in user.roles:
                            user.roles.append(role)
                elif operation == 'remove':
                    # Remove specified roles
                    for role in roles:
                        if role in user.roles:
                            user.roles.remove(role)
                
                # Sync Discord roles if player has Discord integration
                if user.player and user.player.discord_id:
                    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error bulk assigning roles to user {user_id}: {e}")
                failed_users.append({'id': user_id, 'reason': str(e)})
        
        db.session.commit()
        
        # Log the bulk action
        role_names = [role.name for role in roles]
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='bulk_assign_roles',
            resource_type='user_roles',
            resource_id='bulk',
            new_value=f'{operation.title()} roles [{", ".join(role_names)}] for {processed_count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        result_message = f'Successfully {operation}ed roles for {processed_count} users'
        if failed_users:
            result_message += f' ({len(failed_users)} failed)'
        
        return jsonify({
            'success': True,
            'message': result_message,
            'processed_count': processed_count,
            'failed_count': len(failed_users),
            'failed_users': failed_users
        })
        
    except Exception as e:
        logger.error(f"Error in bulk role assignment: {e}")
        return jsonify({'success': False, 'message': 'Bulk role assignment failed'}), 500


@admin_panel_bp.route('/users/bulk-operations/waitlist-process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_process_waitlist():
    """Bulk process waitlist users to pending approval."""
    try:
        current_user_safe = safe_current_user
        data = request.get_json()
        
        user_ids = data.get('user_ids', [])
        action = data.get('action', 'move_to_pending')  # move_to_pending, remove_from_waitlist
        
        if not user_ids:
            return jsonify({'success': False, 'message': 'No users selected'}), 400
        
        # Get roles
        waitlist_role = Role.query.filter_by(name='pl-waitlist').first()
        unverified_role = Role.query.filter_by(name='pl-unverified').first()
        
        if not waitlist_role:
            return jsonify({'success': False, 'message': 'Waitlist role not found'}), 404
        
        processed_count = 0
        failed_users = []
        
        for user_id in user_ids:
            try:
                user = User.query.options(joinedload(User.roles)).get(user_id)
                if not user:
                    failed_users.append({'id': user_id, 'reason': 'User not found'})
                    continue
                
                if waitlist_role not in user.roles:
                    failed_users.append({'id': user_id, 'reason': 'User not on waitlist'})
                    continue
                
                # Remove from waitlist
                user.roles.remove(waitlist_role)
                
                if action == 'move_to_pending':
                    # Add unverified role and set to pending
                    if unverified_role and unverified_role not in user.roles:
                        user.roles.append(unverified_role)
                    user.approval_status = 'pending'
                elif action == 'remove_from_waitlist':
                    # Just remove from waitlist without adding to pending
                    pass
                
                user.updated_at = datetime.utcnow()
                
                # Sync Discord roles
                if user.player and user.player.discord_id:
                    if action == 'move_to_pending':
                        assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
                    else:
                        remove_player_roles_task.delay(player_id=user.player.id)
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing waitlist user {user_id}: {e}")
                failed_users.append({'id': user_id, 'reason': str(e)})
        
        db.session.commit()
        
        # Log the bulk action
        AdminAuditLog.log_action(
            user_id=current_user_safe.id,
            action='bulk_process_waitlist',
            resource_type='user_waitlist',
            resource_id='bulk',
            new_value=f'{action} for {processed_count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        result_message = f'Successfully processed {processed_count} waitlist users'
        if failed_users:
            result_message += f' ({len(failed_users)} failed)'
        
        return jsonify({
            'success': True,
            'message': result_message,
            'processed_count': processed_count,
            'failed_count': len(failed_users),
            'failed_users': failed_users
        })
        
    except Exception as e:
        logger.error(f"Error in bulk waitlist processing: {e}")
        return jsonify({'success': False, 'message': 'Bulk waitlist processing failed'}), 500


@admin_panel_bp.route('/users/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_analytics():
    """Advanced user analytics dashboard."""
    try:
        # Get comprehensive analytics data
        analytics_data = _get_user_analytics()
        
        return render_template('admin_panel/users/analytics.html',
                             analytics_data=analytics_data)
    except Exception as e:
        logger.error(f"Error loading user analytics: {e}")
        flash('User analytics unavailable. Verify database connection and analytics data.', 'error')
        return redirect(url_for('admin_panel.user_management'))


@admin_panel_bp.route('/users/analytics/export', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_user_analytics():
    """Export user analytics data."""
    try:
        data = request.get_json()
        export_type = data.get('type', 'users')  # users, roles, activity
        format_type = data.get('format', 'csv')  # csv, json, xlsx
        date_range = data.get('date_range', '30_days')
        
        # Generate export data
        export_data = _generate_user_export_data(export_type, format_type, date_range)
        
        # Log the export action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='export_user_analytics',
            resource_type='user_analytics',
            resource_id=export_type,
            new_value=f'Exported {export_type} data in {format_type} format',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'User analytics export completed',
            'download_url': export_data.get('url'),
            'filename': export_data.get('filename')
        })
        
    except Exception as e:
        logger.error(f"Error exporting user analytics: {e}")
        return jsonify({'success': False, 'message': 'Export failed'}), 500


# Helper Functions for Actual Data Calculations

def _calculate_avg_wait_time():
    """Calculate the average wait time for user approvals."""
    try:
        # Get users who have been approved and have registration + approval dates
        approved_users = db.session.query(User).filter(
            User.approval_status == 'approved',
            User.approved_at.isnot(None),
            User.created_at.isnot(None)
        ).all()
        
        if not approved_users:
            return '0 days'
        
        total_wait_days = 0
        count = 0
        
        for user in approved_users:
            wait_time = user.approved_at - user.created_at
            total_wait_days += wait_time.days
            count += 1
        
        if count == 0:
            return '0 days'
        
        avg_days = total_wait_days / count
        return f'{avg_days:.1f} days'
        
    except Exception as e:
        logger.warning(f"Error calculating average wait time: {e}")
        return 'N/A'


def _calculate_processing_rate():
    """Calculate the processing rate (approved + rejected / total registrations)."""
    try:
        total_registrations = db.session.query(func.count(User.id)).scalar()
        processed_registrations = db.session.query(func.count(User.id)).filter(
            User.approval_status.in_(['approved', 'rejected'])
        ).scalar()
        
        if total_registrations == 0:
            return '0%'
        
        rate = (processed_registrations / total_registrations) * 100
        return f'{rate:.1f}%'
        
    except Exception as e:
        logger.warning(f"Error calculating processing rate: {e}")
        return 'N/A'


def _calculate_conversion_rate():
    """Calculate the conversion rate (approved / total processed)."""
    try:
        processed_registrations = db.session.query(func.count(User.id)).filter(
            User.approval_status.in_(['approved', 'rejected'])
        ).scalar()
        approved_registrations = db.session.query(func.count(User.id)).filter(
            User.approval_status == 'approved'
        ).scalar()
        
        if processed_registrations == 0:
            return '0%'
        
        rate = (approved_registrations / processed_registrations) * 100
        return f'{rate:.1f}%'
        
    except Exception as e:
        logger.warning(f"Error calculating conversion rate: {e}")
        return 'N/A'


# New comprehensive user management routes

@admin_panel_bp.route('/users/get-roles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_user_roles():
    """Get user roles for management modal via AJAX."""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})
        
        user = User.query.options(joinedload(User.roles)).get_or_404(user_id)
        all_roles = Role.query.order_by(Role.name).all()
        
        # Build HTML for role management interface
        html = f"""
        <div class="user-info mb-3">
            <div class="d-flex align-items-center">
                <div class="avatar-sm me-3">
                    {'<img src="' + (user.profile_picture or '') + '" class="rounded-circle avatar-40">' if user.profile_picture else '<div class="rounded-circle bg-primary d-flex align-items-center justify-content-center text-white avatar-40"><strong>' + (user.username[0].upper() if user.username else 'U') + '</strong></div>'}
                </div>
                <div>
                    <h6 class="mb-1">{user.username or 'N/A'}</h6>
                    <small class="text-muted">{user.email or 'No email'}</small>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-6">
                <h6>Current Roles</h6>
                <div id="currentRoles" class="border rounded p-3 mb-3 min-h-200">
        """

        if user.roles:
            for role in user.roles:
                html += f"""
                    <div class="d-flex justify-content-between align-items-center mb-2 role-item" data-role-id="{role.id}">
                        <span class="badge bg-info">{role.name}</span>
                        <button class="btn btn-sm btn-outline-danger" data-action="remove-role" data-user-id="{user.id}" data-role-id="{role.id}" data-role-name="{role.name}">
                            <i class="ti ti-x"></i>
                        </button>
                    </div>
                """
        else:
            html += '<p class="text-muted">No roles assigned</p>'

        html += """
                </div>
            </div>
            <div class="col-md-6">
                <h6>Available Roles</h6>
                <div class="border rounded p-3 min-h-200">
        """

        user_role_ids = [r.id for r in user.roles]
        available_roles = [r for r in all_roles if r.id not in user_role_ids]

        if available_roles:
            for role in available_roles:
                html += f"""
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span>{role.name}</span>
                        <button class="btn btn-sm btn-outline-success" data-action="add-role" data-user-id="{user.id}" data-role-id="{role.id}" data-role-name="{role.name}">
                            <i class="ti ti-plus"></i>
                        </button>
                    </div>
                """
        else:
            html += '<p class="text-muted">All roles assigned</p>'

        html += """
                </div>
            </div>
        </div>
        """
        
        return jsonify({'success': True, 'html': html})
    except Exception as e:
        logger.error(f"Error getting user roles: {e}")
        return jsonify({'success': False, 'message': 'Error loading user roles'})


@admin_panel_bp.route('/users/assign-role', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_user_role():
    """Assign or remove role from user via AJAX."""
    try:
        user_id = request.form.get('user_id')
        role_id = request.form.get('role_id')
        action = request.form.get('action')  # 'add' or 'remove'
        
        if not all([user_id, role_id, action]):
            return jsonify({'success': False, 'message': 'Missing required parameters'})
        
        user = User.query.get_or_404(user_id)
        role = Role.query.get_or_404(role_id)
        
        if action == 'add':
            if role not in user.roles:
                user.roles.append(role)
                message = f'Role "{role.name}" added to user "{user.username}"'
                audit_action = 'assign_role'
            else:
                return jsonify({'success': False, 'message': 'User already has this role'})
        elif action == 'remove':
            if role in user.roles:
                user.roles.remove(role)
                message = f'Role "{role.name}" removed from user "{user.username}"'
                audit_action = 'remove_role'
            else:
                return jsonify({'success': False, 'message': 'User does not have this role'})
        else:
            return jsonify({'success': False, 'message': 'Invalid action'})
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=audit_action,
            resource_type='user_management',
            resource_id=str(user_id),
            new_value=f'{action}:{role.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error assigning user role: {e}")
        return jsonify({'success': False, 'message': 'Error updating user role'})


@admin_panel_bp.route('/users/update-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_user_status():
    """Update user approval status via AJAX."""
    try:
        user_id = request.form.get('user_id')
        status = request.form.get('status')
        
        if not all([user_id, status]):
            return jsonify({'success': False, 'message': 'Missing required parameters'})
        
        if status not in ['approved', 'pending', 'denied']:
            return jsonify({'success': False, 'message': 'Invalid status'})
        
        user = User.query.get_or_404(user_id)
        old_status = user.approval_status
        user.approval_status = status
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_user_status',
            resource_type='user_management',
            resource_id=str(user_id),
            old_value=old_status,
            new_value=status,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({'success': True, 'message': f'User status updated to {status}'})
    except Exception as e:
        logger.error(f"Error updating user status: {e}")
        return jsonify({'success': False, 'message': 'Error updating user status'})


@admin_panel_bp.route('/users/update-active', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_user_active():
    """Update user active status via AJAX."""
    try:
        user_id = request.form.get('user_id')
        active = request.form.get('active').lower() == 'true'
        
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'})
        
        user = User.query.get_or_404(user_id)
        old_active = user.is_active
        user.is_active = active
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_user_active',
            resource_type='user_management',
            resource_id=str(user_id),
            old_value=str(old_active),
            new_value=str(active),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        action_word = 'activated' if active else 'deactivated'
        return jsonify({'success': True, 'message': f'User {action_word} successfully'})
    except Exception as e:
        logger.error(f"Error updating user active status: {e}")
        return jsonify({'success': False, 'message': 'Error updating user status'})


@admin_panel_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_user_comprehensive(user_id):
    """Comprehensive user edit via modal form."""
    try:
        user = User.query.options(
            joinedload(User.player),
            joinedload(User.roles)
        ).get_or_404(user_id)

        # Get form data
        username = request.form.get('username')
        email = request.form.get('email')
        real_name = request.form.get('real_name')
        is_approved = request.form.get('is_approved') == 'on'
        is_active = request.form.get('is_active') == 'on'
        is_current_player = request.form.get('is_current_player') == 'on'
        role_ids = request.form.getlist('roles')
        league_id = request.form.get('league_id')
        team_id = request.form.get('team_id')
        secondary_league_id = request.form.get('secondary_league_id')
        secondary_team_id = request.form.get('secondary_team_id')

        # Store old values for audit log
        old_values = {
            'username': user.username,
            'email': user.email,
            'is_approved': user.is_approved,
            'is_active': user.is_active,
            'roles': [r.id for r in user.roles],
            'league_id': user.player.primary_league_id if user.player else None,
            'team_id': user.player.primary_team_id if user.player else None,
            'is_current_player': user.player.is_current_player if user.player else None
        }

        # Update user fields
        if username:
            user.username = username
        if email:
            user.email = email
        user.is_approved = is_approved
        user.is_active = is_active

        # Update player profile if exists
        if user.player:
            if real_name:
                user.player.name = real_name

            # Primary league and team
            user.player.primary_league_id = int(league_id) if league_id else None
            user.player.primary_team_id = int(team_id) if team_id else None

            # Active player status
            user.player.is_current_player = is_current_player

            # Handle secondary team (add to teams relationship if not already there)
            if secondary_team_id:
                secondary_team = Team.query.get(int(secondary_team_id))
                if secondary_team and secondary_team not in user.player.teams:
                    user.player.teams.append(secondary_team)

            # Handle secondary league (add to other_leagues relationship)
            if secondary_league_id:
                secondary_league = League.query.get(int(secondary_league_id))
                if secondary_league and secondary_league not in user.player.other_leagues:
                    user.player.other_leagues.append(secondary_league)

        # Update roles
        if role_ids:
            new_roles = Role.query.filter(Role.id.in_(role_ids)).all()
            user.roles = new_roles

        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='edit_user_comprehensive',
            resource_type='user_management',
            resource_id=str(user_id),
            old_value=str(old_values),
            new_value=str({
                'username': user.username,
                'email': user.email,
                'is_approved': user.is_approved,
                'is_active': user.is_active,
                'roles': [r.id for r in user.roles]
            }),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'User {user.username} updated successfully', 'success')
        return redirect(url_for('admin_panel.users_comprehensive'))

    except Exception as e:
        logger.error(f"Error editing user {user_id}: {e}")
        flash('Error updating user', 'error')
        return redirect(url_for('admin_panel.users_comprehensive'))


@admin_panel_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def approve_user_comprehensive(user_id):
    """Quick approve user via AJAX from comprehensive management."""
    try:
        user = User.query.get_or_404(user_id)
        old_status = user.is_approved

        user.is_approved = True
        user.approval_status = 'approved'
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='approve_user_quick',
            resource_type='user_management',
            resource_id=str(user_id),
            old_value=str(old_status),
            new_value='True',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'User {user.username} approved successfully'})

    except Exception as e:
        logger.error(f"Error approving user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Error approving user'}), 500


@admin_panel_bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def deactivate_user_comprehensive(user_id):
    """Quick deactivate user via AJAX from comprehensive management."""
    try:
        user = User.query.get_or_404(user_id)
        old_status = user.is_active

        user.is_active = False
        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='deactivate_user_quick',
            resource_type='user_management',
            resource_id=str(user_id),
            old_value=str(old_status),
            new_value='False',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'User {user.username} deactivated successfully'})

    except Exception as e:
        logger.error(f"Error deactivating user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deactivating user'}), 500


@admin_panel_bp.route('/users/bulk-actions', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def bulk_user_comprehensive_actions():
    """Handle bulk user actions from comprehensive management page."""
    try:
        action = request.form.get('action')
        user_ids = request.form.getlist('user_ids')

        if not action or not user_ids:
            return jsonify({'success': False, 'message': 'Action and user IDs are required'})

        users = User.query.filter(User.id.in_(user_ids)).all()
        if not users:
            return jsonify({'success': False, 'message': 'No users found'})

        count = 0
        for user in users:
            if action == 'approve':
                user.is_approved = True
                user.approval_status = 'approved'
                count += 1
            elif action == 'deactivate':
                user.is_active = False
                count += 1
            elif action == 'activate':
                user.is_active = True
                count += 1
            elif action == 'deny':
                user.is_approved = False
                user.approval_status = 'denied'
                count += 1

        db.session.commit()

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'bulk_{action}_users',
            resource_type='user_management',
            resource_id=','.join(user_ids),
            old_value=None,
            new_value=f'{count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        action_past = {'approve': 'approved', 'deactivate': 'deactivated', 'activate': 'activated', 'deny': 'denied'}
        return jsonify({
            'success': True,
            'message': f'{count} user(s) {action_past.get(action, action)} successfully'
        })

    except Exception as e:
        logger.error(f"Error in bulk user action: {e}")
        return jsonify({'success': False, 'message': 'Error processing bulk action'}), 500


@admin_panel_bp.route('/users/bulk-update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def bulk_update_users():
    """Bulk update users via AJAX."""
    try:
        data = request.get_json()
        user_ids = data.get('user_ids', [])
        action = data.get('action')
        
        if not user_ids or not action:
            return jsonify({'success': False, 'message': 'Missing required parameters'})
        
        users = User.query.filter(User.id.in_(user_ids)).all()
        
        if action == 'update_status':
            status = data.get('status')
            if status not in ['approved', 'pending', 'denied']:
                return jsonify({'success': False, 'message': 'Invalid status'})
            
            for user in users:
                user.approval_status = status
            
            message = f'{len(users)} users updated to {status} status'
            
        elif action == 'update_active':
            active = data.get('active', True)
            for user in users:
                user.is_active = active
            
            action_word = 'activated' if active else 'deactivated'
            message = f'{len(users)} users {action_word}'
            
        else:
            return jsonify({'success': False, 'message': 'Invalid action'})
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'bulk_{action}',
            resource_type='user_management',
            resource_id=','.join(map(str, user_ids)),
            new_value=f'{action}:{len(users)} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error bulk updating users: {e}")
        return jsonify({'success': False, 'message': 'Error updating users'})


# -----------------------------------------------------------
# Duplicate Registration Management
# -----------------------------------------------------------

@admin_panel_bp.route('/users/duplicates')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def duplicate_registrations():
    """Display and manage potential duplicate registrations."""
    try:
        # Find potential duplicates based on email patterns, names, and Discord IDs
        duplicate_groups = _find_duplicate_registrations()

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
        duplicate_groups = _find_duplicate_registrations()

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


def _find_duplicate_registrations():
    """Find potential duplicate registrations based on various criteria."""
    duplicate_groups = []
    processed_ids = set()

    try:
        # 1. Find duplicates by email domain and similar usernames
        all_users = User.query.options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter(User.is_active == True).all()

        # Group by email prefix (before @)
        email_groups = {}
        for user in all_users:
            if user.email:
                email_prefix = user.email.split('@')[0].lower()
                # Normalize - remove numbers and common patterns
                normalized = ''.join(c for c in email_prefix if c.isalpha())
                if len(normalized) >= 3:
                    if normalized not in email_groups:
                        email_groups[normalized] = []
                    email_groups[normalized].append(user)

        # Find groups with multiple users
        for prefix, users in email_groups.items():
            if len(users) > 1:
                user_ids = frozenset(u.id for u in users)
                if user_ids not in processed_ids:
                    processed_ids.add(user_ids)
                    duplicate_groups.append({
                        'match_type': 'email',
                        'match_value': prefix,
                        'users': [_user_to_dict(u) for u in users]
                    })

        # 2. Find duplicates by player name
        if Player:
            name_groups = {}
            players = Player.query.filter(Player.is_current_player == True).all()

            for player in players:
                if player.name:
                    normalized_name = player.name.lower().strip()
                    if normalized_name not in name_groups:
                        name_groups[normalized_name] = []
                    name_groups[normalized_name].append(player)

            for name, players_list in name_groups.items():
                if len(players_list) > 1:
                    users = [p.user for p in players_list if p.user]
                    if len(users) > 1:
                        user_ids = frozenset(u.id for u in users)
                        if user_ids not in processed_ids:
                            processed_ids.add(user_ids)
                            duplicate_groups.append({
                                'match_type': 'name',
                                'match_value': name,
                                'users': [_user_to_dict(u) for u in users]
                            })

        # 3. Find duplicates by Discord ID (should be unique)
        discord_groups = {}
        for user in all_users:
            if user.player and user.player.discord_id:
                discord_id = user.player.discord_id
                if discord_id not in discord_groups:
                    discord_groups[discord_id] = []
                discord_groups[discord_id].append(user)

        for discord_id, users in discord_groups.items():
            if len(users) > 1:
                user_ids = frozenset(u.id for u in users)
                if user_ids not in processed_ids:
                    processed_ids.add(user_ids)
                    duplicate_groups.append({
                        'match_type': 'discord',
                        'match_value': discord_id,
                        'users': [_user_to_dict(u) for u in users]
                    })

        return duplicate_groups

    except Exception as e:
        logger.error(f"Error finding duplicates: {e}")
        return []


def _user_to_dict(user):
    """Convert user to dictionary for duplicate display."""
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'approval_status': user.approval_status,
        'is_active': user.is_active,
        'roles': [r.name for r in user.roles],
        'player': {
            'id': user.player.id,
            'name': user.player.name,
            'discord_id': user.player.discord_id,
            'phone': user.player.phone
        } if user.player else None
    }


def _get_user_analytics():
    """Generate comprehensive user analytics data."""
    try:
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # Basic counts
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()

        # Registration trends
        registrations_30d = User.query.filter(User.created_at >= thirty_days_ago).count()
        registrations_7d = User.query.filter(User.created_at >= seven_days_ago).count()

        # Approval trends
        approvals_30d = User.query.filter(
            User.approved_at >= thirty_days_ago,
            User.approval_status == 'approved'
        ).count()

        # Role distribution
        roles = Role.query.all()
        role_distribution = {role.name: len(role.users) for role in roles}

        # Status distribution
        status_distribution = {
            'pending': User.query.filter_by(approval_status='pending').count(),
            'approved': User.query.filter_by(approval_status='approved').count(),
            'denied': User.query.filter_by(approval_status='denied').count()
        }

        return {
            'total_users': total_users,
            'active_users': active_users,
            'registrations_30d': registrations_30d,
            'registrations_7d': registrations_7d,
            'approvals_30d': approvals_30d,
            'role_distribution': role_distribution,
            'status_distribution': status_distribution,
            'generated_at': now.isoformat()
        }

    except Exception as e:
        logger.error(f"Error generating user analytics: {e}")
        return {}


def _generate_user_export_data(export_type, format_type, date_range):
    """Generate export data for users."""
    # Placeholder - implement actual export logic as needed
    return {
        'url': None,
        'filename': f'user_export_{export_type}_{datetime.utcnow().strftime("%Y%m%d")}.{format_type}'
    }