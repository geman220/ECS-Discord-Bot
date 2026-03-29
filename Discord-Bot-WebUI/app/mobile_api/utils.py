# app/api/utils.py

"""
Utility API Endpoints

Health checks, connectivity testing, debugging endpoints, and mobile logging.
"""

import logging
from datetime import datetime

from flask import jsonify, current_app, request
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import NoAuthorizationError

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required

logger = logging.getLogger(__name__)
mobile_logger = logging.getLogger('mobile_app')


@mobile_api_v2.route('/ping', methods=['GET'])
def ping():
    """
    Simple ping endpoint for connectivity testing.

    Returns:
        JSON response with status and timestamp
    """
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'server': 'ECS Soccer API',
        'version': current_app.config.get('VERSION', '1.0')
    }), 200


@mobile_api_v2.route('/test-connection', methods=['GET'])
@jwt_role_required('Global Admin')
def test_connection():
    """
    Test endpoint for mobile app connection to the API.
    Requires Global Admin role.

    Returns:
        JSON response with API status information
    """
    return jsonify({
        "status": "success",
        "message": "Connection to ECS Soccer API successful",
        "api_version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "server": "Flask API"
    }), 200


@mobile_api_v2.route('/debug/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for monitoring.

    Returns:
        JSON response with health status
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'mobile-api'
    }), 200


# =============================================================================
# Mobile App Logging Endpoints
# =============================================================================

@mobile_api_v2.route('/logs/mobile', methods=['POST'])
def receive_mobile_logs():
    """
    Receive logs from the mobile app for debugging and monitoring.

    This endpoint accepts logs without requiring authentication to ensure
    crash logs and startup errors can be captured. User context is included
    if a valid JWT is provided.

    Expected JSON:
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        context: Additional context data (optional)
        timestamp: Client timestamp ISO format (optional)
        device_info: Device information (optional)
            - platform: ios/android
            - os_version: OS version string
            - app_version: App version string
            - device_model: Device model
        stack_trace: Stack trace for errors (optional)
        tags: List of tags for categorization (optional)

    Returns:
        JSON with acknowledgment
    """
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    # Extract log data
    level = data.get('level', 'info').lower()
    message = data.get('message', '')
    context = data.get('context', {})
    client_timestamp = data.get('timestamp')
    device_info = data.get('device_info', {})
    stack_trace = data.get('stack_trace')
    tags = data.get('tags', [])

    if not message:
        return jsonify({"msg": "message is required"}), 400

    # Try to get user context if JWT is provided
    user_id = None
    username = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            user_id = int(identity)
            # Optionally get username from database
            from app.core.session_manager import managed_session
            from app.models import User
            with managed_session() as session:
                user = session.query(User).get(user_id)
                if user:
                    username = user.username
    except (NoAuthorizationError, Exception):
        pass  # No valid JWT, continue without user context

    # Build log record
    log_data = {
        'source': 'mobile_app',
        'level': level,
        'message': message,
        'user_id': user_id,
        'username': username,
        'client_timestamp': client_timestamp,
        'server_timestamp': datetime.utcnow().isoformat(),
        'device': device_info,
        'context': context,
        'tags': tags,
        'client_ip': request.remote_addr,
        'user_agent': request.headers.get('User-Agent', '')
    }

    # Add stack trace if present
    if stack_trace:
        log_data['stack_trace'] = stack_trace

    # Log based on level
    log_message = f"[MOBILE] {message}"
    if user_id:
        log_message = f"[MOBILE] [user:{user_id}] {message}"

    # Add device info to message if present
    if device_info:
        platform = device_info.get('platform', 'unknown')
        app_version = device_info.get('app_version', 'unknown')
        log_message = f"[MOBILE] [{platform}:{app_version}] " + (f"[user:{user_id}] " if user_id else "") + message

    # Log at appropriate level
    if level == 'debug':
        mobile_logger.debug(log_message, extra={'data': log_data})
    elif level == 'info':
        mobile_logger.info(log_message, extra={'data': log_data})
    elif level == 'warning':
        mobile_logger.warning(log_message, extra={'data': log_data})
    elif level == 'error':
        mobile_logger.error(log_message, extra={'data': log_data})
        if stack_trace:
            mobile_logger.error(f"Stack trace:\n{stack_trace}")
    elif level == 'critical':
        mobile_logger.critical(log_message, extra={'data': log_data})
        if stack_trace:
            mobile_logger.critical(f"Stack trace:\n{stack_trace}")
    else:
        mobile_logger.info(log_message, extra={'data': log_data})

    return jsonify({
        "success": True,
        "message": "Log received",
        "server_timestamp": datetime.utcnow().isoformat()
    }), 200


@mobile_api_v2.route('/logs/mobile/batch', methods=['POST'])
def receive_mobile_logs_batch():
    """
    Receive a batch of logs from the mobile app.

    Useful for offline sync when the app comes back online.

    Expected JSON:
        logs: List of log entries (same format as /logs/mobile)

    Returns:
        JSON with count of processed logs
    """
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    logs = data.get('logs', [])

    if not logs:
        return jsonify({"msg": "No logs provided"}), 400

    if not isinstance(logs, list):
        return jsonify({"msg": "logs must be a list"}), 400

    # Limit batch size
    max_batch_size = 100
    if len(logs) > max_batch_size:
        logs = logs[:max_batch_size]

    # Try to get user context
    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            user_id = int(identity)
    except (NoAuthorizationError, Exception):
        pass

    processed = 0
    errors = 0

    for log_entry in logs:
        try:
            level = log_entry.get('level', 'info').lower()
            message = log_entry.get('message', '')
            device_info = log_entry.get('device_info', {})
            stack_trace = log_entry.get('stack_trace')

            if not message:
                errors += 1
                continue

            log_message = f"[MOBILE:BATCH] {message}"
            if user_id:
                log_message = f"[MOBILE:BATCH] [user:{user_id}] {message}"

            if device_info:
                platform = device_info.get('platform', 'unknown')
                app_version = device_info.get('app_version', 'unknown')
                log_message = f"[MOBILE:BATCH] [{platform}:{app_version}] " + (f"[user:{user_id}] " if user_id else "") + message

            if level == 'error' or level == 'critical':
                mobile_logger.error(log_message)
                if stack_trace:
                    mobile_logger.error(f"Stack trace:\n{stack_trace}")
            elif level == 'warning':
                mobile_logger.warning(log_message)
            else:
                mobile_logger.info(log_message)

            processed += 1

        except Exception as e:
            errors += 1
            logger.warning(f"Error processing batch log entry: {e}")

    return jsonify({
        "success": True,
        "processed": processed,
        "errors": errors,
        "server_timestamp": datetime.utcnow().isoformat()
    }), 200
