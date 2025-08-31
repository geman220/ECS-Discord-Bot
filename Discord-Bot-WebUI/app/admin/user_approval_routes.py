"""
User Approval Routes

This module handles routes for managing user approvals for league placement.
Allows Global Admin and Pub League Admin to approve/deny users for different leagues.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from flask import render_template, request, jsonify, flash, redirect, url_for, g
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload

from flask_login import login_required

from app.models import User, Role, Player, League, Season
from app.utils.db_utils import transactional
from app.decorators import role_required
from app.admin.blueprint import admin_bp
from app.utils.user_helpers import safe_current_user
from app.alert_helpers import show_success, show_error, show_warning
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)


@admin_bp.route('/admin/test-onboarding')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def test_onboarding():
    """
    Redirect to the onboarding testing interface.
    """
    return redirect(url_for('admin.discord_onboarding.admin_test_onboarding'))


@admin_bp.route('/admin/user-approvals')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def user_approvals():
    """
    Display the user approval management interface.
    Shows pending users waiting for league approval.
    """
    db_session = g.db_session
    current_user = safe_current_user
    
    # Get all users with pl-unverified role who are pending approval
    pending_users = db_session.query(User).options(
        joinedload(User.player),
        joinedload(User.roles)
    ).join(User.roles).filter(
        Role.name == 'pl-unverified',
        User.approval_status == 'pending',
        User.player.has()  # Only users with player records
    ).order_by(User.created_at.desc()).all()
    
    # Get recently approved/denied users for reference
    recent_actions = []
    try:
        recent_actions = db_session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter(
            User.approval_status.in_(['approved', 'denied']),
            User.approved_at.isnot(None)
        ).order_by(User.approved_at.desc()).limit(20).all()
        
        # Load approved_by_user for each user
        for user in recent_actions:
            if user.approved_by:
                user.approved_by_user = db_session.query(User).filter_by(id=user.approved_by).first()
    except Exception as e:
        logger.error(f"Error loading recent actions: {str(e)}")
        recent_actions = []
    
    # Count statistics
    stats = {
        'pending_count': len(pending_users),
        'total_approved': db_session.query(func.count(User.id)).filter(User.approval_status == 'approved').scalar(),
        'total_denied': db_session.query(func.count(User.id)).filter(User.approval_status == 'denied').scalar()
    }
    
    return render_template(
        'admin/user_approvals.html',
        pending_users=pending_users,
        recent_actions=recent_actions,
        stats=stats
    )


@admin_bp.route('/admin/user-approvals/approve/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def approve_user(user_id: int):
    """
    Approve a user for a specific league.
    Assigns appropriate roles and updates Discord.
    """
    db_session = g.db_session
    current_user = safe_current_user
    
    try:
        # Get the user to approve
        user = db_session.query(User).options(
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
        
        # Get the appropriate roles and league assignment
        role_mapping = {
            'classic': ['pl-classic'],
            'premier': ['pl-premier'],
            'ecs-fc': ['pl-ecs-fc'],
            'sub-classic': ['Classic Sub', 'pl-classic'],  # Sub gets both sub role AND division role
            'sub-premier': ['Premier Sub', 'pl-premier'],  # Sub gets both sub role AND division role
            'sub-ecs-fc': ['ECS FC Sub', 'pl-ecs-fc']     # Sub gets both sub role AND division role
        }
        
        # League assignment mapping
        league_assignment_mapping = {
            'classic': 'Classic',
            'premier': 'Premier', 
            'ecs-fc': 'ECS FC',
            'sub-classic': 'Classic',    # Subs get assigned to the base league
            'sub-premier': 'Premier',    # Subs get assigned to the base league
            'sub-ecs-fc': 'ECS FC'       # Subs get assigned to the base league
        }
        
        new_role_names = role_mapping[league_type]
        new_roles = []
        
        # Get all the roles that need to be assigned
        for role_name in new_role_names:
            role = db_session.query(Role).filter_by(name=role_name).first()
            if not role:
                return jsonify({'success': False, 'message': f'Role {role_name} not found'}), 404
            new_roles.append(role)
        
        # Remove the pl-unverified role
        unverified_role = db_session.query(Role).filter_by(name='pl-unverified').first()
        if unverified_role and unverified_role in user.roles:
            user.roles.remove(unverified_role)
        
        # Add all the new approved roles
        for new_role in new_roles:
            if new_role not in user.roles:
                user.roles.append(new_role)
        
        # Assign user to the appropriate league WITH CURRENT SEASON
        league_name = league_assignment_mapping[league_type]
        # Get the league with the current season
        league = db_session.query(League).join(
            Season, League.season_id == Season.id
        ).filter(
            League.name == league_name,
            Season.is_current == True
        ).first()
        
        if league:
            user.league_id = league.id
            logger.info(f"Assigned user {user.id} to league '{league_name}' (ID: {league.id}) with current season")
        else:
            logger.warning(f"No current season league '{league_name}' found for user {user.id}")
            # Fallback to any league with that name if no current season exists
            league = db_session.query(League).filter_by(name=league_name).first()
            if league:
                user.league_id = league.id
                logger.warning(f"Fallback: Assigned user {user.id} to league '{league_name}' (ID: {league.id}) - NOT CURRENT SEASON")
            
        # Also set league on the player if exists  
        if user.player and league:
            user.player.league_id = league.id
            logger.info(f"Assigned player {user.player.id} to league '{league_name}' (ID: {league.id})")
        
        # Update user approval status
        user.approval_status = 'approved'
        user.is_approved = True
        user.approval_league = league_type
        user.approved_by = current_user.id
        user.approved_at = datetime.utcnow()
        user.approval_notes = notes
        
        db_session.add(user)
        db_session.flush()
        
        # Trigger Discord role sync
        if user.player and user.player.discord_id:
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for approved user {user.id}")
        
        assigned_roles = [role.name for role in new_roles]
        logger.info(f"User {user.id} approved for {league_type} league by {current_user.id}")
        logger.info(f"Assigned roles: {assigned_roles}")
        if league:
            logger.info(f"Assigned to league: {league.name} (ID: {league.id})")
        
        return jsonify({
            'success': True,
            'message': f'User {user.username} approved for {league_type.title()} league with roles: {", ".join(assigned_roles)}',
            'user_id': user.id,
            'league_type': league_type,
            'assigned_roles': assigned_roles,
            'assigned_league': league.name if league else None,
            'approved_by': current_user.username,
            'approved_at': user.approved_at.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error approving user {user_id}: {str(e)}")
        db_session.rollback()
        return jsonify({'success': False, 'message': 'Error processing approval'}), 500


@admin_bp.route('/admin/user-approvals/deny/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def deny_user(user_id: int):
    """
    Deny a user's application.
    Removes Discord roles and updates status.
    """
    db_session = g.db_session
    current_user = safe_current_user
    
    try:
        # Get the user to deny
        user = db_session.query(User).options(
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
        unverified_role = db_session.query(Role).filter_by(name='pl-unverified').first()
        if unverified_role and unverified_role in user.roles:
            user.roles.remove(unverified_role)
        
        # Update user approval status
        user.approval_status = 'denied'
        user.approval_league = None
        user.approved_by = current_user.id
        user.approved_at = datetime.utcnow()
        user.approval_notes = notes
        
        db_session.add(user)
        db_session.flush()
        
        # Remove Discord roles
        if user.player and user.player.discord_id:
            remove_player_roles_task.delay(player_id=user.player.id)
            logger.info(f"Triggered Discord role removal for denied user {user.id}")
        
        logger.info(f"User {user.id} denied by {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': f'User {user.username} application denied',
            'user_id': user.id,
            'denied_by': current_user.username,
            'denied_at': user.approved_at.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error denying user {user_id}: {str(e)}")
        db_session.rollback()
        return jsonify({'success': False, 'message': 'Error processing denial'}), 500


@admin_bp.route('/admin/user-approvals/user/<int:user_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_user_details(user_id: int):
    """
    Get detailed information about a user for the approval modal.
    """
    db_session = g.db_session
    
    try:
        user = db_session.query(User).options(
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


@admin_bp.route('/admin/user-approvals/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_approval_stats():
    """
    Get statistics about user approvals.
    """
    db_session = g.db_session
    
    try:
        # Get counts by approval status
        pending_count = db_session.query(func.count(User.id)).filter(
            User.approval_status == 'pending'
        ).scalar()
        
        approved_count = db_session.query(func.count(User.id)).filter(
            User.approval_status == 'approved'
        ).scalar()
        
        denied_count = db_session.query(func.count(User.id)).filter(
            User.approval_status == 'denied'
        ).scalar()
        
        # Get counts by league type for approved users
        league_counts = db_session.query(
            User.approval_league,
            func.count(User.id).label('count')
        ).filter(
            User.approval_status == 'approved'
        ).group_by(User.approval_league).all()
        
        league_stats = {league: count for league, count in league_counts if league}
        
        stats = {
            'pending': pending_count,
            'approved': approved_count,
            'denied': denied_count,
            'total': pending_count + approved_count + denied_count,
            'league_breakdown': league_stats
        }
        
        return jsonify({'success': True, 'stats': stats})
        
    except Exception as e:
        logger.error(f"Error getting approval stats: {str(e)}")
        return jsonify({'success': False, 'message': 'Error retrieving statistics'}), 500