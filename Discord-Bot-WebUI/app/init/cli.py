# app/init/cli.py

"""
CLI Commands Registration

Register CLI commands for Flask application management.
"""

import logging

logger = logging.getLogger(__name__)


def init_cli_commands(app):
    """
    Register CLI commands with the Flask application.

    Args:
        app: The Flask application instance.
    """
    from app.cli import (
        build_assets, init_discord_roles, sync_coach_roles,
        fix_duplicate_user_roles, add_user_roles_constraint,
        regenerate_phone_hashes, sync_profile_pictures
    )
    app.cli.add_command(build_assets)
    app.cli.add_command(init_discord_roles)
    app.cli.add_command(sync_coach_roles)
    app.cli.add_command(fix_duplicate_user_roles)
    app.cli.add_command(add_user_roles_constraint)
    app.cli.add_command(regenerate_phone_hashes)
    app.cli.add_command(sync_profile_pictures)

    # Register wallet CLI commands
    from app.wallet_pass.cli import wallet as wallet_cli
    app.cli.add_command(wallet_cli)
