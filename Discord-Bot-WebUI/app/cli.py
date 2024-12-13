import click
from flask.cli import with_appcontext

@click.command()
@with_appcontext
def build_assets():
    """Build and minify assets."""
    from flask import current_app
    assets = current_app.extensions['assets']
    for bundle in assets:
        bundle.build()