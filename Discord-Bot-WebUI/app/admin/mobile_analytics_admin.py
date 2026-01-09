# app/admin/mobile_analytics_admin.py

"""
Mobile Analytics Admin Interface

Provides admin endpoints for managing mobile analytics data including
cleanup operations, statistics, and monitoring.
"""

from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from sqlalchemy import func, desc
import logging

from app import db
from app.decorators import role_required
from app.models_mobile_analytics import MobileErrorAnalytics, MobileErrorPatterns, MobileLogs
from app.tasks.mobile_analytics_cleanup import (
    cleanup_mobile_analytics, 
    get_cleanup_preview, 
    get_analytics_storage_stats
)

logger = logging.getLogger(__name__)

mobile_analytics_admin_bp = Blueprint('mobile_analytics_admin', __name__, url_prefix='/admin/mobile-analytics')


@mobile_analytics_admin_bp.route('/')
@login_required
@role_required(['Global Admin'])
def dashboard():
    """Mobile analytics admin dashboard."""
    try:
        # Get basic statistics
        total_errors = db.session.query(MobileErrorAnalytics).count()
        total_logs = db.session.query(MobileLogs).count()
        total_patterns = db.session.query(MobileErrorPatterns).count()
        
        # Recent activity (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_errors = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at >= week_ago
        ).count()
        
        recent_logs = db.session.query(MobileLogs).filter(
            MobileLogs.created_at >= week_ago
        ).count()
        
        # Top error types this week
        top_errors = db.session.query(
            MobileErrorAnalytics.error_type,
            MobileErrorAnalytics.severity,
            func.count(MobileErrorAnalytics.id).label('count')
        ).filter(
            MobileErrorAnalytics.created_at >= week_ago
        ).group_by(
            MobileErrorAnalytics.error_type,
            MobileErrorAnalytics.severity
        ).order_by(desc('count')).limit(10).all()
        
        # Active patterns
        active_patterns = db.session.query(MobileErrorPatterns).filter(
            MobileErrorPatterns.last_seen >= week_ago
        ).order_by(desc(MobileErrorPatterns.occurrences)).limit(5).all()
        
        # Critical errors (last 24 hours)
        day_ago = datetime.utcnow() - timedelta(days=1)
        critical_errors = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at >= day_ago,
            MobileErrorAnalytics.severity == 'critical'
        ).count()
        
        stats = {
            'total_errors': total_errors,
            'total_logs': total_logs,
            'total_patterns': total_patterns,
            'recent_errors': recent_errors,
            'recent_logs': recent_logs,
            'critical_errors_24h': critical_errors,
            'top_errors': [
                {
                    'error_type': error.error_type,
                    'severity': error.severity,
                    'count': error.count
                } for error in top_errors
            ],
            'active_patterns': [pattern.to_dict() for pattern in active_patterns]
        }
        
        return render_template('admin/mobile_analytics_dashboard_flowbite.html', stats=stats)

    except Exception as e:
        logger.error(f"Error loading mobile analytics dashboard: {str(e)}", exc_info=True)
        flash('Error loading dashboard data', 'error')
        return render_template('admin/mobile_analytics_dashboard_flowbite.html', stats={})


@mobile_analytics_admin_bp.route('/errors')
@login_required
@role_required(['Global Admin'])
def view_errors():
    """View mobile error analytics with filtering and pagination."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        severity_filter = request.args.get('severity')
        error_type_filter = request.args.get('error_type')
        days_filter = request.args.get('days', 7, type=int)
        
        # Build query
        query = db.session.query(MobileErrorAnalytics)
        
        # Date filter
        if days_filter:
            cutoff_date = datetime.utcnow() - timedelta(days=days_filter)
            query = query.filter(MobileErrorAnalytics.created_at >= cutoff_date)
        
        # Severity filter
        if severity_filter:
            query = query.filter(MobileErrorAnalytics.severity == severity_filter)
        
        # Error type filter
        if error_type_filter:
            query = query.filter(MobileErrorAnalytics.error_type == error_type_filter)
        
        # Order by most recent
        query = query.order_by(desc(MobileErrorAnalytics.created_at))
        
        # Paginate
        errors = query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        # Get filter options
        severity_options = db.session.query(
            MobileErrorAnalytics.severity.distinct()
        ).all()
        severity_options = [s[0] for s in severity_options]
        
        error_type_options = db.session.query(
            MobileErrorAnalytics.error_type.distinct()
        ).all()
        error_type_options = [e[0] for e in error_type_options]
        
        return render_template(
            'admin/mobile_errors.html',
            errors=errors,
            severity_options=severity_options,
            error_type_options=error_type_options,
            current_filters={
                'severity': severity_filter,
                'error_type': error_type_filter,
                'days': days_filter
            }
        )
        
    except Exception as e:
        logger.error(f"Error loading mobile errors: {str(e)}", exc_info=True)
        flash('Error loading error data', 'error')
        return redirect(url_for('mobile_analytics_admin.dashboard'))


@mobile_analytics_admin_bp.route('/patterns')
@login_required
@role_required(['Global Admin'])
def view_patterns():
    """View error patterns with analysis."""
    try:
        # Get active patterns (last 30 days)
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        patterns = db.session.query(MobileErrorPatterns).filter(
            MobileErrorPatterns.last_seen >= cutoff_date
        ).order_by(
            desc(MobileErrorPatterns.occurrences),
            desc(MobileErrorPatterns.last_seen)
        ).all()
        
        return render_template('admin/mobile_patterns_flowbite.html', patterns=patterns)
        
    except Exception as e:
        logger.error(f"Error loading mobile patterns: {str(e)}", exc_info=True)
        flash('Error loading pattern data', 'error')
        return redirect(url_for('mobile_analytics_admin.dashboard'))


@mobile_analytics_admin_bp.route('/cleanup')
@login_required
@role_required(['Global Admin'])
def cleanup_page():
    """Data cleanup management page."""
    try:
        # Get cleanup preview
        preview = get_cleanup_preview()
        
        # Get storage stats
        storage_stats = get_analytics_storage_stats()
        
        return render_template(
            'admin/mobile_cleanup.html',
            preview=preview,
            storage_stats=storage_stats
        )
        
    except Exception as e:
        logger.error(f"Error loading cleanup page: {str(e)}", exc_info=True)
        flash('Error loading cleanup data', 'error')
        return redirect(url_for('mobile_analytics_admin.dashboard'))


@mobile_analytics_admin_bp.route('/api/cleanup/preview')
@login_required
@role_required(['Global Admin'])
def api_cleanup_preview():
    """API endpoint for cleanup preview."""
    try:
        preview = get_cleanup_preview()
        return jsonify(preview)
    except Exception as e:
        logger.error(f"Error getting cleanup preview: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@mobile_analytics_admin_bp.route('/api/cleanup/execute', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def api_cleanup_execute():
    """API endpoint to execute cleanup."""
    try:
        # Verify confirmation
        data = request.get_json()
        if not data or not data.get('confirmed'):
            return jsonify({'error': 'Cleanup must be confirmed'}), 400
        
        # Execute cleanup
        result = cleanup_mobile_analytics()
        
        if result['status'] == 'success':
            logger.info(f"Mobile analytics cleanup executed by admin: {result}")
            return jsonify(result)
        else:
            logger.error(f"Mobile analytics cleanup failed: {result}")
            return jsonify(result), 500
            
    except Exception as e:
        logger.error(f"Error executing cleanup: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@mobile_analytics_admin_bp.route('/api/stats')
@login_required
@role_required(['Global Admin'])
def api_storage_stats():
    """API endpoint for storage statistics."""
    try:
        stats = get_analytics_storage_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting storage stats: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@mobile_analytics_admin_bp.route('/api/error/<int:error_id>')
@login_required
@role_required(['Global Admin'])
def api_error_details(error_id):
    """API endpoint for error details."""
    try:
        error = db.session.query(MobileErrorAnalytics).get(error_id)
        if not error:
            return jsonify({'error': 'Error not found'}), 404
        
        return jsonify(error.to_dict())
        
    except Exception as e:
        logger.error(f"Error getting error details: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@mobile_analytics_admin_bp.route('/api/pattern/<int:pattern_id>')
@login_required
@role_required(['Global Admin'])
def api_pattern_details(pattern_id):
    """API endpoint for pattern details."""
    try:
        pattern = db.session.query(MobileErrorPatterns).get(pattern_id)
        if not pattern:
            return jsonify({'error': 'Pattern not found'}), 404
        
        return jsonify(pattern.to_dict())
        
    except Exception as e:
        logger.error(f"Error getting pattern details: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@mobile_analytics_admin_bp.route('/api/summary')
@login_required
@role_required(['Global Admin'])
def api_analytics_summary():
    """API endpoint for analytics summary."""
    try:
        days = request.args.get('days', 7, type=int)
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Error counts by severity
        severity_stats = db.session.query(
            MobileErrorAnalytics.severity,
            func.count(MobileErrorAnalytics.id).label('count')
        ).filter(
            MobileErrorAnalytics.created_at >= cutoff_date
        ).group_by(MobileErrorAnalytics.severity).all()
        
        # Daily error counts
        daily_stats = db.session.query(
            func.date(MobileErrorAnalytics.created_at).label('date'),
            func.count(MobileErrorAnalytics.id).label('count')
        ).filter(
            MobileErrorAnalytics.created_at >= cutoff_date
        ).group_by(func.date(MobileErrorAnalytics.created_at)).order_by('date').all()
        
        # Recovery rate
        total_with_recovery = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at >= cutoff_date,
            MobileErrorAnalytics.was_recovered.isnot(None)
        ).count()
        
        recovered = db.session.query(MobileErrorAnalytics).filter(
            MobileErrorAnalytics.created_at >= cutoff_date,
            MobileErrorAnalytics.was_recovered == True
        ).count()
        
        recovery_rate = (recovered / total_with_recovery) if total_with_recovery > 0 else 0
        
        return jsonify({
            'period_days': days,
            'severity_breakdown': {item.severity: item.count for item in severity_stats},
            'daily_counts': [
                {
                    'date': item.date.isoformat(),
                    'count': item.count
                } for item in daily_stats
            ],
            'recovery_rate': round(recovery_rate, 2),
            'total_errors': sum(item.count for item in severity_stats)
        })
        
    except Exception as e:
        logger.error(f"Error getting analytics summary: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500