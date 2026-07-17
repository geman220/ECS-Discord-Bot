# app/auth/helpers.py

"""
Authentication Helpers

Shared helper functions for authentication routes.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import g

from app.models import User, Player
from app.tasks.tasks_discord import assign_roles_to_player_task

logger = logging.getLogger(__name__)


def registration_enabled() -> bool:
    """Master switch for whether NEW accounts may be created at all.

    When an admin toggles ``registration_enabled`` off, nobody can register —
    normal signup AND waitlist signup alike (waitlist is just a flavor of
    registration). This is the authoritative gate the account-creation routes
    call; the login-page button visibility is cosmetic on top of it.

    Fails OPEN (returns True) on any error so a DB hiccup never locks signups
    when an admin didn't intend to close them.
    """
    try:
        from app.models.admin_config import AdminConfig
        return bool(AdminConfig.get_setting('registration_enabled', True))
    except Exception as e:
        logger.debug(f"registration_enabled check failed, failing open: {e}")
        return True


def sync_discord_for_user(user: User, discord_id: Optional[str] = None):
    """
    Link a user's Discord account and trigger a Celery task to assign roles on Discord.

    This function checks if the player's Discord ID is missing and, if provided,
    updates it. Then, it triggers a task to add (but not remove) relevant roles.

    Args:
        user (User): The user instance.
        discord_id (Optional[str]): The Discord ID to link.
    """
    db_session = g.db_session  # from @transactional or Flask global

    if not user or not user.player:
        return

    # Link the Discord ID if it's missing and one is provided
    if not user.player.discord_id and discord_id:
        user.player.discord_id = discord_id
        db_session.add(user.player)
        logger.info(f"Linked discord_id={discord_id} to player {user.player.id}")

    # Trigger the Celery task to sync roles (only adds roles, never removes them at login)
    # Log additional diagnostic information
    if user.player.is_coach:
        logger.info(f"Player {user.player.id} has is_coach=True")

    # Look for Flask "Pub League Coach" role
    pub_league_coach_role = False
    for role in user.roles:
        if role.name == "Pub League Coach":
            pub_league_coach_role = True
            logger.info(f"Player {user.player.id} has Flask role 'Pub League Coach'")
            break

    # Additional diagnostics for coach-related roles
    if user.player.is_coach and not pub_league_coach_role:
        logger.warning(f"Player {user.player.id} has is_coach=True but missing Flask 'Pub League Coach' role")
    elif not user.player.is_coach and pub_league_coach_role:
        logger.warning(f"Player {user.player.id} has Flask 'Pub League Coach' role but is_coach=False")

    # Only add roles at login, never remove them
    assign_roles_to_player_task.delay(player_id=user.player.id, only_add=True)
    logger.info(f"Triggered Discord role sync for player {user.player.id} (only_add=True)")
