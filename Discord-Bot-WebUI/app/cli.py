# app/cli.py

"""
Command Line Interface (CLI) Module

This module defines CLI commands for the Flask application. In particular,
it provides commands to build and minify static assets, initialize Discord roles,
and synchronize player coach flags with Discord roles.
"""

import click
from flask.cli import with_appcontext
from flask import current_app


@click.command()
@with_appcontext
def build_assets():
    """Build and minify assets."""
    assets = current_app.extensions['assets']
    for bundle in assets:
        bundle.build()


@click.command()
@with_appcontext
def init_discord_roles():
    """Initialize necessary Discord roles for the application."""
    import asyncio
    import aiohttp
    from app.models import Role
    from app.discord_utils import get_or_create_role

    click.echo("Initializing Discord roles...")
    
    # Ensure the pl-unverified role exists in the database
    from flask_sqlalchemy import SQLAlchemy
    db = SQLAlchemy(current_app)
    try:
        # Check and create the database role
        unverified_role = Role.query.filter_by(name='pl-unverified').first()
        if not unverified_role:
            click.echo("Creating pl-unverified role in database...")
            unverified_role = Role(name='pl-unverified', description='Unverified player awaiting league approval')
            g.db_session.add(unverified_role)
            g.db_session.commit()
            click.echo("pl-unverified role created in database.")
        else:
            click.echo("pl-unverified role already exists in database.")
        
        # Create the Discord role
        async def create_discord_role():
            server_id = int(current_app.config['SERVER_ID'])
            click.echo(f"Checking Discord role in server {server_id}...")
            
            async with aiohttp.ClientSession() as session:
                # Check if the ECS-FC-PL-UNVERIFIED role exists
                unverified_role_id = await get_or_create_role(server_id, "ECS-FC-PL-UNVERIFIED", session)
                if unverified_role_id:
                    click.echo(f"ECS-FC-PL-UNVERIFIED role exists or was created with ID: {unverified_role_id}")
                else:
                    click.echo("Failed to create ECS-FC-PL-UNVERIFIED role on Discord")
        
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(create_discord_role())
        finally:
            loop.close()
            
        click.echo("Discord role initialization complete!")
        
    except Exception as e:
        click.echo(f"Error initializing Discord roles: {str(e)}")
        g.db_session.rollback()
        raise

@click.command()
@with_appcontext
def sync_coach_roles():
    """
    Sync player is_coach flags with Discord coach roles.
    
    This command checks all players with Discord IDs and ensures that:
    1. Players with Discord coach roles have is_coach=True in the database
    2. Players without Discord coach roles have is_coach=False in the database
    
    After updating the database, it triggers a full role sync for each player.
    """
    import asyncio
    import aiohttp
    import re
    from app.models import Player
    from app.utils.discord_request_handler import make_discord_request
    from app.tasks.tasks_discord import assign_roles_to_player_task
    from web_config import Config

    click.echo("Syncing coach roles between database and Discord...")
    
    # Create event loop for async operations
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Function to get all player Discord roles
    async def get_player_roles():
        players = Player.query.filter(Player.discord_id.isnot(None)).all()
        click.echo(f"Found {len(players)} players with Discord IDs")
        
        role_pattern = re.compile(r'.*COACH$')
        guild_id = current_app.config['SERVER_ID']
        player_roles = {}
        
        async with aiohttp.ClientSession() as session:
            for player in players:
                url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles"
                try:
                    response = await make_discord_request('GET', url, session)
                    roles = []
                    if isinstance(response, list):
                        roles = response
                    elif response and 'roles' in response:
                        if isinstance(response['roles'], list):
                            roles = response['roles']
                        elif isinstance(response['roles'], dict):
                            roles = list(response['roles'].values())
                    
                    # Check if any role ends with "COACH"
                    has_coach_role = any(role_pattern.match(role) for role in roles if isinstance(role, str))
                    player_roles[player.id] = {
                        'player': player,
                        'has_coach_role': has_coach_role,
                        'roles': roles
                    }
                    click.echo(f"Player {player.name} {'has' if has_coach_role else 'does not have'} coach role")
                except Exception as e:
                    click.echo(f"Error getting roles for player {player.name}: {str(e)}")
        
        return player_roles
    
    try:
        # Get player roles
        player_roles = loop.run_until_complete(get_player_roles())
        
        # Update player is_coach flag based on Discord roles
        from flask_sqlalchemy import SQLAlchemy
        db = SQLAlchemy(current_app)
        updated_players = 0
        
        for player_id, data in player_roles.items():
            player = data['player']
            has_coach_role = data['has_coach_role']

            if player.is_coach != has_coach_role:
                # Update both player.is_coach AND player_teams.is_coach to maintain consistency
                player.is_coach = has_coach_role

                # Update all team relationships for this player
                from sqlalchemy import text
                g.db_session.execute(
                    text("UPDATE player_teams SET is_coach = :is_coach WHERE player_id = :player_id"),
                    {"is_coach": has_coach_role, "player_id": player.id}
                )

                updated_players += 1
                click.echo(f"Updated player {player.name} is_coach to {has_coach_role}")
        
        if updated_players > 0:
            g.db_session.commit()
            click.echo(f"Updated is_coach flag for {updated_players} players")
        else:
            click.echo("No players needed is_coach flag updates")
        
        # Trigger role sync for all players to ensure Discord roles match database
        for player_id in player_roles:
            assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
        
        click.echo("Role sync initiated for all players")
        
    except Exception as e:
        click.echo(f"Error syncing coach roles: {str(e)}")
        raise
    finally:
        loop.close()
