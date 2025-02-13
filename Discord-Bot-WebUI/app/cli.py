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
