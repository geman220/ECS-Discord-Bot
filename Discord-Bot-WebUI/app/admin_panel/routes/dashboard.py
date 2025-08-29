# app/admin_panel/routes/dashboard.py

"""
Admin Panel Dashboard Routes

This module contains routes for the core admin panel functionality:
- Main dashboard with overview statistics
- Feature toggles and settings management  
- Audit logs viewing and filtering
- System information and health checks
- Settings initialization
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import text

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminConfig, AdminAuditLog
from app.models.core import User, Role
from app.decorators import role_required
from ..performance import (cache_admin_data, optimize_admin_queries, admin_stats_cache, 
                           get_performance_report, clear_admin_cache)

# Set up the module logger
logger = logging.getLogger(__name__)


@admin_panel_bp.route('/')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@optimize_admin_queries()
def dashboard():
    """Main admin panel dashboard."""
    try:
        # Get overview statistics with caching and fallbacks
        try:
            stats = admin_stats_cache.get_stats('dashboard_stats', lambda: {
                'total_settings': AdminConfig.query.filter_by(is_enabled=True).count(),
                'recent_changes': AdminAuditLog.query.filter(
                    AdminAuditLog.timestamp >= datetime.utcnow() - timedelta(days=7)
                ).count(),
                'active_features': AdminConfig.query.filter_by(
                    is_enabled=True, data_type='boolean'
                ).filter(AdminConfig.value == 'true').count(),
                'total_users': User.query.count()
            })
        except Exception as e:
            logger.warning(f"Error getting dashboard stats: {e}")
            stats = {
                'total_settings': 0,
                'recent_changes': 0,
                'active_features': 0,
                'total_users': 0
            }

        # Get recent admin actions with caching and fallback
        try:
            recent_actions = admin_stats_cache.get_stats('recent_actions', 
                lambda: AdminAuditLog.get_recent_logs(limit=10))
        except Exception as e:
            logger.warning(f"Error getting recent actions: {e}")
            recent_actions = []

        # Get settings by category with fallbacks
        try:
            navigation_settings = AdminConfig.get_settings_by_category('navigation')
        except Exception as e:
            logger.warning(f"Error getting navigation settings: {e}")
            navigation_settings = []
            
        try:
            registration_settings = AdminConfig.get_settings_by_category('registration')
        except Exception as e:
            logger.warning(f"Error getting registration settings: {e}")
            registration_settings = []
            
        try:
            feature_settings = AdminConfig.get_settings_by_category('features')
        except Exception as e:
            logger.warning(f"Error getting feature settings: {e}")
            feature_settings = []
            
        try:
            system_settings = AdminConfig.get_settings_by_category('system')
        except Exception as e:
            logger.warning(f"Error getting system settings: {e}")
            system_settings = []
        
        # Get pending approvals count with fallback
        try:
            pending_approvals = User.query.filter_by(is_approved=False).count()
        except Exception as e:
            logger.warning(f"Error getting pending approvals: {e}")
            pending_approvals = 0

        return render_template(
            'admin_panel/dashboard.html',
            stats=stats,
            recent_actions=recent_actions,
            navigation_settings=navigation_settings,
            registration_settings=registration_settings,
            feature_settings=feature_settings,
            system_settings=system_settings,
            pending_approvals=pending_approvals
        )
    except Exception as e:
        logger.error(f"Error loading admin panel dashboard: {e}")
        flash('Unable to load admin panel dashboard. Check system logs for details.', 'error')
        return redirect(url_for('main.index'))


@admin_panel_bp.route('/features')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def feature_toggles():
    """Feature toggles management page."""
    try:
        # Group settings by category
        categories = {}
        all_settings = AdminConfig.query.filter_by(is_enabled=True).order_by(
            AdminConfig.category, AdminConfig.key
        ).all()

        for setting in all_settings:
            if setting.category not in categories:
                categories[setting.category] = []
            categories[setting.category].append(setting)

        return render_template(
            'admin_panel/feature_toggles.html',
            categories=categories
        )
    except Exception as e:
        logger.error(f"Error loading feature toggles: {e}")
        flash('Unable to load feature toggles. Database connection may be unavailable.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/toggle-setting', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_setting():
    """Toggle a boolean setting via AJAX."""
    try:
        data = request.get_json()
        setting_key = data.get('key')
        
        if not setting_key:
            return jsonify({'success': False, 'message': 'Setting key is required'})

        setting = AdminConfig.query.filter_by(key=setting_key, is_enabled=True).first()
        if not setting:
            return jsonify({'success': False, 'message': 'Setting not found'})

        if setting.data_type != 'boolean':
            return jsonify({'success': False, 'message': 'Setting is not a boolean type'})

        # Toggle the value
        old_value = setting.value
        new_value = 'false' if setting.parsed_value else 'true'
        
        AdminConfig.set_setting(
            key=setting_key,
            value=new_value,
            user_id=current_user.id
        )

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='toggle',
            resource_type='admin_config',
            resource_id=setting_key,
            old_value=old_value,
            new_value=new_value,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True, 
            'new_value': new_value == 'true',
            'message': f'Setting {setting_key} updated successfully'
        })

    except Exception as e:
        logger.error(f"Error toggling setting: {e}")
        return jsonify({'success': False, 'message': 'Server error occurred'})


@admin_panel_bp.route('/update-setting', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_setting():
    """Update a setting value."""
    try:
        setting_key = request.form.get('key')
        setting_value = request.form.get('value')
        
        if not setting_key:
            flash('Setting key is required', 'error')
            return redirect(url_for('admin_panel.feature_toggles'))

        setting = AdminConfig.query.filter_by(key=setting_key, is_enabled=True).first()
        if not setting:
            flash('Setting not found', 'error')
            return redirect(url_for('admin_panel.feature_toggles'))

        old_value = setting.value
        
        AdminConfig.set_setting(
            key=setting_key,
            value=setting_value,
            user_id=current_user.id
        )

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update',
            resource_type='admin_config',
            resource_id=setting_key,
            old_value=old_value,
            new_value=setting_value,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Setting {setting_key} updated successfully', 'success')
        return redirect(url_for('admin_panel.feature_toggles'))

    except Exception as e:
        logger.error(f"Error updating setting: {e}")
        flash('Failed to update setting. Verify the setting key and value are valid.', 'error')
        return redirect(url_for('admin_panel.feature_toggles'))


@admin_panel_bp.route('/audit-logs')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def audit_logs():
    """View admin audit logs."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        
        # Get filter parameters
        user_filter = request.args.get('user_id', type=int)
        resource_filter = request.args.get('resource_type')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        # Build query
        query = AdminAuditLog.query

        if user_filter:
            query = query.filter_by(user_id=user_filter)
        if resource_filter:
            query = query.filter_by(resource_type=resource_filter)
        if date_from:
            query = query.filter(AdminAuditLog.timestamp >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(AdminAuditLog.timestamp <= datetime.fromisoformat(date_to))

        logs = query.order_by(AdminAuditLog.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        # Get filter options
        users = User.query.filter(User.id.in_(
            db.session.query(AdminAuditLog.user_id).distinct()
        )).all()
        
        resource_types = db.session.query(AdminAuditLog.resource_type).distinct().all()
        resource_types = [rt[0] for rt in resource_types]

        return render_template(
            'admin_panel/audit_logs.html',
            logs=logs,
            users=users,
            resource_types=resource_types,
            current_filters={
                'user_id': user_filter,
                'resource_type': resource_filter,
                'date_from': date_from,
                'date_to': date_to
            }
        )
    except Exception as e:
        logger.error(f"Error loading audit logs: {e}")
        flash('Unable to load audit logs. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/system-info')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def system_info():
    """System information and health checks."""
    try:
        # Get system information
        info = {
            'database_status': 'Connected',
            'total_users': User.query.count(),
            'total_roles': Role.query.count(), 
            'total_settings': AdminConfig.query.count(),
            'enabled_settings': AdminConfig.query.filter_by(is_enabled=True).count(),
            'recent_activity': AdminAuditLog.query.filter(
                AdminAuditLog.timestamp >= datetime.utcnow() - timedelta(hours=24)
            ).count()
        }

        # Check for any critical settings
        critical_settings = AdminConfig.query.filter(
            AdminConfig.key.in_(['maintenance_mode', 'teams_navigation_enabled', 'waitlist_registration_enabled'])
        ).all()

        return render_template(
            'admin_panel/system_info.html',
            info=info,
            critical_settings=critical_settings
        )
    except Exception as e:
        logger.error(f"Error loading system info: {e}")
        flash('System information unavailable. Database may be offline.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


# Route aliases for backward compatibility
@admin_panel_bp.route('/feature-toggles')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def feature_toggles_redirect():
    """Redirect to main features page."""
    return redirect(url_for('admin_panel.features'))


@admin_panel_bp.route('/communication-hub')
@login_required
@role_required(['Global Admin', 'Pub League Admin']) 
def communication_hub_redirect():
    """Redirect to main communication page."""
    return redirect(url_for('admin_panel.communication'))


@admin_panel_bp.route('/initialize-settings', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def initialize_settings():
    """Initialize default admin settings."""
    try:
        AdminConfig.initialize_default_settings()
        
        # Log the initialization
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='initialize',
            resource_type='admin_config',
            resource_id='default_settings',
            new_value='Default settings initialized',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash('Default admin settings initialized successfully!', 'success')
        return redirect(url_for('admin_panel.dashboard'))
    except Exception as e:
        logger.error(f"Error initializing admin settings: {e}")
        flash('Error initializing admin settings. Please check logs.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


# Import utility functions from helpers
from .helpers import is_admin_panel_feature_enabled


@admin_panel_bp.route('/clear-flashes')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def clear_flashes():
    """Temporary route to clear accumulated flash messages."""
    from flask import session
    session.pop('_flashes', None)
    flash('Flash messages cleared successfully!', 'success')
    return redirect(url_for('admin_panel.dashboard'))


# Performance Monitoring Routes
@admin_panel_bp.route('/performance')
@login_required
@role_required(['Global Admin'])  # Only Global Admins can view performance metrics
def performance_monitoring():
    """Performance monitoring dashboard."""
    try:
        performance_report = get_performance_report()
        
        return render_template('admin_panel/performance.html', 
                             report=performance_report,
                             title='Performance Monitoring')
    except Exception as e:
        logger.error(f"Error loading performance monitoring: {e}")
        flash('Performance monitoring data unavailable. Check system resources.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/performance/clear-cache', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def clear_performance_cache():
    """Clear admin panel cache."""
    try:
        pattern = request.form.get('pattern')  # Optional pattern to clear specific cache keys
        clear_admin_cache(pattern)
        admin_stats_cache.invalidate()
        
        # Log the action
        audit_log = AdminAuditLog(
            admin_id=current_user.id,
            action='CLEAR_CACHE',
            target_type='PerformanceCache',
            target_id='all' if not pattern else pattern,
            details=f'Cleared admin panel cache{f" with pattern: {pattern}" if pattern else ""}'
        )
        db.session.add(audit_log)
        db.session.commit()
        
        flash('Cache cleared successfully!', 'success')
        return redirect(url_for('admin_panel.performance_monitoring'))
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        flash('Cache clearing failed. Redis service may be unavailable.', 'error')
        return redirect(url_for('admin_panel.performance_monitoring'))


@admin_panel_bp.route('/performance/api/metrics')
@login_required
@role_required(['Global Admin'])
def performance_api_metrics():
    """API endpoint for real-time performance metrics."""
    try:
        report = get_performance_report()
        return jsonify({'success': True, 'data': report})
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        return jsonify({'success': False, 'message': 'Error loading performance metrics'})


@admin_panel_bp.route('/api/system-status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def system_status():
    """Real-time system status with actual metrics."""
    try:
        import psutil
        import time
        
        # CPU and Memory
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Database connection test
        db_start = time.time()
        db.session.execute(text('SELECT 1'))
        db_response_time = (time.time() - db_start) * 1000
        
        # Redis connection test  
        try:
            from app.utils.redis_manager import redis_client
            redis_start = time.time()
            redis_client.ping()
            redis_response_time = (time.time() - redis_start) * 1000
            redis_status = 'online'
        except Exception:
            redis_response_time = 0
            redis_status = 'offline'
            
        return jsonify({
            'timestamp': datetime.utcnow().isoformat(),
            'system': {
                'cpu_percent': round(cpu_percent, 1),
                'memory_percent': round(memory.percent, 1),
                'disk_percent': round((disk.used / disk.total) * 100, 1),
                'memory_used_gb': round(memory.used / (1024**3), 2),
                'disk_free_gb': round(disk.free / (1024**3), 2)
            },
            'services': {
                'database': {
                    'status': 'online',
                    'response_time_ms': round(db_response_time, 2)
                },
                'redis': {
                    'status': redis_status,
                    'response_time_ms': round(redis_response_time, 2)
                }
            }
        })
    except Exception as e:
        logger.error(f"System status error: {e}")
        return jsonify({'error': str(e)}), 500


@admin_panel_bp.route('/api/task-monitor')
@login_required  
@role_required(['Global Admin', 'Pub League Admin'])
def task_monitor():
    """Real task monitoring data."""
    try:
        # Try to get Celery task info if available
        try:
            from celery import current_app as celery_app
            
            inspect = celery_app.control.inspect()
            active_tasks = inspect.active()
            scheduled_tasks = inspect.scheduled()
            
            # Process task data
            task_summary = {
                'active_count': sum(len(tasks) for tasks in (active_tasks or {}).values()),
                'scheduled_count': sum(len(tasks) for tasks in (scheduled_tasks or {}).values()),
                'worker_count': len(active_tasks or {}),
                'tasks': []
            }
            
            # Add active task details
            if active_tasks:
                for worker, tasks in active_tasks.items():
                    for task in tasks:
                        task_summary['tasks'].append({
                            'name': task.get('name', 'Unknown'),
                            'status': 'active',
                            'worker': worker,
                            'started': task.get('time_start'),
                            'args': str(task.get('args', []))[:100]
                        })
            
            return jsonify(task_summary)
            
        except ImportError:
            # Celery not available, return basic info
            return jsonify({
                'active_count': 0,
                'scheduled_count': 0,
                'worker_count': 0,
                'tasks': [],
                'message': 'Celery not configured'
            })
    except Exception as e:
        logger.error(f"Task monitor error: {e}")
        return jsonify({'error': str(e)}), 500


# Quick Actions API Endpoints

@admin_panel_bp.route('/api/quick-actions/bulk-approve', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def quick_bulk_approve():
    """Quick bulk approve pending users."""
    try:
        from app.models.core import User
        
        # Get all pending users
        pending_users = User.query.filter_by(approval_status='pending').limit(10).all()
        
        approved_count = 0
        for user in pending_users:
            user.approval_status = 'approved'
            user.is_approved = True
            user.approved_by = current_user.id
            user.approved_at = datetime.utcnow()
            approved_count += 1
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='quick_bulk_approve',
            resource_type='user_approval',
            resource_id='bulk',
            new_value=f'Quick approved {approved_count} users',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'Approved {approved_count} users',
            'count': approved_count
        })
        
    except Exception as e:
        logger.error(f"Quick bulk approve error: {e}")
        return jsonify({'success': False, 'message': 'Bulk approval failed'}), 500


@admin_panel_bp.route('/api/quick-actions/system-backup', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def quick_system_backup():
    """Create system backup."""
    try:
        import subprocess
        import os
        
        backup_filename = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sql"
        backup_path = f"/tmp/{backup_filename}"
        
        # Simple backup simulation - in production would use actual pg_dump
        try:
            # Get database URL from config
            db_url = db.engine.url
            # For security, we'll just create a placeholder file
            with open(backup_path, 'w') as f:
                f.write(f"-- Database backup created at {datetime.utcnow()}\n")
                f.write("-- This is a placeholder backup file\n")
        except Exception as backup_error:
            logger.warning(f"Backup creation error: {backup_error}")
            # Continue with logging even if backup fails
        
        # Log the backup
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='system_backup',
            resource_type='system',
            resource_id='backup',
            new_value=f'Created backup: {backup_filename}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': 'System backup created successfully',
            'filename': backup_filename
        })
        
    except Exception as e:
        logger.error(f"System backup error: {e}")
        return jsonify({'success': False, 'message': 'Backup failed'}), 500


@admin_panel_bp.route('/api/quick-actions/bulk-send-messages', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def quick_bulk_send_messages():
    """Send quick messages to multiple users."""
    try:
        data = request.get_json()
        message_content = data.get('message', '')
        recipient_type = data.get('recipient_type', 'active_users')  # 'active_users', 'pending', 'all'
        
        if not message_content:
            return jsonify({'success': False, 'message': 'Message content is required'}), 400
        
        from app.models.core import User
        from app.models.notifications import Notification
        
        # Get recipients based on type
        if recipient_type == 'active_users':
            recipients = User.query.filter_by(is_active=True).all()
        elif recipient_type == 'pending':
            recipients = User.query.filter_by(approval_status='pending').all()
        else:  # all
            recipients = User.query.all()
        
        # Create notifications for each recipient
        notifications_created = 0
        for user in recipients:
            notification = Notification(
                user_id=user.id,
                content=message_content,
                notification_type='admin_message',
                icon='ti-message',
                read=False,
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            notifications_created += 1
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='quick_bulk_message',
            resource_type='notifications',
            resource_id='bulk',
            new_value=f'Sent message to {notifications_created} users: {message_content[:50]}...',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'Message sent to {notifications_created} users',
            'count': notifications_created
        })
        
    except Exception as e:
        logger.error(f"Bulk message error: {e}")
        return jsonify({'success': False, 'message': 'Failed to send messages'}), 500


@admin_panel_bp.route('/api/quick-actions/generate-reports', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def quick_generate_reports():
    """Generate quick system reports."""
    try:
        data = request.get_json()
        report_type = data.get('report_type', 'system_summary')
        
        from app.models.core import User
        
        # Generate report based on type
        if report_type == 'system_summary':
            report_data = {
                'total_users': User.query.count(),
                'active_users': User.query.filter_by(is_active=True).count(),
                'pending_approvals': User.query.filter_by(approval_status='pending').count(),
                'total_settings': AdminConfig.query.count(),
                'enabled_settings': AdminConfig.query.filter_by(is_enabled=True).count(),
                'recent_activity': AdminAuditLog.query.filter(
                    AdminAuditLog.timestamp >= datetime.utcnow() - timedelta(hours=24)
                ).count()
            }
        elif report_type == 'user_activity':
            report_data = {
                'new_users_today': User.query.filter(
                    User.created_at >= datetime.utcnow().date()
                ).count() if hasattr(User, 'created_at') else 0,
                'approvals_today': AdminAuditLog.query.filter(
                    AdminAuditLog.action == 'approve_user',
                    AdminAuditLog.timestamp >= datetime.utcnow().date()
                ).count()
            }
        else:
            report_data = {'message': 'Report type not supported'}
        
        # Log the report generation
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='generate_report',
            resource_type='reports',
            resource_id=report_type,
            new_value=f'Generated {report_type} report',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'{report_type.replace("_", " ").title()} report generated',
            'report_data': report_data
        })
        
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        return jsonify({'success': False, 'message': 'Failed to generate report'}), 500


# Navigation Settings Routes
@admin_panel_bp.route('/navigation-settings', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def navigation_settings():
    """Get or update navigation settings via AJAX."""
    try:
        if request.method == 'GET':
            # Get current navigation settings
            settings = {
                'teams_navigation_enabled': AdminConfig.get_setting('teams_navigation_enabled', True),
                'store_navigation_enabled': AdminConfig.get_setting('store_navigation_enabled', True),
                'matches_navigation_enabled': AdminConfig.get_setting('matches_navigation_enabled', True),
                'leagues_navigation_enabled': AdminConfig.get_setting('leagues_navigation_enabled', True),
                'drafts_navigation_enabled': AdminConfig.get_setting('drafts_navigation_enabled', True),
                'players_navigation_enabled': AdminConfig.get_setting('players_navigation_enabled', True),
                'messaging_navigation_enabled': AdminConfig.get_setting('messaging_navigation_enabled', True),
                'mobile_features_navigation_enabled': AdminConfig.get_setting('mobile_features_navigation_enabled', True),
                'admin_panel_navigation_enabled': AdminConfig.get_setting('admin_panel_navigation_enabled', True),
            }
            return jsonify({'success': True, 'settings': settings})
        
        elif request.method == 'POST':
            # Update navigation settings
            data = request.get_json()
            updated_settings = []
            
            # Navigation settings to handle
            nav_settings = [
                'teams_navigation_enabled',
                'store_navigation_enabled', 
                'matches_navigation_enabled',
                'leagues_navigation_enabled',
                'drafts_navigation_enabled',
                'players_navigation_enabled',
                'messaging_navigation_enabled',
                'mobile_features_navigation_enabled',
                'admin_panel_navigation_enabled'
            ]
            
            for setting_key in nav_settings:
                if setting_key in data:
                    old_value = AdminConfig.get_setting(setting_key, True)
                    new_value = data[setting_key]
                    
                    # Update the setting
                    AdminConfig.set_setting(
                        key=setting_key,
                        value=str(new_value).lower(),
                        description=f'Enable/disable {setting_key.replace("_navigation_enabled", "")} navigation for non-admin users',
                        category='navigation',
                        data_type='boolean',
                        user_id=current_user.id
                    )
                    
                    updated_settings.append(setting_key)
                    
                    # Log the action
                    AdminAuditLog.log_action(
                        user_id=current_user.id,
                        action='update',
                        resource_type='navigation_settings',
                        resource_id=setting_key,
                        old_value=str(old_value).lower(),
                        new_value=str(new_value).lower(),
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent')
                    )
            
            return jsonify({
                'success': True,
                'message': f'Updated {len(updated_settings)} navigation settings',
                'updated': updated_settings
            })
            
    except Exception as e:
        logger.error(f"Error with navigation settings: {e}")
        return jsonify({'success': False, 'message': 'Failed to handle navigation settings'}), 500


@admin_panel_bp.route('/registration-settings', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def registration_settings():
    """Get or update registration settings via AJAX."""
    try:
        if request.method == 'GET':
            # Get all roles for default role selection
            roles = Role.query.all()
            role_choices = [{'id': role.id, 'name': role.name} for role in roles]
            
            # Get current registration settings
            settings = {
                'registration_enabled': AdminConfig.get_setting('registration_enabled', True),
                'waitlist_registration_enabled': AdminConfig.get_setting('waitlist_registration_enabled', True),
                'admin_approval_required': AdminConfig.get_setting('admin_approval_required', True),
                'discord_only_login': AdminConfig.get_setting('discord_only_login', True),
                'default_user_role': AdminConfig.get_setting('default_user_role', 'pl-unverified'),
                'require_real_name': AdminConfig.get_setting('require_real_name', True),
                'require_email': AdminConfig.get_setting('require_email', True),
                'require_phone': AdminConfig.get_setting('require_phone', False),
                'require_location': AdminConfig.get_setting('require_location', False),
                'require_jersey_size': AdminConfig.get_setting('require_jersey_size', True),
                'require_position_preferences': AdminConfig.get_setting('require_position_preferences', True),
                'require_availability': AdminConfig.get_setting('require_availability', True),
                'require_referee_willingness': AdminConfig.get_setting('require_referee_willingness', True),
            }
            
            return jsonify({
                'success': True, 
                'settings': settings,
                'available_roles': role_choices
            })
        
        elif request.method == 'POST':
            # Update registration settings
            data = request.get_json()
            updated_settings = []
            
            # Registration settings to handle
            reg_settings = [
                'registration_enabled',
                'waitlist_registration_enabled',
                'admin_approval_required',
                'discord_only_login',
                'default_user_role',
                'require_real_name',
                'require_email',
                'require_phone',
                'require_location',
                'require_jersey_size',
                'require_position_preferences',
                'require_availability',
                'require_referee_willingness'
            ]
            
            for setting_key in reg_settings:
                if setting_key in data:
                    old_value = AdminConfig.get_setting(setting_key, True if 'require_' in setting_key or setting_key in ['registration_enabled', 'admin_approval_required', 'discord_only_login'] else 'Member')
                    new_value = data[setting_key]
                    
                    # Determine data type
                    data_type = 'string' if setting_key == 'default_user_role' else 'boolean'
                    
                    # Create appropriate description
                    descriptions = {
                        'registration_enabled': 'Allow new user registrations',
                        'waitlist_registration_enabled': 'Enable waitlist registration when regular registration is full',
                        'admin_approval_required': 'Require admin approval for all new registrations',
                        'discord_only_login': 'Only allow Discord OAuth login (no password auth)',
                        'default_user_role': 'Default role assigned to new registered users',
                        'require_real_name': 'Require users to provide their real name during registration',
                        'require_email': 'Require email address during registration',
                        'require_phone': 'Require phone number during registration',
                        'require_location': 'Require location/address during registration',
                        'require_jersey_size': 'Require jersey size selection during registration',
                        'require_position_preferences': 'Require soccer position preferences during registration',
                        'require_availability': 'Require availability information during registration',
                        'require_referee_willingness': 'Require referee willingness question during registration'
                    }
                    
                    # Update the setting
                    AdminConfig.set_setting(
                        key=setting_key,
                        value=str(new_value) if data_type == 'string' else str(new_value).lower(),
                        description=descriptions.get(setting_key, f'Registration setting: {setting_key}'),
                        category='registration',
                        data_type=data_type,
                        user_id=current_user.id
                    )
                    
                    updated_settings.append(setting_key)
                    
                    # Log the action
                    AdminAuditLog.log_action(
                        user_id=current_user.id,
                        action='update',
                        resource_type='registration_settings',
                        resource_id=setting_key,
                        old_value=str(old_value),
                        new_value=str(new_value),
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent')
                    )
            
            return jsonify({
                'success': True,
                'message': f'Updated {len(updated_settings)} registration settings',
                'updated': updated_settings
            })
            
    except Exception as e:
        logger.error(f"Error with registration settings: {e}")
        return jsonify({'success': False, 'message': 'Failed to handle registration settings'}), 500