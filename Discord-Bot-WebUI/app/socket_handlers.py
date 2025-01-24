from flask_socketio import emit
from flask_login import login_required
from app.core import socketio, celery
from app.models import Player
from app.tasks.tasks_discord import fetch_role_status, update_player_discord_roles
from app.utils.user_helpers import safe_current_user
from app.sockets.session import socket_session
from app.core.session_manager import managed_session, db
import logging

logger = logging.getLogger(__name__)

@socketio.on('connect')
@login_required 
def handle_connect():
    with socket_session(db.engine) as session:
        logger.info(f"Client connected: {safe_current_user.username}")

@socketio.on('disconnect')
def handle_disconnect():
    with socket_session(db.engine) as session:
        if safe_current_user.is_authenticated:
            logger.info(f"Client disconnected: {safe_current_user.username}")

@socketio.on('update_single_player')
@login_required
def handle_single_player_update(data):
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
    with managed_session() as session:
        task = fetch_role_status.delay()
        logger.info(f"Queued mass update, task ID: {task.id}")
        emit('mass_update_started', {'task_id': task.id})

@socketio.on('check_task_status')
@login_required
def handle_task_status(data):
    with managed_session() as session:
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