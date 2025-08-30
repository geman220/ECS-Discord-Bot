# app/admin_routes.py

"""
Admin Routes Module

This module serves as the main entry point for all admin routes.
It imports and registers all admin sub-modules to keep the code organized
and maintainable.

All routes are protected by login and role requirements.
"""

import logging
from flask import Blueprint, redirect, url_for

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp

# Import all route modules - this adds routes directly to admin_bp
from app.admin import health_routes
from app.admin import docker_routes  
from app.admin import communication_routes
from app.admin import feedback_routes
from app.admin import reports_routes
from app.admin import verification_routes
from app.admin import scheduling_routes
from app.admin import substitute_routes
from app.admin import discord_routes
from app.admin import mls_routes
from app.admin import user_approval_routes

# The remaining routes will be moved to their respective modules
# For now, we'll keep them here and gradually migrate them

import time
import requests
from datetime import datetime, timedelta

from celery.result import AsyncResult
from flask import (
    render_template, redirect, url_for,
    request, jsonify, abort, g, current_app
)
from sqlalchemy import func
from flask_login import login_required
from sqlalchemy.orm import joinedload, aliased
from flask_wtf.csrf import CSRFProtect

from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.admin_helpers import (
    get_filtered_users, handle_user_action,
    handle_announcement_update, get_role_permissions_data,
    handle_permissions_update,
    get_available_subs, get_match_subs, assign_sub_to_team,
    remove_sub_assignment, get_player_active_sub_assignments,
    cleanup_old_sub_assignments, get_sub_requests, create_sub_request,
    update_sub_request_status
)
from app.decorators import role_required
from app.email import send_email
from app.forms import (
    AnnouncementForm, EditUserForm, ResetPasswordForm
)
from app.models import (
    Role, Permission, MLSMatch, ScheduledMessage,
    Announcement, Team, Match,
    Player, Availability, User, Schedule, Season, League,
    TemporarySubAssignment, SubRequest, LeaguePoll, 
    LeaguePollResponse, LeaguePollDiscordMessage, player_teams
)
from app.utils.task_monitor import get_task_info
from app.core import celery
from sqlalchemy import and_, or_, func, desc
from app.tasks.tasks_core import (
    schedule_season_availability
)
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)
from app.tasks.tasks_live_reporting import (
    force_create_mls_thread_task,
    schedule_all_mls_threads_task,
    schedule_mls_thread_task
)
from app.utils.user_helpers import safe_current_user

# Import CSRF utilities
from flask_wtf.csrf import CSRFProtect, generate_csrf

# Initialize CSRF protection
csrf = CSRFProtect()

# Create a more robust decorator to handle CSRF exemption
def csrf_exempt(route_func):
    """Decorator to exempt a route from CSRF protection and handle token issues."""
    route_func.csrf_exempt = True
    
    # Create a wrapper function to handle the request
    def wrapped_route(*args, **kwargs):
        # The route is already exempt, but we still add extra logging
        logger.info(f"CSRF exempt route called: {route_func.__name__}")
        
        # Proceed with the original route function
        return route_func(*args, **kwargs)
        
    # Preserve the route name and other attributes
    wrapped_route.__name__ = route_func.__name__
    wrapped_route.__module__ = route_func.__module__
    
    return wrapped_route

# -----------------------------------------------------------
# Admin Dashboard and User Management
# -----------------------------------------------------------

@admin_bp.route('/admin', endpoint='index', methods=['GET'])
@login_required
@role_required('Global Admin')
def admin_index():
    """Admin index route that redirects to dashboard."""
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/dashboard', endpoint='admin_dashboard', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
def admin_dashboard():
    """
    Render the admin dashboard and handle user actions such as
    approval, removal, password resets, and announcement creation.
    """
    session = g.db_session

    if request.method == 'POST':
        action = request.form.get('action')

        # Handle user actions: approve, remove, or reset password
        if action in ['approve', 'remove', 'reset_password']:
            user_id = request.form.get('user_id')
            success = handle_user_action(action, user_id, session=session)
            if not success:
                show_error('Error processing user action.')
            return redirect(url_for('admin.admin_dashboard'))

        # Handle announcement creation/update
        elif action == 'create_announcement':
            title = request.form.get('title')
            content = request.form.get('content')
            success = handle_announcement_update(title=title, content=content, session=session)
            if not success:
                show_error('Error creating announcement.')
            return redirect(url_for('admin.admin_dashboard'))

        # Handle permissions update
        elif action == 'update_permissions':
            role_id = request.form.get('role_id')
            permissions = request.form.getlist('permissions')
            # Convert permission IDs to integers
            try:
                role_id = int(role_id) if role_id else None
                permission_ids = [int(p) for p in permissions if p]
            except ValueError:
                show_error('Invalid role or permission IDs.')
                return redirect(url_for('admin.admin_dashboard'))
            
            success = handle_permissions_update(role_id, permission_ids, session=session)
            if success:
                show_success('Permissions updated successfully.')
            else:
                show_error('Error updating permissions.')
            return redirect(url_for('admin.admin_dashboard'))

    # Handle GET request: pagination and filtering of users
    page = request.args.get('page', 1, type=int)
    per_page = 10
    filters = {
        'search': request.args.get('search', ''),
        'role': request.args.get('role', ''),
        'league': request.args.get('league', ''),
        'active': request.args.get('active', ''),
        'approved': request.args.get('approved', '')
    }

    users_query = get_filtered_users(filters)
    total_users = users_query.count()
    users = users_query.offset((page - 1) * per_page).limit(per_page).all()

    # Get teams and preload stats
    teams = session.query(Team).all()
    from app.team_performance_helpers import preload_team_stats_for_request
    team_ids = [team.id for team in teams]
    preload_team_stats_for_request(team_ids, session)

    template_data = {
        'users': users,
        'page': page,
        'total': total_users,
        'per_page': per_page,
        'roles': session.query(Role).all(),
        'permissions': session.query(Permission).all(),
        'announcements': session.query(Announcement).order_by(Announcement.created_at.desc()).all(),
        'teams': teams,
        'edit_form': EditUserForm(),
        'reset_password_form': ResetPasswordForm(),
        'announcement_form': AnnouncementForm()
    }

    # Commit the session before rendering the template to avoid holding
    # the database transaction open during template rendering
    session.commit()

    return render_template('admin_dashboard.html', **template_data)


# -----------------------------------------------------------
# Role & Permission Management
# -----------------------------------------------------------

@admin_bp.route('/admin/get_role_permissions', endpoint='get_role_permissions', methods=['GET'])
@admin_bp.route('/admin/role-permissions/<int:role_id>', endpoint='get_role_permissions_alt', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_role_permissions(role_id=None):
    """
    Retrieve permission details for a specified role.
    """
    if role_id is None:
        role_id = request.args.get('role_id')
    permissions = get_role_permissions_data(role_id, session=g.db_session)
    if permissions is None:
        return jsonify({'success': False, 'error': 'Role not found.'}), 404
    return jsonify({'success': True, 'permissions': permissions})


# -----------------------------------------------------------
# Announcement Management
# -----------------------------------------------------------

@admin_bp.route('/admin/announcements', endpoint='manage_announcements', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_announcements():
    """
    Render the announcement management view.
    On POST, create a new announcement.
    Also include user data so the Manage Users table is not empty.
    """
    session = g.db_session
    announcement_form = AnnouncementForm()

    if announcement_form.validate_on_submit():
        # Determine the next available position
        max_position = session.query(func.max(Announcement.position)).scalar() or 0
        new_announcement = Announcement(
            title=announcement_form.title.data,
            content=announcement_form.content.data,
            position=max_position + 1
        )
        session.add(new_announcement)
        try:
            session.commit()
            show_success("Announcement created successfully.")
            return redirect(url_for('admin.manage_announcements'))
        except Exception as e:
            session.rollback()
            logger.exception(f"Error creating announcement: {str(e)}")
            show_error('Error creating announcement.')
            return redirect(url_for('admin.manage_announcements'))

    announcements = session.query(Announcement).order_by(Announcement.position).all()

    # Build user filters (using empty defaults if not provided)
    filters = {
        'search': request.args.get('search', ''),
        'role': request.args.get('role', ''),
        'league': request.args.get('league', ''),
        'active': request.args.get('active', ''),
        'approved': request.args.get('approved', '')
    }
    users_query = get_filtered_users(filters)
    total_users = users_query.count()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    users = users_query.offset((page - 1) * per_page).limit(per_page).all()

    # Create additional forms for user actions if needed
    edit_form = EditUserForm()
    reset_password_form = ResetPasswordForm()

    # Also pass roles and permissions for the Manage Roles section
    roles = session.query(Role).all()
    permissions = session.query(Permission).all()

    return render_template(
        'admin_dashboard.html',
        announcements=announcements,
        announcement_form=announcement_form,
        users=users,
        total_users=total_users,
        page=page,
        per_page=per_page,
        edit_form=edit_form,
        reset_password_form=reset_password_form,
        roles=roles,
        permissions=permissions
    )


@admin_bp.route('/admin/announcements/<int:announcement_id>/edit', endpoint='edit_announcement', methods=['PUT', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_announcement(announcement_id):
    """
    Update the title and content of an existing announcement.
    """
    session = g.db_session
    
    # Handle both PUT (JSON) and POST (form) requests
    if request.method == 'PUT':
        data = request.get_json()
        title = data.get('title') if data else None
        content = data.get('content') if data else None
    else:  # POST
        title = request.form.get('title')
        content = request.form.get('content')
    
    if not title or not content:
        if request.method == 'PUT':
            return jsonify({'error': 'Title and content are required.'}), 400
        else:
            show_error('Title and content are required.')
            return redirect(url_for('admin.admin_dashboard'))

    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        if request.method == 'PUT':
            return jsonify({'error': 'Announcement not found.'}), 404
        else:
            show_error('Announcement not found.')
            return redirect(url_for('admin.admin_dashboard'))

    announcement.title = title
    announcement.content = content
    session.add(announcement)
    try:
        session.commit()
        if request.method == 'PUT':
            return jsonify({'success': True})
        else:
            show_success('Announcement updated successfully.')
    except Exception as e:
        session.rollback()
        logger.exception(f"Error updating announcement {announcement_id}: {str(e)}")
        if request.method == 'PUT':
            return jsonify({'success': False, 'message': 'Error updating announcement'}), 500
        else:
            show_error('Error updating announcement.')
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/announcements/<int:announcement_id>/delete', endpoint='delete_announcement', methods=['DELETE', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_announcement(announcement_id):
    """
    Delete an announcement by its ID.
    """
    session = g.db_session
    announcement = session.query(Announcement).get(announcement_id)
    if not announcement:
        if request.method == 'DELETE':
            return jsonify({'error': 'Announcement not found.'}), 404
        else:
            show_error('Announcement not found.')
            return redirect(url_for('admin.admin_dashboard'))

    session.delete(announcement)
    session.commit()
    
    if request.method == 'DELETE':
        return jsonify({'success': True})
    else:
        show_success('Announcement deleted successfully.')
        return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/announcements/reorder', endpoint='reorder_announcements', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reorder_announcements():
    """
    Reorder announcements based on a new position order.
    """
    session = g.db_session
    new_order = request.get_json().get('order', [])
    
    for idx, announcement_id in enumerate(new_order):
        announcement = session.query(Announcement).get(announcement_id)
        if announcement:
            announcement.position = idx + 1
            session.add(announcement)
    
    session.commit()
    return jsonify({'success': True})


# -----------------------------------------------------------
# Core Admin Routes (Polls & Match Management)
# -----------------------------------------------------------

@admin_bp.route('/admin/polls', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_polls():
    """View and manage league polls."""
    session = g.db_session
    
    # Get all polls ordered by creation date (newest first)
    polls = session.query(LeaguePoll).order_by(desc(LeaguePoll.created_at)).all()
    
    # Calculate response counts for each poll
    for poll in polls:
        poll.response_counts = poll.get_response_counts()
        poll.total_responses = sum(poll.response_counts.values())
    
    # Commit the session before rendering the template to avoid holding
    # the database transaction open during template rendering
    session.commit()
    
    return render_template('admin/manage_polls.html', polls=polls)


@admin_bp.route('/admin/polls/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_poll():
    """Create a new league poll."""
    session = g.db_session
    
    # Get current Pub League season team count for display
    current_season = session.query(Season).filter(
        Season.league_type == 'Pub League',
        Season.is_current == True
    ).first()
    
    team_count = 0
    if current_season:
        team_count = session.query(Team).join(
            League, Team.league_id == League.id
        ).filter(
            League.season_id == current_season.id,
            Team.discord_channel_id.isnot(None)
        ).count()
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        question = request.form.get('question', '').strip()
        
        if not title or not question:
            show_error('Title and question are required.')
            return render_template('admin/create_poll.html', team_count=team_count, current_season=current_season)
        
        try:
            # Create the poll
            poll = LeaguePoll(
                title=title,
                question=question,
                created_by=safe_current_user.id,
                status='ACTIVE'
            )
            session.add(poll)
            session.flush()  # To get the poll ID
            
            # Get only current season teams with Discord channels
            current_season_post = session.query(Season).filter(
                Season.league_type == 'Pub League',
                Season.is_current == True
            ).first()
            
            if not current_season_post:
                show_error('No active Pub League season found.')
                return render_template('admin/create_poll.html', team_count=0, current_season=None)
            
            # Get teams from current season only
            teams = session.query(Team).join(
                League, Team.league_id == League.id
            ).filter(
                League.season_id == current_season_post.id,
                Team.discord_channel_id.isnot(None)
            ).all()
            
            if not teams:
                show_warning('No teams with Discord channels found. Poll created but not sent.')
                session.commit()
                return redirect(url_for('admin.manage_polls'))
            
            # Create Discord message records for each team
            discord_messages = []
            for team in teams:
                discord_msg = LeaguePollDiscordMessage(
                    poll_id=poll.id,
                    team_id=team.id,
                    channel_id=team.discord_channel_id
                )
                session.add(discord_msg)
                discord_messages.append(discord_msg)
            
            session.commit()
            
            # Send poll to Discord via API call to Discord bot
            try:
                discord_bot_url = current_app.config.get('DISCORD_BOT_URL', 'http://discord-bot:5001')
                payload = {
                    'poll_id': poll.id,
                    'title': poll.title,
                    'question': poll.question,
                    'teams': [{'team_id': msg.team_id, 'channel_id': msg.channel_id, 'message_record_id': msg.id} 
                             for msg in discord_messages]
                }
                
                response = requests.post(
                    f'{discord_bot_url}/api/send_league_poll',
                    json=payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    sent_count = result.get('sent', 0)
                    failed_count = result.get('failed', 0)
                    
                    if failed_count > 0:
                        show_warning(f'Poll {title} sent to {sent_count} teams. Failed to send to {failed_count} teams.')
                    else:
                        show_success(f'Poll {title} successfully sent to all {sent_count} teams!')
                else:
                    logger.error(f"Failed to send poll to Discord: {response.status_code} - {response.text}")
                    show_warning(f'Poll created but failed to send to Discord. Status: {response.status_code}')
                    
            except Exception as e:
                logger.error(f"Error sending poll to Discord: {str(e)}", exc_info=True)
                show_warning('Poll created but failed to send to Discord. Check logs for details.')
            
            return redirect(url_for('admin.manage_polls'))
            
        except Exception as e:
            logger.error(f"Error creating poll: {str(e)}", exc_info=True)
            show_error(f'Error creating poll: {str(e)}')
            session.rollback()
    
    return render_template('admin/create_poll.html', team_count=team_count, current_season=current_season)


@admin_bp.route('/admin/polls/<int:poll_id>/results', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def poll_results(poll_id):
    """View detailed results for a specific poll."""
    session = g.db_session
    
    poll = session.query(LeaguePoll).get(poll_id)
    if not poll:
        show_error('Poll not found.')
        return redirect(url_for('admin.manage_polls'))
    
    # Get overall response counts
    response_counts = poll.get_response_counts()
    total_responses = sum(response_counts.values())
    
    # Get team breakdown
    team_breakdown_raw = poll.get_team_breakdown()
    
    # Organize team breakdown by team
    team_breakdown = {}
    for team_name, team_id, response, count in team_breakdown_raw:
        if team_name not in team_breakdown:
            team_breakdown[team_name] = {
                'team_id': team_id,
                'yes': 0, 'no': 0, 'maybe': 0, 'total': 0
            }
        team_breakdown[team_name][response] = count
        team_breakdown[team_name]['total'] += count
    
    # Get individual responses for detailed view
    responses = session.query(LeaguePollResponse, Player, Team).join(
        Player, Player.id == LeaguePollResponse.player_id
    ).join(
        player_teams, player_teams.c.player_id == Player.id
    ).join(
        Team, Team.id == player_teams.c.team_id
    ).filter(
        LeaguePollResponse.poll_id == poll_id
    ).order_by(Team.name, Player.name).all()
    
    return render_template('admin/poll_results.html', 
                         poll=poll, 
                         response_counts=response_counts,
                         total_responses=total_responses,
                         team_breakdown=team_breakdown,
                         responses=responses)


@admin_bp.route('/admin/polls/<int:poll_id>/close', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def close_poll(poll_id):
    """Close a poll to prevent further responses."""
    session = g.db_session
    
    poll = session.query(LeaguePoll).get(poll_id)
    if not poll:
        show_error('Poll not found.')
        return redirect(url_for('admin.manage_polls'))
    
    if poll.status == 'CLOSED':
        show_info('Poll is already closed.')
        return redirect(url_for('admin.manage_polls'))
    
    try:
        poll.status = 'CLOSED'
        poll.closed_at = datetime.utcnow()
        session.add(poll)
        session.commit()
        
        show_success(f'Poll {poll.title} has been closed.')
        
    except Exception as e:
        logger.error(f"Error closing poll: {str(e)}", exc_info=True)
        show_error(f'Error closing poll: {str(e)}')
        session.rollback()
    
    return redirect(url_for('admin.manage_polls'))


@admin_bp.route('/admin/polls/<int:poll_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_poll(poll_id):
    """Delete a poll and all its responses."""
    session = g.db_session
    
    poll = session.query(LeaguePoll).get(poll_id)
    if not poll:
        show_error('Poll not found.')
        return redirect(url_for('admin.manage_polls'))
    
    try:
        poll_title = poll.title
        poll.status = 'DELETED'
        session.add(poll)
        session.commit()
        
        show_success(f'Poll {poll_title} has been deleted.')
        
    except Exception as e:
        logger.error(f"Error deleting poll: {str(e)}", exc_info=True)
        show_error(f'Error deleting poll: {str(e)}')
        session.rollback()
    
    return redirect(url_for('admin.manage_polls'))


# API endpoint for Discord bot to update poll responses
@admin_bp.route('/api/update_poll_response', methods=['POST'])
@csrf_exempt
def update_poll_response():
    """Update poll response from Discord bot."""
    try:
        data = request.get_json()
        
        poll_id = data.get('poll_id')
        discord_id = data.get('discord_id')
        response = data.get('response')  # 'yes', 'no', 'maybe'
        
        if not all([poll_id, discord_id, response]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if response not in ['yes', 'no', 'maybe']:
            return jsonify({'error': 'Invalid response value'}), 400
        
        session = g.db_session
        
        # Find the player by Discord ID
        player = session.query(Player).filter(Player.discord_id == str(discord_id)).first()
        if not player:
            return jsonify({'error': 'Player not found'}), 404
        
        # Check if poll exists and is active
        poll = session.query(LeaguePoll).filter(
            LeaguePoll.id == poll_id,
            LeaguePoll.status == 'ACTIVE'
        ).first()
        if not poll:
            return jsonify({'error': 'Poll not found or not active'}), 404
        
        # Check if response already exists
        existing_response = session.query(LeaguePollResponse).filter(
            LeaguePollResponse.poll_id == poll_id,
            LeaguePollResponse.player_id == player.id
        ).first()
        
        if existing_response:
            # Update existing response
            existing_response.response = response
            existing_response.responded_at = datetime.utcnow()
            session.add(existing_response)
        else:
            # Create new response
            new_response = LeaguePollResponse(
                poll_id=poll_id,
                player_id=player.id,
                discord_id=str(discord_id),
                response=response
            )
            session.add(new_response)
        
        session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Error updating poll response: {str(e)}", exc_info=True)
        session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/update_poll_message', methods=['POST'])
@csrf_exempt
def update_poll_message():
    """Update poll message record with Discord message ID after sending."""
    try:
        data = request.get_json()
        
        message_record_id = data.get('message_record_id')
        message_id = data.get('message_id')
        sent_at = data.get('sent_at')
        
        if not all([message_record_id, message_id]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        session = g.db_session
        
        # Find the Discord message record
        discord_message = session.query(LeaguePollDiscordMessage).get(message_record_id)
        if not discord_message:
            return jsonify({'error': 'Message record not found'}), 404
        
        # Update the record
        discord_message.message_id = message_id
        if sent_at:
            discord_message.sent_at = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
        else:
            discord_message.sent_at = datetime.utcnow()
        
        session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Error updating poll message: {str(e)}", exc_info=True)
        session.rollback()
        return jsonify({'error': str(e)}), 500


# Match management routes are now in app/admin/mls_routes.py

# Task Management Routes
@admin_bp.route('/admin/task-management', endpoint='task_management', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_task_management():
    """Get task management data for admin dashboard."""
    try:
        from app.utils.task_manager import TaskManager
        
        # Get task statistics with error handling
        try:
            stats = TaskManager.get_task_statistics()
        except Exception as stats_error:
            logger.error(f"Error getting task statistics: {stats_error}")
            stats = {'error': str(stats_error)}
        
        # Get active tasks with error handling
        try:
            active_tasks = TaskManager.get_active_tasks()
        except Exception as tasks_error:
            logger.error(f"Error getting active tasks: {tasks_error}")
            active_tasks = []
        
        # Ensure all data is JSON serializable by cleaning it
        def clean_for_json(obj):
            """Recursively clean data to make it JSON serializable."""
            if obj is None:
                return None
            elif isinstance(obj, (str, int, float, bool)):
                return obj
            elif isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [clean_for_json(item) for item in obj]
            elif isinstance(obj, Exception):
                return str(obj)
            else:
                return str(obj)
        
        # Clean the data
        clean_stats = clean_for_json(stats)
        clean_active_tasks = clean_for_json(active_tasks)
        
        return jsonify({
            'success': True,
            'statistics': clean_stats,
            'active_tasks': clean_active_tasks
        })
        
    except Exception as e:
        logger.error(f"Error fetching task management data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/admin/revoke-task/<task_id>', endpoint='revoke_task', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_revoke_task(task_id):
    """Completely destroy a running task - nuclear option."""
    try:
        from app.utils.task_manager import TaskManager
        
        # Use the nuclear option - completely destroy the task
        success = TaskManager.kill_task_completely(task_id)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to destroy task'
            }), 500
            
    except Exception as e:
        logger.error(f"Error destroying task {task_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/admin/task-details/<task_id>', endpoint='task_details', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_task_details(task_id):
    """Get detailed information about a specific task."""
    try:
        from app.utils.task_manager import TaskManager
        
        task_info = TaskManager.get_task_info(task_id)
        
        if task_info:
            return jsonify({
                'success': True,
                'task': task_info
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Task not found'
            }), 404
            
    except Exception as e:
        logger.error(f"Error fetching task details for {task_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/admin/remove-task/<task_id>', endpoint='remove_task', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_remove_task(task_id):
    """Remove a completed/failed task from the registry."""
    try:
        from app.utils.task_manager import TaskManager
        from celery.result import AsyncResult
        from app.core import celery
        
        # Get task info to check if it's safe to remove
        task_info = TaskManager.get_task_info(task_id)
        if not task_info:
            return jsonify({
                'success': False,
                'error': 'Task not found'
            }), 404
        
        # Check if task can be safely removed
        # Allow removal of completed, failed, or revoked tasks
        celery_result = AsyncResult(task_id, app=celery)
        task_manager_status = task_info.get('status', 'UNKNOWN')
        
        # Allow removal if TaskManager shows it as revoked OR Celery shows it as finished
        if (celery_result.state in ['PENDING', 'PROGRESS', 'STARTED'] and 
            task_manager_status not in ['REVOKED', 'SUCCESS', 'FAILURE']):
            return jsonify({
                'success': False,
                'error': 'Cannot remove active task. Cancel it first.'
            }), 400
        
        # Remove from TaskManager registry
        success = TaskManager.remove_task(task_id)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to remove task'
            }), 500
            
    except Exception as e:
        logger.error(f"Error removing task {task_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/admin/cleanup-tasks', endpoint='cleanup_tasks', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_cleanup_tasks():
    """Clean up old task metadata from Redis."""
    try:
        from app.utils.task_manager import TaskManager
        
        # Clean up both TaskManager registry and Celery metadata
        registry_cleaned = TaskManager.cleanup_completed_tasks(max_age_hours=24)
        metadata_cleaned = TaskManager.cleanup_old_celery_metadata(max_age_hours=168)  # 7 days
        
        return jsonify({
            'success': True,
            'registry_cleaned': registry_cleaned,
            'metadata_cleaned': metadata_cleaned,
            'total_cleaned': registry_cleaned + metadata_cleaned
        })
        
    except Exception as e:
        logger.error(f"Error cleaning up tasks: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500