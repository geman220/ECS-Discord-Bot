# app/sockets/discord_roles.py

"""
Socket.IO Discord Role Handlers

Handlers for Discord role management and task status checking.
"""

import logging

from flask_login import login_required
from flask_socketio import emit

from app.core import socketio, db
from app.sockets.session import socket_session
from app.tasks.tasks_discord import fetch_role_status, update_player_discord_roles

logger = logging.getLogger(__name__)


@socketio.on('update_single_player')
@login_required
def handle_single_player_update(data):
    """Queue an update for a single player's Discord roles."""
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
    """Queue a mass update of Discord roles for all players."""
    with socket_session(db.engine) as session:
        task = fetch_role_status.delay()
        logger.info(f"Queued mass update, task ID: {task.id}")
        emit('mass_update_started', {'task_id': task.id})


@socketio.on('check_task_status')
@login_required
def handle_task_status(data):
    """Check the status of an asynchronous task."""
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
