# app/mobile_api/app_config.py

"""
Mobile App Configuration Endpoint

Provides build version and update configuration for mobile clients.
- GET  /app_config       — unauthenticated, read by the app before login
- PUT  /app_config/build — authenticated via X-Build-Token, called by CI/build scripts
"""

import logging
from flask import jsonify, request, current_app

from app.mobile_api import mobile_api_v2
from app.models.admin_config import AdminConfig, AdminAuditLog
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)

# Default values for app config settings
APP_CONFIG_DEFAULTS = {
    'app_min_build_number': 1,
    'app_latest_build_number': 1,
    'app_update_message': 'A new version is available. Please update for the best experience.',
    'app_force_update': False,
    'app_ios_update_url': '',
    'app_android_update_url': '',
}


@mobile_api_v2.route('/app_config', methods=['GET'])
def get_app_config():
    """
    Get mobile app configuration including build version requirements.

    No authentication required — the app checks this before login
    to determine if a forced update is needed.

    Returns:
        JSON with build numbers, update URLs, and force update flag.
    """
    min_build = AdminConfig.get_setting('app_min_build_number', APP_CONFIG_DEFAULTS['app_min_build_number'])
    latest_build = AdminConfig.get_setting('app_latest_build_number', APP_CONFIG_DEFAULTS['app_latest_build_number'])
    update_message = AdminConfig.get_setting('app_update_message', APP_CONFIG_DEFAULTS['app_update_message'])
    force_update = AdminConfig.get_setting('app_force_update', APP_CONFIG_DEFAULTS['app_force_update'])
    ios_url = AdminConfig.get_setting('app_ios_update_url', APP_CONFIG_DEFAULTS['app_ios_update_url'])
    android_url = AdminConfig.get_setting('app_android_update_url', APP_CONFIG_DEFAULTS['app_android_update_url'])

    # Feature toggles — read by the app to gate features.
    # Defaults must match MOBILE_FEATURE_TOGGLES in mobile_features.py so the
    # API and the admin panel agree when a key has never been explicitly saved.
    feature_toggle_defaults = {
        'mobile_push_notifications': 'true',
        'mobile_wallet_passes': 'true',
        'mobile_offline_sync': 'false',
        'mobile_biometric_auth': 'true',
        'mobile_location_services': 'false',
        'mobile_camera_upload': 'true',
        'mobile_contact_sync': 'false',
        'mobile_analytics_tracking': 'true',
        'mobile_crash_reporting': 'true',
        'mobile_ar_match_views': 'false',
        'mobile_voice_commands': 'false',
        'mobile_smart_predictions': 'false',
    }
    feature_toggles = {}
    for key, default in feature_toggle_defaults.items():
        val = AdminConfig.get_setting(key, default)
        feature_toggles[key] = str(val).lower() in ('true', '1', 'yes', 'on')

    return jsonify({
        'min_build_number': int(min_build) if min_build else 1,
        'latest_build_number': int(latest_build) if latest_build else 1,
        'update_message': update_message or '',
        'force_update': bool(force_update),
        'ios_update_url': ios_url or '',
        'android_update_url': android_url or '',
        'feature_toggles': feature_toggles,
    }), 200


@mobile_api_v2.route('/app_config/build', methods=['PUT'])
def publish_build():
    """
    Update latest_build_number after a successful build.

    Called by CI / build scripts. Authenticated via X-Build-Token header
    (set BUILD_API_TOKEN env var on the server).

    Request JSON:
        {
            "build_number": 51,
            "update_message": "Bug fixes and performance improvements"  // optional
        }

    Returns:
        JSON with the updated config values.
    """
    # --- auth: require X-Build-Token header ---
    token = request.headers.get('X-Build-Token', '')
    expected = current_app.config.get('BUILD_API_TOKEN') or ''
    if not expected:
        logger.error('BUILD_API_TOKEN is not configured on the server')
        return jsonify({'error': 'Build publishing is not configured'}), 503
    if token != expected:
        return jsonify({'error': 'Invalid or missing X-Build-Token'}), 401

    # --- parse body ---
    data = request.get_json(silent=True) or {}
    build_number = data.get('build_number')
    if build_number is None:
        return jsonify({'error': 'build_number is required'}), 400
    try:
        build_number = int(build_number)
    except (TypeError, ValueError):
        return jsonify({'error': 'build_number must be an integer'}), 400

    if build_number < 1:
        return jsonify({'error': 'build_number must be >= 1'}), 400

    update_message = data.get('update_message')

    # --- persist ---
    with managed_session() as session:
        old_value = AdminConfig.get_setting('app_latest_build_number', 1)

        AdminConfig.set_setting(
            key='app_latest_build_number',
            value=str(build_number),
            description='The newest build available for download',
            category='mobile_app',
            data_type='integer',
            auto_commit=True,
        )

        if update_message is not None:
            AdminConfig.set_setting(
                key='app_update_message',
                value=str(update_message),
                category='mobile_app',
                data_type='string',
                auto_commit=True,
            )

        AdminAuditLog.log_action(
            user_id=None,
            action='publish_build',
            resource_type='app_config',
            resource_id='app_latest_build_number',
            old_value=str(old_value),
            new_value=str(build_number),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        session.commit()

    logger.info(f'Build published: latest_build_number updated {old_value} -> {build_number}')

    return jsonify({
        'success': True,
        'latest_build_number': build_number,
        'previous_build_number': int(old_value) if old_value else 1,
    }), 200
