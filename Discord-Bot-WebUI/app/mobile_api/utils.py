# app/api/utils.py

"""
Utility API Endpoints

Health checks, connectivity testing, debugging endpoints, and mobile logging.
"""

import logging
import re
from datetime import datetime

from flask import jsonify, current_app, request
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import NoAuthorizationError

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.utils.log_sanitizer import mask_email

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

def _log_rejected_payload(reason):
    """Say what the client actually sent when we turn a log upload away.

    This endpoint returned 400 on every call for an unknown length of time and
    nobody could tell why, because the rejection was silent. Log the shape — keys
    and a short body prefix, never the full payload — so a rejection is diagnosable
    from the container log instead of by guesswork.
    """
    try:
        raw = request.get_data(as_text=True) or ''
        parsed = request.get_json(force=True, silent=True)
        keys = list(parsed.keys()) if isinstance(parsed, dict) else '<not an object>'
        logger.warning(
            "Rejected mobile log upload (%s) | content-type=%r keys=%s body[:200]=%r",
            reason, request.content_type, keys, raw[:200],
        )
    except Exception:
        logger.warning("Rejected mobile log upload (%s); payload not inspectable", reason)


_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')

# Substring match, like log_sanitizer.mask_session — catches 'claim_code',
# 'auth_token', 'X-API-Key' and friends without enumerating every variant.
_LOG_SENSITIVE_KEY_PARTS = (
    'password', 'secret', 'token', 'api_key', 'apikey', 'authorization',
    'claim_code', 'barcode', 'session_id',
)


def _scrub_text(value):
    """Mask email addresses inside free-text the client sent us.

    The Flutter client already scrubs JWTs/emails/phones before upload
    (lib/core/logging/log_sanitizer.dart), but this is an unauthenticated sink
    that persists whatever arrives — so don't rely on the caller to be honest.
    """
    if not isinstance(value, str):
        return value
    return _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), value)


def _scrub_context(value, _depth=0):
    """Recursively redact credential-bearing keys; mask emails in free text.

    Unlike log_sanitizer.mask_session this does NOT truncate ordinary strings —
    these payloads are crash diagnostics and a 20-char cap would destroy them.
    """
    if _depth > 6:
        return '<max-depth>'
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key_lower = str(k).lower()
            if any(part in key_lower for part in _LOG_SENSITIVE_KEY_PARTS):
                out[k] = '<redacted>'
            else:
                out[k] = _scrub_context(v, _depth + 1)
        return out
    if isinstance(value, list):
        return [_scrub_context(v, _depth + 1) for v in value]
    return _scrub_text(value)


def _emit_mobile_log(entry, user_id, username):
    """Write one client log entry to the mobile logger.

    Returns True if the entry was usable, False if it had no message.
    """
    level = str(entry.get('level', 'info')).lower()
    message = _scrub_text(entry.get('message', ''))
    if not message:
        return False

    context = _scrub_context(entry.get('context', {}))
    client_timestamp = entry.get('timestamp')
    # The client sends 'app_info'; 'device_info' was the original name and is
    # never populated by the current app. Accept either, else the [ios:1.2.3]
    # prefix below never renders.
    device_info = entry.get('device_info') or entry.get('app_info') or {}
    stack_trace = _scrub_text(entry.get('stack_trace'))
    tags = entry.get('tags', [])

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
        'user_agent': request.headers.get('User-Agent', ''),
    }
    if stack_trace:
        log_data['stack_trace'] = stack_trace

    user_prefix = f"[user:{user_id}] " if user_id else ""
    if isinstance(device_info, dict) and device_info:
        platform = device_info.get('platform', 'unknown')
        app_version = device_info.get('app_version', 'unknown')
        log_message = f"[MOBILE] [{platform}:{app_version}] {user_prefix}{message}"
    else:
        log_message = f"[MOBILE] {user_prefix}{message}"

    emit = {
        'debug': mobile_logger.debug,
        'info': mobile_logger.info,
        'warning': mobile_logger.warning,
        'error': mobile_logger.error,
        'critical': mobile_logger.critical,
    }.get(level, mobile_logger.info)
    emit(log_message, extra={'data': log_data})

    if stack_trace and level in ('error', 'critical'):
        emit(f"Stack trace:\n{stack_trace}")

    return True


def _resolve_log_user():
    """(user_id, username) from an optional JWT; (None, None) when absent."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if not identity:
            return None, None
        user_id = int(identity)
        from app.core.session_manager import managed_session
        from app.models import User
        with managed_session() as session:
            user = session.query(User).get(user_id)
            return user_id, (user.username if user else None)
    except (NoAuthorizationError, Exception):
        return None, None


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
    # force=True: don't reject on a missing/incorrect Content-Type. This is a log
    # sink — dropping a crash report because a header was wrong is the worst trade.
    data = request.get_json(force=True, silent=True)

    if not isinstance(data, dict) or not data:
        _log_rejected_payload("unparseable or empty body")
        return jsonify({"msg": "Missing request data"}), 400

    # This URL was, until now, registered by TWO blueprints — this one and
    # api_mobile_analytics.py, which expects a {"logs": [...]} envelope. This one
    # won the route and rejected everything the app sent, so mobile logging has been
    # dead. Accept the envelope too rather than care which contract the client uses.
    #
    # The envelope used to be handled as `data = data['logs'][0]`, silently
    # discarding entries 1..N-1 — the client flushes up to 100 per POST, so all
    # but the first were dropped with a 200 back. Loop instead.
    entries = data['logs'] if isinstance(data.get('logs'), list) and data['logs'] else [data]
    entries = [e for e in entries if isinstance(e, dict)]
    if not entries:
        _log_rejected_payload("no object-shaped log entries")
        return jsonify({"msg": "Missing request data"}), 400

    user_id, username = _resolve_log_user()

    received = sum(1 for entry in entries if _emit_mobile_log(entry, user_id, username))

    if not received:
        # Don't 400 silently — say what actually arrived, so the next capture tells
        # us the real contract instead of us guessing at it.
        _log_rejected_payload("no 'message' field")
        return jsonify({"msg": "message is required"}), 400

    return jsonify({
        "success": True,
        "message": "Log received",
        "received": received,
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

    # Truncating silently is how the single-entry route lost 99% of every flush.
    # Say so in the log if we drop any.
    max_batch_size = 100
    if len(logs) > max_batch_size:
        logger.warning(
            "Mobile log batch of %d exceeded max %d; dropping %d entries",
            len(logs), max_batch_size, len(logs) - max_batch_size,
        )
        logs = logs[:max_batch_size]

    user_id, username = _resolve_log_user()

    processed = 0
    errors = 0

    # Same emitter as /logs/mobile, so both routes sanitize identically and
    # neither can drift into logging raw PII.
    for log_entry in logs:
        try:
            if not isinstance(log_entry, dict) or not _emit_mobile_log(log_entry, user_id, username):
                errors += 1
                continue
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
