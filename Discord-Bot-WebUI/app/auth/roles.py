# app/auth/roles.py

"""
Role Management Routes

Routes for syncing Discord roles and error handlers.
"""

import logging

from flask import render_template, redirect, url_for
from flask_login import login_required

from app.auth import auth
from app.alert_helpers import show_warning, show_success
from app.utils.user_helpers import safe_current_user
from app.utils.db_utils import transactional
from app.tasks.tasks_discord import assign_roles_to_player_task

logger = logging.getLogger(__name__)


@auth.route('/sync_discord_roles', methods=['POST'])
@login_required
@transactional
def sync_discord_roles():
    """
    Force a full sync of Discord roles for the currently logged-in user.
    This will properly add and remove roles based on the user's current status.
    """
    user = safe_current_user
    if not user or not user.player or not user.player.discord_id:
        show_warning('No Discord account linked to your profile.')
        return redirect(url_for('main.index'))

    # Trigger a complete role sync (not just adding roles)
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
    logger.info(f"Triggered complete Discord role sync for player {user.player.id}")

    show_success('Discord roles sync requested. Changes should take effect within a minute.')
    return redirect(url_for('main.index'))


# Error Handlers
@auth.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 error: {error}")
    return render_template('404.html', title='404',), 404


@auth.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}")
    return render_template('500.html', title='500',), 500
