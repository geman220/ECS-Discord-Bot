# app/socket_handlers.py

"""
Socket Handlers Module

This module defines Socket.IO event handlers for updating Discord roles and
tracking task statuses. It uses Flask-SocketIO and Celery to handle real-time
updates and asynchronous tasks.
"""

import logging

from flask_socketio import emit
from flask_login import login_required

from app.core import socketio, db
from app.core.session_manager import managed_session
from app.sockets.session import socket_session
from app.tasks.tasks_discord import fetch_role_status, update_player_discord_roles
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


@socketio.on('connect')
@login_required
def handle_connect():
    """
    Handle a new client connection.
    
    Logs the username of the connected client.
    """
    with socket_session(db.engine) as session:
        logger.info(f"Client connected: {safe_current_user.username}")


@socketio.on('disconnect')
def handle_disconnect():
    """
    Handle client disconnection.
    
    If the user is authenticated, logs the username upon disconnection.
    """
    with socket_session(db.engine) as session:
        if safe_current_user.is_authenticated:
            logger.info(f"Client disconnected: {safe_current_user.username}")


@socketio.on('update_single_player')
@login_required
def handle_single_player_update(data):
    """
    Queue an update for a single player's Discord roles.
    
    Expects a dictionary with player_id. If found, the task is enqueued
    and a role update event is emitted to the client with task details.
    
    Args:
        data (dict): Contains player_id key.
    """
    with socket_session(db.engine) as session:
        player_id = data.get('player_id')
        if player_id:
            task = update_player_discord_roles.delay(player_id)
            logger.info(f"Queued update for player {player_id}, task ID: {task.id}")
            emit('role_update', {
                'id': player_id,
                'status_class': 'info',
                'status_text': 'Update Queued', 
                'task_id': task.id
            })


@socketio.on('mass_update_roles')
@login_required
def handle_mass_update():
    """
    Queue a mass update of Discord roles for all players.
    
    Enqueues an asynchronous task to fetch role status and emits an event
    to notify the client that the update has started.
    """
    # Use socket_session for consistency with other socket handlers
    with socket_session(db.engine) as session:
        task = fetch_role_status.delay()
        logger.info(f"Queued mass update, task ID: {task.id}")
        emit('mass_update_started', {'task_id': task.id})


@socketio.on('check_task_status')
@login_required
def handle_task_status(data):
    """
    Check the status of an asynchronous task and emit updates to the client.
    
    Expects a dictionary with 'task_id'. If the task is complete, emits a
    'task_complete' event with the result; otherwise, emits a 'task_status'
    event with the current status.
    
    Args:
        data (dict): Contains 'task_id' key.
    """
    # Use socket_session for consistency with other socket handlers
    with socket_session(db.engine) as session:
        task_id = data.get('task_id')
        if task_id:
            task = fetch_role_status.AsyncResult(task_id)
            if task.ready():
                emit('task_complete', {
                    'task_id': task_id,
                    'status': 'complete' if task.successful() else 'failed',
                    'result': task.get() if task.successful() else None,
                    'error': str(task.result) if not task.successful() else None
                })
            else:
                emit('task_status', {'task_id': task_id, 'status': task.status})