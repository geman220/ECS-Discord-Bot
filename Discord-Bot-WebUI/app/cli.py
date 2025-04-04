# app/cli.py

"""
Command Line Interface (CLI) Module

This module defines CLI commands for the Flask application. In particular,
it provides a command to build and minify static assets.
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
    
    # Ensure the SUB role exists in the database
    from flask_sqlalchemy import SQLAlchemy
    db = SQLAlchemy(current_app)
    try:
        # Check and create the database role
        sub_role = Role.query.filter_by(name='SUB').first()
        if not sub_role:
            click.echo("Creating SUB role in database...")
            sub_role = Role(name='SUB', description='Substitute Player')
            db.session.add(sub_role)
            db.session.commit()
            click.echo("SUB role created in database.")
        else:
            click.echo("SUB role already exists in database.")
        
        # Create the Discord role
        async def create_discord_role():
            server_id = int(current_app.config['SERVER_ID'])
            click.echo(f"Checking Discord role in server {server_id}...")
            
            async with aiohttp.ClientSession() as session:
                # Check if the ECS-FC-PL-SUB role exists
                sub_role_id = await get_or_create_role(server_id, "ECS-FC-PL-SUB", session)
                if sub_role_id:
                    click.echo(f"ECS-FC-PL-SUB role exists or was created with ID: {sub_role_id}")
                else:
                    click.echo("Failed to create ECS-FC-PL-SUB role on Discord")
        
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
        db.session.rollback()
        raise
