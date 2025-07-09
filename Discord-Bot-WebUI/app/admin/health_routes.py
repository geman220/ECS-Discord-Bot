# app/admin/health_routes.py

"""
System Health and Utilities Routes

This module contains routes for system health checks, task status monitoring,
and utility endpoints like Twilio configuration testing.
"""

import os
import logging
from datetime import datetime
from celery.result import AsyncResult
from flask import Blueprint, jsonify, g, current_app
from flask_login import login_required
from twilio.rest import Client

from app.decorators import role_required
from app.sms_helpers import check_sms_config
from app.utils.task_monitor import TaskMonitor, get_task_info

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# System Health and Task Status Routes
# -----------------------------------------------------------

@admin_bp.route('/admin/health', endpoint='health_check', methods=['GET'])
@login_required
@role_required('Global Admin')
def health_check():
    """
    Perform a system health check.
    """
    health_status = check_system_health(g.db_session)
    return jsonify(health_status)


@admin_bp.route('/admin/task_status', endpoint='get_task_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def get_task_status():
    """
    Retrieve comprehensive task status and statistics.
    """
    try:
        monitor = TaskMonitor()
        
        # Get task statistics
        stats = monitor.get_task_stats(time_window=3600)  # Last hour
        
        # Detect zombie tasks
        zombie_tasks = monitor.detect_zombie_tasks()
        
        task_status = {
            'status': 'success',
            'stats': stats,
            'zombie_tasks': zombie_tasks,
            'zombie_count': len(zombie_tasks),
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify(task_status)
    except Exception as e:
        logger.error(f"Error getting task status: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to retrieve task status: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500


@admin_bp.route('/admin/task_status/<task_id>', endpoint='check_task_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_task_status(task_id):
    """
    Check the detailed status of a specific task.
    """
    try:
        # Get comprehensive task info using the task monitor utility
        task_info = get_task_info(task_id)
        return jsonify(task_info)
    except Exception as e:
        logger.error(f"Error checking task {task_id}: {str(e)}")
        return jsonify({
            'status': 'error',
            'task_id': task_id,
            'message': f'Failed to get task info: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500


@admin_bp.route('/admin/test_twilio', methods=['GET'])
@login_required
@role_required('Global Admin')
def test_twilio_config():
    """
    Test the Twilio configuration.
    
    Checks the environment variables and attempts a connection to Twilio
    without actually sending an SMS. Returns diagnostic information.
    """
    result = {
        'config_check': check_sms_config(),
        'environment_vars': {},
        'auth_check': {},
        'connection_test': {'status': 'UNKNOWN'}
    }
    
    # Add environment variable debug info (hiding actual values)
    for key in os.environ:
        if 'TWILIO' in key or 'TEXTMAGIC' in key:
            result['environment_vars'][key] = "PRESENT"
    
    # Check auth token for any issues
    twilio_sid = current_app.config.get('TWILIO_SID') or current_app.config.get('TWILIO_ACCOUNT_SID')
    twilio_auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
    
    if twilio_sid and twilio_auth_token:
        # Check for common issues in auth token
        result['auth_check']['sid_length'] = len(twilio_sid)
        result['auth_check']['token_length'] = len(twilio_auth_token)
        result['auth_check']['sid_starts_with'] = twilio_sid[:2] if len(twilio_sid) >= 2 else ""
        
        # Check if the auth token is valid Base64
        try:
            # Just check if it could be valid Base64 (not whether it is)
            is_valid_base64 = all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' 
                                for c in twilio_auth_token)
            result['auth_check']['valid_token_format'] = is_valid_base64
        except Exception:
            result['auth_check']['valid_token_format'] = False
    else:
        result['auth_check']['sid_present'] = bool(twilio_sid)
        result['auth_check']['token_present'] = bool(twilio_auth_token)
    
    # Test actual Twilio connection
    try:
        if not twilio_sid or not twilio_auth_token:
            result['connection_test'] = {
                'status': 'FAILED',
                'message': 'Missing Twilio credentials'
            }
        else:
            # Try with hardcoded credentials (redacted in the response)
            raw_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
            result['auth_check']['raw_token_different'] = raw_auth_token != twilio_auth_token
            
            # Check for whitespace issues
            result['auth_check']['token_has_whitespace'] = any(c.isspace() for c in twilio_auth_token)
            cleaned_token = twilio_auth_token.strip()
            
            client = Client(twilio_sid, cleaned_token)
            # Make a simple API call that doesn't send an SMS
            try:
                account = client.api.accounts(twilio_sid).fetch()
                result['connection_test'] = {
                    'status': 'SUCCESS',
                    'account_status': account.status,
                    'account_type': account.type
                }
            except Exception as acc_error:
                # If that fails, try with raw token from environment
                try:
                    client = Client(twilio_sid, raw_auth_token)
                    account = client.api.accounts(twilio_sid).fetch()
                    result['connection_test'] = {
                        'status': 'SUCCESS_WITH_RAW_TOKEN',
                        'account_status': account.status,
                        'account_type': account.type,
                        'error_with_config_token': str(acc_error)
                    }
                except Exception as raw_error:
                    result['connection_test'] = {
                        'status': 'FAILED_BOTH',
                        'config_token_error': str(acc_error),
                        'raw_token_error': str(raw_error)
                    }
    except Exception as e:
        result['connection_test'] = {
            'status': 'ERROR',
            'message': str(e)
        }
    
    return jsonify(result)


# -----------------------------------------------------------
# System Health Helper Functions
# -----------------------------------------------------------

def check_system_health(session):
    """
    Comprehensive system health check including database, Redis, and Celery.
    """
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'components': {}
    }
    
    try:
        # Database health check
        try:
            session.execute('SELECT 1')
            health_status['components']['database'] = {
                'status': 'healthy',
                'message': 'Database connection successful'
            }
        except Exception as db_error:
            health_status['components']['database'] = {
                'status': 'unhealthy',
                'message': f'Database error: {str(db_error)}'
            }
            health_status['status'] = 'degraded'
        
        # Redis health check
        try:
            from app.utils.redis_manager import RedisManager
            redis_client = RedisManager().client
            redis_client.ping()
            health_status['components']['redis'] = {
                'status': 'healthy',
                'message': 'Redis connection successful'
            }
        except Exception as redis_error:
            health_status['components']['redis'] = {
                'status': 'unhealthy', 
                'message': f'Redis error: {str(redis_error)}'
            }
            health_status['status'] = 'degraded'
        
        # Celery health check
        try:
            from app.core import celery
            inspect = celery.control.inspect()
            stats = inspect.stats()
            if stats:
                health_status['components']['celery'] = {
                    'status': 'healthy',
                    'message': f'Celery workers active: {len(stats)}',
                    'worker_count': len(stats)
                }
            else:
                health_status['components']['celery'] = {
                    'status': 'warning',
                    'message': 'No active Celery workers detected'
                }
                if health_status['status'] == 'healthy':
                    health_status['status'] = 'degraded'
        except Exception as celery_error:
            health_status['components']['celery'] = {
                'status': 'unhealthy',
                'message': f'Celery error: {str(celery_error)}'
            }
            health_status['status'] = 'degraded'
            
    except Exception as e:
        health_status = {
            'status': 'unhealthy',
            'message': f'Health check failed: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }
    
    return health_status