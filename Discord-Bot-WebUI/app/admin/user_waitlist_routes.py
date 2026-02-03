"""
User Waitlist Routes

This module handles routes for managing users on the waitlist.
Allows Global Admin and Pub League Admin to manage waitlist users and remove them from waitlist.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from flask import render_template, request, jsonify, flash, redirect, url_for, g
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload

from flask_login import login_required

from app.models import User, Role, Player
from app.utils.db_utils import transactional
from app.decorators import role_required
from app.admin.blueprint import admin_bp
from app.utils.user_helpers import safe_current_user
from app.alert_helpers import show_success, show_error, show_warning
from app.utils.user_locking import lock_user_for_role_update, LockAcquisitionError
from app.utils.deferred_discord import DeferredDiscordQueue
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)


@admin_bp.route('/admin/user-waitlist')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def user_waitlist():
    """
    Display the user waitlist management interface.
    Shows users on the waitlist.
    """
    db_session = g.db_session
    current_user = safe_current_user
    
    # Get all users with pl-waitlist role
    waitlist_users = db_session.query(User).options(
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
        'total_registered': db_session.query(func.count(User.id)).scalar(),
        'total_approved': db_session.query(func.count(User.id)).filter(User.approval_status == 'approved').scalar()
    }
    
    return render_template(
        'admin/user_waitlist_flowbite.html',
        waitlist_users=waitlist_users,
        recent_actions=recent_actions,
        stats=stats
    )


@admin_bp.route('/admin/user-waitlist/remove/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def remove_from_waitlist(user_id: int):
    """
    Remove a user from the waitlist.

    Uses pessimistic locking to prevent concurrent role modifications.
    Discord sync is deferred until after transaction commits.
    """
    db_session = g.db_session
    current_user_safe = safe_current_user

    # Get the pl-waitlist role
    waitlist_role = db_session.query(Role).filter_by(name='pl-waitlist').first()
    if not waitlist_role:
        return jsonify({'success': False, 'message': 'Waitlist role not found'}), 404

    # Queue for deferred Discord operations
    discord_queue = DeferredDiscordQueue()

    try:
        # Acquire lock on user for role modification
        with lock_user_for_role_update(user_id, session=db_session) as user:
            # Check if user is on waitlist
            if waitlist_role not in user.roles:
                return jsonify({'success': False, 'message': 'User is not on waitlist'}), 400

            # Get removal reason from request
            reason = request.json.get('reason', 'No reason provided')

            # Remove the waitlist role
            user.roles.remove(waitlist_role)

            # Clear waitlist joined timestamp since they're no longer on waitlist
            user.waitlist_joined_at = None

            # Update user record
            user.updated_at = datetime.utcnow()

            # Log the action
            logger.info(f"User {user.id} ({user.username}) removed from waitlist by {current_user_safe.id} ({current_user_safe.username}). Reason: {reason}")

            # Queue Discord role removal (deferred until after commit)
            if user.player and user.player.discord_id:
                discord_queue.add_role_removal(user.player.id)

            # Commit the transaction
            db_session.commit()

            username = user.username
            result_user_id = user.id

    except LockAcquisitionError:
        db_session.rollback()
        return jsonify({
            'success': False,
            'message': 'User is being modified by another request. Please try again.'
        }), 409

    except Exception as e:
        db_session.rollback()
        logger.error(f"Error removing user {user_id} from waitlist: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to remove user from waitlist'}), 500

    # Execute deferred Discord operations after successful commit
    discord_queue.execute_all()
    logger.info(f"Queued Discord role removal for user {result_user_id}")

    show_success(f'User {username} has been removed from the waitlist.')

    return jsonify({
        'success': True,
        'message': f'User {username} removed from waitlist successfully',
        'user_id': result_user_id
    })


@admin_bp.route('/admin/user-waitlist/contact/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def contact_waitlist_user(user_id: int):
    """
    Contact a user on the waitlist (placeholder for future implementation).
    """
    db_session = g.db_session
    current_user = safe_current_user
    
    try:
        # Get the user
        user = db_session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter_by(id=user_id).first()
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Get contact message from request
        message = request.json.get('message', '')
        contact_method = request.json.get('contact_method', 'email')
        
        # Log the action
        logger.info(f"Contact initiated for waitlist user {user.id} ({user.username}) by {current_user.id} ({current_user.username}). Method: {contact_method}")
        
        # TODO: Implement actual contact functionality (email, Discord DM, etc.)
        # For now, we'll just log and return success
        
        show_success(f'Contact logged for user {user.username}.')
        
        return jsonify({
            'success': True,
            'message': f'Contact logged for user {user.username}',
            'user_id': user.id
        })
        
    except Exception as e:
        logger.error(f"Error contacting waitlist user {user_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to contact user'}), 500


@admin_bp.route('/admin/user-waitlist/user/<int:user_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_waitlist_user_details(user_id: int):
    """
    Get detailed information about a waitlist user for display in modal.
    """
    db_session = g.db_session
    
    try:
        # Get the user with all necessary relationships
        user = db_session.query(User).options(
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
            'preferred_league': user.preferred_league,
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


@admin_bp.route('/admin/user-waitlist/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_waitlist_stats():
    """
    Get waitlist statistics for dashboard updates.
    """
    db_session = g.db_session
    
    try:
        # Count users on waitlist
        waitlist_count = db_session.query(func.count(User.id)).join(User.roles).filter(
            Role.name == 'pl-waitlist'
        ).scalar()
        
        # Get total registered users
        total_registered = db_session.query(func.count(User.id)).scalar()
        
        # Get total approved users
        total_approved = db_session.query(func.count(User.id)).filter(
            User.approval_status == 'approved'
        ).scalar()
        
        stats = {
            'waitlist_count': waitlist_count,
            'total_registered': total_registered,
            'total_approved': total_approved
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error getting waitlist stats: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to get stats'}), 500