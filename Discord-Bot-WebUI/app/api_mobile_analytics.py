# app/api/mobile_analytics.py

"""
Mobile Analytics API Endpoints

Provides endpoints for receiving error analytics, crash reports, and structured logs
from the Flutter mobile application. Includes comprehensive error tracking,
pattern analysis, and operational monitoring.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_, func
import logging
import uuid

from app import db
from app.models_mobile_analytics import MobileErrorAnalytics, MobileErrorPatterns, MobileLogs
from app.models import User
from app.utils.mobile_auth import mobile_api_auth_required, log_mobile_api_request, get_request_context

logger = logging.getLogger(__name__)

mobile_analytics_bp = Blueprint('mobile_analytics', __name__, url_prefix='/api/v1')


@mobile_analytics_bp.route('/analytics/errors', methods=['POST'])
@mobile_api_auth_required(require_permissions=['analytics'])
def receive_error_analytics():
    """
    Receive error analytics and crash reports from mobile app.
    
    Expected payload:
    {
        "errors": [list of error objects],
        "patterns": [list of pattern objects],
        "metadata": {app info}
    }
    
    Returns:
        JSON response with processing status
    """
    log_mobile_api_request()
    
    try:
        data = request.get_json()
        if not data:
            logger.warning("Empty JSON payload for error analytics")
            return jsonify({
                'error': 'Empty or invalid JSON payload',
                'code': 'INVALID_PAYLOAD'
            }), 400
        
        errors_data = data.get('errors', [])
        patterns_data = data.get('patterns', [])
        metadata = data.get('metadata', {})
        
        errors_processed = 0
        patterns_processed = 0
        request_context = get_request_context()
        
        # Process individual errors
        for error_data in errors_data:
            try:
                # Validate required fields
                if not error_data.get('error_id') or not error_data.get('error_type'):
                    logger.warning(f"Missing required fields in error data: {error_data}")
                    continue
                
                # Parse timestamp
                timestamp_str = error_data.get('timestamp')
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        timestamp = datetime.utcnow()
                else:
                    timestamp = datetime.utcnow()
                
                # Get user ID from JWT or error data
                user_id = g.current_user_id
                if error_data.get('user_id') and str(error_data['user_id']) != str(user_id):
                    logger.warning(f"User ID mismatch in error data: JWT={user_id}, Error={error_data.get('user_id')}")
                
                # Create error record
                error_record = MobileErrorAnalytics(
                    error_id=error_data['error_id'],
                    error_type=error_data['error_type'],
                    error_code=error_data.get('error_code'),
                    error_message=error_data.get('error_message'),
                    technical_message=error_data.get('technical_message'),
                    severity=error_data.get('severity', 'medium').replace('ErrorSeverity.', ''),
                    should_report=error_data.get('should_report', True),
                    operation=error_data.get('operation'),
                    context=error_data.get('context'),
                    timestamp=timestamp,
                    trace_id=error_data.get('trace_id'),
                    user_id=user_id,
                    device_info=error_data.get('device_info'),
                    app_version=error_data.get('app_version') or metadata.get('app_version'),
                    was_recovered=error_data.get('was_recovered', False),
                    recovery_result=error_data.get('recovery_result'),
                    recovery_actions=error_data.get('recovery_actions')
                )
                
                db.session.add(error_record)
                errors_processed += 1
                
            except Exception as e:
                logger.error(f"Failed to process error data: {str(e)}", exc_info=True)
                continue
        
        # Process error patterns
        for pattern_data in patterns_data:
            try:
                # Validate required fields
                if not pattern_data.get('pattern_id') or not pattern_data.get('error_type'):
                    logger.warning(f"Missing required fields in pattern data: {pattern_data}")
                    continue
                
                # Parse timestamps
                first_seen_str = pattern_data.get('first_seen')
                last_seen_str = pattern_data.get('last_seen')
                
                try:
                    first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00')) if first_seen_str else datetime.utcnow()
                    last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00')) if last_seen_str else datetime.utcnow()
                except ValueError:
                    first_seen = last_seen = datetime.utcnow()
                
                # Check if pattern already exists
                existing_pattern = MobileErrorPatterns.query.filter_by(
                    pattern_id=pattern_data['pattern_id']
                ).first()
                
                if existing_pattern:
                    # Update existing pattern
                    existing_pattern.occurrences = pattern_data.get('occurrences', existing_pattern.occurrences)
                    existing_pattern.last_seen = last_seen
                    existing_pattern.recovery_rate = pattern_data.get('recovery_rate', existing_pattern.recovery_rate)
                    existing_pattern.common_context_keys = pattern_data.get('common_context_keys', existing_pattern.common_context_keys)
                    existing_pattern.error_metadata = pattern_data.get('metadata', existing_pattern.error_metadata)
                else:
                    # Create new pattern
                    pattern_record = MobileErrorPatterns(
                        pattern_id=pattern_data['pattern_id'],
                        error_type=pattern_data['error_type'],
                        operation=pattern_data.get('operation'),
                        occurrences=pattern_data.get('occurrences', 1),
                        first_seen=first_seen,
                        last_seen=last_seen,
                        recovery_rate=pattern_data.get('recovery_rate', 0.0),
                        common_context_keys=pattern_data.get('common_context_keys'),
                        error_metadata=pattern_data.get('metadata')
                    )
                    db.session.add(pattern_record)
                
                patterns_processed += 1
                
            except Exception as e:
                logger.error(f"Failed to process pattern data: {str(e)}", exc_info=True)
                continue
        
        # Commit all changes
        try:
            db.session.commit()
            logger.info(f"✅ Processed mobile analytics: {errors_processed} errors, {patterns_processed} patterns from user {user_id}")
            
            return jsonify({
                'status': 'success',
                'errors_received': errors_processed,
                'patterns_received': patterns_processed,
                'message': 'Error analytics received successfully'
            }), 200
            
        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Database integrity error processing analytics: {str(e)}")
            return jsonify({
                'error': 'Database constraint violation',
                'code': 'INTEGRITY_ERROR'
            }), 400
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing mobile analytics: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Failed to process error analytics',
            'code': 'PROCESSING_ERROR'
        }), 500


@mobile_analytics_bp.route('/logs/mobile', methods=['POST'])
@mobile_api_auth_required(require_permissions=['logging'])
def receive_mobile_logs():
    """
    Receive structured logs from mobile app.
    
    Expected payload:
    {
        "logs": [list of log objects],
        "app_info": {platform, version, environment}
    }
    
    Returns:
        JSON response with processing status
    """
    log_mobile_api_request()
    
    try:
        data = request.get_json()
        if not data:
            logger.warning("Empty JSON payload for mobile logs")
            return jsonify({
                'error': 'Empty or invalid JSON payload',
                'code': 'INVALID_PAYLOAD'
            }), 400
        
        logs_data = data.get('logs', [])
        app_info = data.get('app_info', {})
        
        logs_processed = 0
        user_id = g.current_user_id
        
        # Process logs
        for log_data in logs_data:
            try:
                # Validate required fields
                if not log_data.get('message') or not log_data.get('level'):
                    logger.warning(f"Missing required fields in log data: {log_data}")
                    continue
                
                # Parse timestamp
                timestamp_str = log_data.get('timestamp')
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        timestamp = datetime.utcnow()
                else:
                    timestamp = datetime.utcnow()
                
                # Validate log level
                log_level = log_data.get('level', 'INFO').upper()
                if log_level not in ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL']:
                    logger.warning(f"Invalid log level: {log_level}, defaulting to INFO")
                    log_level = 'INFO'
                
                # Create log record
                log_record = MobileLogs(
                    timestamp=timestamp,
                    level=log_level,
                    message=log_data['message'],
                    logger=log_data.get('logger'),
                    trace_id=log_data.get('trace_id'),
                    session_id=log_data.get('session_id'),
                    user_id=user_id,
                    context=log_data.get('context'),
                    error_info=log_data.get('error'),
                    stack_trace=log_data.get('stack_trace'),
                    error_metadata=log_data.get('metadata'),
                    platform=log_data.get('platform') or app_info.get('platform'),
                    app_version=log_data.get('app_version') or app_info.get('version'),
                    flutter_version=log_data.get('flutter_version')
                )
                
                db.session.add(log_record)
                logs_processed += 1
                
            except Exception as e:
                logger.error(f"Failed to process log data: {str(e)}", exc_info=True)
                continue
        
        # Commit all changes
        try:
            db.session.commit()
            logger.info(f"✅ Processed mobile logs: {logs_processed} logs from user {user_id}")
            
            return jsonify({
                'status': 'success',
                'logs_received': logs_processed,
                'message': 'Logs received successfully'
            }), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Database error processing logs: {str(e)}")
            return jsonify({
                'error': 'Failed to store logs',
                'code': 'STORAGE_ERROR'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing mobile logs: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Failed to process mobile logs',
            'code': 'PROCESSING_ERROR'
        }), 500


@mobile_analytics_bp.route('/analytics/summary', methods=['GET'])
@mobile_api_auth_required(require_permissions=['analytics'])
def get_analytics_summary():
    """
    Get error analytics summary for the current user.
    
    Query parameters:
        - days: Number of days to include (default: 7)
        - severity: Filter by severity level
        - error_type: Filter by error type
    
    Returns:
        JSON response with analytics summary
    """
    log_mobile_api_request()
    
    try:
        days = int(request.args.get('days', 7))
        severity_filter = request.args.get('severity')
        error_type_filter = request.args.get('error_type')
        user_id = g.current_user_id
        
        # Build query
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        query = MobileErrorAnalytics.query.filter(
            and_(
                MobileErrorAnalytics.user_id == user_id,
                MobileErrorAnalytics.created_at >= cutoff_date
            )
        )
        
        if severity_filter:
            query = query.filter(MobileErrorAnalytics.severity == severity_filter)
        
        if error_type_filter:
            query = query.filter(MobileErrorAnalytics.error_type == error_type_filter)
        
        # Get summary statistics
        total_errors = query.count()
        
        # Group by severity
        severity_stats = db.session.query(
            MobileErrorAnalytics.severity,
            func.count(MobileErrorAnalytics.id).label('count')
        ).filter(
            and_(
                MobileErrorAnalytics.user_id == user_id,
                MobileErrorAnalytics.created_at >= cutoff_date
            )
        ).group_by(MobileErrorAnalytics.severity).all()
        
        # Group by error type
        error_type_stats = db.session.query(
            MobileErrorAnalytics.error_type,
            func.count(MobileErrorAnalytics.id).label('count')
        ).filter(
            and_(
                MobileErrorAnalytics.user_id == user_id,
                MobileErrorAnalytics.created_at >= cutoff_date
            )
        ).group_by(MobileErrorAnalytics.error_type).order_by(
            func.count(MobileErrorAnalytics.id).desc()
        ).limit(10).all()
        
        # Recovery rate
        total_with_recovery = query.filter(
            MobileErrorAnalytics.was_recovered.isnot(None)
        ).count()
        
        recovered = query.filter(
            MobileErrorAnalytics.was_recovered == True
        ).count()
        
        recovery_rate = (recovered / total_with_recovery) if total_with_recovery > 0 else 0
        
        return jsonify({
            'status': 'success',
            'summary': {
                'total_errors': total_errors,
                'period_days': days,
                'severity_breakdown': {item.severity: item.count for item in severity_stats},
                'top_error_types': [{'type': item.error_type, 'count': item.count} for item in error_type_stats],
                'recovery_rate': round(recovery_rate, 2),
                'user_id': user_id
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting analytics summary: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Failed to get analytics summary',
            'code': 'SUMMARY_ERROR'
        }), 500


@mobile_analytics_bp.route('/analytics/patterns', methods=['GET'])
@mobile_api_auth_required(require_permissions=['analytics'])
def get_error_patterns():
    """
    Get error patterns and trends.
    
    Query parameters:
        - limit: Maximum number of patterns to return (default: 20)
        - error_type: Filter by error type
        - min_occurrences: Minimum occurrences to include (default: 2)
    
    Returns:
        JSON response with error patterns
    """
    log_mobile_api_request()
    
    try:
        limit = int(request.args.get('limit', 20))
        error_type_filter = request.args.get('error_type')
        min_occurrences = int(request.args.get('min_occurrences', 2))
        
        # Build query
        query = MobileErrorPatterns.query.filter(
            MobileErrorPatterns.occurrences >= min_occurrences
        )
        
        if error_type_filter:
            query = query.filter(MobileErrorPatterns.error_type == error_type_filter)
        
        # Order by recent activity and occurrence count
        patterns = query.order_by(
            MobileErrorPatterns.last_seen.desc(),
            MobileErrorPatterns.occurrences.desc()
        ).limit(limit).all()
        
        return jsonify({
            'status': 'success',
            'patterns': [pattern.to_dict() for pattern in patterns],
            'total_patterns': len(patterns)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting error patterns: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Failed to get error patterns',
            'code': 'PATTERNS_ERROR'
        }), 500


# Error handler for mobile analytics blueprint
@mobile_analytics_bp.errorhandler(400)
def handle_bad_request(error):
    return jsonify({
        'error': 'Bad request',
        'code': 'BAD_REQUEST',
        'message': str(error)
    }), 400


@mobile_analytics_bp.errorhandler(401)
def handle_unauthorized(error):
    return jsonify({
        'error': 'Unauthorized',
        'code': 'UNAUTHORIZED',
        'message': 'Invalid or missing authentication'
    }), 401


@mobile_analytics_bp.errorhandler(403)
def handle_forbidden(error):
    return jsonify({
        'error': 'Forbidden',
        'code': 'FORBIDDEN',
        'message': 'Insufficient permissions'
    }), 403


@mobile_analytics_bp.errorhandler(429)
def handle_rate_limit(error):
    return jsonify({
        'error': 'Rate limit exceeded',
        'code': 'RATE_LIMIT_EXCEEDED',
        'message': 'Too many requests. Please try again later.'
    }), 429


@mobile_analytics_bp.errorhandler(500)
def handle_internal_error(error):
    db.session.rollback()
    return jsonify({
        'error': 'Internal server error',
        'code': 'INTERNAL_ERROR',
        'message': 'An unexpected error occurred'
    }), 500