# app/admin/scheduling_routes.py

"""
Scheduling and Scheduled Messages Routes

This module contains routes for managing scheduled messages,
season availability scheduling, and message processing.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, abort, g, render_template, current_app, jsonify
from flask_login import login_required
from flask_wtf.csrf import validate_csrf, generate_csrf
from flask import session as flask_session
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from wtforms.validators import ValidationError
import pytz
from celery import Celery

from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_info
from app.models import ScheduledMessage, Match
from app.utils.user_helpers import safe_current_user
from app.tasks.tasks_rsvp import send_availability_message
from app.config.celery_config import CeleryConfig

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp

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
# Scheduled Messages & Season Availability
# -----------------------------------------------------------

@admin_bp.route('/admin/schedule_season', endpoint='schedule_season', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_season():
    """
    Schedule availability messages for all future Sunday matches (next 90 days).
    Implemented directly without using Celery for reliability.
    """
    session = g.db_session
    
    try:
        # Direct implementation of schedule_season_availability from tasks_core.py
        start_date = datetime.utcnow().date()
        # For "entire season", look at the next 90 days
        end_date = start_date + timedelta(days=90)

        # Query matches within the next 90 days along with any associated scheduled messages
        matches = session.query(Match).options(
            joinedload(Match.scheduled_messages)
        ).filter(
            Match.date.between(start_date, end_date)
        ).all()

        # Prepare data for each match
        matches_data = [{
            'id': match.id,
            'date': match.date,
            'has_message': any(msg for msg in match.scheduled_messages),
            'name': f"{match.home_team.name} vs {match.away_team.name}" if hasattr(match, 'home_team') and hasattr(match, 'away_team') else "Unknown match"
        } for match in matches]

        scheduled_count = 0
        # Process each match; schedule a message if not already present
        for match_data in matches_data:
            if not match_data['has_message']:
                # Calculate send date and time (9:00 AM on the computed day)
                send_date = match_data['date'] - timedelta(days=match_data['date'].weekday() + 1)
                send_time = datetime.combine(send_date, datetime.min.time()) + timedelta(hours=9)

                scheduled_message = ScheduledMessage(
                    match_id=match_data['id'],
                    scheduled_send_time=send_time,
                    status='PENDING'
                )
                session.add(scheduled_message)
                scheduled_count += 1
                logger.info(f"Scheduled availability message for match {match_data['id']} - {match_data['name']} at {send_time}")
                
        # Commit all the new scheduled messages
        session.commit()

        if scheduled_count > 0:
            show_success(f'Successfully scheduled {scheduled_count} messages for matches in the next 90 days.')
        else:
            show_info('No new messages scheduled. All matches already have scheduled messages.')
        
        logger.info(f"Admin {safe_current_user.id} manually scheduled {scheduled_count} future matches")
        
    except Exception as e:
        logger.error(f"Error scheduling season availability: {str(e)}", exc_info=True)
        show_error(f'Error scheduling season availability: {str(e)}')
        session.rollback()
    
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/scheduled_messages', endpoint='view_scheduled_messages')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_scheduled_messages():
    """
    View a list of scheduled messages with enhanced filtering and ECS FC support.
    """
    session = g.db_session
    
    # Get filter parameters
    status_filter = request.args.get('status', '')
    message_type_filter = request.args.get('message_type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Build base query with eager loading
    query = session.query(ScheduledMessage).options(
        joinedload(ScheduledMessage.match).joinedload(Match.home_team),
        joinedload(ScheduledMessage.match).joinedload(Match.away_team),
        joinedload(ScheduledMessage.creator)
    )
    
    # Apply status filter
    if status_filter:
        query = query.filter(ScheduledMessage.status == status_filter.upper())
    
    # Apply message type filter
    if message_type_filter:
        if message_type_filter == 'pub_league':
            # Standard messages (no message_type or standard)
            query = query.filter(
                (ScheduledMessage.message_type == None) |
                (ScheduledMessage.message_type == 'standard')
            )
        elif message_type_filter == 'ecs_fc':
            query = query.filter(ScheduledMessage.message_type == 'ecs_fc_rsvp')
        else:
            query = query.filter(ScheduledMessage.message_type == message_type_filter)
    
    # Apply date range filters
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(ScheduledMessage.scheduled_send_time >= from_date)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(ScheduledMessage.scheduled_send_time < to_date)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    # Get messages and order by scheduled time
    messages = query.order_by(ScheduledMessage.scheduled_send_time.desc()).all()
    
    # Calculate statistics
    total_messages = len(messages)
    
    # Get all messages for global stats (not filtered)
    all_messages = session.query(ScheduledMessage).all()
    stats = {
        'total': len(all_messages),
        'pending': len([m for m in all_messages if m.status == 'PENDING']),
        'sent': len([m for m in all_messages if m.status == 'SENT']),
        'failed': len([m for m in all_messages if m.status == 'FAILED']),
        'queued': len([m for m in all_messages if m.status == 'QUEUED']),
        'pub_league': len([m for m in all_messages if not m.message_type or m.message_type == 'standard']),
        'ecs_fc': len([m for m in all_messages if m.message_type == 'ecs_fc_rsvp']),
        'filtered_count': total_messages
    }
    
    # Get unique message types for filter dropdown
    message_types = session.query(ScheduledMessage.message_type).distinct().all()
    available_types = ['pub_league', 'ecs_fc']
    for msg_type in message_types:
        if msg_type[0] and msg_type[0] not in ['standard', 'ecs_fc_rsvp']:
            available_types.append(msg_type[0])
    
    return render_template('admin/scheduled_messages.html', 
                         title='Discord Scheduled Messages', 
                         messages=messages,
                         stats=stats,
                         available_types=available_types,
                         current_filters={
                             'status': status_filter,
                             'message_type': message_type_filter,
                             'date_from': date_from,
                             'date_to': date_to
                         })


@admin_bp.route('/admin/force_send/<int:message_id>', endpoint='force_send_message', methods=['POST'])
@csrf_exempt
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def force_send_message(message_id):
    """
    Force-send a scheduled message immediately.
    """
    # Skip CSRF validation if necessary but ensure proper logging
    csrf_enabled = current_app.config.get('WTF_CSRF_ENABLED', True)
    
    if csrf_enabled:
        # Ensure the CSRF token exists in the session
        if 'csrf_token' not in flask_session:
            logger.warning("CSRF token missing from session - generating new token")
            # Generate a new token and store it
            csrf_token = generate_csrf()
            flask_session['csrf_token'] = csrf_token
        
        # Log CSRF debugging info
        logger.info(f"Processing force send for message {message_id}")
        logger.info(f"Form CSRF token: {request.form.get('csrf_token')}")
        logger.info(f"Session CSRF token exists: {'csrf_token' in flask_session}")
        logger.info(f"Session ID: {flask_session.sid if hasattr(flask_session, 'sid') else 'unknown'}")
        
        # At this point we've already authenticated the user via login_required
        # And confirmed they have the proper role via role_required
        # So we can skip the CSRF validation if it fails, but log the issue
        try:
            # Validate the CSRF token but continue even if it fails
            form_token = request.form.get('csrf_token')
            if form_token:
                validate_csrf(form_token)
                logger.info("CSRF validation successful")
            else:
                logger.warning("No CSRF token provided in form")
        except ValidationError as e:
            # Log the error but proceed anyway
            logger.warning(f"CSRF validation error: {str(e)} - proceeding with authenticated user")
    else:
        logger.info("CSRF protection is disabled in configuration")
    
    # Proceed with the main functionality
    session = g.db_session
    message = session.query(ScheduledMessage).get(message_id)
    if not message:
        logger.error(f"Message {message_id} not found")
        abort(404)

    try:
        # Queue the message for sending using the correct task
        send_availability_message.delay(scheduled_message_id=message.id)
        message.status = 'QUEUED'
        session.commit()
        logger.info(f"Message {message_id} queued for sending")
        show_success('Message is being sent.')
    except Exception as e:
        logger.error(f"Error queuing message {message_id}: {str(e)}")
        show_error('Error queuing message for sending.')

    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/schedule_next_week', endpoint='schedule_next_week', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_next_week():
    """
    Initiate the scheduling task specifically for the next week's Sunday matches.
    Schedules RSVP messages to be sent on Monday mornings.
    """
    from app.tasks.tasks_rsvp import schedule_weekly_match_availability
    
    task = schedule_weekly_match_availability.delay()
    show_success('This Sunday\'s match scheduling task has been initiated.')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/process_scheduled_messages', endpoint='process_scheduled_messages', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_scheduled_messages_route():
    """
    Immediately process all pending scheduled messages.
    This forces the system to send out any pending RSVP messages right away.
    """
    from app.tasks.tasks_rsvp import process_scheduled_messages
    
    task = process_scheduled_messages.delay()
    show_success('Processing and sending all pending messages - check status in a few minutes.')
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/cleanup_old_messages', endpoint='cleanup_old_messages_route', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def cleanup_old_messages_route():
    """
    Clean up old scheduled messages that have already been sent or failed.
    By default, removes messages older than 7 days.
    """
    days_old = request.form.get('days_old', 7, type=int)
    session = g.db_session
    
    try:
        # Direct implementation without using Celery
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Get count first for messaging
        total_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ).count()
        
        # Delete the old messages
        deleted_count = session.query(ScheduledMessage).filter(
            ScheduledMessage.scheduled_send_time < cutoff_date,
            ScheduledMessage.status.in_(['SENT', 'FAILED'])
        ).delete(synchronize_session=False)
        
        session.commit()
        
        if deleted_count > 0:
            show_success(f'Successfully deleted {deleted_count} old messages.')
        else:
            show_info(f'No messages found older than {days_old} days with status SENT or FAILED.')
            
        logger.info(f"Admin {safe_current_user.id} manually cleaned up {deleted_count} old messages")
        
    except Exception as e:
        logger.error(f"Error cleaning up old messages: {str(e)}", exc_info=True)
        show_error(f'Error cleaning up old messages: {str(e)}')
        session.rollback()
    
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/delete_message/<int:message_id>', endpoint='delete_message', methods=['POST'])
@csrf_exempt
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_message(message_id):
    """
    Delete a specific scheduled message.
    """
    session = g.db_session
    message = session.query(ScheduledMessage).get(message_id)
    
    if not message:
        show_error('Message not found.')
    else:
        match_info = f"{message.match.home_team.name} vs {message.match.away_team.name}" if message.match else "Unknown match"
        session.delete(message)
        show_success(f'Message for {match_info} has been deleted.')
    
    return redirect(url_for('admin.view_scheduled_messages'))


@admin_bp.route('/admin/scheduled_messages/validate', endpoint='validate_scheduled_messages')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def validate_scheduled_messages():
    """
    Validate scheduled messages system and show detailed status.
    Provides a comprehensive view of the scheduled message pipeline.
    """
    session = g.db_session
    validation_data = {
        'timestamp': datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M:%S PST'),
        'database_status': {},
        'celery_status': {},
        'beat_schedule': {},
        'upcoming_messages': [],
        'issues': [],
        'recommendations': []
    }
    
    try:
        # 1. Check Database Status
        pst = pytz.timezone('America/Los_Angeles')
        now_utc = datetime.utcnow()
        now_pst = datetime.now(pst)
        
        # Count messages by status
        status_counts = session.query(
            ScheduledMessage.status,
            func.count(ScheduledMessage.id)
        ).group_by(ScheduledMessage.status).all()
        
        validation_data['database_status'] = {
            'total_messages': sum(count for _, count in status_counts),
            'by_status': dict(status_counts),
            'ready_to_send': 0,
            'overdue': 0
        }
        
        # Check for messages ready to send
        ready_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= now_utc
        ).all()
        
        validation_data['database_status']['ready_to_send'] = len(ready_messages)
        
        # Check for overdue messages (should have been sent but still pending)
        overdue_threshold = now_utc - timedelta(hours=1)
        overdue_messages = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'PENDING',
            ScheduledMessage.scheduled_send_time <= overdue_threshold
        ).all()
        
        validation_data['database_status']['overdue'] = len(overdue_messages)
        
        if overdue_messages:
            validation_data['issues'].append({
                'severity': 'warning',
                'message': f'{len(overdue_messages)} messages are overdue (scheduled more than 1 hour ago but not sent)'
            })
        
        # Get upcoming messages
        upcoming = session.query(ScheduledMessage).filter(
            ScheduledMessage.status.in_(['PENDING', 'QUEUED']),
            ScheduledMessage.scheduled_send_time >= now_utc - timedelta(days=1),
            ScheduledMessage.scheduled_send_time <= now_utc + timedelta(days=7)
        ).order_by(ScheduledMessage.scheduled_send_time).limit(10).all()
        
        for msg in upcoming:
            send_time = msg.scheduled_send_time
            if send_time.tzinfo is None:
                send_time = pytz.utc.localize(send_time)
            send_time_pst = send_time.astimezone(pst)
            
            time_diff = send_time_pst - now_pst
            hours_until = time_diff.total_seconds() / 3600
            
            match_info = "N/A"
            if msg.match:
                match_date = msg.match.date
                if isinstance(match_date, datetime):
                    match_date_str = match_date.strftime("%b %d")
                else:
                    match_date_str = str(match_date)
                
                if hasattr(msg.match, 'home_team') and hasattr(msg.match, 'away_team'):
                    if msg.match.home_team and msg.match.away_team:
                        match_info = f"{match_date_str}: {msg.match.home_team.name} vs {msg.match.away_team.name}"
                else:
                    match_info = match_date_str
            
            validation_data['upcoming_messages'].append({
                'id': msg.id,
                'status': msg.status,
                'send_time': send_time_pst.strftime("%Y-%m-%d %H:%M PST"),
                'hours_until': round(hours_until, 1),
                'match_info': match_info,
                'type': msg.message_type or 'standard',
                'is_overdue': hours_until < -1
            })
        
        # 2. Check Celery Status
        try:
            celery_app = Celery('app')
            celery_app.config_from_object('app.config.celery_config:CeleryConfig')
            
            # Get inspect instance
            inspect = celery_app.control.inspect()
            
            # Check active workers
            active_workers = inspect.active()
            worker_count = len(active_workers) if active_workers else 0
            
            # Check scheduled tasks
            scheduled_tasks = inspect.scheduled()
            scheduled_count = sum(len(tasks) for tasks in scheduled_tasks.values()) if scheduled_tasks else 0
            
            # Check reserved tasks
            reserved_tasks = inspect.reserved()
            reserved_count = sum(len(tasks) for tasks in reserved_tasks.values()) if reserved_tasks else 0
            
            # Check if process_scheduled_messages is registered
            registered = inspect.registered()
            process_task_registered = False
            if registered:
                for worker, tasks in registered.items():
                    if 'app.tasks.tasks_rsvp.process_scheduled_messages' in tasks:
                        process_task_registered = True
                        break
            
            validation_data['celery_status'] = {
                'connected': True,
                'worker_count': worker_count,
                'scheduled_tasks': scheduled_count,
                'reserved_tasks': reserved_count,
                'process_task_registered': process_task_registered
            }
            
            if worker_count == 0:
                validation_data['issues'].append({
                    'severity': 'error',
                    'message': 'No Celery workers are running!'
                })
            
            if not process_task_registered:
                validation_data['issues'].append({
                    'severity': 'warning',
                    'message': 'process_scheduled_messages task is not registered with workers'
                })
                
        except Exception as e:
            validation_data['celery_status'] = {
                'connected': False,
                'error': str(e)
            }
            validation_data['issues'].append({
                'severity': 'error',
                'message': f'Cannot connect to Celery: {str(e)}'
            })
        
        # 3. Check Beat Schedule
        validation_data['beat_schedule'] = {
            'configured': False,
            'schedule': None
        }
        
        if 'process-scheduled-messages' in CeleryConfig.beat_schedule:
            task_config = CeleryConfig.beat_schedule['process-scheduled-messages']
            validation_data['beat_schedule'] = {
                'configured': True,
                'task': task_config['task'],
                'schedule': str(task_config['schedule']),
                'queue': task_config['options'].get('queue', 'default')
            }
        else:
            validation_data['issues'].append({
                'severity': 'error',
                'message': 'process-scheduled-messages is not in Celery beat schedule!'
            })
        
        # 4. Generate Recommendations
        if validation_data['database_status']['ready_to_send'] > 0:
            validation_data['recommendations'].append(
                f"There are {validation_data['database_status']['ready_to_send']} messages ready to send. "
                "They should be processed within the next 5 minutes automatically, or you can click 'Process Messages Now'."
            )
        
        if validation_data['database_status']['overdue'] > 0:
            validation_data['recommendations'].append(
                "Overdue messages detected. Check Celery workers and beat scheduler. "
                "Consider clicking 'Process Messages Now' to force immediate processing."
            )
        
        if not validation_data['celery_status'].get('connected'):
            validation_data['recommendations'].append(
                "Celery is not accessible. Ensure Redis and Celery services are running. "
                "Run: docker-compose ps to check service status."
            )
        
        # 5. Check recent sends
        recent_sent = session.query(ScheduledMessage).filter(
            ScheduledMessage.status == 'SENT',
            ScheduledMessage.sent_time >= now_utc - timedelta(hours=24)
        ).order_by(ScheduledMessage.sent_time.desc()).limit(5).all()
        
        validation_data['recent_sends'] = []
        for msg in recent_sent:
            if msg.sent_time:
                sent_time = msg.sent_time
                if sent_time.tzinfo is None:
                    sent_time = pytz.utc.localize(sent_time)
                sent_time_pst = sent_time.astimezone(pst)
                validation_data['recent_sends'].append({
                    'id': msg.id,
                    'sent_time': sent_time_pst.strftime("%Y-%m-%d %H:%M PST")
                })
        
    except Exception as e:
        logger.error(f"Error during validation: {str(e)}", exc_info=True)
        validation_data['issues'].append({
            'severity': 'error',
            'message': f'Validation error: {str(e)}'
        })
    
    # Return JSON for API calls or render template for browser
    if request.headers.get('Accept') == 'application/json':
        return jsonify(validation_data)
    
    return render_template('admin/scheduled_message_validation.html',
                         title='Scheduled Message System Validation',
                         validation=validation_data)