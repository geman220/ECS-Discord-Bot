# app/api/utils.py

"""
Utility API Endpoints

Health checks, connectivity testing, and debugging endpoints.
"""

import logging
from datetime import datetime

from flask import jsonify, current_app

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required

logger = logging.getLogger(__name__)


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
