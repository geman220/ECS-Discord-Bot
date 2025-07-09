# app/admin/docker_routes.py

"""
Docker Container Management Routes

This module contains routes for managing Docker containers,
viewing container logs, and checking container status.
"""

import logging
from flask import Blueprint, jsonify, redirect, url_for
from flask_login import login_required

from app.decorators import role_required
from app.alert_helpers import show_error
from app.admin_helpers import (
    get_container_data,
    manage_docker_container,
    get_container_logs
)

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# Docker Container Management
# -----------------------------------------------------------

@admin_bp.route('/admin/container/<container_id>/<action>', endpoint='manage_container', methods=['POST'])
@login_required
@role_required('Global Admin')
def manage_container(container_id, action):
    """
    Manage Docker container actions (e.g., start, stop, restart).
    """
    success = manage_docker_container(container_id, action)
    if not success:
        show_error("Failed to manage container.")
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/admin/view_logs/<container_id>', endpoint='view_logs', methods=['GET'])
@login_required
@role_required('Global Admin')
def view_logs(container_id):
    """
    Retrieve logs for a given container.
    """
    logs = get_container_logs(container_id)
    if logs is None:
        return jsonify({"error": "Failed to retrieve logs"}), 500
    return jsonify({"logs": logs})


@admin_bp.route('/admin/docker_status', endpoint='docker_status', methods=['GET'])
@login_required
@role_required('Global Admin')
def docker_status():
    """
    Get status information for all Docker containers.
    """
    containers = get_container_data()
    if containers is None:
        return jsonify({"error": "Failed to fetch container data"}), 500
    return jsonify(containers)