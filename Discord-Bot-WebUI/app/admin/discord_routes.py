# app/admin/discord_routes.py

"""
Discord Role Management Routes

This module contains routes for Discord role synchronization and management.
"""

import logging
from flask import jsonify, g
from flask_login import login_required
from app.decorators import role_required
from app.models import Player
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# Discord Role Management Routes
# -----------------------------------------------------------

@admin_bp.route('/admin/check_role_status/<task_id>', endpoint='check_role_status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def check_role_status(task_id):
    """
    Check the status of a Discord role update task.
    """
    try:
        task = fetch_role_status.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                task_result = task.get()  # Expected format: {'success':True,'results':[...],'message':...}
                return jsonify({
                    'state': 'COMPLETE',
                    'results': task_result['results']
                })
            else:
                return jsonify({
                    'state': 'FAILED',
                    'error': str(task.result)
                })
        return jsonify({'state': 'PENDING'})
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        return jsonify({'state': 'ERROR', 'error': str(e)}), 500


@admin_bp.route('/admin/update_player_roles/<int:player_id>', endpoint='update_player_roles_route', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_player_roles_route(player_id):
    """
    Update a player's Discord roles.
    """
    try:
        # This will block until the task completes; consider async polling if needed
        task_result = update_player_discord_roles.delay(player_id).get(timeout=30)
        if task_result.get('success'):
            return jsonify({
                'success': True,
                'player_data': task_result['player_data']
            })
        else:
            return jsonify({
                'success': False,
                'error': task_result.get('message', 'Unknown error occurred')
            }), 400
    except Exception as e:
        logger.error(f"Error updating roles for player {player_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/update_discord_roles', endpoint='mass_update_discord_roles', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def mass_update_discord_roles():
    """
    Initiate a mass update for Discord roles across players.
    """
    session = g.db_session
    try:
        # Mark all players that are out of sync
        session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).update({Player.discord_needs_update: True}, synchronize_session=False)

        result = process_discord_role_updates.delay()

        return jsonify({
            'success': True,
            'message': 'Mass role update initiated',
            'task_id': result.id
        })

    except Exception as e:
        logger.error(f"Error initiating mass role update: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500